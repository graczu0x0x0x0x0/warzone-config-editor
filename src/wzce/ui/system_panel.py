"""'Your hardware' bar, the hardware/system dialog and the background probe thread.

* ``SystemProbe`` runs ``collect_system_info`` (3-5 s of WMI queries) in a daemon
  thread and hands the result back through a Qt signal (queued to the UI thread).
  A daemon thread - unlike a QThread - never delays closing the app.
* ``HardwareBar`` is the compact, collapsible one-line summary under the header,
  with a button showing how many system checks need attention.
* ``SystemDialog`` has three tabs: the full specification (with "Copy specification"
  to the clipboard), the hardware check list, and "Windows optimization" - the
  Windows-settings checks grouped by section with an evidence chip per row, a
  "only what needs attention" filter, the myths list, a manual BIOS checklist and
  "Refresh" (the main window re-runs the probe and calls ``set_data``). Rows the app
  can change itself get a "Fix" button; changes it made are listed with "Restore".

``spec_rows`` builds the specification once for both the dialog and the clipboard
text, so they never disagree.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.hardware import HardwareInfo
from ..core.i18n import Translator
from ..core.system_checks import CheckResult, Severity, Status
from ..core.system_info import SystemInfo
from ..core.windows_checks import CHECKS, MYTHS, Impact, Section, is_windows_check
from ..core.windows_tweaks import AppliedTweak
from .theme import repolish

SpecRow = tuple[str, str, str]  # (section key, label, value)


class SystemProbe(QObject):
    """Runs the (slow) system probe in a background daemon thread."""

    ready = Signal(object)  # SystemInfo, delivered in the UI thread

    def start(self, provider: Callable[[], SystemInfo]) -> None:
        threading.Thread(target=self._run, args=(provider,), daemon=True).start()

    def _run(self, provider: Callable[[], SystemInfo]) -> None:
        try:
            info = provider()
        except Exception as exc:  # the provider should never raise, but be safe
            info = SystemInfo(errors=[str(exc)])
        # RuntimeError: the window was closed meanwhile and this object deleted.
        with contextlib.suppress(RuntimeError):
            self.ready.emit(info)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _gb(value: float | None) -> str:
    return f"{value:g} GB" if value is not None else "?"


def drive_kind_text(tr: Translator, kind: str) -> str:
    return tr(f"hw.kind_{kind}")


def spec_rows(info: SystemInfo, hardware: HardwareInfo | None, tr: Translator) -> list[SpecRow]:
    """The full specification as (section, label, value) rows; unknown values are skipped."""
    rows: list[SpecRow] = []

    def add(section: str, label_key: str, value: object | None) -> None:
        if value not in (None, "", []):
            rows.append((section, tr(label_key), str(value)))

    # --- CPU
    add("cpu", "spec.model", info.cpu_name)
    if info.cpu_cores:
        add("cpu", "spec.cores", f"{info.cpu_cores} / {info.cpu_threads or '?'}")
    if hardware and hardware.is_hybrid:
        add(
            "cpu",
            "spec.core_types",
            f"{hardware.performance_cores} P + {hardware.efficiency_cores} E",
        )
    if info.cpu_l3_kb:
        cache = f"L2 {(info.cpu_l2_kb or 0) // 1024} MB · L3 {info.cpu_l3_kb // 1024} MB"
        add("cpu", "spec.cache", cache + (" · 3D V-Cache" if info.x3d_cache else ""))
    add("cpu", "spec.socket", info.cpu_socket)
    add("cpu", "spec.base_clock", f"{info.cpu_base_mhz} MHz" if info.cpu_base_mhz else None)

    # --- memory
    if info.memory:
        total = f"{_gb(info.memory_total_gb)} {info.memory_type or ''}"
        summary = f"{total} · {len(info.memory)} x {_gb(info.memory[0].capacity_gb)}"
        add("memory", "spec.total", summary.replace("  ", " "))
        add(
            "memory",
            "spec.speed",
            f"{info.memory_speed_mts} MT/s" if info.memory_speed_mts else None,
        )
        state = info.expo_xmp
        add("memory", "spec.profile", tr(f"spec.profile_{state}"))
        add("memory", "spec.channels", info.memory_channels)
        if info.memory_slots:
            add("memory", "spec.slots", f"{len(info.memory)} / {info.memory_slots}")
        for module in info.memory:
            parts = [module.manufacturer, module.part_number, _gb(module.capacity_gb)]
            if module.voltage_mv:
                parts.append(f"{module.voltage_mv / 1000:.2f} V")
            if module.rated_speed_mts:
                rated = tr("spec.rated", speed=module.rated_speed_mts)
                parts.append(rated + (f" CL{module.rated_cl}" if module.rated_cl else ""))
            rows.append(("memory", module.slot, " · ".join(p for p in parts if p)))

    # --- GPU
    dedicated = info.dedicated_gpu or (info.gpus[0] if info.gpus else None)
    add(
        "gpu",
        "spec.model",
        dedicated.name if dedicated else (hardware.gpu_name if hardware else None),
    )
    if hardware and hardware.vram_mb:
        add("gpu", "spec.vram", f"{round(hardware.vram_mb / 1024)} GB")
    nv = info.nvidia
    if nv:
        add("gpu", "spec.driver", nv.driver_version)
        if nv.pcie_width:
            add(
                "gpu",
                "spec.pcie",
                f"PCIe {nv.pcie_gen}.0 x{nv.pcie_width} "
                f"(max {nv.pcie_gen_max}.0 x{nv.pcie_width_max})",
            )
        if nv.rebar_enabled is not None:
            add("gpu", "spec.rebar", tr("spec.enabled" if nv.rebar_enabled else "spec.disabled"))
        add("gpu", "spec.power_limit", f"{nv.power_limit_w:g} W" if nv.power_limit_w else None)
        add(
            "gpu",
            "spec.temperature",
            f"{nv.temperature_c} °C" if nv.temperature_c is not None else None,
        )
    elif dedicated:
        add("gpu", "spec.driver", f"{dedicated.driver_version} ({dedicated.driver_date or '?'})")
    if info.has_integrated_gpu:
        add("gpu", "spec.integrated", next(g.name for g in info.gpus if g.is_integrated))

    # --- display
    for monitor in info.monitors:
        add("display", "spec.monitor", monitor)
    if hardware and hardware.refresh_hz:
        add(
            "display",
            "spec.refresh",
            f"{hardware.refresh_hz} Hz (max {hardware.best_refresh_hz} Hz)",
        )

    # --- storage
    install = info.game_install
    if install:
        add("storage", "spec.install_path", install.path)
        if install.drive:
            kind = drive_kind_text(tr, install.drive.kind)
            add("storage", "spec.disk", f"{install.drive.letter}: {install.drive.disk} · {kind}")
        add("storage", "spec.free", _gb(install.free_gb) if install.free_gb is not None else None)

    # --- Windows & board
    windows = " ".join(x for x in (info.os_name, info.os_display_version) if x)
    add(
        "system", "spec.windows", f"{windows} (build {info.os_build})" if info.os_build else windows
    )
    add("system", "spec.board", info.board)
    if info.bios_version:
        add("system", "spec.bios", f"{info.bios_version} ({info.bios_date or '?'})")
    if info.power_plan:
        add("system", "spec.power_plan", tr(f"spec.plan_{info.power_plan}"))
    for key, value in (
        ("spec.hags", info.hags),
        ("spec.game_mode", info.game_mode),
        ("spec.recording", info.background_recording),
        ("spec.hvci", info.hvci_running),
    ):
        if value is not None:
            add("system", key, tr("spec.enabled" if value else "spec.disabled"))
    return rows


def spec_text(info: SystemInfo, hardware: HardwareInfo | None, tr: Translator) -> str:
    """Plain-text specification for the clipboard (Discord / forums)."""
    lines = [f"{tr('app.title')} — {tr('spec.title')}"]
    section = None
    for row_section, label, value in spec_rows(info, hardware, tr):
        if row_section != section:
            section = row_section
            lines.append(f"\n[{tr(f'spec.section_{section}')}]")
        lines.append(f"{label}: {value}")
    return "\n".join(lines) + "\n"


def bar_items(info: SystemInfo, hardware: HardwareInfo | None, tr: Translator) -> list[str]:
    """Short chips for the one-line hardware bar."""
    items = []
    if info.cpu_name:
        cpu = info.cpu_name.replace("Processor", "").replace("8-Core", "").split("@")[0]
        cpu = " ".join(cpu.replace("AMD ", "").replace("Intel(R) Core(TM) ", "").split())
        cores = f" · {info.cpu_cores}C/{info.cpu_threads}T" if info.cpu_cores else ""
        items.append(cpu + cores)
    if info.memory:
        expo = " ⚠" if info.expo_xmp == "off" else ""
        total = f"{_gb(info.memory_total_gb)} {info.memory_type or ''}"
        items.append(f"{total} · {info.memory_speed_mts} MT/s{expo}")
    gpu = (
        info.dedicated_gpu.name if info.dedicated_gpu else (hardware.gpu_name if hardware else None)
    )
    if gpu:
        gpu = gpu.replace("NVIDIA GeForce ", "").replace("AMD Radeon ", "Radeon ")
        vram = f" · {round(hardware.vram_mb / 1024)} GB" if hardware and hardware.vram_mb else ""
        items.append(gpu + vram)
    if hardware and hardware.refresh_hz:
        monitor = info.monitors[0].split(" (")[0] if info.monitors else ""
        items.append(f"{monitor} · {hardware.refresh_hz} Hz".strip(" ·"))
    if info.game_install and info.game_install.drive:
        drive = info.game_install.drive
        items.append(tr("hw.game_drive", letter=drive.letter, kind=drive_kind_text(tr, drive.kind)))
    return items


# ---------------------------------------------------------------------------
# Hardware bar
# ---------------------------------------------------------------------------


class HardwareBar(QFrame):
    details_requested = Signal()
    checks_requested = Signal()
    collapsed_changed = Signal(bool)

    def __init__(
        self, tr: Translator, collapsed: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("hwBar")
        self._tr = tr
        self._collapsed = collapsed
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 5, 12, 5)
        layout.setSpacing(10)
        self.toggle = QPushButton()
        self.toggle.setProperty("variant", "ghost")
        self.toggle.clicked.connect(self._toggle)
        layout.addWidget(self.toggle)
        self.title = QLabel()
        self.title.setObjectName("hwTitle")
        layout.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setObjectName("hwSummary")
        layout.addWidget(self.summary, 1)
        self.checks_button = QPushButton()
        self.checks_button.setObjectName("hwChecks")
        self.checks_button.clicked.connect(self.checks_requested)
        layout.addWidget(self.checks_button)
        self.details_button = QPushButton()
        self.details_button.setProperty("variant", "ghost")
        self.details_button.clicked.connect(self.details_requested)
        layout.addWidget(self.details_button)
        self._items: list[str] = []
        self._warnings: int | None = None
        self.set_loading()

    def set_loading(self) -> None:
        self._items, self._warnings = [], None
        self.refresh_texts()

    def set_data(self, items: list[str], warning_count: int) -> None:
        self._items, self._warnings = items, warning_count
        self.refresh_texts()

    def refresh_texts(self) -> None:
        tr = self._tr
        self.title.setText(tr("hw.title"))
        self.toggle.setText("▸" if self._collapsed else "▾")
        self.toggle.setToolTip(tr("hw.expand" if self._collapsed else "hw.collapse"))
        self.details_button.setText(tr("hw.details"))
        if self._warnings is None:
            self.summary.setText(tr("hw.loading"))
            self.checks_button.hide()
            self.details_button.setEnabled(False)
        else:
            self.summary.setText("   ▸ ".join(self._items) if self._items else tr("hw.unavailable"))
            self.checks_button.show()
            self.details_button.setEnabled(True)
            warn = self._warnings > 0
            self.checks_button.setText(
                tr("hw.checks_warn", count=self._warnings) if warn else tr("hw.checks_ok")
            )
            self.checks_button.setProperty("warn", warn)
            repolish(self.checks_button)
        self.summary.setVisible(not self._collapsed)
        self.details_button.setVisible(not self._collapsed)

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self.refresh_texts()
        self.collapsed_changed.emit(self._collapsed)

    @property
    def collapsed(self) -> bool:
        return self._collapsed


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


# Glyphs chosen on purpose (status icons in the check list).
STATUS_ICONS = {Status.WARN: "⚠", Status.INFO: "ℹ", Status.OK: "✓", Status.UNKNOWN: "–"}  # noqa: RUF001


class SystemDialog(QDialog):
    """Specification, hardware checks and the Windows optimization tab."""

    action_requested = Signal(str)  # check action: URI or "setting:Key@0"
    refresh_requested = Signal()  # run the system probe again (Windows tab)
    tweak_requested = Signal(str)  # tweak id - the app changes a Windows setting
    restore_requested = Signal(str)  # journal entry id; "" = restore everything

    TABS = ("spec", "checks", "windows")

    def __init__(
        self,
        info: SystemInfo,
        hardware: HardwareInfo | None,
        checks: list[CheckResult],
        tr: Translator,
        *,
        show_checks: bool = False,
        tab: str | None = None,
        can_refresh: bool = False,
        fixable: dict[str, str] | None = None,
        applied: list[AppliedTweak] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = tr
        self._can_refresh = can_refresh
        self.only_problems = False
        self.setWindowTitle(tr("spec.title"))
        self.resize(1000, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.set_data(info, hardware, checks, fixable, applied)
        if tab is None and show_checks:
            tab = default_checks_tab(checks)
        if tab in self.TABS:
            self.tabs.setCurrentIndex(self.TABS.index(tab))

        buttons = QHBoxLayout()
        self.copy_button = QPushButton(tr("spec.copy"))
        self.copy_button.clicked.connect(self.copy_spec)
        buttons.addWidget(self.copy_button)
        self.copied_label = QLabel()
        self.copied_label.setObjectName("cardRecommend")
        buttons.addWidget(self.copied_label)
        buttons.addStretch()
        close = QPushButton(tr("dialog.close"))
        close.setProperty("variant", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def set_data(
        self,
        info: SystemInfo,
        hardware: HardwareInfo | None,
        checks: list[CheckResult],
        fixable: dict[str, str] | None = None,
        applied: list[AppliedTweak] | None = None,
    ) -> None:
        """(Re)build every tab - after "Refresh", a fix or a restore as well.

        ``fixable`` maps check ids to the tweak the app can apply for them;
        ``applied`` is the journal of changes the app made (restorable).
        """
        self._info, self._hardware, self._checks = info, hardware, checks
        self._fixable = fixable or {}
        self._applied = applied or []
        current = self.tabs.currentIndex()
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        tr = self._tr
        self.check_rows: dict[str, QFrame] = {}
        self.fix_buttons: dict[str, QPushButton] = {}
        self.restore_buttons: dict[str, QPushButton] = {}
        self.tabs.addTab(self._spec_tab(), tr("spec.tab_spec"))
        hardware_checks = [c for c in checks if not is_windows_check(c.id)]
        self.tabs.addTab(self._checks_tab(hardware_checks), tr("spec.tab_checks"))
        self.tabs.addTab(self._windows_tab(), tr("win.tab"))
        if current >= 0:
            self.tabs.setCurrentIndex(current)

    # ------------------------------------------------------------------ spec
    def _spec_tab(self) -> QWidget:
        tr = self._tr
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)
        row = 0
        section = None
        for row_section, label, value in spec_rows(self._info, self._hardware, tr):
            if row_section != section:
                section = row_section
                header = QLabel(tr(f"spec.section_{section}").upper())
                header.setObjectName("subgroupTitle")
                grid.addWidget(header, row, 0, 1, 2)
                row += 1
            key = QLabel(label)
            key.setObjectName("cardDesc")
            grid.addWidget(key, row, 0)
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(value_label, row, 1)
            row += 1
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(row, 1)
        return self._scroll(host)

    def copy_spec(self) -> None:
        QGuiApplication.clipboard().setText(spec_text(self._info, self._hardware, self._tr))
        self.copied_label.setText(self._tr("spec.copied"))

    # ---------------------------------------------------------------- checks
    def _checks_tab(self, checks: list[CheckResult]) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        warn = sum(1 for c in checks if c.status is Status.WARN)
        ok = sum(1 for c in checks if c.status is Status.OK)
        summary = QLabel(self._tr("checks.summary", warnings=warn, ok=ok))
        summary.setObjectName("panelTitle")
        layout.addWidget(summary)
        note = QLabel(self._tr("checks.note"))
        note.setObjectName("cardDesc")
        note.setWordWrap(True)
        layout.addWidget(note)
        for check in checks:
            row = self._check_row(check)
            self.check_rows[check.id] = row
            layout.addWidget(row)
        layout.addStretch()
        return self._scroll(host)

    def _check_row(self, check: CheckResult, impact: Impact | None = None) -> QFrame:
        tr = self._tr
        frame = QFrame()
        frame.setObjectName("checkRow")
        frame.setProperty("status", check.status.value)
        frame.setProperty("severity", check.severity.value if check.severity else "")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        icon = QLabel(STATUS_ICONS[check.status])
        icon.setObjectName("checkIcon")
        icon.setProperty("status", check.status.value)
        layout.addWidget(icon)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        title_label = QLabel(check_title(check, tr))
        title_label.setObjectName("cardTitle")
        heading.addWidget(title_label)
        if impact is not None:
            chip = QLabel(tr(f"win.impact.{impact.value}"))
            chip.setObjectName("chip")
            chip.setProperty("kind", f"impact_{impact.value}")
            chip.setToolTip(tr(f"win.impact.{impact.value}_tip"))
            heading.addWidget(chip)
        heading.addStretch()
        texts.addLayout(heading)
        body = QLabel(check_text(check, tr))
        body.setObjectName("cardDesc")
        body.setWordWrap(True)
        texts.addWidget(body)
        # Fix instructions only where there is something to do: warnings and information.
        if check.status in (Status.WARN, Status.INFO):
            fix = QLabel(tr(f"checks.{check.id}.fix", **check.params))
            fix.setObjectName("checkFix")
            fix.setWordWrap(True)
            texts.addWidget(fix)
        layout.addLayout(texts, 1)
        tweak = self._fixable.get(check.id) if impact is not None else None
        if tweak and check.status in (Status.WARN, Status.INFO):
            fix_button = QPushButton(tr("win.fix_button"))
            fix_button.setProperty("variant", "primary")
            fix_button.setToolTip(tr(f"tweaks.{tweak}.title"))
            fix_button.clicked.connect(lambda _=False, t=tweak: self.tweak_requested.emit(t))
            layout.addWidget(fix_button)
            self.fix_buttons[check.id] = fix_button
        if check.action and check.status in (Status.WARN, Status.INFO):
            button = QPushButton(action_label(check.action, tr))
            button.clicked.connect(lambda _=False, a=check.action: self.action_requested.emit(a))
            layout.addWidget(button)
        return frame

    # --------------------------------------------------------------- windows
    def _windows_tab(self) -> QWidget:
        tr = self._tr
        checks = [c for c in self._checks if is_windows_check(c.id)]
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.windows_summary = QLabel(windows_summary(checks, tr))
        self.windows_summary.setObjectName("panelTitle")
        self.windows_summary.setWordWrap(True)
        layout.addWidget(self.windows_summary)
        note = QLabel(tr("win.note"))
        note.setObjectName("cardDesc")
        note.setWordWrap(True)
        layout.addWidget(note)
        tools = QHBoxLayout()
        self.only_problems_check = QCheckBox(tr("win.only_problems"))
        self.only_problems_check.setChecked(self.only_problems)
        self.only_problems_check.toggled.connect(self._set_only_problems)
        tools.addWidget(self.only_problems_check)
        tools.addStretch()
        self.refresh_button = QPushButton(tr("win.refresh"))
        self.refresh_button.setToolTip(tr("win.refresh_tip"))
        self.refresh_button.setVisible(self._can_refresh)
        self.refresh_button.clicked.connect(self._request_refresh)
        tools.addWidget(self.refresh_button)
        layout.addLayout(tools)
        if self._applied:
            layout.addWidget(self._applied_section())

        # Rows grouped by section, in CHECKS order; problems first inside a section.
        self._section_widgets: list[tuple[QLabel, list[tuple[QFrame, CheckResult]]]] = []
        order = {check_id: i for i, check_id in enumerate(CHECKS)}
        for section in Section:
            in_section = sorted(
                (c for c in checks if CHECKS[c.id][0] is section),
                key=lambda c: (c.sort_key[0], order[c.id]),
            )
            if not in_section:
                continue
            header = QLabel(tr(f"win.section.{section.value}").upper())
            header.setObjectName("subgroupTitle")
            layout.addWidget(header)
            rows = []
            for check in in_section:
                row = self._check_row(check, CHECKS[check.id][1])
                self.check_rows[check.id] = row
                layout.addWidget(row)
                rows.append((row, check))
            self._section_widgets.append((header, rows))

        self.myths_box = self._text_section(
            tr("win.myths_title"), tr("win.myths_note"),
            [(tr(f"myths.{m}.title"), tr(f"myths.{m}.why")) for m in MYTHS],
        )  # fmt: skip
        layout.addWidget(self.myths_box)
        self.bios_box = self._text_section(
            tr("win.bios_title"), tr("win.bios_note"),
            [(tr(f"win.bios.{b}.title"), tr(f"win.bios.{b}.text")) for b in BIOS_ITEMS],
        )  # fmt: skip
        layout.addWidget(self.bios_box)
        layout.addStretch()
        self._apply_filter()
        return self._scroll(host)

    def _applied_section(self) -> QWidget:
        """Changes the app made in Windows, newest first, each with "Restore"."""
        tr = self._tr
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        head = QHBoxLayout()
        header = QLabel(tr("win.applied_title").upper())
        header.setObjectName("subgroupTitle")
        head.addWidget(header)
        head.addStretch()
        self.restore_all_button = QPushButton(tr("win.restore_all"))
        self.restore_all_button.setProperty("variant", "ghost")
        self.restore_all_button.clicked.connect(lambda: self.restore_requested.emit(""))
        head.addWidget(self.restore_all_button)
        layout.addLayout(head)
        for entry in reversed(self._applied):
            frame = QFrame()
            frame.setObjectName("checkRow")
            frame.setProperty("status", "info")
            row = QHBoxLayout(frame)
            row.setContentsMargins(12, 8, 12, 8)
            texts = QVBoxLayout()
            texts.setSpacing(2)
            name = QLabel(tr(f"tweaks.{entry.tweak}.title"))
            name.setObjectName("cardTitle")
            texts.addWidget(name)
            when = QLabel(tr("win.applied_when", when=entry.when.replace("T", " ")))
            when.setObjectName("cardDesc")
            texts.addWidget(when)
            row.addLayout(texts, 1)
            button = QPushButton(tr("win.restore"))
            button.clicked.connect(lambda _=False, e=entry.id: self.restore_requested.emit(e))
            row.addWidget(button)
            self.restore_buttons[entry.id] = button
            layout.addWidget(frame)
        return box

    def _text_section(self, title: str, note: str, items: list[tuple[str, str]]) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = QLabel(title.upper())
        header.setObjectName("subgroupTitle")
        layout.addWidget(header)
        intro = QLabel(note)
        intro.setObjectName("cardDesc")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        for item_title, text in items:
            frame = QFrame()
            frame.setObjectName("checkRow")
            frame.setProperty("status", "")
            inner = QVBoxLayout(frame)
            inner.setContentsMargins(12, 8, 12, 8)
            inner.setSpacing(2)
            name = QLabel(item_title)
            name.setObjectName("cardTitle")
            inner.addWidget(name)
            body = QLabel(text)
            body.setObjectName("cardDesc")
            body.setWordWrap(True)
            inner.addWidget(body)
            layout.addWidget(frame)
        return box

    def _set_only_problems(self, only: bool) -> None:
        self.only_problems = only
        self._apply_filter()

    def _apply_filter(self) -> None:
        for header, rows in self._section_widgets:
            visible = 0
            for row, check in rows:
                show = not self.only_problems or check.status in (Status.WARN, Status.INFO)
                row.setVisible(show)
                visible += show
            header.setVisible(visible > 0)
        self.myths_box.setVisible(not self.only_problems)
        self.bios_box.setVisible(not self.only_problems)

    def _request_refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText(self._tr("win.refreshing"))
        self.refresh_requested.emit()

    @staticmethod
    def _scroll(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll


# Manual BIOS checklist (texts: win.bios.<id>.title/text); statuses that Windows can
# see indirectly are in the check rows above.
BIOS_ITEMS = ("expo", "rebar", "secure_boot", "tpm", "svm", "pbo", "intel_profile")


def default_checks_tab(checks: list[CheckResult]) -> str:
    """Where the "System check: N" button lands: the tab with the warnings."""
    hardware_warn = any(c.status is Status.WARN and not is_windows_check(c.id) for c in checks)
    windows_warn = any(c.status is Status.WARN and is_windows_check(c.id) for c in checks)
    return "windows" if windows_warn and not hardware_warn else "checks"


def windows_summary(checks: list[CheckResult], tr: Translator) -> str:
    required = [c for c in checks if CHECKS[c.id][0] is Section.REQUIREMENTS]
    missing = sum(1 for c in required if c.status is Status.WARN)
    if missing:
        requirements = tr("win.requirements_missing", count=missing)
    elif any(c.status is Status.UNKNOWN for c in required):
        requirements = tr("win.requirements_unknown")
    else:
        requirements = tr("win.requirements_ok")
    warn = sum(1 for c in checks if c.status is Status.WARN)
    info = sum(1 for c in checks if c.status is Status.INFO)
    return tr("win.summary", requirements=requirements, warnings=warn, info=info)


def check_title(check: CheckResult, tr: Translator) -> str:
    title = tr(f"checks.{check.id}.title")
    if check.severity is Severity.HIGH and check.status is Status.WARN:
        return f"{title}  ·  {tr('checks.severity_high')}"
    return title


def check_text(check: CheckResult, tr: Translator) -> str:
    if check.status is Status.UNKNOWN:
        return tr("checks.unknown")
    if check.status is Status.OK:
        key = f"checks.{check.id}.ok" + (f"_{check.variant}" if check.variant else "")
        return tr(key, **check.params)
    key = f"checks.{check.id}.problem" + (f"_{check.variant}" if check.variant else "")
    return tr(key, **check.params)


def action_label(action: str, tr: Translator) -> str:
    if action.startswith("setting:"):
        return tr("checks.go_to_setting")
    if action.startswith("http"):
        return tr("checks.open_page")
    return tr("checks.open_settings")
