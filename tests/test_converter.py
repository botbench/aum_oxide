"""
Tests for aum_oxide.converter — targeting 100% line and branch coverage.

Each test has a docstring stating:
  - what behaviour is being verified
  - what the expected output is
"""

import json

import pytest

from aum_oxide.converter import (
    aum_channel_to_midi,
    build_oxiindef,
    classify_cc,
    decode_nskeyedarchiver,
    detect_prefix,
    extract_params,
    make_abbr,
    prettify_name,
    should_skip,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wrap(root_obj, *extra_objects):
    """Wrap an object in the minimal NSKeyedArchiver envelope expected by
    decode_nskeyedarchiver. The root is placed at index 1 of $objects."""
    return {
        "$top": {"root": {"CF$UID": 1}},
        "$objects": ["$null", root_obj, *extra_objects],
    }


def _mapping(enabled=False, cc=0, channel=0, min_=0.0, max_=1.0):
    """Build a minimal AUM parameter mapping dict."""
    spec = {"enabled": enabled}
    if enabled:
        spec["data1"] = cc
    return {"specState": spec, "channel": channel, "min": min_, "max": max_}


# ── decode_nskeyedarchiver ────────────────────────────────────────────────────

class TestDecodeNSKeyedArchiver:

    def test_primitive_at_root(self):
        """A CF$UID pointer to a primitive (string) at the root should
        resolve and return the primitive unchanged.
        Expected: "hello"."""
        assert decode_nskeyedarchiver(_wrap("hello")) == "hello"

    def test_cf_uid_resolution(self):
        """CF$UID pointers anywhere in the object graph must be dereferenced
        to the value at that index in $objects.
        Expected: {"key": "value"} after resolving two levels of CF$UID."""
        raw = {
            "$top": {"root": {"CF$UID": 1}},
            "$objects": [
                "$null",
                {"NS.keys": [{"CF$UID": 2}], "NS.objects": [{"CF$UID": 3}]},
                "key",
                "value",
            ],
        }
        assert decode_nskeyedarchiver(raw) == {"key": "value"}

    def test_nsdictionary_decoded(self):
        """An object with NS.keys / NS.objects encodes an NSDictionary and
        must be decoded to a plain Python dict.
        Expected: {"alpha": 1, "beta": 2}."""
        raw = {
            "$top": {"root": {"CF$UID": 1}},
            "$objects": [
                "$null",
                {
                    "NS.keys":    [{"CF$UID": 2}, {"CF$UID": 3}],
                    "NS.objects": [{"CF$UID": 4}, {"CF$UID": 5}],
                },
                "alpha", "beta", 1, 2,
            ],
        }
        assert decode_nskeyedarchiver(raw) == {"alpha": 1, "beta": 2}

    def test_plain_dict_strips_class_key(self):
        """Plain dicts inside $objects encode Objective-C objects; the
        '$class' key is metadata and must be excluded from the output.
        Expected: {"field": 99} without the $class entry."""
        raw = _wrap({"field": 99, "$class": "NSIgnoreMe"})
        assert decode_nskeyedarchiver(raw) == {"field": 99}

    def test_list_decoded_element_wise(self):
        """Lists must have each element decoded recursively so CF$UID
        pointers inside lists are also resolved.
        Expected: ["x", "y"]."""
        raw = {
            "$top": {"root": {"CF$UID": 1}},
            "$objects": ["$null", [{"CF$UID": 2}, {"CF$UID": 3}], "x", "y"],
        }
        assert decode_nskeyedarchiver(raw) == ["x", "y"]

    def test_nested_nsdictionary(self):
        """Nested NSDictionary structures must be decoded at every level.
        Expected: {"outer": {"inner": 42}}."""
        raw = {
            "$top": {"root": {"CF$UID": 1}},
            "$objects": [
                "$null",
                {"NS.keys": [{"CF$UID": 2}], "NS.objects": [{"CF$UID": 3}]},
                "outer",
                {"NS.keys": [{"CF$UID": 4}], "NS.objects": [{"CF$UID": 5}]},
                "inner",
                42,
            ],
        }
        assert decode_nskeyedarchiver(raw) == {"outer": {"inner": 42}}

    def test_numeric_primitive_passthrough(self):
        """Non-dict, non-list primitives (int, float, bool) must be returned
        as-is without modification.
        Expected: 3.14."""
        assert decode_nskeyedarchiver(_wrap(3.14)) == 3.14


# ── should_skip ───────────────────────────────────────────────────────────────

class TestShouldSkip:

    def test_skip_aum_node_prefix(self):
        """Names starting with '_AUMNode:' are internal AUM bookkeeping keys
        that must never appear in the instrument definition.
        Expected: True."""
        assert should_skip("_AUMNode:someKey") is True

    def test_skip_collection_prefix(self):
        """Names starting with '_collection_' are internal AUM metadata.
        Expected: True."""
        assert should_skip("_collection_map_name") is True

    def test_skip_seq_step_pattern(self):
        """Names matching 'seqStepN…' are sequencer step parameters; they
        are not plugin parameters and must be excluded.
        Expected: True for 'seqStep4Attack'."""
        assert should_skip("seqStep4Attack") is True

    def test_keep_regular_parameter(self):
        """Normal plugin parameter names must pass through unchanged.
        Expected: False for 'bassCutoff'."""
        assert should_skip("bassCutoff") is False

    def test_keep_name_containing_step(self):
        """The word 'step' alone does not match the seqStepN pattern; only
        the full 'seqStep' prefix followed by digits is skipped.
        Expected: False for 'stepVolume'."""
        assert should_skip("stepVolume") is False


# ── aum_channel_to_midi ───────────────────────────────────────────────────────

class TestAumChannelToMidi:

    def test_none_returns_default_channel(self):
        """AUM uses None to indicate an unassigned channel; this must fall
        back to DEFAULT_MIDI_CHANNEL (1).
        Expected: 1."""
        assert aum_channel_to_midi(None) == 1

    def test_255_returns_default_channel(self):
        """AUM uses the sentinel value 255 for an unassigned channel; this
        must also fall back to DEFAULT_MIDI_CHANNEL (1).
        Expected: 1."""
        assert aum_channel_to_midi(255) == 1

    def test_zero_maps_to_midi_channel_one(self):
        """AUM channels are 0-based; channel 0 is MIDI channel 1.
        Expected: 1."""
        assert aum_channel_to_midi(0) == 1

    def test_nonzero_maps_one_based(self):
        """AUM channel 1 is MIDI channel 2, etc.
        Expected: 2 for AUM channel 1."""
        assert aum_channel_to_midi(1) == 2

    def test_max_channel(self):
        """AUM channel 15 is MIDI channel 16, the last valid MIDI channel.
        Expected: 16."""
        assert aum_channel_to_midi(15) == 16


# ── detect_prefix ─────────────────────────────────────────────────────────────

class TestDetectPrefix:

    def test_empty_list_returns_empty(self):
        """With no parameter names there is nothing to analyse.
        Expected: ''."""
        assert detect_prefix([]) == ""

    def test_name_starting_with_digit_has_no_prefix(self):
        """A name that starts with a digit has no leading lowercase run; the
        regex matches nothing, so no prefix can be found.
        Expected: ''."""
        assert detect_prefix(["123abc"]) == ""

    def test_single_name_returns_lowercase_run(self):
        """A single camelCase name returns the leading lowercase-only run as
        the prefix (the part before the first uppercase letter or digit).
        Expected: 'bass' for 'bassCutoff'."""
        assert detect_prefix(["bassCutoff"]) == "bass"

    def test_shared_prefix_detected(self):
        """All names sharing the same lowercase prefix should return that prefix.
        Expected: 'bass' for ['basscutoff', 'bassattack', 'basslayer1Volume']."""
        assert detect_prefix(["basscutoff", "bassattack", "basslayer1Volume"]) == "bass"

    def test_no_shared_prefix_returns_empty(self):
        """Names with completely different leading prefixes share no prefix.
        Expected: '' for ['alpha', 'beta']."""
        assert detect_prefix(["alpha", "beta"]) == ""

    def test_prefix_trimmed_to_shortest_common_run(self):
        """When one name's prefix is a substring of another's, the result is
        trimmed to the shorter common match.
        Expected: 'bass' for ['basslow', 'bass']."""
        assert detect_prefix(["basslow", "bass"]) == "bass"

    def test_single_char_prefix_match(self):
        """Names sharing only a single leading character still return that
        character as the common prefix.
        Expected: 'b' for ['blow', 'buzz']."""
        assert detect_prefix(["blow", "buzz"]) == "b"


# ── prettify_name ─────────────────────────────────────────────────────────────

class TestPrettifyName:

    def test_prefix_stripped_and_remainder_capitalised(self):
        """The shared namespace prefix is removed and the first remaining
        character is uppercased.
        Expected: 'Cutoff' from 'basscutoff' with prefix 'bass'."""
        assert prettify_name("basscutoff", prefix="bass") == "Cutoff"

    def test_camelcase_split_on_lower_upper_boundary(self):
        """A lowercase-to-uppercase transition in a camelCase name causes a
        space to be inserted between the two characters.
        Expected: 'Chorus Depth' from 'basschorusDepth' with prefix 'bass'."""
        assert prettify_name("basschorusDepth", prefix="bass") == "Chorus Depth"

    def test_letter_to_digit_boundary_adds_space(self):
        """A letter-to-digit transition causes a space to be inserted.
        Expected: 'Layer 1 Volume' from 'basslayer1Volume' with prefix 'bass'."""
        assert prettify_name("basslayer1Volume", prefix="bass") == "Layer 1 Volume"

    def test_digit_to_uppercase_boundary_adds_space(self):
        """A digit-to-uppercase transition also causes a space.
        Expected: 'Track 1 Pan' from 'track1Pan'."""
        assert prettify_name("track1Pan") == "Track 1 Pan"

    def test_adsr_abbreviation_uppercased(self):
        """'Adsr' produced by title-casing must be converted to 'ADSR'.
        Expected: 'ADSR Link Enable' from 'bassadsrLinkEnable'."""
        assert prettify_name("bassadsrLinkEnable", prefix="bass") == "ADSR Link Enable"

    def test_lfo_abbreviation_uppercased(self):
        """'Lfo' produced by title-casing must be converted to 'LFO'.
        Expected: 'LFO Rate' from 'lfoRate'."""
        assert prettify_name("lfoRate") == "LFO Rate"

    def test_pwm_abbreviation_uppercased(self):
        """'Pwm' produced by title-casing must be converted to 'PWM'.
        Expected: 'PWM Width' from 'pwmWidth'."""
        assert prettify_name("pwmWidth") == "PWM Width"

    def test_osc_abbreviation_uppercased(self):
        """'Osc' produced by title-casing must be converted to 'OSC'.
        Expected: 'OSC Pitch' from 'oscPitch'."""
        assert prettify_name("oscPitch") == "OSC Pitch"

    def test_already_capitalised_name_unchanged_by_case_step(self):
        """A name that already starts with an uppercase letter skips the
        manual capitalisation step but is still title-cased.
        Expected: 'Cutoff' from 'Cutoff' with no prefix."""
        assert prettify_name("Cutoff") == "Cutoff"

    def test_prefix_not_matching_leaves_name_intact(self):
        """When the provided prefix does not appear at the start of the name
        it is not stripped; the full name is prettified as-is.
        Expected: 'Reverb Mix' from 'reverbMix' with prefix 'bass'."""
        assert prettify_name("reverbMix", prefix="bass") == "Reverb Mix"

    def test_empty_raw_name_returns_empty(self):
        """An empty input string produces an empty result after all
        transformations; the fallback also returns '' so the return is ''.
        Expected: ''."""
        assert prettify_name("") == ""


# ── make_abbr ─────────────────────────────────────────────────────────────────

class TestMakeAbbr:

    def test_empty_string_produces_question_marks(self):
        """An empty display name has no words to work with, so the sentinel
        '????' is used.
        Expected: '????'."""
        assert make_abbr("", set()) == "????"

    def test_single_short_word_is_padded(self):
        """A single word shorter than 4 characters is padded with its last
        character to reach exactly 4.
        Expected: 'Cutt' from 'Cut' (padded with 't')."""
        assert make_abbr("Cut", set()) == "Cutt"

    def test_single_long_word_is_truncated(self):
        """A single word of 5+ characters is truncated to the first 4.
        Expected: 'Chor' from 'Chorus'."""
        assert make_abbr("Chorus", set()) == "Chor"

    def test_two_words_take_two_chars_each(self):
        """A two-word name takes the first 2 characters of each word and
        joins them (up to 4 chars total).
        Expected: 'ChDe' from 'Chorus Depth'."""
        assert make_abbr("Chorus Depth", set()) == "ChDe"

    def test_digit_word_kept_whole(self):
        """A token that is a pure digit string is appended as-is (not
        abbreviated to 2 chars), so numeric layer/step numbers stay readable.
        Expected: 'La1V' from 'Layer 1 Volume'."""
        assert make_abbr("Layer 1 Volume", set()) == "La1V"

    def test_short_multi_word_result_padded_with_x(self):
        """When the joined initials of a multi-word name total fewer than 4
        chars, 'x' is used as padding.
        Expected: 'ABxx' from 'A B' (single-char words produce 2-char join)."""
        assert make_abbr("A B", set()) == "ABxx"

    def test_duplicate_gets_numeric_suffix(self):
        """When the natural candidate is already in the used set, a numeric
        suffix replaces the 4th character (base[:3] + str(suffix)).
        Expected: 'ChD1' when 'ChDe' is already taken."""
        used = {"ChDe"}
        assert make_abbr("Chorus Depth", used) == "ChD1"

    def test_multiple_duplicates_increment_suffix(self):
        """Successive duplicates keep incrementing the suffix until a unique
        abbreviation is found.
        Expected: 'ChD2' when both 'ChDe' and 'ChD1' are taken."""
        used = {"ChDe", "ChD1"}
        assert make_abbr("Chorus Depth", used) == "ChD2"

    def test_chosen_abbr_added_to_used_set(self):
        """After make_abbr returns, the chosen abbreviation must be present
        in the used set so the next call can detect the collision.
        Expected: 'Cuto' present in used after abbreviating 'Cutoff'."""
        used: set = set()
        make_abbr("Cutoff", used)
        assert "Cuto" in used


# ── extract_params ────────────────────────────────────────────────────────────

class TestExtractParams:

    def test_basic_unassigned_parameter(self):
        """An unassigned parameter (enabled=False) should appear with cc=0
        and its raw_name preserved in the output.
        Expected: one entry, cc=0, raw_name='cutoff'."""
        result = extract_params({"cutoff": _mapping()}, prefix="")
        assert len(result) == 1
        assert result[0]["cc"] == 0
        assert result[0]["raw_name"] == "cutoff"
        assert result[0]["enabled"] is False

    def test_enabled_parameter_cc_extracted(self):
        """An enabled parameter with data1=74 must have cc=74 in the output.
        Expected: cc=74."""
        result = extract_params({"cutoff": _mapping(enabled=True, cc=74)}, prefix="")
        assert result[0]["cc"] == 74
        assert result[0]["enabled"] is True

    def test_non_dict_value_is_skipped(self):
        """A key whose value is not a dict (e.g. a plain string) must be
        silently skipped — it cannot be a parameter mapping.
        Expected: empty list."""
        result = extract_params({"mapName": "My Synth"}, prefix="")
        assert result == []

    def test_skip_pattern_filters_seq_step(self):
        """Keys matching the skip patterns (_AUMNode:, seqStep) must be
        excluded before any parameter processing.
        Expected: empty list."""
        all_params = {
            "_AUMNode:foo": _mapping(),
            "seqStep1Pitch": _mapping(),
        }
        assert extract_params(all_params, prefix="") == []

    def test_full_range_scaled_to_0_127(self):
        """An AUM float range of 0.0–1.0 must map to the full MIDI CC range
        of 0–127 after rounding.
        Expected: min=0, max=127."""
        result = extract_params({"vol": _mapping(min_=0.0, max_=1.0)}, prefix="")
        assert result[0]["min"] == 0
        assert result[0]["max"] == 127

    def test_partial_range_scaled(self):
        """A partial AUM range (0.5–1.0) must map proportionally to MIDI.
        Expected: min=round(0.5*127)=64, max=127."""
        result = extract_params({"vol": _mapping(min_=0.5, max_=1.0)}, prefix="")
        assert result[0]["min"] == round(0.5 * 127)
        assert result[0]["max"] == 127

    def test_channel_converted_from_aum_to_midi(self):
        """AUM channel 0 (0-based) must be converted to MIDI channel 1 (1-based).
        Expected: channel=1."""
        result = extract_params({"cutoff": _mapping(channel=0)}, prefix="")
        assert result[0]["channel"] == 1

    def test_results_sorted_alphabetically(self):
        """Parameters must be returned in alphabetical order by raw_name
        regardless of dictionary insertion order.
        Expected: [attack, cutoff, release]."""
        all_params = {
            "cutoff":  _mapping(),
            "attack":  _mapping(),
            "release": _mapping(),
        }
        result = extract_params(all_params, prefix="")
        assert [p["raw_name"] for p in result] == ["attack", "cutoff", "release"]

    def test_prefix_stripped_from_display_name(self):
        """The namespace prefix must be stripped when computing the
        human-readable display_name.
        Expected: display_name='Cutoff' for 'bassCutoff' with prefix 'bass'."""
        result = extract_params({"bassCutoff": _mapping()}, prefix="bass")
        assert result[0]["display_name"] == "Cutoff"

    def test_missing_specstate_defaults_to_disabled(self):
        """A mapping dict with no 'specState' key must default to
        enabled=False and cc=0.
        Expected: cc=0, enabled=False."""
        result = extract_params({"cutoff": {"channel": 0, "min": 0.0, "max": 1.0}}, prefix="")
        assert result[0]["cc"] == 0
        assert result[0]["enabled"] is False

    def test_missing_channel_defaults_to_midi_1(self):
        """A mapping dict with no 'channel' key uses the AUM sentinel 255,
        which falls back to MIDI channel 1.
        Expected: channel=1."""
        result = extract_params({"cutoff": {"specState": {}, "min": 0.0, "max": 1.0}}, prefix="")
        assert result[0]["channel"] == 1


# ── classify_cc ───────────────────────────────────────────────────────────────

class TestClassifyCc:

    def test_free_cc_returns_none(self):
        """CCs in the free/safe range must return None — no annotation needed.
        Expected: None for CC 14."""
        assert classify_cc(14) is None

    def test_reserved_cc_returns_reserved_level(self):
        """A spec-defined reserved CC must return level 'reserved'.
        Expected: ('reserved', ...) for CC 64 (Sustain Pedal)."""
        result = classify_cc(64)
        assert result is not None
        level, description = result
        assert level == "reserved"
        assert "Sustain" in description

    def test_reserved_cc_bank_select(self):
        """CC 0 (Bank Select MSB) is spec-reserved.
        Expected: ('reserved', 'Bank Select MSB')."""
        assert classify_cc(0) == ("reserved", "Bank Select MSB")

    def test_reserved_cc_channel_mode(self):
        """Channel Mode messages (120–127) are spec-reserved.
        Expected: 'reserved' level for CC 123 (All Notes Off)."""
        level, description = classify_cc(123)
        assert level == "reserved"
        assert "All Notes Off" in description

    def test_reserved_cc_rpn_nrpn(self):
        """RPN/NRPN controllers (98–101) are spec-reserved.
        Expected: 'reserved' level for CC 98 (NRPN LSB)."""
        level, _ = classify_cc(98)
        assert level == "reserved"

    def test_soft_cc_returns_soft_level(self):
        """A conventionally-claimed CC must return level 'soft'.
        Expected: ('soft', ...) for CC 74 (Sound Controller 5 / Brightness)."""
        result = classify_cc(74)
        assert result is not None
        level, description = result
        assert level == "soft"
        assert "Brightness" in description

    def test_soft_cc_effects_depth(self):
        """Effects Depth CCs (91–95) return 'soft' level.
        Expected: 'soft' for CC 91 (Reverb Send Level)."""
        level, description = classify_cc(91)
        assert level == "soft"
        assert "Reverb" in description

    def test_soft_cc_portamento_control(self):
        """CC 84 (Portamento Control) is conventionally claimed.
        Expected: ('soft', 'Portamento Control')."""
        assert classify_cc(84) == ("soft", "Portamento Control")

    def test_boundary_free_cc_3(self):
        """CC 3 is explicitly in the free range.
        Expected: None."""
        assert classify_cc(3) is None

    def test_boundary_free_cc_102(self):
        """CC 102 is in the free range (102–119).
        Expected: None."""
        assert classify_cc(102) is None

    def test_all_reserved_ccs_have_reserved_level(self):
        """Every spec-reserved CC from the requirements must return 'reserved'.
        Expected: 'reserved' level for each of the listed reserved CCs."""
        reserved = [0, 1, 6, 7, 10, 11, 32, 38, 64, 65, 66, 67, 68, 69,
                    96, 97, 98, 99, 100, 101, 120, 121, 122, 123, 124, 125, 126, 127]
        for cc in reserved:
            result = classify_cc(cc)
            assert result is not None, f"CC {cc} should be annotated"
            assert result[0] == "reserved", f"CC {cc} should be 'reserved', got {result[0]}"

    def test_all_soft_ccs_have_soft_level(self):
        """Every conventionally-claimed CC must return 'soft' level.
        Expected: 'soft' for each of 70–79, 84, 91–95."""
        soft = list(range(70, 80)) + [84] + list(range(91, 96))
        for cc in soft:
            result = classify_cc(cc)
            assert result is not None, f"CC {cc} should be annotated"
            assert result[0] == "soft", f"CC {cc} should be 'soft', got {result[0]}"


# ── build_oxiindef ────────────────────────────────────────────────────────────

class TestBuildOxiindef:

    def _build(self, params=None, name="Test Synth", id_="test_synth",
               abbr="TeSy", manufacturer="Acme"):
        return json.loads(build_oxiindef(
            params or [],
            instrument_name=name,
            instrument_id=id_,
            instrument_abbr=abbr,
            manufacturer=manufacturer,
        ))

    def test_top_level_fields_present(self):
        """The output JSON must contain all six top-level OXI One fields
        with the correct values passed in.
        Expected: id, name, abbr, manufacturer, parameters=[], script=None."""
        doc = self._build()
        assert doc["id"] == "test_synth"
        assert doc["name"] == "Test Synth"
        assert doc["abbr"] == "TeSy"
        assert doc["manufacturer"] == "Acme"
        assert doc["parameters"] == []
        assert doc["script"] is None

    def test_abbr_truncated_to_four_chars(self):
        """An instrument abbreviation longer than 4 characters must be
        silently truncated to exactly 4.
        Expected: 'ABCD' from 'ABCDEFGH'."""
        doc = self._build(abbr="ABCDEFGH")
        assert doc["abbr"] == "ABCD"

    def test_parameter_entry_fields(self):
        """Each parameter must appear with all required OXI One fields: type,
        name, abbr, minimum, maximum, default_value, nr1, nr2, value_labels.
        Expected: a correctly populated parameter dict for cc=74, range 0–127."""
        param = {"display_name": "Cutoff", "cc": 74, "min": 0, "max": 127}
        doc = self._build(params=[param])
        p = doc["parameters"][0]
        assert p["type"] == "cc"
        assert p["name"] == "Cutoff"
        assert p["nr1"] == 74
        assert p["nr2"] == 0
        assert p["minimum"] == 0
        assert p["maximum"] == 127
        assert p["default_value"] == 0
        assert p["value_labels"] == []

    def test_unassigned_parameter_has_nr1_zero(self):
        """An unassigned parameter (cc=0) must produce nr1=0 so the OXI One
        lists it as unassigned rather than assigned to CC 0.
        Expected: nr1=0."""
        param = {"display_name": "Volume", "cc": 0, "min": 0, "max": 127}
        doc = self._build(params=[param])
        assert doc["parameters"][0]["nr1"] == 0

    def test_duplicate_display_names_get_unique_abbrs(self):
        """Multiple parameters with the same display name must each receive a
        unique abbreviation; no two entries may share the same abbr.
        Expected: all three abbr values are distinct."""
        params = [
            {"display_name": "Cutoff", "cc": i, "min": 0, "max": 127}
            for i in range(3)
        ]
        doc = self._build(params=params)
        abbrs = [p["abbr"] for p in doc["parameters"]]
        assert len(abbrs) == len(set(abbrs))

    def test_output_is_valid_json_string(self):
        """build_oxiindef must always return a string that is valid JSON.
        Expected: json.loads succeeds and returns a dict."""
        result = build_oxiindef([], "Name", "name", "Nm", "")
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_parameter_count_matches_input(self):
        """The number of entries in the output 'parameters' list must equal
        the number of param dicts passed in.
        Expected: 3 parameter entries for 3 input params."""
        params = [
            {"display_name": f"Param {i}", "cc": i, "min": 0, "max": 127}
            for i in range(3)
        ]
        doc = self._build(params=params)
        assert len(doc["parameters"]) == 3
