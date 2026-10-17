"""Undo/redo, persistent history and detection of changes made by the game."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import not_running
from wzce.core import ConfigDocument, SettingsFileSet
from wzce.core.document import ValueChange
from wzce.core.history import EntryKind, HistoryStore
from wzce.core.session import EditorSession
from wzce.core.undo import MERGE_WINDOW_S, CommandKind, UndoCommand, UndoStack


@pytest.fixture
def session(cod25_set: SettingsFileSet) -> EditorSession:
    return EditorSession(cod25_set, game_running=not_running)


def _value(session: EditorSession, setting_id: str) -> str:
    return session.document.get(setting_id).raw_value


def _game_writes(fileset: SettingsFileSet, **values: object) -> None:
    """Simulate the game rewriting both slots with some values changed."""
    doc = fileset.load().document
    for key, value in values.items():
        doc.set_value(f"{key}@0", value, allow_read_only=True)
    for path in fileset.slots:
        path.write_bytes(doc.to_bytes())


# ------------------------------------------------------------- undo stack


def _edit(setting_id: str, old: str, new: str, t: float) -> UndoCommand:
    return UndoCommand(CommandKind.EDIT, [ValueChange(setting_id, old, new)], timestamp=t)


def test_stack_merges_quick_edits_of_same_setting() -> None:
    stack = UndoStack()
    stack.push(_edit("A@0", "1", "2", 0.0))
    stack.push(_edit("A@0", "2", "3", 0.5))
    assert stack.peek_undo().changes == [ValueChange("A@0", "1", "3")]
    stack.push(_edit("A@0", "3", "4", 0.5 + MERGE_WINDOW_S + 1))  # too late: new step
    stack.push(_edit("B@0", "x", "y", 10.0))  # other setting: new step
    assert len(stack._undo) == 3


def test_stack_drops_edit_that_returns_to_start() -> None:
    stack = UndoStack()
    stack.push(_edit("A@0", "1", "2", 0.0))
    stack.push(_edit("A@0", "2", "1", 0.1))
    assert not stack.can_undo


def test_stack_ignores_noop_and_clears_redo() -> None:
    stack = UndoStack()
    stack.push(_edit("A@0", "1", "1", 0.0))
    assert not stack.can_undo
    stack.push(_edit("A@0", "1", "2", 0.0))
    stack.take_undo()
    assert stack.can_redo
    stack.push(_edit("B@0", "1", "2", 5.0))
    assert not stack.can_redo


def test_stack_limit() -> None:
    stack = UndoStack(max_steps=3)
    for i in range(5):
        stack.push(_edit(f"S{i}@0", "0", "1", float(i * 10)))
    assert [c.setting_ids[0] for c in stack._undo] == ["S2@0", "S3@0", "S4@0"]


# ---------------------------------------------------------- session undo


def test_undo_redo_edits(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.undo_stack.peek_undo().timestamp = -100  # force a separate step
    session.set_value("ShaderQuality@0", "Medium")

    assert session.undo() == ["ShaderQuality@0"]
    assert _value(session, "ShaderQuality@0") == "Low"
    assert session.undo() == ["MaxFpsInGame@0"]
    assert not session.is_dirty
    assert session.undo() == []  # nothing left

    assert session.redo() == ["MaxFpsInGame@0"]
    assert session.redo() == ["ShaderQuality@0"]
    assert session.changed_ids() == {"MaxFpsInGame@0", "ShaderQuality@0"}


def test_revert_and_discard_are_undoable(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.revert("MaxFpsInGame@0")
    session.undo()
    assert _value(session, "MaxFpsInGame@0") == "144"

    session.set_value("ShaderQuality@0", "Medium")
    assert set(session.discard_all()) == {"MaxFpsInGame@0", "ShaderQuality@0"}
    assert not session.is_dirty
    assert set(session.undo()) == {"MaxFpsInGame@0", "ShaderQuality@0"}
    assert session.changed_ids() == {"MaxFpsInGame@0", "ShaderQuality@0"}


def test_undo_survives_save(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.save()
    assert not session.is_dirty
    session.undo()
    assert session.changed_ids() == {"MaxFpsInGame@0"}
    assert _value(session, "MaxFpsInGame@0") == "250"


def test_reload_clears_undo(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.reload()
    assert not session.undo_stack.can_undo


# ---------------------------------------------------------------- history


def test_save_records_history_entry(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.save(note="test")
    entries = session.history.list(session.fileset)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.kind is EntryKind.SAVE
    assert entry.note == "test"
    assert [(c.setting_id, c.old_raw, c.new_raw) for c in entry.changes] == [
        ("MaxFpsInGame@0", "250", "144")
    ]
    assert entry.load_snapshot().get("MaxFpsInGame@0").raw_value == "144"
    assert session.external_change is None  # our own save is not a "game change"


def test_first_open_records_nothing(session: EditorSession) -> None:
    assert session.history.list(session.fileset) == []
    assert session.external_change is None


def test_game_change_between_sessions_is_detected(cod25_set: SettingsFileSet) -> None:
    EditorSession(cod25_set, game_running=not_running)  # first run: remembers the file
    _game_writes(cod25_set, MaxFpsInGame=60, VSync="100%")

    session = EditorSession(cod25_set, game_running=not_running)
    entry = session.external_change
    assert entry is not None and entry.kind is EntryKind.GAME_CHANGE
    assert {c.setting_id for c in entry.changes} >= {"MaxFpsInGame@0", "VSync@0"}
    assert not session.is_dirty

    # "Undo the game's changes" = write the old values of just those settings.
    touched = session.apply_raw_values(entry.old_values())
    assert set(touched) >= {"MaxFpsInGame@0", "VSync@0"}
    assert _value(session, "MaxFpsInGame@0") == "250"
    session.undo()  # one step undoes the whole restore
    assert not session.is_dirty

    session.acknowledge_external_change()
    assert session.external_change is None


def test_game_change_while_open_is_detected_on_reload(session: EditorSession) -> None:
    _game_writes(session.fileset, ShowFPSCounter=True)
    assert session.disk_changed()
    session.reload()
    assert session.external_change is not None
    assert [c.setting_id for c in session.external_change.changes] == ["ShowFPSCounter@0"]


def test_restore_snapshot_into_working_copy(session: EditorSession) -> None:
    session.set_value("MaxFpsInGame@0", 144)
    session.save()
    session.set_value("MaxFpsInGame@0", 200)
    session.save()

    oldest = session.history.list(session.fileset)[-1]
    touched = session.restore_snapshot(oldest.load_snapshot())
    assert touched == ["MaxFpsInGame@0"]
    assert _value(session, "MaxFpsInGame@0") == "144"
    assert session.is_dirty  # restoring only edits the working copy


def test_apply_raw_values_skips_unknown_ids(session: EditorSession) -> None:
    assert session.apply_raw_values({"MotionBlur@0": "Off"}) == []  # cod26-only key
    assert not session.undo_stack.can_undo


def test_history_prune_and_damaged_entries(cod25_set: SettingsFileSet, tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history")
    base = cod25_set.load().document
    for fps in (100, 110, 120):
        after = base.copy()
        after.set_value("MaxFpsInGame@0", fps)
        store.record(cod25_set, EntryKind.SAVE, base, after)
    (store.folder(cod25_set) / "broken.json").write_text("{nope", encoding="utf-8")
    assert len(store.list(cod25_set)) == 3
    assert store.prune(cod25_set, keep=1) == 2
    remaining = store.list(cod25_set)
    assert remaining[0].changes[0].new_raw == "120"


def test_record_without_changes_returns_none(cod25_set: SettingsFileSet, tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history")
    doc = cod25_set.load().document
    assert store.record(cod25_set, EntryKind.SAVE, doc, doc.copy()) is None


def test_history_folders_are_per_directory(players_dir: Path, tmp_path: Path) -> None:
    store = HistoryStore(tmp_path / "history")
    a = SettingsFileSet.from_path(players_dir / "s.1.0.cod25.txt0")
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    b = SettingsFileSet(other_dir, "s.1.0.cod25", is_ab=True)
    assert store.folder(a) != store.folder(b)


def test_corrupted_last_seen_behaves_like_first_run(session: EditorSession) -> None:
    marker = session.history.folder(session.fileset) / "last_seen.snapshot"
    marker.write_bytes(b"garbage")
    assert session.history.check_external_change(session.fileset, session.original) is None
    assert ConfigDocument.from_bytes(marker.read_bytes()).values() == session.original.values()


def test_game_float_round_off_is_not_a_change(session: EditorSession) -> None:
    """The game rewrites 119.900000 as 119.900002 - not a game change, not a pending edit."""
    session.set_value("VoiceVolume@0", 0.75)
    session.save()
    path = session.fileset.slots[0]
    for slot in session.fileset.slots:
        slot.write_bytes(slot.read_bytes().replace(b"= 0.750000 //", b"= 0.750001 //"))
    assert b"0.750001" in path.read_bytes()
    session.reload()
    assert session.external_change is None
    assert not session.is_changed("VoiceVolume@0")
