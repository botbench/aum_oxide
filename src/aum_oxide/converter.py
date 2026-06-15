"""
Core conversion logic: AUM .aum_midimap → OXI One .oxiindef.

Sequencer step parameters (seqStepN…) and internal AUM node keys
(_AUMNode:*, _collection_*) are excluded. All other parameters are
included; unmapped ones (enabled=False / CC=0) get nr1=0 in the output
so the OXI One lists them as unassigned.
"""

import json
import re

DEFAULT_MIDI_CHANNEL = 1

_SKIP_PATTERN = re.compile(r'seqStep\d+')
_SKIP_PREFIXES = ('_AUMNode:', '_collection_')


def decode_nskeyedarchiver(raw: dict) -> dict:
    """Resolve CF$UID pointers and NSDictionary encoding into a plain dict."""
    objects = raw["$objects"]

    def decode(obj):
        if isinstance(obj, dict):
            if "CF$UID" in obj:
                return decode(objects[obj["CF$UID"]])
            if "NS.keys" in obj and "NS.objects" in obj:
                keys = [decode(k) for k in obj["NS.keys"]]
                vals = [decode(v) for v in obj["NS.objects"]]
                return dict(zip(keys, vals))
            return {k: decode(v) for k, v in obj.items() if k != "$class"}
        elif isinstance(obj, list):
            return [decode(i) for i in obj]
        return obj

    return decode(raw["$top"]["root"])


def should_skip(name: str) -> bool:
    if any(name.startswith(p) for p in _SKIP_PREFIXES):
        return True
    if _SKIP_PATTERN.search(name):
        return True
    return False


def aum_channel_to_midi(aum_channel) -> int:
    """Convert AUM channel value to 1-based MIDI channel."""
    if aum_channel is None or aum_channel == 255:
        return DEFAULT_MIDI_CHANNEL
    return int(aum_channel) + 1


def detect_prefix(param_names: list) -> str:
    """
    Detect the shared lowercase namespace prefix across all parameter names.
    e.g. ['basscutoff', 'bassattack', 'basslayer1Volume'] → 'bass'
    """
    if not param_names:
        return ""
    prefixes = []
    for n in param_names:
        m = re.match(r'^([a-z]+)', n)
        prefixes.append(m.group(1) if m else "")
    if not prefixes or not prefixes[0]:
        return ""
    common = prefixes[0]
    for p in prefixes[1:]:
        while not p.startswith(common):
            common = common[:-1]
        if not common:
            return ""
    return common


def prettify_name(raw_name: str, prefix: str = "") -> str:
    """
    Turn camelCase AUv3 parameter IDs into readable display names.

    Examples:
        'basscutoff'         → 'Cutoff'
        'basschorusDepth'    → 'Chorus Depth'
        'bassadsrLinkEnable' → 'ADSR Link Enable'
        'basslayer1Volume'   → 'Layer 1 Volume'
    """
    name = raw_name

    if prefix and name.startswith(prefix):
        name = name[len(prefix):]

    if name and name[0].islower():
        name = name[0].upper() + name[1:]

    name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name)
    name = re.sub(r'(?<=[a-zA-Z])(?=[0-9])', ' ', name)
    name = re.sub(r'(?<=[0-9])(?=[A-Z])', ' ', name)

    name = name.strip().title()

    for abbr in ('Adsr', 'Lfo', 'Pwm', 'Osc'):
        name = name.replace(abbr, abbr.upper())

    return name if name else raw_name


def make_abbr(display_name: str, used: set) -> str:
    """
    Generate a unique 4-character abbreviation for a parameter display name.
    Strategy: take initials of words, pad/trim to 4 chars, deduplicate with suffix.

    e.g. 'Chorus Depth' → 'ChDp', 'Layer 1 Volume' → 'L1Vo'
    """
    words = display_name.split()
    if not words:
        candidate = "????"
    elif len(words) == 1:
        w = words[0]
        candidate = (w[:4]).ljust(4, w[-1])
    else:
        parts = []
        for w in words:
            if w.isdigit():
                parts.append(w)
            else:
                parts.append(w[:2])
        candidate = "".join(parts)[:4].ljust(4, "x")

    base = candidate
    suffix = 1
    while candidate in used:
        candidate = base[:3] + str(suffix)
        suffix += 1

    used.add(candidate)
    return candidate


def extract_params(all_params: dict, prefix: str) -> list:
    """
    Filter and normalise AUM parameter entries into a list of param dicts.

    Each returned dict has: raw_name, display_name, cc, channel, min, max, enabled.
    """
    filtered = sorted(
        ((k, v) for k, v in all_params.items() if not should_skip(k)),
        key=lambda kv: kv[0],
    )

    params = []
    for raw_name, mapping in filtered:
        if not isinstance(mapping, dict):
            continue

        spec    = mapping.get("specState", {})
        enabled = spec.get("enabled", False)
        cc      = spec.get("data1", 0) if enabled else 0
        channel = aum_channel_to_midi(mapping.get("channel", 255))

        aum_min  = mapping.get("min", 0.0)
        aum_max  = mapping.get("max", 1.0)

        params.append({
            "raw_name":     raw_name,
            "display_name": prettify_name(raw_name, prefix=prefix),
            "cc":           cc,
            "channel":      channel,
            "min":          round(aum_min * 127),
            "max":          round(aum_max * 127),
            "enabled":      enabled,
        })

    return params


def build_oxiindef(
    params: list,
    instrument_name: str,
    instrument_id: str,
    instrument_abbr: str,
    manufacturer: str,
) -> str:
    """
    Build the JSON content of an .oxiindef file matching the OXI One format.

    nr1 = CC number (0 = unassigned)
    nr2 = channel override (0 = use track channel)
    """
    used_abbrs: set = set()

    parameters = []
    for p in params:
        parameters.append({
            "type":          "cc",
            "name":          p["display_name"],
            "abbr":          make_abbr(p["display_name"], used_abbrs),
            "minimum":       p["min"],
            "maximum":       p["max"],
            "default_value": 0,
            "nr1":           p["cc"],
            "nr2":           0,
            "value_labels":  [],
        })

    doc = {
        "id":           instrument_id,
        "name":         instrument_name,
        "abbr":         instrument_abbr[:4],
        "manufacturer": manufacturer,
        "parameters":   parameters,
        "script":       None,
    }

    return json.dumps(doc, ensure_ascii=False)
