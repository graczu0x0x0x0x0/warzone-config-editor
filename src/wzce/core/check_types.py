"""Result types shared by the hardware checks and the Windows-settings checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    WARN = "warn"
    INFO = "info"
    OK = "ok"
    UNKNOWN = "unknown"  # data not available on this PC


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class CheckResult:
    id: str
    status: Status
    severity: Severity | None = None
    params: dict[str, object] = field(default_factory=dict)
    variant: str | None = None  # selects checks.<id>.problem_<variant> / .ok_<variant>
    action: str | None = None  # "ms-settings:...", "https://...", "setting:Key@0"

    @property
    def sort_key(self) -> tuple[int, int]:
        status_rank = {Status.WARN: 0, Status.INFO: 1, Status.UNKNOWN: 3, Status.OK: 2}
        severity_rank = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2, None: 3}
        return status_rank[self.status], severity_rank[self.severity]
