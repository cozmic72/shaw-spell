#!/usr/bin/env python3
"""Focused tests for annotate_definitions.annotate — the pure has_definition pass.

has_definition is WORDNET-ONLY: true iff the record is WordNet-attested (source
`wordnet` or `generated`) AND its (word, pos) is in wn_keys. The Wiktionary arm
was dropped so the flag matches what the editor and the shipped library actually
display (neither carries Wiktionary definitions). These tests pin that: WordNet
backs True, Wiktionary-only goes False, generated-with-WordNet-def stays True.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import annotate_definitions as ad


def _record(latn, pos, source):
    return {"Latn": latn, "pos": pos, "source": source}


def test_annotate_wordnet_only_semantics():
    # WordNet has (cat, NN1); Wiktionary has (widget, NN1) but WordNet does not.
    wn_keys = {("cat", "NN1")}
    wikt_keys = {("widget", "NN1")}

    supplement = {
        "cat": [_record("cat", "NN1", [ad.SOURCE_WORDNET])],
        "widget": [_record("widget", "NN1", [ad.SOURCE_WIKTIONARY])],
        "robot": [_record("robot", "NN1", [ad.SOURCE_GENERATED])],
    }
    # `robot` (generated) IS backed by a WordNet def.
    wn_keys.add(("robot", "NN1"))

    ad.annotate(supplement, wn_keys, wikt_keys)

    # WordNet-backed -> True.
    assert supplement["cat"][0]["has_definition"] is True

    # Wiktionary-ONLY (in wikt_keys, NOT in wn_keys) -> now False (the fix).
    assert supplement["widget"][0]["has_definition"] is False

    # Generated record with a WordNet def -> still True (from_wordnet covers it).
    assert supplement["robot"][0]["has_definition"] is True


def test_wiktionary_arm_never_grants_definition():
    # A record attested by BOTH wordnet and wiktionary, where ONLY Wiktionary
    # carries the def, must be False — proves the dropped arm cannot leak through.
    wn_keys = set()
    wikt_keys = {("gadget", "NN1")}
    supplement = {
        "gadget": [_record("gadget", "NN1",
                           [ad.SOURCE_WORDNET, ad.SOURCE_WIKTIONARY])],
    }
    ad.annotate(supplement, wn_keys, wikt_keys)
    assert supplement["gadget"][0]["has_definition"] is False


def test_wordnet_key_matches_lowercased_word():
    # wn_keys are keyed on the lowercased Latn; a capitalised record still matches.
    wn_keys = {("paris", "NP0")}
    supplement = {"Paris": [_record("Paris", "NP0", [ad.SOURCE_WORDNET])]}
    ad.annotate(supplement, wn_keys, set())
    assert supplement["Paris"][0]["has_definition"] is True


if __name__ == "__main__":
    test_annotate_wordnet_only_semantics()
    test_wiktionary_arm_never_grants_definition()
    test_wordnet_key_matches_lowercased_word()
    print("all tests passed")
