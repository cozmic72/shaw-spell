#!/usr/bin/env python3
"""Characterization tests for the definitions index (definitions.py) and its patch
overlay (definition_patches.py).

Locks the lemma|synset join, the internal `_sense` shape, the divergence-only
gb/us serialisation, and the correction/revert overlay. Fixtures are hand-built
sense dicts and patch dicts — the corpus files are never read (load_definitions_
index / _require are not exercised); DefinitionsIndex is constructed directly from
a synthetic by_word map. The def-patch store round-trip runs against a THROWAWAY
file via SHAW_SPELL_DEFINITION_PATCH_STORE.

Covers:
  - _split_key parses `word|synset` and fails loud on a missing separator
  - _sense_source derives wordnet from a WordNet synset offset, generated otherwise
  - _sense joins the Latin gloss/POS with the per-dialect Shavian; empty→None
  - _serialise_sense shows shaw_us ONLY when it diverges from shaw_gb
  - correct() overlays a correction onto the matching sense (owner edit shows
    through), and returns False (orphan) when the anchor resolves to nothing
  - revert() restores the pristine machine transliteration
  - overlay_corpus applies corrections in order and returns orphans, leaving the
    corpus mutated only where an anchor resolved
  - the def-patch store upserts by anchor and round-trips

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

import definition_patches as defpatches
import definitions

WORDNET_SYNSET = "12345678-n"


def sense(word_lower="cat", synset=WORDNET_SYNSET, gloss="a small feline",
          pos="n", gb="ГБ", us=None):
    """A synthetic internal sense via the real _sense join, so the shape under test
    is the production one. gb/us are Shavian transliteration strings (opaque here);
    us=None means the US Shavian is absent (a coverage gap)."""
    latin = {"definition": gloss, "pos": pos}
    gb_shaw = {"transliterated_definition": gb, "transliterated_pos": "POS"}
    us_shaw = {"transliterated_definition": us} if us is not None else None
    return definitions._sense(word_lower, synset, latin, gb_shaw, us_shaw)


def index_of(*senses):
    by_word = {}
    for one in senses:
        by_word.setdefault(one["word_lower"], []).append(one)
    return definitions.DefinitionsIndex(by_word)


def def_anchor(word="cat", synset=WORDNET_SYNSET, dialect="gb"):
    return {"word": word, "synset": synset, "dialect": dialect}


# ---- key parsing + source derivation ----

def test_split_key_parses_word_and_synset():
    assert definitions._split_key(f"cat|{WORDNET_SYNSET}") == ("cat", WORDNET_SYNSET)


def test_split_key_fails_loud_without_separator():
    try:
        definitions._split_key("catnosynset")
    except ValueError:
        return
    assert False, "expected ValueError on a key with no '|'"


def test_sense_source_wordnet_from_offset():
    assert definitions._sense_source(WORDNET_SYNSET) == definitions.SOURCE_WORDNET


def test_sense_source_generated_for_non_offset():
    assert definitions._sense_source("func-word-001") == definitions.SOURCE_GENERATED


# ---- the join + sense shape ----

def test_sense_joins_latin_gloss_with_shavian():
    one = sense(gloss="a small feline", pos="n", gb="GBDEF", us="USDEF")
    assert one["gloss"] == "a small feline"
    assert one["pos"] == "n"
    assert one["shaw"] == {"gb": "GBDEF", "us": "USDEF"}
    assert one["source"] == definitions.SOURCE_WORDNET
    # The pristine copy mirrors the working copy at construction.
    assert one["_pristine"] == {"gb": "GBDEF", "us": "USDEF"}


def test_sense_empty_shavian_normalises_to_none():
    one = sense(gb="", us=None)
    assert one["shaw"]["gb"] is None
    assert one["shaw"]["us"] is None


# ---- divergence-only serialisation ----

def test_serialise_shows_us_only_on_divergence():
    diverged = definitions._serialise_sense(sense(gb="GBDEF", us="USDEF"))
    assert diverged["shaw_gb"] == "GBDEF"
    assert diverged["shaw_us"] == "USDEF"

    same = definitions._serialise_sense(sense(gb="GBDEF", us="GBDEF"))
    assert same["shaw_gb"] == "GBDEF"
    assert same["shaw_us"] is None, same["shaw_us"]


# ---- correction overlay + revert ----

def test_correct_overlays_onto_matching_sense():
    index = index_of(sense(gb="GBDEF", us="USDEF"))
    applied = index.correct(def_anchor(dialect="gb"), {"shaw": "CORRECTED"})
    assert applied is True
    assert index.senses("cat")[0]["shaw_gb"] == "CORRECTED"


def test_correct_targets_only_the_anchored_dialect():
    index = index_of(sense(gb="GBDEF", us="USDEF"))
    index.correct(def_anchor(dialect="us"), {"shaw": "USFIX"})
    serialised = index.senses("cat")[0]
    assert serialised["shaw_gb"] == "GBDEF"    # GB untouched
    assert serialised["shaw_us"] == "USFIX"    # US corrected


def test_correct_returns_false_on_orphan_anchor():
    index = index_of(sense())
    # A synset the corpus does not hold — the correction resolves to nothing.
    applied = index.correct(def_anchor(synset="99999999-n"), {"shaw": "X"})
    assert applied is False


def test_correct_fails_loud_on_bad_dialect():
    index = index_of(sense())
    try:
        index.correct(def_anchor(dialect="fr"), {"shaw": "X"})
    except ValueError:
        return
    assert False, "expected ValueError on a non-gb/us dialect"


def test_revert_restores_pristine_transliteration():
    index = index_of(sense(gb="GBDEF"))
    index.correct(def_anchor(dialect="gb"), {"shaw": "CORRECTED"})
    assert index.senses("cat")[0]["shaw_gb"] == "CORRECTED"
    reverted = index.revert(def_anchor(dialect="gb"))
    assert reverted is True
    assert index.senses("cat")[0]["shaw_gb"] == "GBDEF"


# ---- overlay_corpus: order + orphan collection ----

def test_overlay_corpus_applies_and_reports_orphans():
    index = index_of(sense(gb="GBDEF"))
    live = defpatches.make_patch(def_anchor(dialect="gb"), {"shaw": "LIVEFIX"},
                                 {"author": "joro", "origin": "editor"})
    orphan = defpatches.make_patch(def_anchor(synset="99999999-n", dialect="gb"),
                                   {"shaw": "GHOST"},
                                   {"author": "joro", "origin": "editor"})
    orphans = defpatches.overlay_corpus(index, [live, orphan])

    assert [p["id"] for p in orphans] == [orphan["id"]], orphans
    assert index.senses("cat")[0]["shaw_gb"] == "LIVEFIX"


# ---- def-patch store: upsert-by-anchor + round-trip ----

class _defstore:
    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        self._path = Path(self._dir.name) / "definition-patches.jsonl"
        self._prev = os.environ.get("SHAW_SPELL_DEFINITION_PATCH_STORE")
        os.environ["SHAW_SPELL_DEFINITION_PATCH_STORE"] = str(self._path)
        return self._path

    def __exit__(self, *_exc):
        if self._prev is None:
            os.environ.pop("SHAW_SPELL_DEFINITION_PATCH_STORE", None)
        else:
            os.environ["SHAW_SPELL_DEFINITION_PATCH_STORE"] = self._prev
        self._dir.cleanup()
        return False


def test_def_store_upserts_by_anchor_and_round_trips():
    with _defstore():
        first = defpatches.make_patch(def_anchor(dialect="gb"), {"shaw": "ONE"},
                                      {"author": "joro", "origin": "editor"})
        outcome, previous = defpatches.upsert_patch(first)
        assert outcome == "appended" and previous is None

        second = defpatches.make_patch(def_anchor(dialect="gb"), {"shaw": "TWO"},
                                       {"author": "joro", "origin": "editor"})
        outcome2, previous2 = defpatches.upsert_patch(second)
        assert outcome2 == "replaced"
        assert previous2["id"] == first["id"]

        stored = defpatches.load_patches()
        assert len(stored) == 1, stored
        assert stored[0]["changes"] == {"shaw": "TWO"}


def test_def_store_different_dialect_is_a_distinct_anchor():
    with _defstore():
        defpatches.upsert_patch(defpatches.make_patch(
            def_anchor(dialect="gb"), {"shaw": "GB"},
            {"author": "joro", "origin": "editor"}))
        outcome, _previous = defpatches.upsert_patch(defpatches.make_patch(
            def_anchor(dialect="us"), {"shaw": "US"},
            {"author": "joro", "origin": "editor"}))
        assert outcome == "appended", outcome
        assert len(defpatches.load_patches()) == 2


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
