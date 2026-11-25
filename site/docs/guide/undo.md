# Undo

`u` takes back the last change, `ctrl+r` makes it again.

![A move taken back](/screenshots/undo.svg)

Creating, editing, moving, resizing, pasting and deleting can all be undone, up
to the last 20 changes, for as long as tcal runs. A pasted batch is one step.
The message at the bottom right says what was undone, and the event is selected.

Undoing works on iCloud as well: a deleted event that was already synced is
created again, a move that reached the server is moved back.

After a new change there is nothing left to redo.
