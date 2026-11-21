"""A small month block (weekday initials + 6 week rows), shared by MiniCal and YearView."""

from collections.abc import Collection
from datetime import date

from rich.style import Style
from rich.text import Text

from tcal.ui.calgrid import month_weeks, weekday_names
from tcal.ui.theme import Palette

WIDTH = 20  # 7 two-character day cells, one space apart
HEIGHT = 7  # weekday initials + 6 weeks
WEEKS = 6


def mini_month(
    month: date,
    *,
    week_start: int,
    palette: Palette,
    today: date,
    selected: date,
    event_days: Collection[date],
    marked: Collection[date] = (),
    adjacent: bool = True,
) -> list[Text]:
    """``HEIGHT`` lines of ``WIDTH`` cells for the month of ``month``.

    Today is accented, ``selected`` highlighted, days with events bold and
    bright, days without dimmed, ``marked`` days (e.g. the shown week) get a
    band background and days of the adjacent months are faint (or left blank
    with ``adjacent=False``).
    """
    p = palette
    header = Text(" ".join(f"{name[0]:>2}" for name in weekday_names(week_start)))
    header.stylize(Style(color=p.foreground1, dim=True))
    lines = [header]
    for week in month_weeks(month.year, month.month, week_start, WEEKS):
        line = Text()
        for i, day in enumerate(week):
            if day.month != month.month:
                style = Style(color=p.background3)
            elif day in event_days:
                style = Style(color=p.foreground3, bold=True)
            else:
                style = Style(color=p.foreground1, dim=True)
            if day in marked:
                style += Style(bgcolor=p.background3)
            if day == selected:
                style += Style(bold=True, color=p.background1, bgcolor=p.foreground1, dim=False)
            if day == today:
                style += Style(bold=True, color=p.background1, bgcolor=p.primary, dim=False)
            if i:
                gap = (
                    Style(bgcolor=p.background3) if day in marked and week[i - 1] in marked else ""
                )
                line.append(" ", style=gap)
            if day.month == month.month or adjacent:
                line.append(f"{day.day:>2}", style=style)
            else:
                line.append("  ")
        lines.append(line)
    return lines


def day_at(month: date, week_start: int, x: int, y: int) -> date | None:
    """The day under offset (x, y) of a ``mini_month`` block, or None."""
    if not (1 <= y < HEIGHT and 0 <= x < WIDTH):
        return None
    return month_weeks(month.year, month.month, week_start, WEEKS)[y - 1][x // 3]
