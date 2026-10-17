"""Value editor widgets, one per value type, plus the factory that picks them.

Every editor derives from ``ValueEditor``:

* ``set_raw(raw)``   shows a raw file value WITHOUT emitting ``edited``
* ``edited(object)`` fires when the *user* changes the value; the payload is a
  Python value (bool / int / float / str) ready for ``EditorSession.set_value``

Widget choice (``create_editor``):
  bool                      -> toggle switch
  enum, few short options   -> segmented buttons;  otherwise -> combo box
  int/float, sane range     -> slider + spin box;  huge range or widget "spin" -> spin box only
  float with widget percent -> values shown as 0-100 %
  string                    -> line edit (monospace for device ids)
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from ..core.i18n import Translator
from ..core.knowledge import KnowledgeEntry
from ..core.model import Setting, ValueType, parse_raw_value
from .theme import COLORS, MONO_FAMILY, repolish

# Segmented buttons only when the options fit comfortably on one row.
SEGMENT_MAX_OPTIONS = 4
SEGMENT_MAX_CHARS = 44
# Slider resolution for float ranges (steps between min and max).
FLOAT_SLIDER_STEPS = 1000
# Spin boxes cannot show the game's +-3.4e38 "unbounded" float ranges sensibly.
SPIN_ABS_LIMIT = 1e9
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1


# ---------------------------------------------------------------------------
# Wheel guard
# ---------------------------------------------------------------------------


class _WheelGuard:
    """Mixin: ignore the mouse wheel unless the widget has keyboard focus.

    Cards live in a scroll area; without this, scrolling the page over a slider,
    spin box or combo box would silently change a game setting. The ignored
    event propagates to the scroll area, which scrolls as expected.
    """

    def _init_guard(self) -> None:
        # WheelFocus (Qt's default for these widgets) would grab focus on wheel.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # type: ignore[attr-defined]

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():  # type: ignore[attr-defined]
            super().wheelEvent(event)  # type: ignore[misc]
        else:
            event.ignore()


class GuardedSlider(_WheelGuard, QSlider):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._init_guard()


class GuardedSpinBox(_WheelGuard, QSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_guard()


class GuardedDoubleSpinBox(_WheelGuard, QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_guard()


class GuardedComboBox(_WheelGuard, QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_guard()


class ValueEditor(QWidget):
    edited = Signal(object)

    def set_raw(self, raw: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def set_error(self, message: str | None) -> None:
        """Show/clear a validation problem (tooltip by default)."""
        self.setToolTip(message or "")


# ---------------------------------------------------------------------------
# Toggle switch
# ---------------------------------------------------------------------------


class ToggleSwitch(QAbstractButton):
    """iOS-style on/off switch painted by hand (no stylesheet support needed)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(42, 22)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = rect.height() / 2
        if not self.isEnabled():
            track = QColor(COLORS["border"])
        elif self.isChecked():
            track = QColor(COLORS["accent"])
        else:
            track = QColor(COLORS["border_strong"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)

        knob_r = radius - 3
        x = rect.right() - radius if self.isChecked() else rect.left() + radius
        painter.setBrush(QColor(COLORS["text"] if self.isEnabled() else COLORS["text_faint"]))
        painter.drawEllipse(QPointF(x, rect.center().y()), knob_r, knob_r)


class BoolEditor(ValueEditor):
    def __init__(self, tr: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr = tr
        self.switch = ToggleSwitch(self)
        self.text = QLabel(self)
        self.text.setObjectName("toggleText")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.switch)
        layout.addWidget(self.text)
        layout.addStretch()
        self.switch.toggled.connect(self._on_toggled)

    def set_raw(self, raw: str) -> None:
        self.switch.blockSignals(True)
        self.switch.setChecked(raw == "true")
        self.switch.blockSignals(False)
        self._update_text()

    def _update_text(self) -> None:
        self.text.setText(self._tr("value.true" if self.switch.isChecked() else "value.false"))

    def _on_toggled(self, checked: bool) -> None:
        self._update_text()
        self.edited.emit(checked)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SegmentedEditor(ValueEditor):
    def __init__(
        self, options: tuple[str, ...], labels: list[str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for index, (option, label) in enumerate(zip(options, labels, strict=True)):
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(options) - 1)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if label != option:
                button.setToolTip(option)
            self._group.addButton(button)
            self._buttons[option] = button
            layout.addWidget(button)
            button.clicked.connect(lambda _=False, o=option: self.edited.emit(o))
        layout.addStretch()

    def set_raw(self, raw: str) -> None:
        button = self._buttons.get(raw)
        if button is not None:
            button.setChecked(True)
        else:  # value not among options (odd file) - show nothing selected
            self._group.setExclusive(False)
            for b in self._buttons.values():
                b.setChecked(False)
            self._group.setExclusive(True)


class ComboEditor(ValueEditor):
    def __init__(
        self, options: tuple[str, ...], labels: list[str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.combo = GuardedComboBox(self)
        for option, label in zip(options, labels, strict=True):
            self.combo.addItem(label, option)
        self.combo.setMinimumWidth(220)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        layout.addStretch()
        self.combo.activated.connect(lambda i: self.edited.emit(self.combo.itemData(i)))

    def set_raw(self, raw: str) -> None:
        self.combo.blockSignals(True)
        index = self.combo.findData(raw)
        if index < 0:  # unknown value: show it, but keep it selectable-free
            self.combo.addItem(raw, raw)
            index = self.combo.count() - 1
        self.combo.setCurrentIndex(index)
        self.combo.blockSignals(False)


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


class NumberEditor(ValueEditor):
    """Spin box with an optional slider. Handles int, float and percent display."""

    def __init__(
        self,
        *,
        is_float: bool,
        minimum: float,
        maximum: float,
        with_slider: bool,
        percent: bool = False,
        unit: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_float = is_float
        self._percent = percent
        self._factor = 100.0 if percent else 1.0
        self._min, self._max = minimum, maximum

        if is_float:
            spin: QSpinBox | QDoubleSpinBox = GuardedDoubleSpinBox(self)
            span = (maximum - minimum) * self._factor
            spin.setDecimals(1 if percent else (3 if span <= 2 else 2))
            lo = max(minimum * self._factor, -SPIN_ABS_LIMIT)
            hi = min(maximum * self._factor, SPIN_ABS_LIMIT)
            spin.setRange(lo, hi)
            spin.setSingleStep(1.0 if percent else (0.01 if span <= 2 else 0.1))
        else:
            spin = GuardedSpinBox(self)
            spin.setRange(int(max(minimum, INT32_MIN)), int(min(maximum, INT32_MAX)))
        spin.setKeyboardTracking(False)  # emit on Enter / focus out, not per keystroke
        spin.setMinimumWidth(110)
        suffix = " %" if percent else (f" {unit}" if unit else "")
        spin.setSuffix(suffix)
        self.spin = spin

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider: QSlider | None = None
        if with_slider:
            slider = GuardedSlider(Qt.Orientation.Horizontal, self)
            if is_float:
                slider.setRange(0, FLOAT_SLIDER_STEPS)
            else:
                slider.setRange(int(minimum), int(maximum))
            slider.setMinimumWidth(220)
            slider.valueChanged.connect(self._on_slider_moved)
            slider.sliderReleased.connect(self._emit_current)
            layout.addWidget(slider, 1)
            self.slider = slider
        layout.addWidget(spin)
        if not with_slider:
            layout.addStretch()
        spin.valueChanged.connect(self._on_spin_changed)

    # ------------------------------------------------------------ conversions
    def _slider_from_value(self, value: float) -> int:
        if not self._is_float:
            return int(value)
        span = self._max - self._min
        return round((value - self._min) / span * FLOAT_SLIDER_STEPS) if span else 0

    def _value_from_slider(self, position: int) -> float:
        if not self._is_float:
            return float(position)
        return self._min + (self._max - self._min) * position / FLOAT_SLIDER_STEPS

    def _current_value(self) -> int | float:
        shown = self.spin.value()
        if not self._is_float:
            return int(shown)
        return round(shown / self._factor, 6)

    # ---------------------------------------------------------------- signals
    def set_raw(self, raw: str) -> None:
        value = parse_raw_value(raw, ValueType.FLOAT if self._is_float else ValueType.INT)
        if isinstance(value, str):  # unparsable raw text - leave the widget as is
            return
        for w in (self.spin, self.slider):
            if w is not None:
                w.blockSignals(True)
        self.spin.setValue(value * self._factor if self._is_float else int(value))
        if self.slider is not None:
            self.slider.setValue(self._slider_from_value(value))
        for w in (self.spin, self.slider):
            if w is not None:
                w.blockSignals(False)

    def _on_slider_moved(self, position: int) -> None:
        value = self._value_from_slider(position)
        self.spin.blockSignals(True)
        self.spin.setValue(value * self._factor if self._is_float else int(value))
        self.spin.blockSignals(False)
        assert self.slider is not None
        if not self.slider.isSliderDown():  # keyboard / page click: commit immediately
            self._emit_current()

    def _on_spin_changed(self, _shown: float) -> None:
        if self.slider is not None:
            self.slider.blockSignals(True)
            self.slider.setValue(self._slider_from_value(self._current_value()))
            self.slider.blockSignals(False)
        self._emit_current()

    def _emit_current(self) -> None:
        self.edited.emit(self._current_value())


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


class TextEditor(ValueEditor):
    def __init__(self, *, monospace: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.line = QLineEdit(self)
        self.line.setMinimumWidth(320)
        if monospace:
            self.line.setStyleSheet(f"font-family: {MONO_FAMILY};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line, 1)
        self._raw = ""
        self.line.editingFinished.connect(self._on_finished)

    def set_raw(self, raw: str) -> None:
        self._raw = raw
        self.line.blockSignals(True)
        self.line.setText(raw)
        self.line.blockSignals(False)

    def _on_finished(self) -> None:
        if self.line.text() != self._raw:
            self.edited.emit(self.line.text())

    def set_error(self, message: str | None) -> None:
        super().set_error(message)
        self.line.setProperty("invalid", bool(message))
        repolish(self.line)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_editor(setting: Setting, entry: KnowledgeEntry, tr: Translator) -> ValueEditor:
    """Pick and configure the right editor for a setting."""
    constraint = setting.constraint
    match setting.value_type:
        case ValueType.BOOL:
            editor: ValueEditor = BoolEditor(tr)
        case ValueType.ENUM:
            assert constraint is not None
            options = constraint.options
            labels = [entry.option_label(o, tr.language) for o in options]
            fits = (
                len(options) <= SEGMENT_MAX_OPTIONS and sum(map(len, labels)) <= SEGMENT_MAX_CHARS
            )
            editor = SegmentedEditor(options, labels) if fits else ComboEditor(options, labels)
        case ValueType.INT | ValueType.FLOAT:
            assert constraint is not None and constraint.min_value is not None
            assert constraint.max_value is not None
            editor = NumberEditor(
                is_float=setting.value_type is ValueType.FLOAT,
                minimum=constraint.min_value,
                maximum=constraint.max_value,
                with_slider=constraint.is_slider_friendly and entry.widget != "spin",
                percent=entry.widget == "percent" and setting.value_type is ValueType.FLOAT,
                unit=entry.unit,
            )
        case _:
            editor = TextEditor(monospace=entry.widget == "device")
    editor.set_raw(setting.raw_value)
    return editor


def display_value(raw: str, setting: Setting, entry: KnowledgeEntry, tr: Translator) -> str:
    """Human-readable form of a raw value (changes panel, recommendation line)."""
    if raw == "":
        return tr("value.empty")
    match setting.value_type:
        case ValueType.BOOL:
            return tr("value.true" if raw == "true" else "value.false")
        case ValueType.ENUM:
            return entry.option_label(raw, tr.language)
        case ValueType.FLOAT:
            value = parse_raw_value(raw, ValueType.FLOAT)
            if isinstance(value, float):
                if entry.widget == "percent":
                    return f"{value * 100:g} %"
                return f"{value:g}" + (f" {entry.unit}" if entry.unit else "")
        case ValueType.INT:
            return raw + (f" {entry.unit}" if entry.unit else "")
    return raw
