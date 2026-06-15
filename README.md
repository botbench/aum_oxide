# AUM Oxide

[![CI](https://github.com/botbench/aum-oxide/actions/workflows/ci.yml/badge.svg)](https://github.com/botbench/aum-oxide/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/botbench/aum-oxide/graph/badge.svg)](https://codecov.io/gh/botbench/aum-oxide)

Converts an [AUM](https://kymatica.com/apps/aum) `.aum_midimap` file into an [OXI One](https://oxiinstruments.com) `.oxiindef` instrument definition file.

AUM stores MIDI CC mappings for AUv3 plugins in a binary plist format. This tool reads those mappings and produces the JSON instrument definition that the OXI One sequencer uses to display and control parameters by name.

Parameter names are automatically cleaned up — the shared namespace prefix is stripped and camelCase IDs are expanded into readable display names (e.g. `bassadsrLinkEnable` → `ADSR Link Enable`). Parameters that have a CC assigned in AUM are written with that CC number; unassigned ones are included with `nr1: 0` so the OXI One lists them as available to map.

---

## Installation

Requires Python 3.9 or later.

**Clone and install in editable mode (recommended for development):**

```bash
git clone <repo-url>
cd "AUM Oxide"
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Install from source as a regular package:**

```bash
pip install .
```

After installation the `aum-to-oxiindef` command is available on your `PATH`.

---

## Building a distributable package

```bash
pip install build
python -m build
```

This produces a wheel and a source distribution in `dist/`.

---

## Running the tests

Install the package with dev dependencies and run the suite:

```bash
pip install -e ".[dev]"
pytest
```

To see a line-by-line coverage report:

```bash
pytest --cov=aum_oxide.converter --cov-report=term-missing
```

---

## Usage

```
aum-to-oxiindef <input.aum_midimap> [output.oxiindef] [-n NAME] [-m MANUFACTURER] [-a ABBR]
```

You can also invoke it without installing via:

```bash
python -m aum_oxide <input.aum_midimap>
```

### Options

| Flag | Long form | Description |
|------|-----------|-------------|
| | `input` | Path to the `.aum_midimap` file (required) |
| | `output` | Path for the `.oxiindef` output (default: same folder as input, same stem) |
| `-n` | `--name` | Instrument name shown on the OXI display |
| `-m` | `--manufacturer` | Manufacturer string stored in the file |
| `-a` | `--abbr` | Abbreviation shown in tight UI spaces (max 4 characters) |

If `--name` is given but `--abbr` is not, the abbreviation defaults to the first four characters of the name.

The defaults for `--name`, `--abbr`, and `--manufacturer` can also be edited directly in `src/aum_oxide/__main__.py` under the `Configuration` section, which is convenient when batch-converting files for the same instrument.

---

## Examples

**Basic conversion — output written next to the input file:**

```bash
aum-to-oxiindef "King of Bass.aum_midimap"
# Writes: King of Bass.oxiindef
```

**Specify the output path explicitly:**

```bash
aum-to-oxiindef "King of Bass.aum_midimap" ~/OXI/king_of_bass.oxiindef
```

**Override the instrument name:**

```bash
aum-to-oxiindef "King of Bass.aum_midimap" -n "King of Bass"
# Abbreviation defaults to "King" (first 4 chars of the name)
```

**Override name, abbreviation, and manufacturer:**

```bash
aum-to-oxiindef "King of Bass.aum_midimap" \
    -n "King of Bass" \
    -a "KoB" \
    -m "Bram Bos"
```

**Override only the manufacturer, keep other defaults from the script:**

```bash
aum-to-oxiindef "King of Bass.aum_midimap" -m "Bram Bos"
```

**Use the module form without installing:**

```bash
python -m aum_oxide "King of Bass.aum_midimap" -n "King of Bass" -a "KoB"
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*This tool was created with the help of [Claude.ai](https://claude.ai) and [Claude Code](https://claude.ai/code).*
