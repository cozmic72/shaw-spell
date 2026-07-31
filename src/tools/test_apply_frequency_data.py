#!/usr/bin/env python3
"""Focused unit tests for the frequency-enrichment stage's LRW POS-split pass.

Everything runs on synthetic tiny corpora and hand-built LrwData — no real
corpus, no readlex.json, no build. Covers: the rule-1 surface split (same-class
sharing, unresolved leftover), the overlap-conflict hard skip (no rule-2
fallthrough), the attestation floors, the rule-2 lemma inheritance, the
contraction min-of-parts annotation + split exclusion, info-tag idempotency
with foreign tags preserved, and the file parser on an inline fixture
(@ @ continuation inheritance, html-unescape, case-fold union, max-merge).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import apply_frequency_data as afd
from basis import INFO_FIELD
from lrw_frequencies import LrwData, load_lrw


def _entry(word, pos, **kw):
    base = {"Latn": word, "Shaw": "𐑖", "pos": pos}
    base.update(kw)
    return base


def _lrw(surface_readings=None, parent_lemmas=None):
    return LrwData(surface_readings or {}, parent_lemmas or {})


def enrich(entries, corpus, lrw):
    """Run enrich_all over one bucket (the basis-shaped call) and return stats."""
    return afd.enrich_all({None: entries}, corpus, lrw)


# --- rule 1: surface-level POS multiplex ------------------------------------

def test_rule1_splits_by_class_weight():
    # The worked `i` example: Pron 10241, Num 86, Lett 53, NoP 14, Uncl 32,
    # Fore 0. PNP/CRD/ZZ0 resolve; ITJ (Int absent) and UNC (uninformative
    # acceptable set) keep the whole count.
    entries = [_entry("i", "PNP"), _entry("i", "ZZ0"), _entry("I", "CRD"),
               _entry("I", "ITJ"), _entry("I", "UNC")]
    lrw = _lrw({"i": {"Pron": 10241, "Num": 86, "Lett": 53, "NoP": 14,
                      "Uncl": 32, "Fore": 0}})
    stats = enrich(entries, {"i": 27_086_011}, lrw)
    by_pos = {e["pos"]: e for e in entries}
    assert by_pos["PNP"]["freq"] == round(27_086_011 * 10241 / 10380)
    assert by_pos["CRD"]["freq"] == round(27_086_011 * 86 / 10380)
    assert by_pos["ZZ0"]["freq"] == round(27_086_011 * 53 / 10380)
    assert by_pos["ITJ"]["freq"] == 27_086_011
    assert by_pos["UNC"]["freq"] == 27_086_011
    for pos in ("PNP", "CRD", "ZZ0"):
        assert by_pos[pos][INFO_FIELD] == [afd.INFO_POS_SPLIT], pos
    for pos in ("ITJ", "UNC"):
        assert INFO_FIELD not in by_pos[pos], pos
    assert stats["multiplexed"] == 3
    assert stats["split_words_with_leftover"] == 1
    assert stats["leftover_records"] == 2
    assert stats["high_freq_report"] and all(
        w == "i" and before == 27_086_011
        for w, _pos, before, _after in stats["high_freq_report"])


def test_rule1_identical_effective_sets_share_one_class():
    # NN1 and NN2 both resolve to {NoC}: ONE class, counted once in the
    # denominator, both records get the same share.
    entries = [_entry("run", "NN1"), _entry("run", "NN2"), _entry("run", "VVB")]
    lrw = _lrw({"run": {"NoC": 30, "Verb": 90}})
    stats = enrich(entries, {"run": 1000}, lrw)
    noun_share = round(1000 * 30 / 120)
    assert [e["freq"] for e in entries] == [noun_share, noun_share, 750]
    assert stats["multiplexed"] == 3
    assert stats["split_words_with_leftover"] == 0


def test_rule1_needs_two_distinct_classes():
    # Only {NoC} resolves -> no split, freq untouched (and no lemma parents).
    entries = [_entry("cat", "NN1"), _entry("cat", "VVB")]
    lrw = _lrw({"cat": {"NoC": 40}})
    stats = enrich(entries, {"cat": 500}, lrw)
    assert [e["freq"] for e in entries] == [500, 500]
    assert stats["multiplexed"] == 0


def test_rule1_portmanteau_and_unmapped_never_resolve():
    entries = [_entry("gonna", "VVG+TO0"), _entry("gonna", "PRE"),
               _entry("gonna", "XYZ")]
    lrw = _lrw({"gonna": {"Verb": 40, "NoC": 20}})
    stats = enrich(entries, {"gonna": 900}, lrw)
    assert [e["freq"] for e in entries] == [900, 900, 900]
    assert stats["multiplexed"] == 0


# --- overlap conflict: hard skip, no rule-2 fallthrough ----------------------

def test_overlap_conflict_skips_word_entirely():
    # ORD -> {Num, Adj} vs AJ0 -> {Adj}: different effective sets that overlap.
    entries = [_entry("first", "ORD"), _entry("first", "AJ0")]
    lrw = _lrw({"first": {"Num": 200, "Adj": 300}},
               # Parents exist and would split cleanly — must NOT be consulted.
               parent_lemmas={"first": {"one"}})
    stats = enrich(entries, {"first": 10_000}, lrw)
    assert [e["freq"] for e in entries] == [10_000, 10_000]
    assert stats["overlap_conflict_words"] == 1
    assert stats["multiplexed"] == stats["inherited"] == 0
    assert all(INFO_FIELD not in e for e in entries)


# --- attestation floors ------------------------------------------------------

def test_floor_zero_weight_reading_does_not_resolve():
    # Adj attested at 0 (= "<0.5/M"): no magnitude, AJ0 must not resolve, so
    # only one class remains -> no split.
    entries = [_entry("dim", "NN1"), _entry("dim", "AJ0")]
    lrw = _lrw({"dim": {"NoC": 50, "Adj": 0}})
    stats = enrich(entries, {"dim": 800}, lrw)
    assert [e["freq"] for e in entries] == [800, 800]
    assert stats["multiplexed"] == 0


def test_floor_total_below_split_minimum():
    # Two resolved classes but 4 + 5 = 9 < 10: rounding noise, no split.
    entries = [_entry("blip", "NN1"), _entry("blip", "VVB")]
    lrw = _lrw({"blip": {"NoC": 4, "Verb": 5}})
    stats = enrich(entries, {"blip": 800}, lrw)
    assert [e["freq"] for e in entries] == [800, 800]
    assert stats["multiplexed"] == 0


def test_floor_total_exactly_at_minimum_splits():
    # 4 + 6 = 10 == MIN_SPLIT_TOTAL_PER_MILLION: the floor is inclusive.
    entries = [_entry("blop", "NN1"), _entry("blop", "VVB")]
    lrw = _lrw({"blop": {"NoC": 4, "Verb": 6}})
    stats = enrich(entries, {"blop": 100}, lrw)
    assert [e["freq"] for e in entries] == [40, 60]
    assert stats["multiplexed"] == 2


def test_zero_freq_word_untouched_by_pass2():
    # Uncovered word: pass-1 freq 0, so there is nothing to apportion — even
    # with splittable LRW readings the records stay at 0, unannotated.
    entries = [_entry("zilch", "NN1"), _entry("zilch", "VVB")]
    lrw = _lrw({"zilch": {"NoC": 40, "Verb": 60}})
    stats = enrich(entries, {}, lrw)
    assert [e["freq"] for e in entries] == [0, 0]
    assert all(INFO_FIELD not in e for e in entries)
    assert stats["multiplexed"] == stats["inherited"] == 0


def test_round_to_zero_share_keeps_freq_source():
    # A resolved share below 0.5 of the count rounds to freq 0; the word IS
    # corpus-covered, so freq_source stays and the info tag records why.
    entries = [_entry("wisp", "NN1"), _entry("wisp", "VVB")]
    lrw = _lrw({"wisp": {"NoC": 1, "Verb": 99}})
    enrich(entries, {"wisp": 4}, lrw)
    assert entries[0]["freq"] == 0  # round(4 * 1/100)
    assert entries[1]["freq"] == 4
    assert entries[0]["freq_source"] == afd.FREQ_SOURCE_TAG
    assert entries[0][INFO_FIELD] == [afd.INFO_POS_SPLIT]


# --- rule 2: lemma-ratio inheritance -----------------------------------------

def test_rule2_inherits_parent_lemma_ratio():
    # Surface `hopes` is filed under one POS only; the summed parents' readings
    # carry the noun/verb ratio, applied to the word's OWN count.
    entries = [_entry("hopes", "NN2"), _entry("hopes", "VVZ")]
    lrw = _lrw({"hopes": {"NoC": 12}, "hope": {"NoC": 50, "Verb": 150}},
               parent_lemmas={"hopes": {"hope"}})
    stats = enrich(entries, {"hopes": 2000}, lrw)
    assert entries[0]["freq"] == round(2000 * 50 / 200) == 500
    assert entries[1]["freq"] == round(2000 * 150 / 200) == 1500
    assert entries[0][INFO_FIELD] == [afd.INFO_FROM_LEMMA]
    assert stats["inherited"] == 2
    assert stats["multiplexed"] == 0


def test_rule2_sums_multiple_parents():
    entries = [_entry("mixes", "NN2"), _entry("mixes", "VVZ")]
    lrw = _lrw({"mixes": {"Verb": 3},
                "mix": {"NoC": 10, "Verb": 20}, "mixe": {"NoC": 10}},
               parent_lemmas={"mixes": {"mix", "mixe"}})
    enrich(entries, {"mixes": 400}, lrw)
    # Summed parents: NoC 20, Verb 20 -> even split.
    assert [e["freq"] for e in entries] == [200, 200]


def test_rule2_not_tried_without_parents():
    entries = [_entry("void", "NN1"), _entry("void", "VVB")]
    lrw = _lrw({"void": {"NoC": 12}})
    stats = enrich(entries, {"void": 700}, lrw)
    assert [e["freq"] for e in entries] == [700, 700]
    assert stats["inherited"] == 0


def test_rule2_overlap_conflict_skips_word():
    # No surface readings, so rule 2 is consulted — and the parents' summed
    # readings put ORD {Num, Adj} against AJ0 {Adj}: overlapping distinct
    # sets, so the word is skipped with no split and no annotation.
    entries = [_entry("thirds", "ORD"), _entry("thirds", "AJ0")]
    lrw = _lrw({"third": {"Num": 50, "Adj": 60}},
               parent_lemmas={"thirds": {"third"}})
    stats = enrich(entries, {"thirds": 5000}, lrw)
    assert [e["freq"] for e in entries] == [5000, 5000]
    assert stats["overlap_conflict_words"] == 1
    assert stats["inherited"] == 0
    assert all(INFO_FIELD not in e for e in entries)


# --- contraction min-of-parts: annotated, excluded from splitting ------------

def test_contraction_annotated_and_not_split():
    entries = [_entry("don't", "VDB+XX0"), _entry("don't", "VDI+XX0")]
    corpus = {"don": 500_000, "'t": 9_600_000}
    # Even a surface that WOULD split must not touch a min-of-parts bound.
    lrw = _lrw({"don't": {"Verb": 100, "NoC": 50}})
    stats = enrich(entries, corpus, lrw)
    for e in entries:
        assert e["freq"] == 500_000
        assert e[INFO_FIELD] == [afd.INFO_FROM_PARTS]
    assert stats["from_parts"] == 2
    assert stats["multiplexed"] == stats["inherited"] == 0


# --- annotation idempotency --------------------------------------------------

def test_stale_own_tags_stripped_foreign_tags_kept():
    entries = [_entry("i", "PNP",
                      info=["obsolete", afd.INFO_FROM_LEMMA, "dialectal"]),
               _entry("i", "CRD", info=[afd.INFO_POS_SPLIT])]
    lrw = _lrw({"i": {"Pron": 10241, "Num": 86}})
    enrich(entries, {"i": 27_086_011}, lrw)
    # Foreign tags survive in order; the stale lemma tag is replaced by the
    # split tag actually earned this run.
    assert entries[0][INFO_FIELD] == ["obsolete", "dialectal",
                                     afd.INFO_POS_SPLIT]
    assert entries[1][INFO_FIELD] == [afd.INFO_POS_SPLIT]


def test_stale_tag_removed_entirely_when_no_longer_earned():
    # A record that no longer splits must lose its stale tag AND the empty
    # info key.
    entries = [_entry("cat", "NN1", info=[afd.INFO_POS_SPLIT])]
    enrich(entries, {"cat": 500}, _lrw())
    assert INFO_FIELD not in entries[0]


def test_enrichment_is_idempotent():
    def build():
        return [_entry("i", "PNP"), _entry("i", "CRD")]
    corpus = {"i": 27_086_011}
    lrw = _lrw({"i": {"Pron": 10241, "Num": 86}})
    once = build()
    enrich(once, corpus, lrw)
    twice = build()
    enrich(twice, corpus, lrw)
    enrich(twice, corpus, lrw)
    assert once == twice


def test_idempotent_with_freq_readlex_stash():
    # First run stashes the original ReadLex-scale freq; the second run sees
    # freq_source and must NOT restash the corpus value over it.
    def build():
        return [_entry("i", "PNP", freq=123), _entry("i", "CRD", freq=45)]
    corpus = {"i": 27_086_011}
    lrw = _lrw({"i": {"Pron": 10241, "Num": 86}})
    once = build()
    enrich(once, corpus, lrw)
    twice = build()
    enrich(twice, corpus, lrw)
    enrich(twice, corpus, lrw)
    assert once == twice
    assert [e["freq_readlex"] for e in twice] == [123, 45]


# --- the file parser ---------------------------------------------------------

PARSER_FIXTURE = "\n".join([
    # Lemma with two continuation rows; `run` itself repeated as a
    # continuation (a self-link that must NOT enter parent_lemmas).
    "\trun\tVerb\t%\t120\t100\t0.95",
    "\t@\t@\trun\t80\t100\t0.94",
    "\t@\t@\tran\t25\t90\t0.90",
    "\t@\t@\truns\t15\t80\t0.88",
    # Case variants of one surface: readings union under one key.
    "\ti\tPron\t:\t10241\t100\t0.98",
    "\tI\tNoP\t:\t14\t40\t0.50",
    # Duplicate (key, tag) keeps the max perMillion.
    "\ti\tPron\t:\t9000\t100\t0.98",
    # HTML entity + accent: &eacute; -> é -> e.
    "\tcaf&eacute;\tNoC\t:\t7\t30\t0.40",
    "",
])


def _load_fixture(text):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="latin-1",
                                     delete=False) as f:
        f.write(text)
        fixture_path = Path(f.name)
    try:
        return load_lrw(fixture_path)
    finally:
        fixture_path.unlink()


def test_parser_fixture():
    lrw = _load_fixture(PARSER_FIXTURE)
    # @ @ rows inherit the preceding lemma's POS with their OWN perMillion.
    assert lrw.surface_readings["ran"] == {"Verb": 25}
    assert lrw.surface_readings["runs"] == {"Verb": 15}
    assert lrw.parent_lemmas["ran"] == {"run"}
    assert lrw.parent_lemmas["runs"] == {"run"}
    # The self-continuation merged into the lemma surface (max 120 vs 80)
    # without a self parent link.
    assert lrw.surface_readings["run"] == {"Verb": 120}
    assert "run" not in lrw.parent_lemmas
    # Case-fold union + max-merge.
    assert lrw.surface_readings["i"] == {"Pron": 10241, "NoP": 14}
    assert "I" not in lrw.surface_readings
    # html-unescape then accent-strip.
    assert lrw.surface_readings["cafe"] == {"NoC": 7}


def test_load_lrw_missing_path_fails_loud():
    try:
        load_lrw(Path("/nonexistent/bncfreq/1_1_all_fullalpha.txt"))
    except SystemExit:
        return
    raise AssertionError("expected SystemExit for a missing LRW file")


def test_load_lrw_malformed_row_fails_loud():
    # A 6-column row means corruption or a changed re-download: abort.
    broken = PARSER_FIXTURE + "\tbroken\tNoC\t:\t5\t10\n"
    try:
        _load_fixture(broken)
    except SystemExit:
        return
    raise AssertionError("expected SystemExit for a malformed LRW row")


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
