# Knowledge base (`src/wzce/data/settings_db/`) — schema and conventions

The knowledge base adds human-friendly metadata on top of what the game file
already says. Loader: `wzce.core.knowledge.KnowledgeBase.load()`. Validation is strict and
`tests/test_knowledge.py` cross-checks everything against the sample game files.

## Files

| File | Contents |
|---|---|
| `_meta.json` | presets, groups + subgroups (editor navigation order), section fallback map |
| `<group>.json` | `{"group": "<group id>", "settings": {"Key@Variant": {...}}}` — one file per group |

One file per group keeps edits small and reviewable. The group of an entry is the file's
`group`; it is not repeated in each entry.

## Entry fields

```jsonc
"NvidiaReflex@0": {
  "subgroup": "sync_latency",                  // required, must exist in _meta.json for this group
  "label": {"en": "...", "pl": "..."},         // required, both languages
  "desc":  {"en": "...", "pl": "..."},         // required, both languages, PL must differ from EN
  "options": {"Enabled": {"pl": "Włączony"}},  // enum option display labels; EN defaults to raw spelling
  "impact": {"latency": 3, "fps": 1},          // 0..3 per fps/latency/visibility/vram; omitted = 0
  "recommend": {"competitive": "Enabled + boost", "balanced": "Enabled"},  // per preset id
  "tip": {"en": "...", "pl": "..."},           // why the recommendation (optional)
  "flags": ["advanced"],                       // advanced | hardware_specific | game_managed
  "vendor": "nvidia",                          // nvidia | amd | intel: only relevant on that GPU
  "widget": "percent",                         // percent | spin | device | text (UI hint)
  "unit": "ms",                                // display unit (free text)
  "rule": "physical_cores",                    // physical_cores | vram_fraction | refresh_rate_cap (core/optimizer.py)
  "related": ["GPUUploadHeaps@0"]              // must reference existing entries
}
```

### Value conventions

- `recommend` values use **JSON types**: `true/false` for bools, numbers for int/float, and the
  game's **exact** enum spelling (`"Very_Low"`, `"aniso 16x"`, `"0_Off"`). Tests reject
  non-canonical spellings.
- A preset that should not touch a setting simply omits it (audio volumes, devices, window).
- Hardware-dependent values use `rule`; a static `recommend` value may still be given as a
  fallback when detection is unavailable.
- Constraints differ between titles (cod26 removed `DLAA` from `DLSSModeMP@0`). Such cases
  are listed in `KNOWN_TITLE_DIFFERENCES` in `tests/test_knowledge.py`; applying a preset
  reports them via `ConfigDocument.apply_values` errors instead of failing.
- `vendor` marks settings that only do something on that GPU vendor. Presets should skip
  them for other vendors (stage 5/6). FSR, XeSS upscaling and CAS work on all GPUs → no vendor.

### Flags

| Flag | Meaning in the UI |
|---|---|
| `advanced` | hidden in Simple mode |
| `hardware_specific` | excluded from shareable templates (devices, GPU/monitor names, window geometry, detected HW) |
| `game_managed` | written by the game; shown but de-emphasized. Every `DO NOT MODIFY` setting must have it |
| `new` | **never in JSON** — set on synthesized entries for settings missing from the knowledge base |

## Groups (editor categories)

`display`, `performance`, `upscaling`, `quality`, `gameplay`, `audio`, `interface`, `controls`,
`power`, `system`. They intentionally differ from the game's 7 file sections — e.g. the
64-setting "Graphics" section is split into performance / upscaling / quality, and HDR moves
to display. The reserved subgroup `system/unknown` collects synthesized entries.

## Unknown settings

`KnowledgeBase.entry_for(setting)` returns a synthesized entry when an id is missing:
group from `section_fallback` (file section → group), humanized key as label
(`MaxFpsInGame` → `Max Fps In Game`), the file's English comment as description in every
language, flags `new` + `advanced`. So a game update never breaks the editor — it only adds
"New" badges until the knowledge base is updated.

## Adding / updating entries (checklist)

1. Copy a new sample file into `examples/` (or a `live_snapshot_*` folder).
2. Run `uv run pytest tests/test_knowledge.py` — missing ids are listed.
3. Add entries to the right group file; write both languages; check enum spelling.
4. Re-run tests; add genuine title differences to `KNOWN_TITLE_DIFFERENCES`.

## Sources

Descriptions and recommendations are compiled from the game's own comments and the
community guides listed in `docs/RAPORT.md`. Impact values are estimates. Uncertain semantics
are stated as such in the description ("undocumented", "most likely").
