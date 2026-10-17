"""Shareable summary of the current settings as Markdown or JSON.

Different from templates: a template stores raw values to *apply* later, while a
share export is for *people* - translated names, readable values ("Pełny ekran",
"75 %"), grouped by editor category, optionally with a short hardware summary
("RTX 5090 · 32 GB") so others can judge the settings. The JSON variant also
carries the raw values and file keys for tools.

Privacy: hardware-specific and game-managed settings (audio device ids, window
geometry, detected hardware, driver versions) are never included - the same
``exclusion_reason`` rule as templates. No file paths or account ids either.

Markdown uses bullet lists instead of tables because Discord does not render tables.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .display import display_value
from .document import ConfigDocument
from .hardware import HardwareInfo
from .i18n import Translator
from .knowledge import KnowledgeBase, localized
from .system_info import SystemInfo
from .templates import exclusion_reason

FORMAT_ID = "wzce-settings-share"
FORMAT_VERSION = 1
# The "basic picture" people usually ask about: display + graphics + quality.
DEFAULT_GROUPS: tuple[str, ...] = ("display", "performance", "upscaling", "quality")


@dataclass(frozen=True, slots=True)
class ShareRow:
    key: str  # "DisplayMode@0"
    name: str  # translated label
    value: str  # human-readable value
    raw: str  # value exactly as in the file


@dataclass(slots=True)
class ShareGroup:
    id: str
    name: str
    rows: list[ShareRow] = field(default_factory=list)


@dataclass(slots=True)
class ShareExport:
    game: str
    title_code: str | None
    app: str
    language: str
    exported: datetime
    groups: list[ShareGroup]
    hardware: list[tuple[str, str, str]]  # (id, label, value)

    @property
    def setting_count(self) -> int:
        return sum(len(g.rows) for g in self.groups)


def hardware_summary(
    info: SystemInfo | None, hardware: HardwareInfo | None, tr: Translator
) -> list[tuple[str, str, str]]:
    """Short, non-identifying hardware lines: CPU, GPU, RAM, monitor."""
    lines: list[tuple[str, str, str]] = []
    if info and info.cpu_name:
        cpu = " ".join(info.cpu_name.replace("Processor", "").split())
        if info.cpu_cores:
            cpu += f" ({info.cpu_cores}C/{info.cpu_threads}T)"
        lines.append(("cpu", tr("spec.section_cpu"), cpu))
    gpu = info.dedicated_gpu.name if info and info.dedicated_gpu else None
    gpu = gpu or (hardware.gpu_name if hardware else None)
    if gpu:
        if hardware and hardware.vram_mb:
            gpu += f" · {round(hardware.vram_mb / 1024)} GB VRAM"
        lines.append(("gpu", tr("spec.section_gpu"), gpu))
    if info and info.memory:
        ram = f"{info.memory_total_gb:g} GB {info.memory_type or ''}".strip()
        if info.memory_speed_mts:
            ram += f" · {info.memory_speed_mts} MT/s"
        if info.expo_xmp != "unknown":
            ram += f" · {tr(f'share.expo_{info.expo_xmp}')}"
        lines.append(("ram", tr("spec.section_memory"), ram))
    if hardware and hardware.refresh_hz:
        monitor = info.monitors[0].split(" (")[0] if info and info.monitors else ""
        lines.append(
            (
                "monitor",
                tr("spec.section_display"),
                f"{monitor} · {hardware.refresh_hz} Hz".strip(" ·"),
            )
        )
    return lines


def build_share(
    document: ConfigDocument,
    knowledge: KnowledgeBase,
    tr: Translator,
    *,
    game: str,
    title_code: str | None = None,
    app: str = "",
    groups: Iterable[str] = DEFAULT_GROUPS,
    include_advanced: bool = False,
    hardware: list[tuple[str, str, str]] | None = None,
    gpu_vendor: str | None = None,
) -> ShareExport:
    """Collect the chosen categories in the same order as the editor shows them.

    With ``gpu_vendor`` known, settings that only matter on another vendor's card
    (e.g. AMD Anti-Lag on an NVIDIA PC) are left out, like the editor's default view.
    """
    wanted = set(groups)
    group_order = [g.id for g in knowledge.groups]
    entry_order = {sid: i for i, sid in enumerate(knowledge.entries)}
    collected: dict[str, list[tuple[tuple[int, int, int], ShareRow]]] = {}
    for setting in document:
        entry = knowledge.entry_for(setting)
        if entry.group not in wanted or exclusion_reason(setting, entry) is not None:
            continue
        if entry.advanced and not include_advanced:
            continue
        if gpu_vendor and entry.vendor and entry.vendor != gpu_vendor:
            continue
        group = knowledge.group(entry.group)
        sub_ids = [s.id for s in group.subgroups]
        sort_key = (
            sub_ids.index(entry.subgroup) if entry.subgroup in sub_ids else len(sub_ids),
            entry_order.get(setting.id, len(entry_order)),
            setting.line_index,
        )
        row = ShareRow(
            key=setting.id,
            name=localized(entry.label, tr.language),
            value=display_value(setting.raw_value, setting, entry, tr),
            raw=setting.raw_value,
        )
        collected.setdefault(entry.group, []).append((sort_key, row))

    share_groups = [
        ShareGroup(
            id=group_id,
            name=localized(knowledge.group(group_id).label, tr.language),
            rows=[row for _, row in sorted(collected[group_id], key=lambda item: item[0])],
        )
        for group_id in group_order
        if group_id in collected
    ]
    return ShareExport(
        game=game,
        title_code=title_code,
        app=app,
        language=tr.language,
        exported=datetime.now(),
        groups=share_groups,
        hardware=list(hardware or []),
    )


def to_markdown(export: ShareExport, tr: Translator) -> str:
    stamp = export.exported.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {tr('share.md_title', game=export.game)}",
        "",
        f"_{tr('share.md_exported', date=stamp, app=export.app)}_",
    ]
    if export.hardware:
        lines += ["", f"## {tr('share.md_hardware')}", ""]
        lines += [f"- **{label}:** {value}" for _, label, value in export.hardware]
    for group in export.groups:
        lines += ["", f"## {group.name}", ""]
        lines += [f"- **{row.name}:** {row.value} `{row.key}`" for row in group.rows]
    return "\n".join(lines) + "\n"


def to_json(export: ShareExport) -> str:
    payload = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "app": export.app,
        "game": export.game,
        "title_code": export.title_code,
        "exported": export.exported.isoformat(timespec="seconds"),
        "language": export.language,
        "hardware": {hw_id: value for hw_id, _, value in export.hardware},
        "groups": [
            {
                "id": group.id,
                "name": group.name,
                "settings": [
                    {"key": r.key, "name": r.name, "value": r.value, "raw": r.raw}
                    for r in group.rows
                ],
            }
            for group in export.groups
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
