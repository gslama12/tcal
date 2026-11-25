"""SQLite cache: calendars, events and the queue of local edits not yet pushed.

The UI reads only from here (offline-first, PLAN D3). There is one row per
VEVENT, keyed by (uid, recurrence_id): parsed fields for queries plus the
resource's iCalendar text (``raw``) for writing back. A local edit updates the
rows and queues an op; ``SyncEngine`` pushes the queue, then replaces each
calendar's rows with the server's, except events that still have ops pending.

The rows' ``href``/``etag`` are the truth about the server's copy: the UI may hold an
event read before a push that just ran, so a saved event takes them from its row.
``bases`` remembers what we know of the server's copy, so that only changes by someone
else count as conflicts. Every read-then-write runs in one transaction (``_write``):
the UI and the sync worker write at the same time.

Open one ``Store`` per thread (the sync worker opens its own).
"""

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from tcal import ics
from tcal.model import Calendar, Event
from tcal.tz import UTC_STAMP, local_midnight, utc_stamp

OpKind = Literal["create", "update", "delete"]
OWN_ETAGS = 20  # replaced etags remembered per event

SCHEMA = """
CREATE TABLE IF NOT EXISTS calendars (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL,
    readonly INTEGER NOT NULL,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    uid TEXT NOT NULL,
    recurrence_id TEXT NOT NULL,  -- UTC key of the overridden instance, '' for the master
    calendar_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    start TEXT NOT NULL,          -- ISO 8601 with offset
    end TEXT NOT NULL,
    tz TEXT NOT NULL,             -- zone name of start, '' if not a named zone
    all_day INTEGER NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL,
    rrule TEXT,
    exdates TEXT NOT NULL,        -- JSON list of ISO datetimes
    etag TEXT,
    href TEXT,
    raw TEXT,
    start_utc TEXT NOT NULL,      -- UTC keys for range queries
    end_utc TEXT NOT NULL,
    PRIMARY KEY (uid, recurrence_id)
);
CREATE INDEX IF NOT EXISTS events_range ON events (start_utc, end_utc);
CREATE TABLE IF NOT EXISTS ops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    uid TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    href TEXT,
    etag TEXT,
    raw TEXT                      -- for deletes: the deleted resource
);
CREATE TABLE IF NOT EXISTS bases (
    uid TEXT PRIMARY KEY,
    raw TEXT,                     -- the server's copy the local edits build on
    sent TEXT,                    -- a later one, if its push arrived but the answer didn't
    own TEXT NOT NULL             -- JSON list of etags our own pushes replaced
);
"""


@dataclass(frozen=True)
class PendingOp:
    id: int
    kind: OpKind
    event: Event  # create/update: the current master; delete: the deleted event


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[None]:
        """One write transaction, locked from the start (joins the one under way)."""
        if self.db.in_transaction:
            yield
            return
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            yield

    # ----- calendars ------------------------------------------------------

    def calendars(self) -> list[Calendar]:
        rows = self.db.execute("SELECT * FROM calendars ORDER BY position")
        return [
            Calendar(r["id"], r["name"], r["color"], readonly=bool(r["readonly"])) for r in rows
        ]

    def upsert_calendars(self, calendars: Iterable[Calendar]) -> None:
        """Make the cached calendars exactly ``calendars`` (dropping vanished ones' events)."""
        calendars = list(calendars)
        ids = [c.id for c in calendars]
        marks = ",".join("?" * len(ids))
        with self._write():
            self.db.execute(f"DELETE FROM calendars WHERE id NOT IN ({marks})", ids)
            self.db.execute(f"DELETE FROM events WHERE calendar_id NOT IN ({marks})", ids)
            self.db.executemany(
                "INSERT OR REPLACE INTO calendars VALUES (?, ?, ?, ?, ?)",
                [(c.id, c.name, c.color, c.readonly, i) for i, c in enumerate(calendars)],
            )

    # ----- events ---------------------------------------------------------

    def events_between(self, start: datetime, end: datetime) -> list[Event]:
        """Events that may occur in [start, end): overlapping ones, all series and overrides.

        A superset (by a day either side); ``recurrence.expand`` does the exact cut.
        """
        lo, hi = utc_stamp(start - timedelta(days=1)), utc_stamp(end + timedelta(days=1))
        rows = self.db.execute(
            """SELECT * FROM events
               WHERE (start_utc < :hi AND end_utc >= :lo)
                  OR (rrule IS NOT NULL AND start_utc < :hi)
                  OR recurrence_id != ''""",
            {"lo": lo, "hi": hi},
        )
        return [_event(r) for r in rows]

    def get_event(self, uid: str) -> Event | None:
        """The master of ``uid`` (or its first override if the master isn't cached)."""
        row = self.db.execute(
            "SELECT * FROM events WHERE uid = ? ORDER BY recurrence_id LIMIT 1", (uid,)
        ).fetchone()
        return _event(row) if row else None

    def rows(self, uid: str) -> list[Event]:
        """All rows of ``uid`` (master first, then overrides), e.g. to ``restore`` them later."""
        rows = self.db.execute("SELECT * FROM events WHERE uid = ? ORDER BY recurrence_id", (uid,))
        return [_event(r) for r in rows]

    def upsert_events(self, calendar_id: str, events: Iterable[Event]) -> None:
        """Replace the calendar's events with ``events`` (from the server).

        Events with pending ops keep their local version.
        """
        events = list(events)
        with self._write():
            pending = {r["uid"] for r in self.db.execute("SELECT uid FROM ops")}
            self._check_bases(calendar_id, {e.uid: e for e in events})
            self.db.execute(
                "DELETE FROM events WHERE calendar_id = ? AND uid NOT IN (SELECT uid FROM ops)",
                (calendar_id,),
            )
            for event in events:
                if event.uid not in pending:
                    self._put(event)

    def save_event(self, event: Event) -> Event:
        """Write a new or edited event to the cache and queue it for the server."""
        with self._write():
            old = self.get_event(event.uid)
            if old:
                self._remember(old)
                if old.calendar_id == event.calendar_id:
                    event = self._rebased(event, old)
                else:
                    # Moving between calendars is a delete there + a create here in CalDAV.
                    self._queue_delete(old)
                    event = replace(event, href=None, etag=None)
            event = replace(event, raw=ics.to_ics(event))
            self._put(event)
            # Overrides share the resource: keep them in step.
            self.db.execute(
                "UPDATE events SET raw = ?, calendar_id = ?, href = ?, etag = ? WHERE uid = ?",
                (event.raw, event.calendar_id, event.href, event.etag, event.uid),
            )
            self._queue(event)
        return event

    def delete_event(self, uid: str, occurrence: datetime | None = None) -> list[Event]:
        """Delete a whole event, or with ``occurrence`` (an instance's original
        start, i.e. its recurrence id) just that instance of a series (EXDATE).

        Returns the event's rows as they were, for ``restore`` (undo)."""
        before = self.rows(uid)
        master = self.get_event(uid)
        if master is None:
            return before
        if occurrence is not None and master.rrule:
            with self._write():
                self.db.execute(
                    "DELETE FROM events WHERE uid = ? AND recurrence_id = ?",
                    (uid, utc_stamp(occurrence)),
                )
                master = ics.without_instance(master, occurrence)
                self.save_event(replace(master, exdates=(*master.exdates, occurrence)))
            return before
        with self._write():
            master = self.get_event(uid) or master
            self._remember(master)
            self.db.execute("DELETE FROM events WHERE uid = ?", (uid,))
            self._queue_delete(master)
        return before

    def restore(self, rows: list[Event]) -> None:
        """Undo ``delete_event`` or an edit: put back the rows ``rows``/``delete_event``
        returned and queue the push.

        The event keeps its server resource if that still exists (an unpushed
        delete is cancelled, also the one a move to another calendar queued; a
        deleted instance updates the series), otherwise it is created again."""
        if not rows:
            return
        master, *overrides = rows
        with self._write():
            current = self.get_event(master.uid)
            if current is not None:
                self._remember(current)
            unpushed = self.db.execute(
                "SELECT * FROM ops WHERE uid = ? AND calendar_id = ? AND kind = 'delete'",
                (master.uid, master.calendar_id),
            ).fetchone()
            if unpushed:  # the old resource is still on the server
                if current is not None and current.calendar_id != master.calendar_id:
                    self._queue_delete(current)
                self.db.execute("DELETE FROM ops WHERE id = ?", (unpushed["id"],))
                href, etag = unpushed["href"], unpushed["etag"]
            elif current is not None and current.calendar_id == master.calendar_id:
                href, etag = current.href, current.etag
            else:
                if current is not None:  # back to its other calendar: a delete + a create
                    self._queue_delete(current)
                href = etag = None
            self.db.execute("DELETE FROM events WHERE uid = ?", (master.uid,))
            for override in overrides:
                self._put(override)
            self.save_event(replace(master, href=href, etag=etag))

    # ----- the server's copy ----------------------------------------------

    def record_push(self, op: PendingOp, done: Event | None) -> None:
        """``op`` reached the server, which now has ``done`` (None: deleted).

        Clears the op; what was edited since it was read stays queued, on top of ``done``."""
        with self._write():
            self.clear_op(op.id)
            if done is None:  # restored meanwhile: needs a new resource
                self.db.execute(
                    "UPDATE events SET href = NULL, etag = NULL WHERE uid = ? AND href = ?",
                    (op.event.uid, op.event.href),
                )
            else:
                self._stored(op.event, done)

    def _stored(self, sent: Event, done: Event) -> None:
        uid, current = sent.uid, self.get_event(sent.uid)
        own = [*self._own(uid), sent.etag][-OWN_ETAGS:]
        self.db.execute(
            "INSERT OR REPLACE INTO bases VALUES (?, ?, NULL, ?)", (uid, done.raw, json.dumps(own))
        )
        deleting = self.db.execute(  # deleted or moved to another calendar meanwhile
            "UPDATE ops SET etag = ? WHERE uid = ? AND kind = 'delete' AND href = ?",
            (done.etag, uid, done.href),
        ).rowcount
        if deleting:
            return
        if current is not None and current.calendar_id == sent.calendar_id:
            self.db.execute(
                "UPDATE events SET href = ?, etag = ? WHERE uid = ?", (done.href, done.etag, uid)
            )
        elif sent.href is None:  # ... while it was being created: nothing is queued for it
            self._queue_delete(done)
            if current is not None:
                self._queue(current)  # after the delete

    def record_attempt(self, event: Event) -> None:
        """``event`` is about to be sent; if no answer comes, the server may have it."""
        with self._write():
            self.db.execute(
                """INSERT INTO bases VALUES (:uid, NULL, :raw, '[]')
                   ON CONFLICT (uid) DO UPDATE SET sent = :raw""",
                {"uid": event.uid, "raw": event.raw},
            )

    def bases(self, uid: str) -> list[str | None]:
        """The iCalendar texts the server may have of ``uid`` if only we changed it."""
        row = self.db.execute("SELECT raw, sent FROM bases WHERE uid = ?", (uid,)).fetchone()
        return list(row) if row else []

    def _own(self, uid: str) -> list[str | None]:
        """The etags of ``uid`` that our own pushes replaced."""
        row = self.db.execute("SELECT own FROM bases WHERE uid = ?", (uid,)).fetchone()
        return json.loads(row["own"]) if row else []

    def _remember(self, old: Event) -> None:
        """Before the first edit since a push: ``old`` is the base (unless a pull brought
        it back from before our push: then that push is)."""
        pending = self.db.execute("SELECT 1 FROM ops WHERE uid = ?", (old.uid,)).fetchone()
        if pending or old.href is None or old.etag in self._own(old.uid):
            return
        self.db.execute(
            """INSERT INTO bases VALUES (:uid, :raw, NULL, '[]')
               ON CONFLICT (uid) DO UPDATE SET raw = :raw""",
            {"uid": old.uid, "raw": old.raw},
        )

    def _rebased(self, event: Event, old: Event) -> Event:
        """``event``, perhaps read before our last pushes, with its row's current resource.

        If the row has since been replaced by someone else's version it keeps its old
        etag, and no base: pushing it is a conflict."""
        ours = event.etag == old.etag or event.etag in self._own(event.uid)
        if ours or ics.same_content(event.raw, old.raw):
            return replace(event, href=old.href, etag=old.etag)
        self.db.execute("UPDATE bases SET raw = NULL WHERE uid = ?", (event.uid,))
        return event

    def _check_bases(self, calendar_id: str, pulled: dict[str, Event]) -> None:
        """Forget the bases of events changed by someone else, or gone."""
        rows = self.db.execute(
            """SELECT DISTINCT uid, events.etag, bases.raw, own FROM bases JOIN events USING (uid)
               WHERE events.calendar_id = ? AND uid NOT IN (SELECT uid FROM ops)""",
            (calendar_id,),
        ).fetchall()
        for row in rows:
            uid, own, new = row["uid"], json.loads(row["own"]), pulled.get(row["uid"])
            if new is not None and (new.etag == row["etag"] or new.etag in own):
                continue
            if new is not None and ics.same_content(new.raw, row["raw"]):
                own = json.dumps([*own, row["etag"]][-OWN_ETAGS:])
                self.db.execute("UPDATE bases SET own = ? WHERE uid = ?", (own, uid))
            else:
                self.db.execute("DELETE FROM bases WHERE uid = ?", (uid,))

    # ----- pending ops ----------------------------------------------------

    def pending_ops(self) -> list[PendingOp]:
        ops = []
        for row in self.db.execute("SELECT * FROM ops ORDER BY id").fetchall():
            if row["kind"] == "delete":
                event = ics.from_ics(row["raw"], row["calendar_id"], row["href"], row["etag"])[0]
            elif (current := self.get_event(row["uid"])) is not None:
                event = current
            else:  # deleted meanwhile; its delete op follows
                continue
            kind: OpKind = row["kind"]
            if kind != "delete":  # the event may have got its resource since it was queued
                kind = "update" if event.href else "create"
            ops.append(PendingOp(row["id"], kind, event))
        return ops

    def pending_count(self) -> int:
        """Number of queued edits not yet pushed to the server."""
        return int(self.db.execute("SELECT COUNT(*) FROM ops").fetchone()[0])

    def clear_op(self, op_id: int) -> None:
        with self._write():
            self.db.execute("DELETE FROM ops WHERE id = ?", (op_id,))

    def _queue(self, event: Event) -> None:
        """Queue a create/update; a later edit supersedes an unpushed one."""
        self.db.execute("DELETE FROM ops WHERE uid = ? AND kind != 'delete'", (event.uid,))
        self.db.execute(
            "INSERT INTO ops (kind, uid, calendar_id) VALUES (?, ?, ?)",
            ("update" if event.href else "create", event.uid, event.calendar_id),
        )

    def _queue_delete(self, event: Event) -> None:
        self.db.execute("DELETE FROM ops WHERE uid = ? AND kind != 'delete'", (event.uid,))
        if not event.href:
            return  # the server never saw it (or is being sent it: see ``_stored``)
        self.db.execute(
            "INSERT INTO ops (kind, uid, calendar_id, href, etag, raw) VALUES (?, ?, ?, ?, ?, ?)",
            ("delete", event.uid, event.calendar_id, event.href, event.etag, ics.to_ics(event)),
        )

    def _put(self, e: Event) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                e.uid,
                utc_stamp(e.recurrence_id) if e.recurrence_id else "",
                e.calendar_id,
                e.summary,
                e.start.isoformat(),
                e.end.isoformat(),
                e.start.tzinfo.key if isinstance(e.start.tzinfo, ZoneInfo) else "",
                e.all_day,
                e.location,
                e.description,
                e.rrule,
                json.dumps([x.isoformat() for x in e.exdates]),
                e.etag,
                e.href,
                e.raw,
                utc_stamp(e.start),
                utc_stamp(e.end),
            ),
        )


def _event(row: sqlite3.Row) -> Event:
    zone = ZoneInfo(row["tz"]) if row["tz"] else None

    def in_zone(dt: datetime) -> datetime:
        return dt.astimezone(zone) if zone else dt

    def load(text: str) -> datetime:
        return in_zone(datetime.fromisoformat(text))

    start, end = load(row["start"]), load(row["end"])
    if row["all_day"]:  # dates are local, wherever the cache was written
        start, end = local_midnight(start.date()), local_midnight(end.date())
    rid = row["recurrence_id"]
    recurrence_id = in_zone(datetime.strptime(rid, UTC_STAMP).replace(tzinfo=UTC)) if rid else None
    return Event(
        uid=row["uid"],
        calendar_id=row["calendar_id"],
        summary=row["summary"],
        start=start,
        end=end,
        all_day=bool(row["all_day"]),
        location=row["location"],
        description=row["description"],
        rrule=row["rrule"],
        recurrence_id=recurrence_id,
        exdates=tuple(load(x) for x in json.loads(row["exdates"])),
        etag=row["etag"],
        href=row["href"],
        raw=row["raw"],
    )
