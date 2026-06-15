"""CLI entry point: aum-to-oxiindef (or python -m aum_oxide)."""

import argparse
import plistlib
import re
import sys
from pathlib import Path

from .converter import (
    build_oxiindef,
    decode_nskeyedarchiver,
    detect_prefix,
    extract_params,
    should_skip,
)

# ── Configuration ─────────────────────────────────────────────────────────────
# Edit these defaults when converting a specific instrument, or override via
# CLI flags (-n / -m).

INSTRUMENT_NAME = "Unknown Synth"    # shown on OXI display
INSTRUMENT_ID   = re.sub(r'[^a-z0-9]+', '_', INSTRUMENT_NAME.lower()).strip('_')
INSTRUMENT_ABBR = "Unkn"             # up to 4 chars, shown in tight UI spaces
MANUFACTURER    = "ACME CORP"       # e.g. "Korg", "Roland"

# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert an AUM .aum_midimap file to an OXI One .oxiindef instrument definition."
    )
    parser.add_argument("input",  type=Path, help="Input .aum_midimap file")
    parser.add_argument("output", type=Path, nargs="?",
                        help="Output .oxiindef file (default: alongside input)")
    parser.add_argument("-n", "--name",         default=None, help="Override instrument name")
    parser.add_argument("-m", "--manufacturer", default=None, help="Override manufacturer string")
    parser.add_argument("-a", "--abbr",         default=None, help="Override instrument abbreviation (max 4 chars)")
    args = parser.parse_args()

    input_path  = args.input
    output_path = args.output or input_path.with_suffix(".oxiindef")

    if not input_path.exists():
        parser.error(f"File not found: {input_path}")

    with open(input_path, "rb") as f:
        raw = plistlib.load(f)

    all_params = decode_nskeyedarchiver(raw)

    instrument_name = INSTRUMENT_NAME
    instrument_id   = INSTRUMENT_ID

    if "_collection_map_name" in all_params:
        raw_map_name = all_params["_collection_map_name"]
        if isinstance(raw_map_name, str) and raw_map_name:
            instrument_name = raw_map_name.split(".AU-")[0].strip() or INSTRUMENT_NAME
            instrument_id   = re.sub(r'[^a-z0-9]+', '_', instrument_name.lower()).strip('_')

    if args.name:
        instrument_name = args.name
        instrument_id   = re.sub(r'[^a-z0-9]+', '_', instrument_name.lower()).strip('_')
    manufacturer = args.manufacturer if args.manufacturer is not None else MANUFACTURER

    if args.abbr is not None:
        instrument_abbr = args.abbr[:4]
    elif args.name:
        instrument_abbr = args.name[:4]
    else:
        instrument_abbr = INSTRUMENT_ABBR

    param_names = [k for k, v in all_params.items() if not should_skip(k) and isinstance(v, dict)]
    prefix = detect_prefix(param_names)
    if prefix:
        print(f"Detected namespace prefix: '{prefix}' (stripped from display names)")

    params  = extract_params(all_params, prefix)
    skipped = sum(1 for k, v in all_params.items() if not should_skip(k) and not isinstance(v, dict))

    mapped_count = sum(1 for p in params if p["enabled"])
    print(f"Input:      {input_path}")
    print(f"Instrument: {instrument_name}  (id: {instrument_id})")
    print(f"Parameters: {len(params)} included, {skipped} non-dict skipped")
    print(f"Mapped CCs: {mapped_count}")
    if mapped_count:
        print("  Already assigned:")
        for p in params:
            if p["enabled"]:
                print(f"    CC{p['cc']:3d}  ch{p['channel']}  {p['display_name']} ({p['raw_name']})")

    json_content = build_oxiindef(
        params,
        instrument_name=instrument_name,
        instrument_id=instrument_id,
        instrument_abbr=instrument_abbr,
        manufacturer=manufacturer,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json_content)

    print(f"\nWritten → {output_path}")


if __name__ == "__main__":
    main()
