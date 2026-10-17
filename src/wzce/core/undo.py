"""Undo/redo for an editing session (Qt-free, so it is unit-testable).

A command is a list of ``ValueChange`` objects (old raw -> new raw per setting).
Undo writes every ``old_raw`` back, redo every ``new_raw``, always through
``ConfigDocument.restore_raw`` so values come back byte-identical.

Rapid edits of the same setting (spin box arrow clicks, typing digits) are merged
into one command when they arrive within ``MERGE_WINDOW_S`` - otherwise one
Ctrl+Z would only step back by a single click.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from .document import ValueChange

MERGE_WINDOW_S = 1.5
MAX_UNDO_STEPS = 500


class CommandKind(StrEnum):
    EDIT = "edit"  # user changed one value
    REVERT = "revert"  # user reverted one pending change
    DISCARD = "discard"  # "discard all"
    RESTORE = "restore"  # history version / entry restored into the working copy
    BULK = "bulk"  # several values at once (presets, recommendations - stage 5)


@dataclass(slots=True)
class UndoCommand:
    kind: CommandKind
    changes: list[ValueChange]
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def setting_ids(self) -> list[str]:
        return [c.setting_id for c in self.changes]

    def can_merge(self, other: UndoCommand) -> bool:
        """True when ``other`` (newer) continues editing the same single setting."""
        return (
            self.kind is CommandKind.EDIT
            and other.kind is CommandKind.EDIT
            and len(self.changes) == len(other.changes) == 1
            and self.changes[0].setting_id == other.changes[0].setting_id
            and other.timestamp - self.timestamp <= MERGE_WINDOW_S
        )


class UndoStack:
    def __init__(self, max_steps: int = MAX_UNDO_STEPS) -> None:
        self._undo: list[UndoCommand] = []
        self._redo: list[UndoCommand] = []
        self._max = max_steps

    def push(self, command: UndoCommand, *, allow_merge: bool = True) -> None:
        """Record an already-applied command. Clears the redo history."""
        command.changes = [c for c in command.changes if not c.is_noop]
        if not command.changes:
            return
        self._redo.clear()
        top = self._undo[-1] if self._undo else None
        if allow_merge and top is not None and top.can_merge(command):
            first, last = top.changes[0], command.changes[0]
            merged = ValueChange(first.setting_id, first.old_raw, last.new_raw)
            if merged.is_noop:
                self._undo.pop()  # edited back to where it started: nothing to undo
            else:
                top.changes = [merged]
                top.timestamp = command.timestamp
            return
        self._undo.append(command)
        if len(self._undo) > self._max:
            del self._undo[0]

    def take_undo(self) -> UndoCommand | None:
        if not self._undo:
            return None
        command = self._undo.pop()
        self._redo.append(command)
        return command

    def take_redo(self) -> UndoCommand | None:
        if not self._redo:
            return None
        command = self._redo.pop()
        command.timestamp = 0.0  # never merge a redone command with a later edit
        self._undo.append(command)
        return command

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def peek_undo(self) -> UndoCommand | None:
        return self._undo[-1] if self._undo else None

    def peek_redo(self) -> UndoCommand | None:
        return self._redo[-1] if self._redo else None

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
