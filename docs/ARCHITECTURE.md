# Architecture & development guide

How the code is organised, how data flows through it, and how to extend, test and release it.
File-format facts live in [`FILE_FORMAT.md`](FILE_FORMAT.md), the knowledge-base schema in
[`KNOWLEDGE_BASE.md`](KNOWLEDGE_BASE.md), the API cheat sheet and hard rules in
[`CLAUDE.md`](../CLAUDE.md).

## 1. Layers

```
wzce.__main__  (CLI: GUI | --report | --smoke-test | --version)
      │
      ▼
wzce.ui        PySide6 widgets/dialogs. Reads and drives an EditorSession.
      │        Never parses or writes game files itself.
      ▼
wzce.core      Pure Python, no Qt import anywhere (a project rule, see CLAUDE.md).
      │        Everything testable here.
      ▼
wzce.data      Read-only package data: knowledge base, translations, icons.
```

`core` must stay Qt-free: the `--report` CLI and most tests import it without Qt, and it keeps
the game-file logic reviewable on its own.

## 2. Module map

### `src/wzce/core/`

| Module | Responsibility |
|---|---|
| `errors.py` | `WzceError` hierarchy (parse, validation, unknown setting, game running, write verification, backup); `KnowledgeError` lives in `knowledge.py` |
| `model.py` | `Setting`, `Constraint`, `ValueType`; value validation and canonical formatting |
| `document.py` | text ⇄ `ConfigDocument`, byte-exact round-trip, `set_value`, `apply_values` |
| `diff.py` | setting-level diff of documents/snapshots; `same_value()` float32 tolerance |
| `storage.py` | `SettingsFileSet`: A/B slots (`txt0/txt1` or single `.txt`), atomic save of both slots, read-only attribute, rollback |
| `backup.py` | `BackupManager`: timestamped copies of `txt0/txt1/.m` + sha256 manifest, restore, prune |
| `discovery.py` | finds machine (`s.1.0.codNN`) and account (`g.codNN.1.0.l`, `g.codNN.pm.1.0.l`) files; `TITLE_NAMES`, `classify_stem()` |
| `process.py` | `cod.exe` detection (psutil) |
| `paths.py` | app data root (`%APPDATA%\WarzoneConfigEditor`, `WZCE_DATA_DIR` override), game folders |
| `undo.py` | undo stack; quick edits of one setting merge into one step |
| `history.py` | `HistoryStore`: SAVE and GAME_CHANGE entries (diff + snapshot), `last_seen` snapshot |
| `session.py` | `EditorSession`: original vs working copy, edits, undo/redo, save, reload, external change |
| `knowledge.py` | `KnowledgeBase` loader/validator, `entry_for()` synthesizes entries for unknown ids |
| `i18n.py` | `Translator` with EN fallback and language-change listeners |
| `templates.py` | templates, built-in presets, `plan_template()` preview, `exclusion_reason()`, `TemplateStore` |
| `hardware.py` | `detect_hardware()` → `HardwareInfo` (cores/P-cores, VRAM, GPU vendor, refresh rate, ReBAR) |
| `optimizer.py` | `recommend()`: goal + bottleneck + hardware → values with `Reason`s |
| `system_info.py` | `collect_system_info()` → `SystemInfo` (PowerShell CIM JSON, registry, powercfg, nvidia-smi, Steam manifests); pure `parse_*` helpers |
| `system_checks.py` | `evaluate_checks()` → 15 `CheckResult`s (EXPO, channels, HDD, refresh, driver, PCIe, ReBAR, power plan…) |
| `display.py` | `display_value()`: one human-readable rendering of a value for cards, panels and exports |
| `share_export.py` | `build_share()` → `to_markdown()` / `to_json()` for "Share settings" |

### `src/wzce/ui/`

| Module | Responsibility |
|---|---|
| `app.py` | `run()` (QApplication, theme, main window), `smoke_test()` (exit codes 2/3/4 = failure stage) |
| `app_settings.py` | `settings.ini` via `QSettings` (language, filters, geometry, collapsed bar…) |
| `theme.py` | colour/size tokens, stylesheet, `repolish()`, `icon_path()` |
| `main_window.py` | window, file picker, category nav, card page, toolbar/menus, game/disk polling, dialog hooks |
| `setting_card.py` | one setting: title + file key, description, badges, editor, recommendation, revert |
| `editors.py` | `create_editor()`: toggle, slider+spin, segmented, combo, text; wheel-guarded |
| `changes_panel.py` | pending changes "before → after" |
| `history_dialog.py` | history list, diff, restore |
| `templates_dialog.py` | built-in presets, user templates, import/export, template from another file |
| `plan_table.py` | shared preview table for template/optimizer plans (choose which changes to apply) |
| `optimizer_dialog.py` | optimizer wizard (goal, bottleneck, system hints) |
| `system_panel.py` | `SystemProbe` (daemon thread), `HardwareBar`, `SystemDialog` (spec + checks) |
| `share_dialog.py` | "Share settings" dialog: groups, language, format, live preview, copy/save |

### Other

| Path | Responsibility |
|---|---|
| `src/wzce/data/settings_db/` | knowledge base (`_meta.json`, `<group>.json`, `account_<group>.json`) |
| `src/wzce/data/i18n/{en,pl}.json` | UI strings, flat keys, `{placeholder}` format |
| `src/wzce/data/icons/` | UI icons (SVG) and `app.svg` → `app.png` / `app.ico` |
| `scripts/build_exe.py` | PyInstaller build (`--onefile` default, `--onedir`), version resource, smoke test, `.sha256` |
| `scripts/build_icon.py` | renders `app.svg` to png/ico |
| `scripts/launcher.py` | PyInstaller entry script (calls `wzce.__main__.main`) |

## 3. Data flows

**Load.** `discover()` → `ConfigLocation` → `SettingsFileSet.load()` reads the slot named by the marker
`.m` (the other slot is compared, a broken one is tolerated) and reports `slot_differences` → `EditorSession`
keeps `original` and a working `document` copy → `HistoryStore.check_external_change()`
compares with `last_seen`; a difference becomes a GAME_CHANGE entry (`session.external_change`)
and the UI shows the banner.

**Edit.** Card `value_edited` → `MainWindow._on_value_edited` → `session.set_value()` (validates,
pushes undo) → `_after_changes(ids)` refreshes cards, nav counters, changes panel and buttons.
Bulk changes (templates, optimizer, history restore) go `plan_template()` → user picks rows in
`plan_table` → `session.apply_raw_values(..., kind=BULK)` → one undo step.

**Save.** `MainWindow` refuses while the game runs and asks before overwriting a file that
changed on disk → `session.save()`: records the overwritten external state, then
`SettingsFileSet.save()` (backup → write temp files → `os.replace` both slots → rollback on
error) → history SAVE entry → `last_seen` updated → prune (50 backups, 200 history entries) →
`reload(keep_undo=True)`; the card page keeps its scroll position (`_page_key`).

**Polling.** Every 2 s `_poll()` checks `cod.exe` and `disk_changed()`. A clean session reloads
silently; a dirty one only shows a status warning.

**Hardware/system.** `detect_hardware(doc)` is fast and synchronous (Win32 + values the game
wrote into the machine file). `collect_system_info()` takes 2–4 s and runs in `SystemProbe`
(daemon thread, result delivered to the UI thread by a signal). Both never raise: unknown
values are `None` and the UI shows "unknown".

**What never leaves the machine.** `exclusion_reason()` (hardware-specific, game-managed,
read-only) is the single rule used by templates, history restores and the share export. The
share export also drops other-vendor settings and never includes device ids, driver versions,
paths or account ids.

## 4. App data

`%APPDATA%\WarzoneConfigEditor\` (override: `WZCE_DATA_DIR`):

| Folder/file | Contents |
|---|---|
| `backups/` | one folder per backup with copies of `txt0/txt1/.m` and a manifest |
| `history/` | JSON entries per settings file (path hash keeps installs/accounts apart) |
| `templates/` | user templates (`format: wzce-template`) |
| `settings.ini` | UI preferences |

## 5. Extending

- **New game setting / title**: add the sample file to `examples/`, run
  `uv run pytest tests/test_knowledge.py` — it lists ids missing from the knowledge base. Add
  entries to the right `settings_db/*.json` (both languages). Unknown settings still render
  without this step (synthesized entry, "New" badge).
- **New UI text**: add the key to both `i18n/en.json` and `i18n/pl.json` with the same
  placeholders (`tests/test_i18n.py`).
- **New dialog**: open it through `MainWindow._exec_dialog` so tests can replace it; questions
  and messages through `_ask` / `_show_message`.
- **New system check**: add it to `system_checks.py` with texts `checks.<id>.title/problem/fix/ok`
  and a case in `tests/test_system.py` (use `tests/fixtures/system_cim.json`).
- **New optimizer rule**: knowledge-base `rule` field + implementation in `optimizer.py`;
  results always go through `plan_template()`.
- **Anything that writes game files** must follow the hard rules in `CLAUDE.md`.

## 6. Testing

```
uv run pytest                 # all tests (core + GUI offscreen)
uv run pytest tests/test_ui.py -k share
uv run ruff check . && uv run ruff format .
uv run wzce --smoke-test      # build the whole UI headless, exit 0 = OK
```

- Tests use copies of `examples/` files in `tmp_path`; never the live game folder.
- An autouse fixture sets `WZCE_DATA_DIR` to a temp folder.
- GUI tests run with `QT_QPA_PLATFORM=offscreen` (set in `tests/conftest.py`) and pytest-qt;
  inject `game_running=lambda: False`, `hardware_provider`, `system_info_provider=None` or a fixture.
- Modal `exec()` hangs the headless run — always go through the dialog hooks.
- Screenshots offscreen need `QT_QPA_FONTDIR=C:/Windows/Fonts`.

## 7. Release checklist

1. Bump `__version__` in `src/wzce/__init__.py` (the only place; `pyproject.toml` reads it).
2. Add a `CHANGELOG.md` section (Polish, Keep a Changelog style) and update the version/file
   name in `README.md` (download section).
3. Tick finished items in `docs/PLAN.md`; update screenshots in `docs/img/` if the UI changed.
4. `uv run ruff check . && uv run ruff format . && uv run pytest`.
5. `uv run python scripts/build_exe.py` → `dist/WarzoneConfigEditor-<version>.exe` + `.sha256`
   (the script runs the smoke test on the built exe).
6. Commit, then tag `v<version>`.
