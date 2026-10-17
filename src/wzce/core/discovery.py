"""Find editable settings files on this machine.

Two scopes exist (docs/FILE_FORMAT.md section 1):

* MACHINE  ``players/s.1.0.codNN.txt0|1`` - graphics, display, audio devices, system.
* ACCOUNT  ``players/<platform id>/g.codNN.1.0.l.txt0|1`` - sensitivity, FOV, HDR...
           ``players/<platform id>/g.codNN.pm.1.0.l.txt0|1`` - FOV only.

Title codes are discovered, never hard-coded, so a new title (cod26, ...) shows
up automatically. Binary files and the SteamCloud mirror are deliberately ignored.
Stems that do not match exactly (``s.1.0.cod24_bu.txt0``, ``..._copy.txt0`` - manual
backups made by users following online guides) are ignored too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .paths import game_players_dirs
from .storage import AB_SUFFIXES, SINGLE_SUFFIX, SettingsFileSet

# Known title codes. Unknown codes are still listed, just without a friendly name.
TITLE_NAMES: dict[str, str] = {
    "cod24": "Black Ops 6",
    "cod25": "Black Ops 7 / Warzone",
}

# Folders inside an account folder that we must not treat as accounts or touch.
_IGNORED_SUBDIRS = {"steamcloud"}


class Scope(StrEnum):
    MACHINE = "machine"
    ACCOUNT = "account"


class FileKind(StrEnum):
    SETTINGS = "settings"  # s.1.0.codNN
    PROFILE = "profile"  # g.codNN.1.0.l
    PROFILE_PM = "profile_pm"  # g.codNN.pm.1.0.l


_STEM_PATTERNS: list[tuple[re.Pattern[str], Scope, FileKind]] = [
    (re.compile(r"^s\.1\.0\.(cod\d+)$"), Scope.MACHINE, FileKind.SETTINGS),
    (re.compile(r"^g\.(cod\d+)\.1\.0\.l$"), Scope.ACCOUNT, FileKind.PROFILE),
    (re.compile(r"^g\.(cod\d+)\.pm\.1\.0\.l$"), Scope.ACCOUNT, FileKind.PROFILE_PM),
]


@dataclass(frozen=True, slots=True)
class ConfigLocation:
    fileset: SettingsFileSet
    scope: Scope
    kind: FileKind
    title_code: str
    account_id: str | None = None  # SteamID64 / Battle.net id folder name

    @property
    def title_name(self) -> str:
        return TITLE_NAMES.get(self.title_code, self.title_code)

    @property
    def title_number(self) -> int:
        return int(self.title_code.removeprefix("cod"))


def discover(players_dirs: list[Path] | None = None) -> list[ConfigLocation]:
    """All settings file sets, newest title first, machine scope before account scope."""
    dirs = game_players_dirs() if players_dirs is None else players_dirs
    found: dict[tuple[Path, str], ConfigLocation] = {}

    for players in dirs:
        if not players.is_dir():
            continue
        _scan_dir(players, None, found)
        for sub in players.iterdir():
            if sub.is_dir() and sub.name.lower() not in _IGNORED_SUBDIRS:
                _scan_dir(sub, sub.name, found)

    def sort_key(loc: ConfigLocation) -> tuple[int, int, str, str]:
        scope_rank = 0 if loc.scope is Scope.MACHINE else 1
        return (-loc.title_number, scope_rank, loc.account_id or "", loc.kind.value)

    return sorted(found.values(), key=sort_key)


def _scan_dir(
    directory: Path, account_id: str | None, found: dict[tuple[Path, str], ConfigLocation]
) -> None:
    for path in directory.iterdir():
        if not path.is_file():
            continue
        stem = _slot_stem(path.name)
        if stem is None or (directory, stem) in found:
            continue
        for pattern, scope, kind in _STEM_PATTERNS:
            match = pattern.match(stem)
            if match is None:
                continue
            # Machine files are only valid at the players root, account files only
            # inside an account folder - anything else is someone's manual copy.
            if (scope is Scope.MACHINE) != (account_id is None):
                break
            found[(directory, stem)] = ConfigLocation(
                fileset=SettingsFileSet.from_path(path),
                scope=scope,
                kind=kind,
                title_code=match.group(1),
                account_id=account_id,
            )
            break


def _slot_stem(name: str) -> str | None:
    for suffix in (*AB_SUFFIXES, SINGLE_SUFFIX):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None
