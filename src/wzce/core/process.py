"""Detect whether Call of Duty is running.

The game rewrites both settings slots when it exits, so any edit made while it
runs is silently lost. The storage layer refuses to write in that case.
"""

from __future__ import annotations

from collections.abc import Callable

import psutil

# Executable of the CoD HQ build (BO6, BO7, Warzone) - guides say "fully close cod.exe".
# Lower-case; compared case-insensitively. Add names here only after observing them
# in Task Manager (e.g. if a future title ships a differently named executable).
GAME_PROCESS_NAMES: frozenset[str] = frozenset({"cod.exe"})

# A callable returning True when the game runs. Injected into storage functions
# so tests can simulate a running game without spawning processes.
GameRunningCheck = Callable[[], bool]


def find_game_processes() -> list[psutil.Process]:
    """Return running game processes (empty list when the game is closed)."""
    found: list[psutil.Process] = []
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in GAME_PROCESS_NAMES:
            found.append(proc)
    return found


def is_game_running() -> bool:
    return bool(find_game_processes())
