# CLAUDE.md — Warzone Config Editor

GUI editor for Call of Duty: Black Ops 7 / Warzone PC settings files
(`%LOCALAPPDATA%\Activision\Call of Duty\players\s.1.0.cod25.txt0` / `.txt1`).

## Status
Released and working: **v1.2.0**, stages 0–9 of `docs/PLAN.md` done, ~420 tests green.
Current version: `src/wzce/__init__.py`; what changed recently: `CHANGELOG.md` + `git log`.
Remaining ideas are the unchecked `[ ]` items in `docs/PLAN.md` - nothing is in progress unless
the user says so.

## Getting oriented in a new session
1. This file (rules + API), then `docs/ARCHITECTURE.md` (module map, data flows, release checklist).
2. `docs/PLAN.md` for status/open items, top of `CHANGELOG.md` for the latest release.
3. Before touching parsing/saving: `docs/FILE_FORMAT.md`. Before touching settings texts:
   `docs/KNOWLEDGE_BASE.md`.
4. Run `uv run pytest` once to confirm the environment works.

Docs: `FILE_FORMAT.md` is the **source of truth for parsing**; `PLAN.md` has checkboxes - tick them
when finishing work; `RAPORT.md` (research, Polish) and `RAPORT_SPRZET.md` (hardware/system
detection, Polish) are historical reports with recommendations and sources.

## Working with the user
- Bigger features: first a short report/plan in Polish (what, how, risks), wait for approval,
  then implement. The user approves stages one at a time ("Tak, zaczynaj etap N").
- Anything only the game can confirm (does the game accept an edit?) is tested **by the user**
  in game - ask for a concrete test, wait for the result, record it in `FILE_FORMAT.md`.
- Finishing a change: pytest + ruff, update `PLAN.md` checkboxes, `CHANGELOG.md` entry (Polish),
  README if user-visible, version bump for releases (see ARCHITECTURE.md §7).
- Git: work directly on `main` (no remote, nothing to push); one commit per feature/fix;
  release commits are tagged `vX.Y.Z`.
- The user's own PC is the test machine (Steam, CoD on drive G:, NVIDIA GPU) - the live game
  folder may be **read** (e.g. `uv run wzce --report`), never written without explicit consent.

## Communication
- The user writes in **Polish** → answer in Polish. User-facing docs (`RAPORT.md`, `PLAN.md`,
  `CHANGELOG.md`) in Polish; README is bilingual (PL first, then EN).
- **Code, comments, docstrings, commit messages, dev docs: English.**
- Comments: explain *why* and game-file quirks, not the obvious. Every module starts with a docstring
  describing its responsibility.

## Stack (approved 2026-10-17)
Python 3.12 (pinned in `.python-version`) + PySide6-Essentials, psutil, pytest, pytest-qt, ruff, uv,
PyInstaller (`scripts/build_exe.py`). Package `src/wzce/`. `core/` must never import Qt (keeps it
unit-testable); the UI lives in `ui/`. Use PySide6-**Essentials**, not `PySide6` (avoids WebEngine bloat;
switching between them breaks the install - fix with `uv sync --reinstall-package pyside6-essentials --reinstall-package shiboken6`).

Environment quirks (Windows 11, repo inside a Syncthing folder):
- This machine intercepts TLS, so uv needs system certs - already set via
  `[tool.uv] native-tls = true` in `pyproject.toml`.
- Python's `Path.write_text()` on Windows writes **CRLF**. When a script edits repo files use
  `write_bytes()` or `newline="\n"` (`.gitattributes` normalizes source to LF, but the working
  copy and diffs get noisy).
- `examples/**` and `*.txt0/1` are `-text` in `.gitattributes`: never re-save fixtures with an
  editor or script - the round-trip tests compare bytes.
- Shell heredocs mangle backticks/`\n`; for multi-line patches use the Edit tool or a script in
  the scratchpad. `*.sync-conflict-*` files (Syncthing) are git-ignored - delete, never commit.

## Core API cheat sheet (`from wzce.core import ...`)
- `discover()` -> `list[ConfigLocation]` (`.fileset`, `.scope`, `.kind`, `.title_code`, `.account_id`)
- `SettingsFileSet.from_path(p)`; `.load()` -> `LoadedConfig(document, source, slot_differences)`;
  `.save(doc, backup_manager=..., game_running=...)` (refuses if game runs, backs up, writes both slots, rolls back on failure)
- `ConfigDocument`: `.get(id)`, iteration, `.sections`, `.values()`, `.set_value(id, v)` -> `ValueChange`,
  `.apply_values(mapping)` -> `(applied, errors)`, `.copy()`, `.to_bytes()`
- `Setting`: `.id` (`Key@Variant`), `.value_type`, `.value`, `.constraint`, `.description`, `.section`, `.read_only`
- `BackupManager().create/list/restore/prune`; `diff_documents(a, b)`
- `EditorSession` (`core/session.py`): `set_value/revert/discard_all/apply_raw_values/restore_snapshot`
  all push onto `session.undo_stack` (`core/undo.py`); `undo()/redo()` return touched ids.
  `reload()` clears undo unless `keep_undo=True` (used by `save`).
- Templates (`core/templates.py`): `template_from_document(doc, kb, name, groups=...)`,
  `builtin_templates(kb, doc, lang)`, `plan_template(doc, kb, values, gpu_vendor=...)` -> `TemplatePlan`
  (changes/unchanged/skipped+reason); apply with `session.apply_raw_values(plan.values(...), kind=BULK)`.
  `exclusion_reason()` is THE rule for what may never be copied (hardware_specific, game_managed, read-only).
  `TemplateStore` keeps user templates as JSON (`format: wzce-template`).
- Hardware (`core/hardware.py`): `detect_hardware(doc)` -> `HardwareInfo` (never raises; `None` =
  unknown). Win32 calls are wrapped; parsing helpers are pure and unit-tested.
  `MainWindow.hardware` detects lazily once (`hardware_provider` is injectable for tests).
- Optimizer (`core/optimizer.py`): `recommend(kb, doc, hw, Goal, Bottleneck)` -> values + `Reason`
  (i18n key + params); always feed the values through `plan_template` before applying.
- System (`core/system_info.py`, `core/system_checks.py`): `collect_system_info()` (slow, 3-5 s,
  never raises) -> `SystemInfo`; `evaluate_checks(info, hardware, machine_doc)` -> `CheckResult`s
  (texts: i18n `checks.<id>.title/problem[_variant]/fix/ok`). UI runs the probe in `SystemProbe`
  (daemon thread); tests pass `system_info_provider=None` or a fixture (`tests/fixtures/system_cim.json`).
- Windows settings (`core/windows_info.py`, stage 10): `SystemInfo.windows` -> `WindowsInfo`
  (Secure Boot/TPM/GPT, hypervisor/VBS, AV, DirectX, power, background apps). Read-only, no admin;
  absent registry value = Windows default, `None` = unknown. Plan: `docs/RAPORT_WINDOWS.md` §7.
  Rules: `core/windows_checks.py` (`CHECKS` id -> section/impact, `MYTHS`); niche rules return
  `None` when not applicable. `evaluate_checks()` merges them with the hardware checks.
- Display & sharing: `core/display.display_value(raw, setting, entry, tr)` renders values for every
  view (cards, panels, exports). `core/share_export.build_share(...)` -> `to_markdown/to_json`;
  it reuses `exclusion_reason()` and skips other GPU vendors - keep exports free of identifying data.
- `HistoryStore` (`core/history.py`): SAVE / GAME_CHANGE entries with diff + snapshot after;
  `last_seen.snapshot` drives `check_external_change`; `session.external_change` holds the latest
  GAME_CHANGE until the UI calls `acknowledge_external_change()`.
- `KnowledgeBase.load()`: `.groups`, `.presets`, `.entries[id]`, `.entry_for(setting)` (synthesizes unknown ids),
  `.preset_values(preset_id)`; `KnowledgeEntry.label/desc` are `{en, pl}` -> use `localized(text, lang)`
- `Translator(lang)`: `tr("key", **params)`, `.set_language()`, `.add_listener(cb)` for live re-labelling
- Inject `game_running=lambda: False` in tests; `WZCE_DATA_DIR` redirects app data (autouse fixture does it).

## UI architecture (`src/wzce/ui/`)
- `EditorSession` (core) is the single source of truth; widgets read it, edits flow
  card `value_edited` -> `MainWindow._on_value_edited` -> session -> refresh card/nav/changes panel.
- The card page is rebuilt on category/search/filter/language change (`_render_page`).
  Never rebuild synchronously inside a card's own signal: use `QTimer.singleShot(0, self, ...)`.
  Delayed callbacks touching cards must use the context-object form `singleShot(ms, widget, fn)`
  so Qt cancels them when the widget dies (a captured card caused "C++ object already deleted").
- Styling only via `theme.py` tokens + dynamic properties (`changed`, `variant`, `kind`); call
  `repolish(widget)` after changing a property. Icons: `data/icons/*.svg`.
- Editors: `editors.create_editor()`; sliders/spins/combos are wheel-guarded (no value change
  while scrolling the page). `set_raw()` must never emit `edited`.
- All dialogs go through `MainWindow._ask/_prompt_unsaved/_show_message/_exec_dialog` - tests replace them;
  a real modal `exec()` hangs the headless test run.
- Any change to the working copy must end in `_after_changes(ids)` (cards, nav, panel, buttons).
- History restores pass through `_user_values()`, which drops read-only and `game_managed` settings.
- Account files (`g.codNN.1.0.l`, `g.codNN.pm.1.0.l`) are editable since stage 7; edits were
  confirmed in game (FILE_FORMAT.md: `.l.b` analysis + in-game tests #1/#2). The game writes floats
  back via float32 (119.9 -> 119.900002), hence `diff.same_value()` tolerance.
  `discovery.classify_stem()` tells machine vs account files apart.

## Hard rules for touching game files
1. Never write while `cod.exe` is running.
2. Always back up `txt0`, `txt1` and `.m` before writing.
3. Write identical content to **both** `.txt0` and `.txt1`, atomically (temp + `os.replace`). Never edit `.m`.
4. Round-trip guarantee: untouched lines stay byte-identical. LF line endings, no BOM, trailing newline.
5. Never change the numbers after `@` (`Variant;TypeId;DefaultId`). Setting identity = `Key@Variant`.
6. Never touch binary files (`*.b0`, `*.b1`, `*.l.b0/1`, `*.kb`, `*.cdb`) or the SteamCloud folder.
7. Do not hard-code `cod25` — discover `s.1.0.cod*.txt*`. Unknown keys must still render (from inline constraint).
8. Tests and manual experiments use copies in `examples/` or a temp dir — never the live folder,
   unless the user explicitly asks.

## Layout
```
docs/            design docs (see above); docs/img/ = README screenshots
examples/        sample files from the user's machine (fixtures for tests)
  live_snapshot_2026-10-17/   .m marker, cod26 file, account-level profile files
scripts/         build_exe.py (PyInstaller), build_icon.py (svg -> png/ico), launcher.py (exe entry)
src/wzce/
  __init__.py    __version__ (single source of the version)
  __main__.py    CLI: GUI (default), --report, --system-report, --smoke-test, --version
  core/          Qt-free logic: parsing, storage, session, history, templates, hardware, exports
  data/          settings_db/ (knowledge base), i18n/{en,pl}.json, icons/
  ui/            PySide6 widgets and dialogs
tests/           pytest (+ fixtures/system_cim.json)
build/, dist/    PyInstaller output (git-ignored)
```
Module-by-module map: `docs/ARCHITECTURE.md`.

## Commands
```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run wzce                   # start the GUI
uv run wzce --report          # read-only text report of the real files
uv run wzce --system-report   # read-only hardware + Windows settings probe as JSON
uv run wzce --smoke-test      # build the UI headless and exit (0 = OK)
uv run python scripts/build_exe.py [--onedir]   # PyInstaller build + smoke test -> dist/
uv run python scripts/build_icon.py             # after editing data/icons/app.svg
```
Version lives only in `src/wzce/__init__.py`; bump it and add a CHANGELOG.md entry per release.
Run pytest + ruff before every commit. Tests import helpers with `from conftest import ...`.
GUI tests run offscreen (`QT_QPA_PLATFORM` set in `tests/conftest.py`). For screenshots offscreen
also set `QT_QPA_FONTDIR=C:/Windows/Fonts`, otherwise text renders as boxes.

## i18n and knowledge base
- UI strings: `src/wzce/data/i18n/{en,pl}.json` (flat keys, `{placeholder}` format). Every new key goes
  into **both** files with the same placeholders - `tests/test_i18n.py` enforces it.
- Setting labels/descriptions/recommendations: `src/wzce/data/settings_db/<group>.json` for the
  machine file and `account_<group>.json` for account files (+ `_meta.json`). Polish must be a
  real translation, enum values in `recommend` must use the game's exact spelling -
  `tests/test_knowledge.py` enforces it.
- New game setting -> add a sample file to `examples/`, run the knowledge tests, they list missing ids.
