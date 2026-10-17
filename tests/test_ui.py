"""GUI behaviour (pytest-qt, offscreen). Works on copies of the sample files only."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel

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
        system_info_provider=None,  # no real WMI/PowerShell probe in tests
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


# ------------------------------------------------------- stage 5: templates


def _templates_dialog(window: MainWindow):
    from wzce.ui.templates_dialog import TemplatesDialog

    dialog = TemplatesDialog(
        window.session, window.knowledge, window.tr, window.template_store, parent=window
    )
    dialog.errors = []
    dialog._show_error = dialog.errors.append
    dialog._ask = lambda *_a: True
    return dialog


def test_templates_dialog_previews_builtin_preset(window: MainWindow) -> None:
    dialog = _templates_dialog(window)
    names = [t.name for t in dialog.templates]
    assert names[:4] == ["Competitive", "Balanced", "Quality", "Low-end PC / laptop"]
    assert dialog.current_template.builtin_id == "competitive"
    plan = dialog.plan
    assert plan.changes and dialog.table.rowCount() == len(plan.changes)
    assert dialog.apply_button.text() == f"Apply selected ({len(plan.changes)})"
    assert not dialog.delete_button.isEnabled()  # built-ins cannot be deleted
    dialog._set_all_checked(False)
    assert not dialog.apply_button.isEnabled()


def test_apply_template_with_unchecked_rows(window: MainWindow) -> None:
    planned = {}

    def run(dialog) -> bool:
        dialog.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
        planned["kept"] = set(dialog.checked_ids())
        planned["dropped"] = dialog.table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        dialog.apply_selected()
        return dialog.result() == dialog.DialogCode.Accepted

    window._exec_dialog = run
    window.open_templates()
    assert window.session.changed_ids() == planned["kept"]
    assert planned["dropped"] not in window.session.changed_ids()
    assert "Competitive" in window.statusBar().currentMessage()
    window.undo()  # the whole template is one step
    assert not window.session.is_dirty


def test_create_template_from_current_settings(window: MainWindow) -> None:
    dialog = _templates_dialog(window)
    dialog._edit_template_info = lambda default, groups: ("Moje FPS", "opis", ["quality"])
    template = dialog.create_from_current()
    assert template.path.exists()
    assert dialog.current_template.path == template.path
    assert {window.knowledge.entries[sid].group for sid in template.values} == {"quality"}
    assert dialog.delete_button.isEnabled()  # user templates can be deleted
    assert dialog.plan.changes == []  # identical to current settings
    assert "already match" in dialog.summary_label.text()


def test_import_game_file_export_and_delete(window: MainWindow, tmp_path: Path) -> None:
    from conftest import COD26_SINGLE

    dialog = _templates_dialog(window)
    dialog._edit_template_info = lambda default, groups: (default, "", groups)
    imported = dialog.import_path(COD26_SINGLE)
    assert imported.name == "s.1.0.cod26"
    assert imported.title_code == "cod26"
    assert "GPUName@0" not in imported.values  # hardware data stripped

    exported = dialog.export_to(tmp_path / "shared")
    assert exported.suffix == ".json" and exported.exists()
    again = dialog.import_path(exported)
    assert again.values == imported.values
    assert len(window.template_store.list()) == 2

    dialog.delete_selected()
    assert len(window.template_store.list()) == 1


def test_import_invalid_file_shows_error(window: MainWindow, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": true}', encoding="utf-8")
    dialog = _templates_dialog(window)
    assert dialog.import_path(bad) is None
    assert dialog.errors and "not a Warzone Config Editor template" in dialog.errors[0]


# ------------------------------------------------------- stage 6: optimizer


def _fake_hardware():
    from wzce.core.hardware import HardwareInfo

    return HardwareInfo(
        cpu_name="AMD Ryzen 7 9800X3D 8-Core Processor",
        physical_cores=8,
        logical_cores=16,
        ram_mb=65536,
        gpu_name="NVIDIA GeForce RTX 5090",
        gpu_vendor="nvidia",
        vram_mb=32607,
        refresh_hz=240,
        max_refresh_hz=240,
    )


def _optimizer_dialog(window: MainWindow, hardware=None):
    from wzce.ui.optimizer_dialog import OptimizerDialog

    return OptimizerDialog(
        window.session, window.knowledge, window.tr, hardware or _fake_hardware(), parent=window
    )


def _row_for(dialog, setting_id: str) -> int:
    for row in range(dialog.plan_table.table.rowCount()):
        if dialog.plan_table.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == setting_id:
            return row
    raise AssertionError(f"{setting_id} not in plan")


def test_optimizer_shows_hardware_and_reasons(window: MainWindow) -> None:
    dialog = _optimizer_dialog(window)
    labels = {k: v.text() for k, v in dialog.hardware_labels.items()}
    assert labels["Processor"].startswith("AMD Ryzen 7 9800X3D")
    assert labels["Cores"] == "8 physical / 16 threads"
    assert labels["VRAM"] == "32 GB"
    assert labels["Monitor"] == "240 Hz (max 240 Hz)"

    table = dialog.plan_table.table
    row = _row_for(dialog, "RendererWorkerCount@0")  # sample file has 9
    assert (table.item(row, 1).text(), table.item(row, 2).text()) == ("9", "8")
    assert table.item(row, 3).text() == "8 physical cores"
    row = _row_for(dialog, "MaxFpsInGame@0")
    assert table.item(row, 2).text() == "237 fps"
    assert "240 Hz" in table.item(row, 3).text()
    row = _row_for(dialog, "ShaderQuality@0")
    assert table.item(row, 3).text() == "Competitive preset"


def test_optimizer_bottleneck_changes_plan(window: MainWindow) -> None:
    from wzce.core.optimizer import Bottleneck, Goal

    dialog = _optimizer_dialog(window)
    dialog.set_choice(Goal.BALANCED, Bottleneck.CPU)
    row = _row_for(dialog, "GPUUploadHeaps@0")  # sample: true -> CPU-bound wants false
    assert dialog.plan_table.table.item(row, 3).text() == "CPU-bound"
    dialog.set_choice(Goal.BALANCED, Bottleneck.GPU)
    ids = {
        dialog.plan_table.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
        for r in range(dialog.plan_table.table.rowCount())
    }
    assert "GPUUploadHeaps@0" not in ids  # already true: nothing to change


def test_optimizer_with_unknown_hardware(window: MainWindow) -> None:
    from wzce.core.hardware import HardwareInfo

    dialog = _optimizer_dialog(window, HardwareInfo())
    assert dialog.hardware_labels["VRAM"].text() == "not detected"
    ids = {
        dialog.plan_table.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
        for r in range(dialog.plan_table.table.rowCount())
    }
    assert "RendererWorkerCount@0" not in ids  # needs a core count


def test_open_optimizer_applies_one_undo_step(window: MainWindow) -> None:
    window._hardware = _fake_hardware()

    def run(dialog) -> bool:
        dialog.apply_selected()
        return True

    window._exec_dialog = run
    window.open_optimizer()
    assert window.session.document.get("RendererWorkerCount@0").raw_value == "8"
    assert window.session.document.get("MaxFpsInGame@0").raw_value == "237"
    assert "optimized" in window.statusBar().currentMessage()
    window.undo()
    assert not window.session.is_dirty


def test_hardware_is_detected_once(window: MainWindow) -> None:
    calls = []
    window._hardware = None
    window._hardware_provider = lambda doc: calls.append(doc) or _fake_hardware()
    assert window.hardware.vram_mb == 32607
    assert window.hardware.vram_mb == 32607
    assert len(calls) == 1 and calls[0] is window.session.original


# ------------------------------------------------------------ stage 6: tools


def test_game_reset_sets_recommended_flag(window: MainWindow) -> None:
    window.request_game_reset()
    assert window.session.document.get("RecommendedSet@0").raw_value == "false"
    assert window.session.changed_ids() == {"RecommendedSet@0"}
    window._ask = lambda *_a: False
    window.undo()
    window.request_game_reset()  # declined
    assert not window.session.is_dirty


def test_read_only_lock_toggle(window: MainWindow) -> None:
    fileset = window.session.fileset
    window.set_files_read_only(True)
    assert fileset.is_read_only()
    assert window.read_only_action.isChecked()
    assert "read-only" in window.status_file.text()

    _edit(window, "MaxFpsInGame@0", 144)
    assert window.save() is True  # saving keeps working and keeps the lock
    assert fileset.is_read_only()

    window.set_files_read_only(False)
    assert not fileset.is_read_only()
    assert not window.read_only_action.isChecked()


def test_read_only_lock_needs_confirmation(window: MainWindow) -> None:
    window._ask = lambda *_a: False
    window.set_files_read_only(True)
    assert not window.session.fileset.is_read_only()
    assert not window.read_only_action.isChecked()


# --------------------------------------------------- stage 7: account files


def _open_by_stem(window: MainWindow, stem: str) -> None:
    for index in range(window.file_combo.count()):
        data = window.file_combo.itemData(index)
        if isinstance(data, SettingsFileSet) and data.stem == stem:
            window._on_file_activated(index)
            return
    raise AssertionError(f"{stem} not in the file list")


def test_account_files_are_listed_with_labels(window: MainWindow) -> None:
    labels = [window.file_combo.itemText(i) for i in range(window.file_combo.count())]
    assert "Black Ops 7 / Warzone · Account profile …0000" in labels
    assert "Black Ops 7 / Warzone · Account FOV …0000" in labels


def test_edit_and_save_account_sensitivity_and_fov(window: MainWindow, players_dir: Path) -> None:
    _open_by_stem(window, "g.cod25.1.0.l")
    assert window.is_account_file()
    nav = [window.nav.item(i).text() for i in range(window.nav.count())]
    assert any(text.startswith("Aim & field of view") for text in nav)

    account = players_dir / "76561190000000000"
    marker_before = (account / "g.cod25.1.0.l.m").read_bytes()
    _edit(window, "Fov@1", 105)
    _edit(window, "MouseHorizontalSensibility@0", 6.5)
    card = window.cards["MouseHorizontalSensibility@0"]
    assert card.entry.label["en"] == "Mouse sensitivity"
    assert window.save() is True

    for slot in ("txt0", "txt1"):
        doc = ConfigDocument.from_bytes((account / f"g.cod25.1.0.l.{slot}").read_bytes())
        assert doc.get("Fov@1").raw_value == "105.000000"
        assert doc.get("MouseHorizontalSensibility@0").raw_value == "6.500000"
    assert (account / "g.cod25.1.0.l.m").read_bytes() == marker_before


def test_switching_between_account_and_machine_files(window: MainWindow) -> None:
    _open_by_stem(window, "g.cod25.pm.1.0.l")
    assert window.is_account_file()
    _open_by_stem(window, "s.1.0.cod25")
    assert not window.is_account_file()


def test_template_from_account_file_keeps_aim_settings(window: MainWindow) -> None:
    from wzce.core.templates import template_from_document

    _open_by_stem(window, "g.cod25.1.0.l")
    template = template_from_document(
        window.session.document, window.knowledge, "My aim", groups=["aim"]
    )
    assert {"Fov@1", "MouseHorizontalSensibility@0", "ADSSensitivity@1"} <= set(template.values)


def test_fov_changes_by_whole_degrees(window: MainWindow) -> None:
    """Regression: one arrow click used to set FOV to 119.9, shown in game as 120."""
    _open_by_stem(window, "g.cod25.1.0.l")
    window.navigate_to("Fov@1")
    editor = window.cards["Fov@1"].editor
    assert editor.spin.decimals() == 0
    assert editor.spin.singleStep() == 1
    editor.spin.stepBy(-1)
    assert window.session.document.get("Fov@1").raw_value == "119.000000"
    editor.slider.setValue(editor.slider.value() - 7)  # keyboard-like move snaps to degrees
    value = float(window.session.document.get("Fov@1").raw_value)
    assert value == int(value)


# ------------------------------------------- stage 9: hardware bar & checks


def _system_fixture():
    from test_system import _info

    return _info()


def _with_system(window: MainWindow, refresh=(240, 240)):
    from wzce.core.hardware import HardwareInfo

    window._hardware = HardwareInfo(
        gpu_name="NVIDIA GeForce RTX 5090",
        gpu_vendor="nvidia",
        vram_mb=32607,
        refresh_hz=refresh[0],
        max_refresh_hz=refresh[1],
        physical_cores=8,
        logical_cores=16,
    )
    window._on_system_info(_system_fixture())
    return window


def test_hardware_bar_loading_then_data(window: MainWindow) -> None:
    assert window.hw_bar.summary.text() == "Detecting hardware…"
    assert window.hw_bar.checks_button.isHidden()
    _with_system(window)
    text = window.hw_bar.summary.text()
    assert "Ryzen 7 9800X3D · 8C/16T" in text
    assert "64 GB DDR5 · 4800 MT/s ⚠" in text  # EXPO off is flagged
    assert "RTX 5090 · 32 GB" in text
    assert "Game: G: SATA SSD" in text
    assert window.hw_bar.checks_button.text() == "System check: 2 ⚠"
    assert window.hardware.rebar is True  # merged from nvidia-smi data


def test_hardware_bar_collapse_is_remembered(window: MainWindow) -> None:
    _with_system(window)
    window.hw_bar.toggle.click()
    assert window.hw_bar.summary.isHidden()
    assert window.settings.hardware_bar_collapsed is True
    window.hw_bar.toggle.click()
    assert not window.hw_bar.summary.isHidden()


def test_system_dialog_spec_and_copy(window: MainWindow, qtbot) -> None:
    from PySide6.QtGui import QGuiApplication

    from wzce.ui.system_panel import SystemDialog, spec_text

    _with_system(window)
    dialog = SystemDialog(window.system_info, window.hardware, window.system_checks, window.tr)
    qtbot.addWidget(dialog)
    dialog.copy_spec()
    copied = QGuiApplication.clipboard().text()
    assert copied == spec_text(window.system_info, window.hardware, window.tr)
    for expected in (
        "[Processor]",
        "Cores / threads: 8 / 16",
        "L3 96 MB · 3D V-Cache",
        "EXPO / XMP: off - running at the default JEDEC speed",
        "P0 CHANNEL A / DIMM 1: PATRIOT · 6400 Series · 32 GB · 1.10 V · rated 6400 MT/s",
        "PCIe link: PCIe 5.0 x16 (max 5.0 x16)",
        "Resizable BAR: on",
        "Monitor: MAG 321U X24 (2024)",
        "Disk: G: WDC WDS100T2G0A-00JH30 · SATA SSD",
        "Power plan: High performance",
    ):
        assert expected in copied, expected
    assert dialog.copied_label.text() == "Copied to clipboard."
    assert dialog.check_rows["expo"].property("status") == "warn"


def test_system_dialog_in_polish(window: MainWindow) -> None:
    from wzce.ui.system_panel import spec_text

    window.set_language("pl")
    _with_system(window)
    text = spec_text(window.system_info, window.hardware, window.tr)
    assert "[Pamięć RAM]" in text and "wyłączony — prędkość domyślna JEDEC" in text
    assert window.hw_bar.checks_button.text() == "Kontrola systemu: 2 ⚠"


def test_check_action_navigates_to_setting(window: MainWindow) -> None:
    import dataclasses

    info = _system_fixture()
    info.nvidia = dataclasses.replace(info.nvidia, bar1_mb=256)  # ReBAR off
    window._on_system_info(info)
    rebar = next(c for c in window.system_checks if c.id == "rebar")
    assert rebar.variant == "heaps"

    def run(dialog) -> bool:
        dialog.action_requested.emit("setting:GPUUploadHeaps@0")
        return True

    window._exec_dialog = run
    window.open_system_dialog(show_checks=True)
    assert "GPUUploadHeaps@0" in window.cards


def test_check_action_opens_windows_settings(window: MainWindow) -> None:
    opened = []
    window._open_external = opened.append
    _with_system(window, refresh=(60, 240))
    refresh = next(c for c in window.system_checks if c.id == "refresh")
    assert refresh.action == "ms-settings:display-advanced"

    def run(dialog) -> bool:
        dialog.action_requested.emit(refresh.action)
        return False

    window._exec_dialog = run
    window.open_system_dialog()
    assert opened == ["ms-settings:display-advanced"]


def test_optimizer_gets_system_hints_and_rebar(window: MainWindow) -> None:
    import dataclasses

    info = _system_fixture()
    info.nvidia = dataclasses.replace(info.nvidia, bar1_mb=256)  # ReBAR off
    window._on_system_info(info)
    captured = {}

    def run(dialog) -> bool:
        captured["hint"] = dialog.hint_label.text()
        captured["visible"] = not dialog.hint_label.isHidden()
        row = _row_for(dialog, "GPUUploadHeaps@0")
        captured["reason"] = dialog.plan_table.table.item(row, 3).text()
        return False

    window._exec_dialog = run
    window.open_optimizer()
    assert captured["visible"] and "Memory profile (EXPO/XMP)" in captured["hint"]
    assert captured["reason"] == "Resizable BAR is off"


def test_account_file_checks_use_machine_file(window: MainWindow) -> None:
    _open_by_stem(window, "g.cod25.1.0.l")
    _with_system(window)
    driver = next(c for c in window.system_checks if c.id == "driver")
    assert driver.status.value == "ok"  # recommended driver read from the machine file


def test_probe_signal_after_close_is_harmless(qtbot) -> None:
    from wzce.ui.system_panel import SystemProbe

    probe = SystemProbe()
    received = []
    probe.ready.connect(received.append)
    with qtbot.waitSignal(probe.ready, timeout=5000):
        probe.start(_system_fixture)
    assert received and received[0].cpu_cores == 8


# ------------------------------------------------ scroll position (bug fix)


def test_save_keeps_scroll_position(window: MainWindow, qtbot) -> None:
    """Regression: saving rebuilt the page and jumped back to the top of the list."""
    window.resize(1440, 800)
    window.show()
    window.navigate_to("ShaderQuality@0")  # long "Graphics quality" page
    bar = window.scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 1500)
    bar.setValue(1200)

    window.cards["ShaderQuality@0"].editor.edited.emit("Medium")
    assert window.save() is True
    qtbot.wait(20)
    assert bar.value() == 1200

    window.cards["ShaderQuality@0"].editor.edited.emit("Low")
    window.undo()
    qtbot.wait(20)
    assert bar.value() == 1200


def test_other_view_starts_at_top(window: MainWindow, qtbot) -> None:
    window.resize(1440, 800)
    window.show()
    window.navigate_to("ShaderQuality@0")
    bar = window.scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 1500)
    bar.setValue(1200)
    window.search.setText("vsync")  # a different view
    qtbot.wait(20)
    assert bar.value() == 0


def test_card_title_shows_original_file_name(window: MainWindow) -> None:
    window.navigate_to("DLSSModeMP@0")
    card = window.cards["DLSSModeMP@0"]
    assert card.key_label.text() == "(DLSSModeMP@0)"
    assert card.key_label.toolTip() == "Original setting name in the game file"
    # The key is shown once, next to the title - not repeated in the footer.
    keys = [w for w in card.findChildren(QLabel) if w.objectName() == "cardKey"]
    assert keys == [card.key_label]


# ------------------------------------------------------- share export (1.2.0)


def _share_dialog(window: MainWindow):
    captured = {}

    def run(dialog) -> bool:
        captured["dialog"] = dialog
        return True

    window._exec_dialog = run
    window.open_share_dialog()
    return captured["dialog"]


def test_share_dialog_markdown_and_json(window: MainWindow, tmp_path: Path) -> None:
    import json

    from PySide6.QtGui import QGuiApplication

    dialog = _share_dialog(window)
    checked = [gid for gid, c in dialog.group_checks.items() if c.isChecked()]
    assert checked == ["display", "performance", "upscaling", "quality"]
    text = dialog.preview.toPlainText()
    assert text.startswith("# Call of Duty settings — Black Ops 7 / Warzone")
    assert "## Display" in text and "`VSync@0`" in text
    assert "AmdAntilag2@0" not in text  # sample file reports an NVIDIA GPU

    dialog.copy()
    assert QGuiApplication.clipboard().text() == text

    dialog.json_radio.setChecked(True)
    data = json.loads(dialog.preview.toPlainText())
    assert data["title_code"] == "cod25"
    saved = dialog.save_to(tmp_path / "my-settings")
    assert saved.suffix == ".json" and json.loads(saved.read_text(encoding="utf-8")) == data

    for check in dialog.group_checks.values():
        check.setChecked(False)
    assert not dialog.copy_button.isEnabled()


def test_share_dialog_mentions_unsaved_changes(window: MainWindow) -> None:
    _edit(window, "ShaderQuality@0", "Medium")
    dialog = _share_dialog(window)
    assert "Shader quality:** Medium" in dialog.preview.toPlainText()
    labels = [w.text() for w in dialog.findChildren(QLabel)]
    assert "The export includes your unsaved changes." in labels


def test_share_dialog_for_account_file_preselects_its_groups(window: MainWindow) -> None:
    _open_by_stem(window, "g.cod25.1.0.l")
    dialog = _share_dialog(window)
    assert all(c.isChecked() for c in dialog.group_checks.values())
    assert "Field of view (FOV):** 120 °" in dialog.preview.toPlainText()


def test_share_dialog_includes_hardware_when_known(window: MainWindow) -> None:
    _with_system(window)
    dialog = _share_dialog(window)
    assert dialog.include_hardware.isChecked()
    text = dialog.preview.toPlainText()
    assert "## Hardware" in text and "EXPO/XMP off" in text
    dialog.include_hardware.setChecked(False)
    assert "## Hardware" not in dialog.preview.toPlainText()


# ------------------------------------------- stage 10c: Windows optimization tab


def _windows_dialog(window: MainWindow, info=None, tab: str = "windows"):
    from test_windows_checks import _users_pc

    window._on_system_info(info or _users_pc())
    captured = {}

    def run(dialog) -> bool:
        captured["dialog"] = dialog
        return False

    window._exec_dialog = run
    window.open_system_dialog(tab=tab)
    return captured["dialog"]


def test_windows_tab_groups_checks_by_section(window: MainWindow) -> None:
    from wzce.core.windows_checks import is_windows_check

    dialog = _windows_dialog(window)
    assert dialog.tabs.currentIndex() == 2
    assert dialog.tabs.tabText(2) == "Windows optimization"
    assert dialog.tabs.tabText(1) == "Hardware check"
    summary = dialog.windows_summary.text()
    assert summary == "Game requirements: met ✓ · To improve: 0 · Information: 7"
    headers = [header.text() for header, _rows in dialog._section_widgets]
    assert headers[0] == "GAME REQUIREMENTS (ANTI-CHEAT)" and "MOUSE AND NETWORK" in headers
    # Every check sits in exactly one tab: hardware rows are not repeated here.
    windows_rows = {c.id for _h, rows in dialog._section_widgets for _r, c in rows}
    assert windows_rows == {c.id for c in window.system_checks if is_windows_check(c.id)}
    assert "expo" not in windows_rows and "expo" in dialog.check_rows
    chips = [w.text() for w in dialog.findChildren(QLabel) if w.objectName() == "chip"]
    assert "Required by the game" in chips and "No effect on CoD" in chips


def test_windows_tab_filter_hides_ok_rows_myths_and_bios(window: MainWindow) -> None:
    dialog = _windows_dialog(window)
    dialog.show()
    assert dialog.check_rows["secure_boot"].isVisible() and dialog.myths_box.isVisible()
    dialog.only_problems_check.setChecked(True)
    assert not dialog.check_rows["secure_boot"].isVisible()
    assert dialog.check_rows["virtualization"].isVisible()  # information stays
    assert not dialog.myths_box.isVisible() and not dialog.bios_box.isVisible()
    requirements = dialog._section_widgets[0][0]
    assert not requirements.isVisible()  # all OK -> the section header hides too
    dialog.close()


def test_windows_action_in_tools_menu(window: MainWindow) -> None:
    assert not window.windows_action.isEnabled()  # no probe result yet
    assert window.windows_action.text() == "Windows optimization…"
    from test_windows_checks import _users_pc

    window._on_system_info(_users_pc())
    assert window.windows_action.isEnabled()
    opened = []
    window._exec_dialog = lambda dialog: opened.append(dialog.tabs.currentIndex()) or False
    window.windows_action.trigger()
    assert opened == [2]


def test_checks_button_lands_on_tab_with_warnings(window: MainWindow) -> None:
    import dataclasses

    from test_windows_checks import _users_pc

    info = _users_pc()
    info.windows.secure_boot = False  # only a Windows warning, hardware is fine
    info.memory = [dataclasses.replace(m, speed_mts=6000, voltage_mv=1350) for m in info.memory]
    nvme = next(d for d in info.drives if d.letter == "C")
    info.game_install = dataclasses.replace(info.game_install, drive=nvme)
    dialog = _windows_dialog(window, info, tab=None)
    assert dialog.tabs.currentIndex() == 0  # plain "details" opens the specification

    opened = []
    window._exec_dialog = lambda dialog: opened.append(dialog.tabs.currentIndex()) or False
    window.hw_bar.checks_requested.emit()
    assert opened == [2]
    window._on_system_info(_users_pc())  # EXPO off again: hardware warning first
    window.hw_bar.checks_requested.emit()
    assert opened == [2, 1]


def test_refresh_updates_the_open_dialog(window: MainWindow) -> None:
    from test_windows_checks import _users_pc

    fresh = _users_pc()
    fresh.windows.auto_hdr = False  # the user turned Auto HDR off meanwhile
    window._system_info_provider = lambda: fresh
    window._system_probe.start = lambda provider: window._on_system_info(provider())
    window._on_system_info(_users_pc())
    seen = {}

    def run(dialog) -> bool:
        assert dialog.refresh_button.isVisibleTo(dialog)
        assert dialog.check_rows["auto_hdr"].property("status") == "info"
        dialog.refresh_button.click()
        seen["status"] = dialog.check_rows["auto_hdr"].property("status")
        seen["tab"] = dialog.tabs.currentIndex()
        return False

    window._exec_dialog = run
    window.open_system_dialog(tab="windows")
    assert seen == {"status": "ok", "tab": 2}
    assert window._system_dialog is None


def test_windows_tab_in_polish(window: MainWindow) -> None:
    window.set_language("pl")
    dialog = _windows_dialog(window)
    assert dialog.tabs.tabText(2) == "Optymalizacja Windows"
    assert dialog.windows_summary.text().startswith("Wymagania gry: spełnione ✓")
    assert window.windows_action.text() == "Optymalizacja Windows…"
