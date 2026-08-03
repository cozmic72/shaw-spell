#!/usr/bin/env python3
"""Focused unit tests for dialect-merger classification, centred on the widened
attestation rule: a candidate is attested by an unflagged non-merged sibling at
its own accent level or any ancestor accent (upstream ReadLex or pool
candidate) — never by a descendant/lateral accent, a merger-flagged record, a
record this stage itself flags, or a differing POS — and a merger is only
flaggable on an accent that has it (MERGER_ACCENTS)."""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from classify_dialect_mergers import AttestationIndex, classify_supplement
from dialect_mergers import LOT, MERGER_COT_CAUGHT, MERGER_LOT_PALM, \
    MERGER_TRAP_BATH, PALM, THOUGHT, _MERGER_SWAPS_ALL, _is_swap, merger_of

LOT_FORM = "𐑚𐑪𐑔"
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


# --- the widened attestation rule -------------------------------------------

def test_upstream_rrp_sibling_attests():
    assert _mergers_of_candidate([_candidate()], [_upstream_entry()]) == \
        [MERGER_TRAP_BATH]


def test_pool_british_sibling_attests():
    for var in ("RSSB", "RRP"):
        sibling = _candidate(shaw=PALM_FORM, var=var)
        assert _mergers_of_candidate([sibling, _candidate()], []) == \
            [MERGER_TRAP_BATH]


def test_pool_peer_attests():
    peer = _candidate(shaw=PALM_FORM, var="GenAm")
    assert _mergers_of_candidate([peer, _candidate()], []) == \
        [MERGER_TRAP_BATH]


def test_upstream_peer_attests():
    assert _mergers_of_candidate(
        [_candidate()], [_upstream_entry(var="GenAm")]) == [MERGER_TRAP_BATH]


def test_intermediate_ancestor_attests():
    genam = _candidate(shaw=PALM_FORM, var="GenAm")
    gencan = _candidate(var="GenCan")
    [record] = [r for r in _classify([genam, gencan], [])
                if r["var"] == "GenCan"]
    assert record.get("mergers") == [MERGER_TRAP_BATH]


def test_merger_accent_eligibility():
    """A merger is only flaggable on an accent that HAS it (MERGER_ACCENTS):
    GenAus/NZ ɔ-for-LOT is a source transcription convention, not cot-caught."""
    caught_form = "𐑚𐑷𐑔"
    for var, expected in (("GenAm", [MERGER_COT_CAUGHT]),
                          ("GenCan", [MERGER_COT_CAUGHT]),
                          ("GenAus", None), ("NZ", None),
                          ("SthAfr", None), ("IrEng", None)):
        [record] = [r for r in _classify(
            [_candidate(shaw=caught_form, var=var)],
            [_upstream_entry(shaw=LOT_FORM)]) if r["Shaw"] == caught_form]
        assert record.get("mergers") == expected, var


def test_trap_bath_accent_eligibility():
    """Flat BATH is native to North America/Ireland and variable in Australia;
    NZ and South Africa hold a firm split so never carry trap-bath."""
    for var, expected in (("GenAus", [MERGER_TRAP_BATH]),
                          ("IrEng", [MERGER_TRAP_BATH]),
                          ("NZ", None), ("SthAfr", None)):
        assert _mergers_of_candidate(
            [_candidate(var=var)], [_upstream_entry()]) == expected, var


def test_descendant_or_lateral_accent_does_not_attest():
    for var in ("GenCan", "GenAus"):
        sibling = _candidate(shaw=PALM_FORM, var=var)
        assert _mergers_of_candidate([sibling, _candidate()], []) is None
        assert _mergers_of_candidate(
            [_candidate()], [_upstream_entry(var=var)]) is None


def test_merger_declaration_precedence_wins():
    """A candidate matching two mergers via different siblings takes the
    earliest merger in MERGER_SWAPS declaration order (trap-bath here), so a
    newly added merger can never re-claim an already-claimed record."""
    candidate = _candidate(shaw="𐑨𐑤𐑷")
    trap_witness = _candidate(shaw="𐑭𐑤𐑷", var="RSSB")
    cot_witness = _candidate(shaw="𐑨𐑤𐑪", var="RSSB")
    [record] = [r for r in _classify(
        [candidate, trap_witness, cot_witness], []) if r["Shaw"] == "𐑨𐑤𐑷"]
    assert record.get("mergers") == [MERGER_TRAP_BATH]


def test_upstream_attestation_reported_before_pool():
    pool = _candidate(shaw=PALM_FORM, var="RSSB")
    index = AttestationIndex({"bath_NN1": [_upstream_entry()]},
                             {"bath_NN1": [pool]})
    assert index.merger_for(_candidate()) == \
        (MERGER_TRAP_BATH, PALM_FORM, "upstream-ancestor")


def test_index_from_upstream():
    index = AttestationIndex({"bath_NN1": [_upstream_entry()]}, {})
    assert index.merger_for(_candidate()) == \
        (MERGER_TRAP_BATH, PALM_FORM, "upstream-ancestor")


# --- the correctness guards -------------------------------------------------

def test_upstream_merger_flagged_entry_does_not_attest():
    flagged = _upstream_entry(mergers=[MERGER_TRAP_BATH])
    assert _mergers_of_candidate([_candidate()], [flagged]) is None


def test_pool_merger_flagged_entry_does_not_attest():
    flagged = _candidate(shaw=PALM_FORM, var="RSSB",
                         mergers=[MERGER_TRAP_BATH])
    assert _mergers_of_candidate([flagged, _candidate()], []) is None


def test_flagged_by_this_stage_does_not_attest():
    """A pool 𐑭 form that is itself a lot-palm swap of an 𐑪 sibling is a merged
    mutant: it takes the lot-palm flag and must not then witness a trap-bath
    swap onto the 𐑨 form."""
    lot = _candidate(shaw=LOT_FORM, var="RSSB")
    palm = _candidate(shaw=PALM_FORM, var="GenAm")
    trap = _candidate(shaw=TRAP_FORM, var="GenAm")
    by_shaw = {r["Shaw"]: r for r in _classify([lot, palm, trap], [])}
    assert by_shaw[PALM_FORM].get("mergers") == [MERGER_LOT_PALM]
    assert by_shaw[TRAP_FORM].get("mergers") is None


def test_pos_must_match():
    assert _mergers_of_candidate(
        [_candidate()], [_upstream_entry(pos="VVI")]) is None
    other_pos = _candidate(shaw=PALM_FORM, var="RRP", pos="VVI")
    assert _mergers_of_candidate([other_pos, _candidate()], []) is None


def test_no_sibling_never_flagged():
    assert _mergers_of_candidate([_candidate()], []) is None


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
