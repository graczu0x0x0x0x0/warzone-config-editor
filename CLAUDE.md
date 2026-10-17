# CLAUDE.md — Warzone Config Editor

GUI editor for Call of Duty: Black Ops 7 / Warzone PC settings files
(`%LOCALAPPDATA%\Activision\Call of Duty\players\s.1.0.cod25.txt0` / `.txt1`).

## Read first
- `docs/FILE_FORMAT.md` — file grammar, A/B slot mechanism, special keys. **Source of truth for parsing.**
- `docs/PLAN.md` — phased plan with checkboxes. Update checkboxes when finishing work.
- `docs/RAPORT.md` — research report for the user (Polish), optimization recommendations + sources.

## Communication
- The user writes in **Polish** → answer in Polish. User-facing docs (`RAPORT.md`, `PLAN.md`, README) in Polish.
- **Code, comments, docstrings, commit messages, dev docs: English.**
- Comments: explain *why* and game-file quirks, not the obvious. Every module starts with a docstring
  describing its responsibility.

## Stack (proposed, pending user approval)
Python 3.12 + PySide6, pytest, ruff, uv, PyInstaller. Package `src/wzce/`.
`core/` must never import Qt (keeps it unit-testable). UI lives in `ui/`.

## Hard rules for touching game files
1. Never write while `cod.exe` is running.
2. Always back up `txt0`, `txt1` and `.m` before writing.
3. Write identical content to **both** `.txt0` and `.txt1`, atomically (temp + `os.replace`). Never edit `.m`.
4. Round-trip guarantee: untouched lines stay byte-identical. LF line endings, no BOM, trailing newline.
5. Never change the numbers after `@` (`Variant;TypeId;DefaultId`). Setting identity = `Key@Variant`.
6. Never touch binary files (`*.b0`, `*.b1`, `*.kb`, `*.cdb`) or the SteamCloud folder.
7. Do not hard-code `cod25` — discover `s.1.0.cod*.txt*`. Unknown keys must still render (from inline constraint).
8. Tests and manual experiments use copies in `examples/` or a temp dir — never the live folder,
   unless the user explicitly asks.

## Layout
```
docs/        design docs (see above)
examples/    sample files from the user's machine (fixtures for tests)
  live_snapshot_2026-10-17/   .m marker, cod26 file, account-level profile files
src/wzce/    application package (core/, data/, ui/)
tests/       pytest
```

## Commands (once scaffolded)
```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
uv run python -m wzce
```

## i18n
UI strings: `src/wzce/data/i18n/{en,pl}.json`. Setting labels/descriptions: `src/wzce/data/settings_db.json`
(fields `label.en/pl`, `desc.en/pl`). Every new UI string goes into **both** files.
