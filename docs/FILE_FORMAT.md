# CoD settings file format (`s.1.0.cod25.txt0/1`) — technical spec

> Reverse-engineered from real files on 2026-10-17 (Black Ops 7 / Warzone, `cod25`).
> Sample files live in `examples/`. Anything marked **HYPOTHESIS** is not confirmed —
> verify before relying on it and update this file when you learn more.

## 1. File ecosystem

Root: `%LOCALAPPDATA%\Activision\Call of Duty\players\`

| File | Format | Scope | Contents |
|---|---|---|---|
| `s.1.0.cod25.txt0` / `.txt1` | text | machine | Audio devices/volumes, Display, Graphics, Gameplay (FPS caps, blood), Interface, Mouse & Gamepad (menu/gamepad speeds), System (VRAM, worker threads, detected HW) |
| `s.1.0.cod25.m` | 2 bytes | machine | A/B slot marker for the two files above (see §4) |
| `<platformId>\g.cod25.1.0.l.txt0` / `.txt1` (+ `.l.m`, `.l.b0/.b1`) | text | account | Mouse sensitivity, ADS multipliers, FOV, audio mix preset, HDR, HUD bounds, accessibility |
| `<platformId>\g.cod25.pm.1.0.l.txt0` / `.txt1` | text | account | FOV (small file) |
| `<platformId>\g.cod25.1.0.b0` / `.b1`, `g.cod25.pm.1.0.b0/.b1` | binary | account | Binary profile (probably the authoritative/cloud copy) — **do not touch** |
| `<platformId>\keybinds.cod25.kb` | binary (`codk` magic) | account | Key bindings — **do not touch** |
| `<platformId>\settingspresets.cod25.2.cdb`, `favoritesettings.cod25.2.cdb` | binary | account | In-game presets/favourites |
| `<platformId>\SteamCloud\...` | mixed | account | Steam Cloud mirror |
| `s.1.0.cod26.txt` (single file, no A/B) | text | machine | Next title (`cod26`), same grammar, 163 settings |

`<platformId>` is e.g. a SteamID64 (`7656119...`). Older title BO6 (`cod24`) lives in
`%USERPROFILE%\Documents\Call of Duty\players\` with the same naming scheme.

The **title code** (`cod24`, `cod25`, `cod26`) must never be hard-coded — discover files by
glob `s.1.0.cod*.txt*`.

## 2. Encoding

- ASCII / UTF-8 without BOM, **LF** line endings (no `\r`), trailing newline at EOF.
- Keep everything byte-identical except the value we change (round-trip guarantee).

## 3. Grammar

```
file        := header blank* (section | entry | blank)*
header      := "1"                       ; format version, first line
section     := "//" NL "// " SectionName ; a bare "//" line followed by "// Name"
entry       := "// " Description NL setting
setting     := Key "@" Variant ";" TypeId ";" DefaultId " = " Value [ " // " Constraint ]
Constraint  := Min " to " Max            ; numeric range (int or float, 6 decimals)
             | "one of " Opt (", " Opt)* ; enum
```

Examples:

```
ResolutionMultiplier@0;64786;30730 = 100 // 0 to 200
NvidiaReflex@0;33761;11445 = Enabled + boost // one of Disabled, Enabled, Enabled + boost
WindowsSonicEnable@0;57752;48403 = false
SoundOutputDevice@0;2059;35888 = {0.0.0.00000000}.{d54d4c6c-f7bb-4fdf-a193-20e12ee43b61}
SoundInputDevice@0;2059;35888 =             <- empty value is valid
Handheld Fov@0;24892;5108 = 80.000000 // 60.000000 to 120.000000   <- key may contain spaces
```

Parsing rules / pitfalls:

- Split the setting line on the **first** `" = "`; then split the right side on the **first**
  `" // "` (values never contain `//`, but enum options contain spaces, `+`, `%`, `:`, `.`).
- Keys can contain spaces (`TextChat background opacity`), so the key is everything before `@`.
- Value types inferred from the constraint + value:
  - `true`/`false` and no constraint → **bool**
  - `one of ...` → **enum** (options are case-sensitive, keep exact spelling: `Very_Low`, `0_Off`, `aniso 2x`)
  - `A to B` with decimals → **float** (always written with 6 decimals: `0.850000`)
  - `A to B` without decimals → **int**
  - no constraint, non-bool → **string** (device GUIDs, GPU/monitor names, `Auto`)
- Some float ranges are absurd (`-3.4e38 to 3.4e38`, `0 to 2147483647`) → use a spin box, not a slider.
- The same key can appear with different variants: `DepthOfField@0` (bool) and `DepthOfField@1`
  (enum). The **identity of a setting is `Key@Variant`**, not `Key`.
- Description comments may be duplicated or shared between variants.
- One trailing block (`LicensedMusicVolume`, `MouseUsesRawInput`, `VRSValidationMask`) sits
  **after** the System section without its own section header → treat as "Other".

### Meaning of the two numbers after the variant

- `TypeId` (2nd field) — **HYPOTHESIS:** hash of the value domain/type.
  `57752` = bool (51 occurrences), `14317`/`54363` = float 0..1, `2059` = free string,
  `27441` = upscaler quality enum, `24622` = sensitivity multiplier 0.1..4.
- `DefaultId` (3rd field) — **HYPOTHESIS:** hash of the default value.
  `48403` ≈ default `false`, `20945` ≈ default `true`, `21371` ≈ default `1.0`,
  `7764` ≈ default `0`/first option, `43096` ≈ 1, `11445` ≈ 2, `58629` ≈ 3.
  Not a plain CRC16/CRC32/FNV/Adler of the value text (tested). If cracked, we get
  "reset to game default" for free.
- **Never modify these numbers.** Copy them verbatim.

## 4. Why two files (`.txt0` / `.txt1`) + `.m`

Evidence from the live folder (2026-10-17):

- Every persisted file in the profile folder follows the same pattern: `X0`, `X1` and `X.m`
  (`g.cod25.1.0.b0/.b1` + `g.cod25.1.0.m`, `...l.txt0/.txt1` + `...l.m`).
- `.m` is 2 bytes: `00 00` or `01 01`. In every case where timestamps differ, the slot named
  by `.m` is the newer file (`g.cod25.1.0.m = 01 01` → `b1` newer; `g.cod25.1.0.l.m = 00 00` → `l.txt0` newer).

**Conclusion (high confidence):** A/B ("ping-pong") double buffering for crash-safe saving.
The game writes the inactive slot, then flips `.m`. If a write is interrupted, the other slot is
still valid. On load it reads the slot from `.m` and falls back to the other one.
The two bytes are probably the slot index written twice for integrity.

Editor strategy:

1. Refuse to write while `cod.exe` is running (the game rewrites both files on exit).
2. Write the **same content to both** `.txt0` and `.txt1` (community advice: "mimic txt0 with txt1").
   Then `.m` does not matter. Do not change `.m`.
3. Write atomically: temp file in the same folder → `os.replace`.
4. Back up all three files before every save.

## 5. Special keys

- `DO NOT MODIFY` in description → render read-only (`DetectedFrequencyGHz`,
  `DetectedMemoryAmountMB`, `GPUDriverVersion`, `LastUsedGPU`, `VRSValidationMask`).
- `RecommendedSet = false` → game resets everything to recommended on next start
  (useful "factory reset" button).
- `ConfigCloudStorageEnabled = true` → cloud may overwrite local edits.
- `DisableHWChangeDetection = false` → new GPU/driver may trigger re-detection and reset.
- Hardware-specific (exclude from shareable templates): `GPUName`, `LastUsedGPU`, `Monitor`,
  `SoundOutputDevice`, `SoundInputDevice`, `VoiceOutputDevice`, `Window*`, `Detected*`,
  `DisplayDriverVersion*`, `GPUDriverVersion`, `ESSDI`, `LastSavedDriveType`.

## 6. Differences cod25 → cod26 (for forward compatibility)

New in cod26: `DLSSFrameGenerationDynamicMulti@0/1`, `DLSSFrameGenerationmulti@1`,
`DLSSFrameGenerationmultiType@0`, `DLSSModeMP@1`, `DofEnable@0`, `DofWeaponDisable@0`,
`DofWorldDisable@0`, `IntelXEFGMulti@0`, `IntelXeFG@0`, `IntelXeLL@0/1`, `MotionBlur@0`,
`OfflineGameUpdaterUsage@0`, `SMAAFilmicAlphaStrength@0`, `SSRQuality@1`, `ShadingQuality@0`,
`ShadowFilteringQuality@0`, `SustainabilityPauseRendering@1`, `VolumetricQuality@1`,
`WeaponMotionBlur@0`.
Removed: `DepthOfField@0/1`, `LicensedMusicVolume@0`, `MouseUsesRawInput@0`, `VRSValidationMask@0`.

→ The editor must render **unknown keys automatically** from the inline constraint, using the
knowledge base only for labels/descriptions/recommendations.
