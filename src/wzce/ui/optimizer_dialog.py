"""Optimizer wizard: detected hardware + goal + bottleneck -> previewed recommendations.

Everything happens on one page so the effect of each answer is visible at once:
changing the goal or the bottleneck recomputes ``optimizer.recommend`` and the
preview table (with a "why" column) immediately.

Like the templates dialog it never touches the session: "Apply" stores the
chosen raw values in ``result_values`` for the main window.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.hardware import HardwareInfo
from ..core.i18n import Translator
from ..core.knowledge import KnowledgeBase, localized
from ..core.optimizer import Bottleneck, Goal, Reason, recommend
from ..core.session import EditorSession
from ..core.templates import plan_template
from .plan_table import PlanTable


class OptimizerDialog(QDialog):
    def __init__(
        self,
        session: EditorSession,
        knowledge: KnowledgeBase,
        tr: Translator,
        hardware: HardwareInfo,
        *,
        goal: Goal = Goal.COMPETITIVE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._kb = knowledge
        self._tr = tr
        self.hardware = hardware
        self.goal = goal
        self.bottleneck = Bottleneck.UNKNOWN
        self.result_values: dict[str, str] = {}

        self.setWindowTitle(tr("optimizer.title"))
        self.resize(1100, 760)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(tr("optimizer.title"))
        title.setObjectName("pageTitle")
        root.addWidget(title)
        root.addWidget(self._hardware_box())

        # --- goal -----------------------------------------------------------
        root.addWidget(self._section_label(tr("optimizer.goal")))
        goal_items = [
            (Goal(p.id), localized(p.label, tr.language), localized(p.desc, tr.language))
            for p in knowledge.presets
        ]
        self.goal_buttons = self._segmented(goal_items, goal, self._on_goal)
        root.addLayout(self.goal_buttons[0])

        # --- bottleneck -----------------------------------------------------
        root.addWidget(self._section_label(tr("optimizer.bottleneck")))
        bottleneck_items = [
            (Bottleneck.UNKNOWN, tr("optimizer.bottleneck_unknown"), ""),
            (Bottleneck.CPU, tr("optimizer.bottleneck_cpu"), ""),
            (Bottleneck.GPU, tr("optimizer.bottleneck_gpu"), ""),
        ]
        self.bottleneck_buttons = self._segmented(
            bottleneck_items, Bottleneck.UNKNOWN, self._on_bottleneck
        )
        root.addLayout(self.bottleneck_buttons[0])
        hint = QLabel(tr("optimizer.bottleneck_hint"))
        hint.setObjectName("cardDesc")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # --- preview ----------------------------------------------------------
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)
        self.plan_table = PlanTable(
            tr, knowledge, with_reasons=True, template_header=tr("optimizer.col_new")
        )
        self.plan_table.selection_changed.connect(self._update_apply_button)
        root.addWidget(self.plan_table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton(tr("dialog.close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        self.apply_button = QPushButton()
        self.apply_button.setProperty("variant", "primary")
        self.apply_button.clicked.connect(self.apply_selected)
        buttons.addWidget(self.apply_button)
        root.addLayout(buttons)

        self.refresh_plan()

    # ------------------------------------------------------------- widgets
    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("subgroupTitle")
        return label

    def _segmented(
        self,
        items: list[tuple[object, str, str]],
        selected: object,
        on_change: Callable[[object], None],
    ) -> tuple[QHBoxLayout, dict[object, QPushButton]]:
        """Row of exclusive segment buttons; returns (layout, {value: button})."""
        layout = QHBoxLayout()
        layout.setSpacing(0)
        group = QButtonGroup(self)
        buttons = {}
        for index, (value, text, tooltip) in enumerate(items):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(items) - 1)
            button.setChecked(value == selected)
            if tooltip:
                button.setToolTip(tooltip)
            button.clicked.connect(lambda _=False, v=value: on_change(v))
            group.addButton(button)
            buttons[value] = button
            layout.addWidget(button)
        layout.addStretch()
        return layout, buttons

    def _hardware_box(self) -> QFrame:
        tr, hw = self._tr, self.hardware
        unknown = tr("optimizer.unknown")
        box = QFrame()
        box.setObjectName("card")
        grid = QGridLayout(box)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(24)
        heading = QLabel(tr("optimizer.hardware"))
        heading.setObjectName("cardTitle")
        grid.addWidget(heading, 0, 0, 1, 4)

        if hw.is_hybrid:
            cores = tr(
                "optimizer.cores_hybrid",
                p=hw.performance_cores,
                e=hw.efficiency_cores,
                logical=hw.logical_cores or "?",
            )
        elif hw.physical_cores:
            cores = tr(
                "optimizer.cores_value", physical=hw.physical_cores, logical=hw.logical_cores or "?"
            )
        else:
            cores = unknown
        if hw.refresh_hz:
            refresh = tr("optimizer.refresh_value", hz=hw.refresh_hz, max=hw.best_refresh_hz)
        else:
            refresh = unknown
        rows = [
            (tr("optimizer.cpu"), hw.cpu_name or unknown),
            (tr("optimizer.cores"), cores),
            (tr("optimizer.ram"), f"{round(hw.ram_mb / 1024)} GB" if hw.ram_mb else unknown),
            (tr("optimizer.gpu"), hw.gpu_name or unknown),
            (tr("optimizer.vram"), f"{round(hw.vram_mb / 1024)} GB" if hw.vram_mb else unknown),
            (tr("optimizer.monitor"), refresh),
        ]
        self.hardware_labels: dict[str, QLabel] = {}
        for index, (name, value) in enumerate(rows):
            row, column = 1 + index % 3, (index // 3) * 2
            key = QLabel(name)
            key.setObjectName("cardDesc")
            grid.addWidget(key, row, column)
            value_label = QLabel(str(value))
            grid.addWidget(value_label, row, column + 1)
            self.hardware_labels[name] = value_label
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return box

    # ---------------------------------------------------------------- logic
    def _on_goal(self, goal: Goal) -> None:
        self.goal = goal
        self.refresh_plan()

    def _on_bottleneck(self, bottleneck: Bottleneck) -> None:
        self.bottleneck = bottleneck
        self.refresh_plan()

    def set_choice(self, goal: Goal, bottleneck: Bottleneck) -> None:
        """Programmatic selection (keeps the buttons in sync); used by tests."""
        self.goal_buttons[1][goal].setChecked(True)
        self.bottleneck_buttons[1][bottleneck].setChecked(True)
        self.goal, self.bottleneck = goal, bottleneck
        self.refresh_plan()

    def reason_text(self, reason: Reason) -> str:
        params = dict(reason.params)
        if reason.key == "optimizer.reason_preset":
            preset = self._kb.preset(str(params["preset"]))
            params["preset"] = localized(preset.label, self._tr.language)
        return self._tr(reason.key, **params)

    def refresh_plan(self) -> None:
        tr = self._tr
        document = self._session.document
        result = recommend(self._kb, document, self.hardware, self.goal, self.bottleneck)
        plan = plan_template(
            document,
            self._kb,
            result.values,
            gpu_vendor=self.hardware.gpu_vendor or self._session.gpu_vendor,
        )
        self.plan = plan
        reasons = {sid: self.reason_text(r) for sid, r in result.reasons.items()}
        self.summary_label.setText(
            tr(
                "optimizer.summary",
                changes=len(plan.changes),
                unchanged=len(plan.unchanged),
                skipped=len(plan.skipped),
            )
            if plan.changes
            else tr("optimizer.nothing")
        )
        self.plan_table.set_plan(plan, document, reasons)

    def _update_apply_button(self, count: int | None = None) -> None:
        if count is None:
            count = len(self.plan_table.checked_ids())
        self.apply_button.setText(self._tr("templates.apply", count=count))
        self.apply_button.setEnabled(count > 0)

    def apply_selected(self) -> None:
        self.result_values = self.plan_table.checked_values()
        if self.result_values:
            self.accept()
