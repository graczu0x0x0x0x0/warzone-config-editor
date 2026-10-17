"""GUI behaviour (pytest-qt, offscreen). Works on copies of the sample files only."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from wzce.core import ConfigDocument, KnowledgeBase, SettingsFileSet, Translator, discover
from wzce.ui.app_settings import AppSettings
from wzce.ui.editors import NumberEditor
from wzce.ui.main_window import NAV_CHANGED, MainWindow


class GameState:
    """Mutable stand-in for ``is_game_running`` so tests can start/stop the 'game'."""

    def __init__(self) -> None:
        self.running = False

    def __call__(self) -> bool:
        return self.running


@pytest.fixture(scope="module")
def knowledge() -> KnowledgeBase:
    return KnowledgeBase.load()


@pytest.fixture
def game() -> GameState:
    return GameState()


@pytest.fixture
def window(qtbot, players_dir: Path, tmp_path: Path, knowledge, game) -> MainWindow:
    settings = AppSettings(QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    settings.language = "en"
    settings.last_file = str(players_dir / "s.1.0.cod25.txt0")
    win = MainWindow(
        knowledge,
        Translator("en"),
        settings,
        locations=discover([players_dir]),
        game_running=game,
        poll=False,
    )
    win.messages = []  # type: ignore[attr-defined]
    # Replace every modal dialog: a real QMessageBox.exec() would block the test run
    # (e.g. the "unsaved changes" prompt when qtbot closes a dirty window).
    win._ask = lambda *_a: True
    win._prompt_unsaved = lambda _count: "discard"
    win._show_message = lambda level, title, text: win.messages.append((level, text))
    qtbot.addWidget(win)
    return win


def _disk_value(window: MainWindow, setting_id: str, slot: int = 0) -> str:
    path = window.session.fileset.slots[slot]
    return ConfigDocument.from_bytes(path.read_bytes()).get(setting_id).raw_value


# ------------------------------------------------------------------- startup


def test_opens_last_file_and_lists_files(window: MainWindow) -> None:
    assert window.session is not None
    assert window.session.fileset.stem == "s.1.0.cod25"
    labels = [window.file_combo.itemText(i) for i in range(window.file_combo.count())]
    assert labels[-1] == "Open another file…"
    assert any("Black Ops 7" in label for label in labels)
    assert window.cards, "default category should show cards"


# ------------------------------------------------------------- edit & save


def test_edit_shows_in_panel_and_saves_both_slots(window: MainWindow) -> None:
    window.navigate_to("MaxFpsInGame@0")
    card = window.cards["MaxFpsInGame@0"]
    card.editor.edited.emit(144)

    assert window.session.changed_ids() == {"MaxFpsInGame@0"}
    assert window.save_button.text() == "Save (1)"
    assert window.changes_panel.title.text().endswith("(1)")
    assert card.property("changed") is True

    assert window.save() is True
    assert _disk_value(window, "MaxFpsInGame@0", 0) == "144"
    assert _disk_value(window, "MaxFpsInGame@0", 1) == "144"
    assert not window.session.is_dirty
    assert window.session.backup_manager.list(window.session.fileset)


def test_invalid_value_is_rejected_and_card_resets(window: MainWindow) -> None:
    window.navigate_to("MaxFpsInGame@0")
    card = window.cards["MaxFpsInGame@0"]
    card.editor.edited.emit(999)
    assert not window.session.is_dirty
    assert "outside the range" in card.editor.toolTip()


def test_revert_from_changes_panel(window: MainWindow, qtbot) -> None:
    window.navigate_to("ShaderQuality@0")
    window.cards["ShaderQuality@0"].editor.edited.emit("Medium")
    window.changes_panel.revert_requested.emit("ShaderQuality@0")
    assert not window.session.is_dirty


def test_use_recommended_button(window: MainWindow) -> None:
    window.navigate_to("ShaderQuality@0")  # preset defaults to competitive -> Medium
    card = window.cards["ShaderQuality@0"]
    assert card.apply_recommended.isVisibleTo(card)
    card.apply_recommended.click()
    assert window.session.document.get("ShaderQuality@0").raw_value == "Medium"


def test_changed_view_drops_reverted_settings(window: MainWindow, qtbot) -> None:
    window.navigate_to("ShaderQuality@0")
    window.cards["ShaderQuality@0"].editor.edited.emit("Medium")
    window._nav_key = NAV_CHANGED
    window._render_all()
    assert set(window.cards) == {"ShaderQuality@0"}
    window.cards["ShaderQuality@0"].revert_requested.emit("ShaderQuality@0")
    qtbot.waitUntil(lambda: not window.cards)


def test_discard_all(window: MainWindow, qtbot) -> None:
    window.navigate_to("ShaderQuality@0")
    window.cards["ShaderQuality@0"].editor.edited.emit("Medium")
    window._discard_all()
    assert not window.session.is_dirty


# ------------------------------------------------------------- filtering


def test_search_finds_across_categories(window: MainWindow) -> None:
    window.search.setText("vram")
    assert "VideoMemoryScaleMP@0" in window.cards
    assert "TextureQuality@0" in window.cards
    window.search.setText("zzzz-nothing")
    assert window.cards == {}


def test_simple_mode_hides_advanced(window: MainWindow) -> None:
    window.advanced_check.setChecked(False)
    window.navigate_to("DisplayMode@0")
    assert "WindowWidth@0" not in window.cards
    window.advanced_check.setChecked(True)
    assert "WindowWidth@0" in window.cards


def test_vendor_filter_hides_other_gpu_vendors(window: MainWindow) -> None:
    window.vendor_check.setChecked(True)  # sample file reports an NVIDIA GPU
    window.navigate_to("NvidiaReflex@0")
    assert "NvidiaReflex@0" in window.cards
    assert "AmdAntilag2@0" not in window.cards
    window.vendor_check.setChecked(False)
    assert "AmdAntilag2@0" in window.cards


def test_read_only_setting_needs_unlock(window: MainWindow) -> None:
    window.advanced_check.setChecked(True)
    window.navigate_to("DetectedMemoryAmountMB@0")
    card = window.cards["DetectedMemoryAmountMB@0"]
    assert not card.editor.isEnabled()
    card.unlock_button.click()
    assert card.editor.isEnabled()


# ----------------------------------------------------------- game / disk


def test_running_game_blocks_saving(window: MainWindow, game: GameState) -> None:
    window.navigate_to("MaxFpsInGame@0")
    window.cards["MaxFpsInGame@0"].editor.edited.emit(144)
    game.running = True
    window._poll()
    assert not window.save_button.isEnabled()
    assert window.game_pill.property("running") is True
    assert window.save() is False
    assert window.messages and window.messages[-1][0] == "warning"
    assert _disk_value(window, "MaxFpsInGame@0") == "250"


def test_clean_session_reloads_when_game_writes(window: MainWindow) -> None:
    path = window.session.fileset.slots[window.session.fileset.active_slot_index()]
    doc = ConfigDocument.from_bytes(path.read_bytes())
    doc.set_value("MaxFpsInGame@0", 165)
    path.write_bytes(doc.to_bytes())
    window._poll()
    assert window.session.document.get("MaxFpsInGame@0").raw_value == "165"


# ------------------------------------------------------- language / close


def test_language_switch_relabels_everything(window: MainWindow) -> None:
    window.set_language("pl")
    assert window.save_button.text() == "Zapisz"
    assert window.nav.item(0).text() == "Wszystkie ustawienia"
    assert window.settings.language == "pl"
    assert window.cards  # page rebuilt
    window.set_language("en")
    assert window.save_button.text() == "Save"


def test_close_with_unsaved_changes_can_be_cancelled(window: MainWindow) -> None:
    window.show()
    window.navigate_to("MaxFpsInGame@0")
    window.cards["MaxFpsInGame@0"].editor.edited.emit(144)
    window._prompt_unsaved = lambda _count: "cancel"
    window.close()
    assert window.isVisible()
    window._prompt_unsaved = lambda _count: "discard"
    window.close()
    assert not window.isVisible()


def test_switching_file_asks_about_unsaved(window: MainWindow, players_dir: Path) -> None:
    window.navigate_to("MaxFpsInGame@0")
    window.cards["MaxFpsInGame@0"].editor.edited.emit(144)
    window._prompt_unsaved = lambda _count: "save"
    cod26_index = next(
        i
        for i in range(window.file_combo.count())
        if isinstance(window.file_combo.itemData(i), SettingsFileSet)
        and window.file_combo.itemData(i).stem == "s.1.0.cod26"
    )
    window._on_file_activated(cod26_index)
    assert window.session.fileset.stem == "s.1.0.cod26"
    cod25 = SettingsFileSet.from_path(players_dir / "s.1.0.cod25.txt0")
    assert cod25.load().document.get("MaxFpsInGame@0").raw_value == "144"


# ------------------------------------------------------------- editors


def test_percent_editor_emits_fraction(qtbot) -> None:
    editor = NumberEditor(is_float=True, minimum=0.0, maximum=2.0, with_slider=True, percent=True)
    qtbot.addWidget(editor)
    editor.set_raw("0.500000")
    assert editor.spin.value() == pytest.approx(50.0)
    with qtbot.waitSignal(editor.edited) as blocker:
        editor.spin.setValue(75.0)
    assert blocker.args == [pytest.approx(0.75)]


def test_wheel_does_not_change_unfocused_slider(qtbot) -> None:
    editor = NumberEditor(is_float=False, minimum=0, maximum=100, with_slider=True)
    qtbot.addWidget(editor)
    editor.set_raw("50")
    slider = editor.slider
    event = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )  # fmt: skip
    QApplication.sendEvent(slider, event)
    assert slider.value() == 50


# ------------------------------------------------------- stage 4: undo/redo


def _edit(window: MainWindow, setting_id: str, value: object) -> None:
    window.navigate_to(setting_id)
    window.cards[setting_id].editor.edited.emit(value)
    # Make the next edit a separate undo step regardless of timing.
    window.session.undo_stack.peek_undo().timestamp = -100


def test_undo_redo_buttons_and_tooltips(window: MainWindow) -> None:
    assert not window.undo_button.isEnabled()
    _edit(window, "MaxFpsInGame@0", 144)
    assert window.undo_button.isEnabled()
    assert "Max FPS in match" in window.undo_button.toolTip()

    window.undo()
    assert not window.session.is_dirty
    assert window.redo_button.isEnabled()
    assert window.cards["MaxFpsInGame@0"].editor.spin.value() == 250
    window.redo()
    assert window.session.changed_ids() == {"MaxFpsInGame@0"}


def test_undo_jumps_to_the_setting_on_another_page(window: MainWindow) -> None:
    _edit(window, "MaxFpsInGame@0", 144)
    window.navigate_to("Volume@0")  # audio page, the fps card is not shown
    assert "MaxFpsInGame@0" not in window.cards
    window.undo()
    assert "MaxFpsInGame@0" in window.cards


def test_discard_all_is_undoable_without_confirmation(window: MainWindow) -> None:
    window._ask = lambda *_a: pytest.fail("discard must not ask any more")
    _edit(window, "MaxFpsInGame@0", 144)
    _edit(window, "ShaderQuality@0", "Medium")
    window._discard_all()
    assert not window.session.is_dirty
    window.undo()
    assert window.session.changed_ids() == {"MaxFpsInGame@0", "ShaderQuality@0"}


# --------------------------------------------------------- stage 4: history


def test_history_dialog_lists_saves_with_diff(window: MainWindow, knowledge) -> None:
    from wzce.ui.history_dialog import HistoryDialog

    _edit(window, "MaxFpsInGame@0", 144)
    window.save()
    _edit(window, "ShaderQuality@0", "Medium")
    window.save()

    dialog = HistoryDialog(window.session, knowledge, window.tr)
    assert dialog.entry_list.count() == 2
    assert "Saved in editor" in dialog.entry_list.item(0).text()
    assert dialog.table.rowCount() == 1  # newest entry: ShaderQuality
    assert dialog.table.item(0, 0).text() == "Shader quality"
    assert (dialog.table.item(0, 1).text(), dialog.table.item(0, 2).text()) == ("Low", "Medium")
    dialog.close()


@pytest.mark.parametrize(("action", "expected_fps"), [("undo", "250"), ("restore", "144")])
def test_history_restore_actions(window: MainWindow, action: str, expected_fps: str) -> None:
    _edit(window, "MaxFpsInGame@0", 144)
    window.save()
    _edit(window, "MaxFpsInGame@0", 200)
    window.save()

    def run(dialog) -> bool:
        dialog.entry_list.setCurrentRow(1)  # the older save (250 -> 144)
        if action == "undo":
            dialog._choose_undo_entry()
        else:
            dialog._choose_restore_state()
        return True

    window._exec_dialog = run
    window.open_history()
    # Restoring only touches the working copy; it is one undoable step.
    assert window.session.document.get("MaxFpsInGame@0").raw_value == expected_fps
    assert _disk_value(window, "MaxFpsInGame@0") == "200"
    window.undo()
    assert not window.session.is_dirty


# ------------------------------------------------- stage 4: game changes


def _game_writes(window: MainWindow, **values: object) -> None:
    fileset = window.session.fileset
    doc = fileset.load().document
    for key, value in values.items():
        doc.set_value(f"{key}@0", value, allow_read_only=True)
    for path in fileset.slots:
        path.write_bytes(doc.to_bytes())


def test_game_change_shows_notice_and_can_be_undone(window: MainWindow) -> None:
    _game_writes(window, MaxFpsInGame=60, ShowFPSCounter=True)
    window._poll()  # clean session: reloads and detects the change
    assert not window.notice.isHidden()
    assert "Max FPS in match" in window.notice_text.text()

    window._on_notice_undo()
    assert window.notice.isHidden()
    assert window.session.document.get("MaxFpsInGame@0").raw_value == "250"
    assert window.session.document.get("ShowFPSCounter@0").raw_value == "false"
    assert window.session.is_dirty  # needs saving to take effect


def test_game_managed_changes_stay_quiet(window: MainWindow) -> None:
    _game_writes(window, DisplayDriverVersion="999.99", WindowX=100)
    window._poll()
    assert window.notice.isHidden()
    entries = window.session.history.list(window.session.fileset)
    assert entries and entries[0].kind.value == "game_change"  # still recorded


def test_notice_details_open_history_on_that_entry(window: MainWindow) -> None:
    _game_writes(window, MaxFpsInGame=60)
    window._poll()
    seen = {}

    def run(dialog) -> bool:
        seen["entry"] = dialog.current_entry
        return False

    window._exec_dialog = run
    window._on_notice_show()
    assert seen["entry"].id == window.session.external_change.id


def test_game_change_while_editing_only_warns(window: MainWindow) -> None:
    _edit(window, "ShaderQuality@0", "Medium")
    _game_writes(window, MaxFpsInGame=60)
    window._poll()
    assert window.session.is_dirty  # user's work is not thrown away
    assert window.session.document.get("MaxFpsInGame@0").raw_value == "250"
    assert window.notice.isHidden()


def test_saving_over_game_changes_asks_and_keeps_them_in_history(window: MainWindow) -> None:
    _edit(window, "ShaderQuality@0", "Medium")
    _game_writes(window, MaxFpsInGame=60)
    questions = []
    window._ask = lambda title, text: questions.append(text) or False
    assert window.save() is False  # declined
    assert _disk_value(window, "MaxFpsInGame@0") == "60"

    window._ask = lambda *_a: True
    assert window.save() is True
    kinds = [e.kind.value for e in window.session.history.list(window.session.fileset)]
    assert kinds == ["save", "game_change"]  # the overwritten game change is recoverable
