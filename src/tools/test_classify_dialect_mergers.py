#!/usr/bin/env python3
"""Focused unit tests for dialect-merger classification, centred on the
attestation rule: a candidate is flagged only against an RP/SSB-attested
upstream sibling — never against another (unverified) supplement candidate,
never against a merged-accent or merger-flagged upstream entry."""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from classify_dialect_mergers import classify_supplement, merger_for, \
    non_merged_spellings
from dialect_mergers import LOT, MERGER_COT_CAUGHT, MERGER_LOT_PALM, \
    MERGER_TRAP_BATH, PALM, THOUGHT, _MERGER_SWAPS_ALL, _is_swap, merger_of

PALM_FORM = "𐑚𐑭𐑔"
TRAP_FORM = "𐑚𐑨𐑔"


def _candidate(shaw=TRAP_FORM, var="GenAm", **kw):
    entry = {"Latn": "bath", "Shaw": shaw, "pos": "NN1", "var": var,
             "source": ["wiktionary"]}
    entry.update(kw)
    return entry


def _upstream_entry(shaw=PALM_FORM, var="RRP", **kw):
    entry = {"Latn": "bath", "Shaw": shaw, "pos": "NN1", "var": var}
    entry.update(kw)
    return entry


def _classify(pool_entries, upstream_entries):
    supplement = {"bath_NN1": [dict(e) for e in pool_entries]}
    upstream = {"bath_NN1": [dict(e) for e in upstream_entries]}
    out = classify_supplement(supplement, Counter(), defaultdict(list),
                              upstream=upstream)
    return out["bath_NN1"]


def _mergers_of_candidate(pool_entries, upstream_entries):
    [record] = [r for r in _classify(pool_entries, upstream_entries)
                if r["Shaw"] == TRAP_FORM]
    return record.get("mergers")


# --- the narrowed attestation rule ------------------------------------------

def test_candidate_sibling_does_not_attest():
    for var in ("RSSB", "RRP"):
        sibling = _candidate(shaw=PALM_FORM, var=var)
        assert _mergers_of_candidate([sibling, _candidate()], []) is None


def test_upstream_rrp_sibling_attests():
    assert _mergers_of_candidate([_candidate()], [_upstream_entry()]) == \
        [MERGER_TRAP_BATH]


def test_upstream_merger_flagged_entry_does_not_attest():
    flagged = _upstream_entry(mergers=[MERGER_TRAP_BATH])
    assert _mergers_of_candidate([_candidate()], [flagged]) is None


def test_upstream_merged_accent_var_does_not_attest():
    for var in ("GenAm", "GenAus"):
        assert _mergers_of_candidate(
            [_candidate()], [_upstream_entry(var=var)]) is None


def test_pos_must_match():
    assert _mergers_of_candidate(
        [_candidate()], [_upstream_entry(pos="VVI")]) is None


def test_no_sibling_never_flagged():
    assert _mergers_of_candidate([_candidate()], []) is None


def test_index_from_upstream():
    index = non_merged_spellings({"bath_NN1": [_upstream_entry()]})
    assert index[("bath", "NN1")] == {PALM_FORM}
    assert merger_for(_candidate(), index) == (MERGER_TRAP_BATH, PALM_FORM)


# --- non-merged bases and upstream pool records are never tagged ------------

def test_base_var_candidate_never_tagged():
    for var in ("RSSB", "RRP"):
        [record] = _classify([_candidate(var=var)], [_upstream_entry()])
        assert record.get("mergers") is None


def test_upstream_pool_record_passes_verbatim():
    core = _candidate(shaw=TRAP_FORM, var="RRP", source=["readlex"],
                      mergers=[MERGER_TRAP_BATH])
    [record] = _classify([core], [_upstream_entry()])
    assert record == core


# --- swap detection ---------------------------------------------------------

def test_merger_of_exact_swap():
    assert merger_of(PALM_FORM, TRAP_FORM) == MERGER_TRAP_BATH


def test_merger_of_multi_position_swap():
    assert merger_of("𐑭𐑤𐑭", "𐑨𐑤𐑨") == MERGER_TRAP_BATH


def test_merger_of_rejects_identical():
    assert merger_of(PALM_FORM, PALM_FORM) is None


def test_merger_of_rejects_length_mismatch():
    assert merger_of(PALM_FORM, TRAP_FORM + "𐑟") is None


def test_merger_of_rejects_extra_difference():
    assert merger_of(PALM_FORM, "𐑨𐑨𐑔") is None


def test_merger_of_is_directional():
    assert merger_of(TRAP_FORM, PALM_FORM) is None


def test_lot_palm_merged_target_is_palm():
    """Owner-settled direction: canonical bother 𐑚𐑪𐑞𐑼 (LOT) is the distinguished
    form; the merged spelling 𐑚𐑭𐑞𐑼 shows PALM and gets the flag. Pinned against
    the full table because the merger is enable-gated."""
    distinguished, flattened = _MERGER_SWAPS_ALL[MERGER_LOT_PALM]
    assert (distinguished, flattened) == (LOT, PALM)
    assert _is_swap("𐑚𐑪𐑞𐑼", "𐑚𐑭𐑞𐑼", distinguished, flattened)
    assert not _is_swap("𐑚𐑭𐑞𐑼", "𐑚𐑪𐑞𐑼", distinguished, flattened)


def test_cot_caught_merged_target_is_thought():
    """Owner-settled direction: canonical dog 𐑛𐑪𐑜 (LOT) is the distinguished form;
    the merged spelling 𐑛𐑷𐑜 shows THOUGHT and gets the flag. This direction was
    coded the other way round twice before the owner ruled, hence the pin."""
    distinguished, flattened = _MERGER_SWAPS_ALL[MERGER_COT_CAUGHT]
    assert (distinguished, flattened) == (LOT, THOUGHT)
    assert _is_swap("𐑛𐑪𐑜", "𐑛𐑷𐑜", distinguished, flattened)
    assert not _is_swap("𐑛𐑷𐑜", "𐑛𐑪𐑜", distinguished, flattened)


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
