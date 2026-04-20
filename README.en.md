# Goru Font Builder

A config-driven font build system that merges English, Korean, and Japanese monospace fonts
into a single perfectly aligned multilingual coding font. CJK glyphs are exactly 2× the
width of Latin glyphs, so every column lines up regardless of language.

---

## Profiles

Four built-in profiles cover the most common use cases.

| Profile | Half-width | Full-width | Description |
|---|---|---|---|
| `mono` | 1024 | 2048 | Standard 1:2 ratio — default |
| `mono-c` | 870 | 1740 | Condensed — narrower Latin glyphs |
| `absolute-mono` | 1024 | 1024 | All glyphs the same width |
| `absolute-mono-c` | 870 | 870 | Condensed absolute |

Profiles inherit from each other via `extends` — only the values that differ are specified.

---

## Prerequisites

### 1. Python 3.8+

```bash
python --version
```

### 2. FontForge

FontForge must be available on your `PATH` as the `fontforge` command.

```bash
# macOS
brew install fontforge

# Ubuntu / Debian
sudo apt-get install fontforge

# Windows — download the installer from https://fontforge.org
# After installing, add the bin directory to PATH, e.g.:
# C:\Program Files (x86)\FontForgeBuilds\bin
```

Verify:
```bash
fontforge --version
```

### 3. Python dependencies

```bash
pip install -r requirements.txt
```

| Package | Role |
|---|---|
| `fonttools` | Post-processing: writes monospace metadata to TTF |
| `jinja2` | Renders FontForge scripts from templates |
| `pyyaml` | Reads YAML config files |
| `rich` | Optional — enhanced parallel progress display |

### 4. Source fonts

The build system merges three source fonts.
Place the font files exactly as shown below — filenames must match the entries in
`src/configs/build/mono.yaml` under each language's `source_files`.

```
src/resources/source_fonts/
├── english/
│   ├── MesloLGM-Regular.ttf
│   ├── MesloLGM-Bold.ttf
│   ├── MesloLGM-Italic.ttf
│   └── MesloLGM-BoldItalic.ttf
├── korean/
│   ├── SarasaFixedK-Regular.ttf
│   ├── SarasaFixedK-Bold.ttf
│   ├── SarasaFixedK-Italic.ttf
│   └── SarasaFixedK-BoldItalic.ttf
└── japanese/
    ├── SarasaFixedJ-Regular.ttf
    ├── SarasaFixedJ-Bold.ttf
    ├── SarasaFixedJ-Italic.ttf
    └── SarasaFixedJ-BoldItalic.ttf
```

Download links:
- **Meslo LG M** — [github.com/andreberg/Meslo-Font](https://github.com/andreberg/Meslo-Font)
- **Sarasa Gothic** — [github.com/be5invis/Sarasa-Gothic](https://github.com/be5invis/Sarasa-Gothic)
  (use the `SarasaFixed` variant)

---

## Usage

All commands are run from the project root (`goru-font/`).

```
python run.py [-p <profile>...] [-s <style>...] [-w <n>] [-seq]
```

```bash
# Build all 4 styles with the default profile (mono)
python run.py

# Build specific styles only
python run.py -s regular bold

# Build a single profile
python run.py -p mono-c

# Build multiple profiles sequentially
python run.py -p mono mono-c absolute-mono absolute-mono-c

# Limit parallel workers (reduces memory use)
python run.py -w 2

# Sequential style processing — one style at a time (useful for debugging)
python run.py --sequential

# Combine options
python run.py -p mono-c -s regular --sequential
```

### CLI reference

| Flag | Default | Description |
|---|---|---|
| `-p / --profile` | `mono` | Profile name(s) — space-separated list for multi-profile builds |
| `-s / --styles` | all | `regular` `bold` `italic` `bold_italic` |
| `-w / --workers` | `4` | Parallel worker count |
| `-seq / --sequential` | off | Force sequential processing |

### Output

Built fonts are written to:

```
output/v{version}/
├── GoruMono-Regular.ttf
├── GoruMono-Bold.ttf
├── GoruMono-Italic.ttf
└── GoruMono-BoldItalic.ttf
```

The version comes from `font.version` in the font config (`src/configs/font/mono.yaml`).

---

## Build Process

Here is exactly what happens when you run `python run.py`.

### Step 0 — Config loading

The builder loads three config files and deep-merges them:

1. `src/configs/font/mono.yaml` — font identity (family name, version, copyright)
2. `src/configs/build/mono.yaml` — metrics, grid widths, source files, per-language scale
3. `src/configs/logging/logging.yaml` — terminal/file log settings

`mono.yaml` extends `base.yaml`, which in turn provides the language processing pipeline
(templates, order, overlap rules, character classification).

### Step 1 — Validation

Before any files are touched, the builder checks:

- All required config fields are present (`font.family`, `metrics.*`, `width.*`,
  `languages.*.scale.*`, `languages.*.source_files.*`)
- Every source font file actually exists on disk

If anything is missing, the builder prints exactly which field is absent and exits.
Nothing is created until validation passes.

### Step 2 — Temp directory

A timestamped working directory is created under `temp/`:

```
temp/build_20260419_153000/
```

Intermediate `.sfd` files (FontForge's native format) and generated `.pe` scripts are
stored here. The directory is automatically deleted when the build finishes (or is
interrupted).

To keep the scripts for inspection, set `output.save_temp_files: true` in your build
config. Scripts are then copied to `backups/scripts_{timestamp}/` before cleanup.

### Step 3 — Script generation

For each style (`regular`, `bold`, `italic`, `bold_italic`), Jinja2 renders a FontForge
PE script from the template specified in each language config:

| Language | Template |
|---|---|
| English | `src/ff/service/en_processing.pe.j2` |
| Korean | `src/ff/service/kr_processing.pe.j2` |
| Japanese | `src/ff/service/jp_processing.pe.j2` |
| Merge | `src/ff/service/final_merge.pe.j2` (configurable via `output.merge_template`) |

The templates receive the language config (`lang.*`), input font paths, output SFD paths,
and reference SFD paths (for overlap removal). No language names are hardcoded in Python.

### Step 4 — Language processing (FontForge)

Each language is processed in order (English → Korean → Japanese). For each language,
FontForge:

1. Opens the source TTF
2. Removes excluded glyphs (English only)
3. Unlinks composite glyphs
4. Scales to the target EM (`em_ascent` / `em_descent`)
5. Classifies every glyph:
   - **`no_center`** ranges → width set, no centering (box-drawing, block elements)
   - **`no_scale`** ranges → centering only, no scaling (arrows, symbols, Powerline)
   - **`halfwidth`** ranges → scale to `half_width` slot using `lang.scale.half_width_*`
   - **`fullwidth`** ranges → scale to `full_width` slot using `lang.scale.full_width_*`
   - Everything else → classified by original glyph width vs. `width.threshold`
6. Removes kerning (GPOS) and ligature (GSUB) tables
7. Rounds all coordinates to integers
8. Saves as `.sfd` to the temp directory

Korean and Japanese also remove any glyphs that already appear in previously processed
fonts (controlled by `remove_overlaps_with` in each language config). This is how the
English glyphs take precedence over CJK variants of the same code point.

Styles run in parallel by default (4 workers). Each worker processes all languages for
one style independently.

### Step 5 — Merge (FontForge)

The final merge script:

1. Opens the English SFD as the base
2. Merges Korean and Japanese SFDs in order
3. Sets all font metadata (names, OS/2 values, copyright, version)
4. Removes any remaining kerning and ligature tables
5. Generates the final TTF to `output/v{version}/`

### Step 6 — Post-processing (Python)

`fonttools` opens each generated TTF and writes three monospace metadata fields:

| Field | Value | Effect |
|---|---|---|
| `post.isFixedPitch` | `1` | Declares the font as fixed-pitch |
| `OS/2.panose.bProportion` | `9` | PANOSE monospace classification |
| `OS/2.xAvgCharWidth` | `half_width` | Correct average character width |

Without this step, some applications (VS Code, Windows terminal) may not recognize the
font as monospace.

---

## Configuration Structure

```
src/
├── configs/
│   ├── paths.yaml              ← All directory paths (one place to change paths)
│   ├── font/                   ← Font identity only (name, version, copyright)
│   │   ├── mono.yaml
│   │   ├── mono-c.yaml
│   │   ├── absolute-mono.yaml
│   │   └── absolute-mono-c.yaml
│   ├── build/                  ← Processing settings (metrics, grid, scale, source files)
│   │   ├── base.yaml           ← Language pipeline, character classification, build flags
│   │   ├── mono.yaml           ← Extends base + metrics + width + per-language settings
│   │   ├── mono-c.yaml         ← Extends mono, overrides width + scale
│   │   ├── absolute-mono.yaml  ← Extends mono, overrides full_width + scale
│   │   ├── absolute-mono-c.yaml
│   │   └── minimal.yaml        ← Extends mono, regular-only (for quick testing)
│   └── logging/
│       └── logging.yaml
└── profiles/
    └── profile.yaml            ← Maps profile names to font + build config filenames
```

### `paths.yaml`

Controls where every directory lives, relative to the project root.
Change a directory here — no Python file needs to be edited.

```yaml
source_fonts:     "src/resources/source_fonts"
templates:        "src/ff/service"
output:           "output"
logs:             "logs"
temp:             "temp"
backups:          "backups"
profile_registry: "src/profiles/profile.yaml"

config_dirs:
  font:    "src/configs/font"
  build:   "src/configs/build"
  logging: "src/configs/logging"
```

Override at runtime with an environment variable:

```bash
GORU_PATHS_FILE=/path/to/custom-paths.yaml python run.py
```

### Font config (`src/configs/font/mono.yaml`)

Font identity only — name, version, copyright, URLs.

```yaml
font:
  family:       "Goru Mono"
  family_short: "GoruMono"
  version:      "1.0.0"
  copyright:    "Copyright (c) 2026, kkotdari"
  ...
```

### Build config (`src/configs/build/mono.yaml`)

Everything needed to process and assemble the font. Per-language source files and scale
are grouped together inside each language entry.

```yaml
extends: "base.yaml"

metrics:
  em_ascent:  1792
  em_descent:  512
  ...

width:
  half_width: 1024
  full_width: 2048
  threshold:  1536

languages:
  english:
    source_files:
      regular:     "MesloLGM-Regular.ttf"
      bold:        "MesloLGM-Bold.ttf"
      italic:      "MesloLGM-Italic.ttf"
      bold_italic: "MesloLGM-BoldItalic.ttf"
    scale:
      half_width_x: 0.78
      half_width_y: 0.86
      full_width_x: 0.99
      full_width_y: 0.96
  korean:
    ...
```

---

## Adding a New Language

No Python changes are required. Only YAML and a template file are needed.

1. **Add the template** — copy `src/ff/service/kr_processing.pe.j2` to
   `src/ff/service/zh_processing.pe.j2` and adjust as needed.

2. **Add the language entry** to `src/configs/build/base.yaml`:

```yaml
languages:
  chinese:
    enabled:  true
    template: "zh_processing.pe.j2"
    dir:      "chinese"
    order:    4
    timeout:  900
    vertical_shift: 0
    remove_overlaps: true
    remove_overlaps_with: ["english", "korean", "japanese"]
```

3. **Add source files and scale** to `src/configs/build/mono.yaml`:

```yaml
languages:
  chinese:
    source_files:
      regular:     "SourceHanMono-Regular.ttf"
      bold:        "SourceHanMono-Bold.ttf"
      italic:      "SourceHanMono-Regular.ttf"   # use regular if no italic
      bold_italic: "SourceHanMono-Bold.ttf"
    scale:
      half_width_x: 0.78
      half_width_y: 0.86
      full_width_x: 0.99
      full_width_y: 0.96
```

4. **Place the font files** in `src/resources/source_fonts/chinese/`.

---

## Troubleshooting

### FontForge not found

```bash
# Verify the command works
fontforge --version

# Windows: check PATH
where fontforge
```

### Build fails at validation

The builder prints each missing field. Add the value to the appropriate config file:

```
ERROR: configuration is incomplete — cannot start build:
  languages.english.scale.half_width_x: required
```

→ Add `scale.half_width_x` to the `english` entry in your build config.

### Source font not found

```
[english] regular: file not found (src/resources/source_fonts/english/MesloLGM-Regular.ttf)
```

→ Place the file at the path shown, or update `source_files.regular` in the build config.

### Out of memory during parallel build

```bash
# Reduce workers
python run.py --workers 2

# Or process one style at a time
python run.py --sequential
```

### Inspect intermediate scripts

```yaml
# src/configs/build/mono.yaml (or any build config)
output:
  save_temp_files: true
```

Generated `.pe` scripts are saved to `backups/scripts_{timestamp}/` before the temp
directory is cleaned up. Open them in a text editor to see exactly what FontForge ran.

---

## License

### Generated fonts
Licensed under **SIL Open Font License 1.1**, based on:
- **Meslo LG** by André Berg — Apache License 2.0
- **Sarasa Gothic** by Belleve Invis — SIL OFL 1.1

### Build system
**Apache License 2.0**

```
Copyright (c) 2026, kkotdari
```

---

**Author**: kkotdari | **Repository**: https://github.com/kkotdari/goru-font
