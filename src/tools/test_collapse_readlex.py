#!/usr/bin/env python3
"""Focused unit tests for the ReadLex-compatibility collapse (stage two of the
export boundary, basis.collapse_readlex).

Everything runs on hand-built publish-shape dicts — no real readlex.json.
Covers: the reinterpretation reversal (trap-bath merger → TrapBath, variant →
RRPVar, mergers-over-variant precedence, held-back variation on non-RRP
carriers), the regional prunes (each UNPUBLISHED_VARS member, plus a slot whose
only record is pruned), the RSSB slot collapse (drop beside RRP, relabel when
canonical, cross-bucket slots), the exceptions model (GenAm/GenAus kept beside
RRP, same-Shaw redundancy drop), the unknown-var failure, and
determinism/idempotency over a mixed fixture.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from basis import UNPUBLISHED_VARS, collapse_readlex


def _rec(word, pos, shaw, var, **kw):
    base = {"Latn": word, "Shaw": shaw, "pos": pos, "ipa": "", "freq": 0,
            "var": var}
    base.update(kw)
    return base


def _bucket(*records):
    """One publish dict keyed the way production keys it: word_POS_shaw."""
    published = {}
    for record in records:
        key = f"{record['Latn']}_{record['pos']}_{record['Shaw']}"
        published.setdefault(key, []).append(record)
    return published


def _vars(collapsed):
    return [r["var"] for records in collapsed.values() for r in records]


# --- reinterpretation reversal ----------------------------------------------

def test_trap_bath_merger_reverses_to_trapbath():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("bath", "NN1", "𐑚𐑭𐑔", "RRP"),
        _rec("bath", "NN1", "𐑚𐑨𐑔", "RRP", mergers=["trap-bath"])))
    assert sorted(_vars(collapsed)) == ["RRP", "TrapBath"]
    assert stats["reversed to TrapBath"] == 1
    assert all("mergers" not in r
               for records in collapsed.values() for r in records)


def test_variant_flag_reverses_to_rrpvar():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("gaol", "NN1", "𐑡𐑱𐑤", "RRP", variant=True)))
    assert _vars(collapsed) == ["RRPVar"]
    assert stats["reversed to RRPVar"] == 1
    assert all("variant" not in r
               for records in collapsed.values() for r in records)


def test_rssb_variant_reverses_to_rrpvar():
    collapsed, _ = collapse_readlex(_bucket(
        _rec("gaol", "NN1", "𐑡𐑱𐑤", "RSSB", variant=True)))
    assert _vars(collapsed) == ["RRPVar"]


def test_mergers_take_precedence_over_variant():
    collapsed, _ = collapse_readlex(_bucket(
        _rec("bath", "NN1", "𐑚𐑨𐑔", "RRP",
             mergers=["trap-bath"], variant=True)))
    assert _vars(collapsed) == ["TrapBath"]


def test_variation_on_non_rrp_carrier_is_held_back():
    # A trap-bath merger on a GenAm record and a variant flag on a GenAm record
    # have no upstream var: the flags are stripped, the plain var stays.
    collapsed, stats = collapse_readlex(_bucket(
        _rec("dance", "VVB", "𐑛𐑨𐑯𐑕", "GenAm", mergers=["trap-bath"]),
        _rec("color", "NN1", "𐑒𐑳𐑤𐑼", "GenAm", variant=True)))
    assert sorted(_vars(collapsed)) == ["GenAm", "GenAm"]
    assert stats["variation held back"] == 2


def test_non_trap_bath_merger_is_held_back():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("caught", "VVN", "𐑒𐑪𐑑", "RRP", mergers=["cot-caught"])))
    assert _vars(collapsed) == ["RRP"]
    assert stats["variation held back"] == 1


def test_variant_beside_held_back_merger_still_reverses():
    # A merger with no upstream counterpart never blocks the variant reversal.
    collapsed, _ = collapse_readlex(_bucket(
        _rec("caught", "VVN", "𐑒𐑪𐑑", "RRP",
             mergers=["cot-caught"], variant=True)))
    assert _vars(collapsed) == ["RRPVar"]


# --- regional prunes ---------------------------------------------------------

def test_each_regional_var_is_pruned():
    for var in sorted(UNPUBLISHED_VARS):
        collapsed, stats = collapse_readlex(_bucket(
            _rec("word", "NN1", "𐑢𐑻𐑛", "RRP"),
            _rec("word", "NN1", "𐑢𐑳𐑮𐑛", var)))
        assert _vars(collapsed) == ["RRP"], var
        assert stats[f"pruned {var}"] == 1, var


def test_slot_with_only_pruned_var_is_dropped_and_counted():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("koru", "NN1", "𐑒𐑹𐑵", "NZ")))
    assert collapsed == {}
    assert stats["pruned NZ"] == 1
    assert stats["emptied groups dropped"] == 1


# --- RSSB slot collapse ------------------------------------------------------

def test_rssb_drops_beside_slot_rrp():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("better", "AJC", "𐑚𐑧𐑑𐑼", "RRP"),
        _rec("better", "AJC", "𐑚𐑧𐑑𐑻", "RSSB")))
    assert _vars(collapsed) == ["RRP"]
    assert stats["RSSB dropped for slot RRP"] == 1


def test_solo_rssb_relabels_to_rrp():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("vaper", "NN1", "𐑝𐑱𐑐𐑻", "RSSB")))
    assert _vars(collapsed) == ["RRP"]
    assert stats["RSSB collapsed to RRP"] == 1


def test_slot_spans_buckets_and_ignores_word_case():
    # The slot is (word.lower(), pos) across group_key buckets: an RSSB record
    # in a different bucket (different Shaw) still sees its slot's RRP.
    collapsed, stats = collapse_readlex(_bucket(
        _rec("Better", "AJC", "𐑚𐑧𐑑𐑼", "RRP"),
        _rec("better", "AJC", "𐑚𐑧𐑑𐑻", "RSSB"),
        _rec("better", "NN1", "𐑚𐑧𐑑𐑻", "RSSB")))
    assert sorted(_vars(collapsed)) == ["RRP", "RRP"]
    assert stats["RSSB dropped for slot RRP"] == 1   # the AJC record
    assert stats["RSSB collapsed to RRP"] == 1       # the NN1 slot canonical


def test_trapbath_slot_without_plain_rrp_keeps_relabelled_rssb():
    # The real 'polygraph' shape: a trap-bath RRP record plus an RSSB sibling
    # and no plain RRP — the reversal takes the RRP record to TrapBath, so the
    # RSSB becomes the slot's canonical RRP.
    collapsed, _ = collapse_readlex(_bucket(
        _rec("polygraph", "NN1", "𐑐𐑪𐑤𐑦𐑜𐑮𐑭𐑓", "RRP", mergers=["trap-bath"]),
        _rec("polygraph", "NN1", "𐑐𐑪𐑤𐑦𐑜𐑮𐑨𐑓", "RSSB")))
    assert sorted(_vars(collapsed)) == ["RRP", "TrapBath"]


# --- exceptions model --------------------------------------------------------

def test_genam_and_genaus_survive_beside_rrp():
    collapsed, _ = collapse_readlex(_bucket(
        _rec("tomato", "NN1", "𐑑𐑩𐑥𐑭𐑑𐑴", "RRP"),
        _rec("tomato", "NN1", "𐑑𐑩𐑥𐑱𐑑𐑴", "GenAm"),
        _rec("tomato", "NN1", "𐑑𐑩𐑥𐑧𐑑𐑴", "GenAus")))
    assert sorted(_vars(collapsed)) == ["GenAm", "GenAus", "RRP"]


def test_same_shaw_duplicate_of_rrp_drops():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("robot", "NN1", "𐑮𐑴𐑚𐑪𐑑", "RRP"),
        _rec("robot", "NN1", "𐑮𐑴𐑚𐑪𐑑", "GenAm")))
    assert _vars(collapsed) == ["RRP"]
    assert stats["redundant RRP duplicate dropped"] == 1


def test_solo_genam_survives():
    collapsed, _ = collapse_readlex(_bucket(
        _rec("zip code", "NN1", "𐑟𐑦𐑐 𐑒𐑴𐑛", "GenAm")))
    assert _vars(collapsed) == ["GenAm"]


def test_ssb_passes_through():
    collapsed, stats = collapse_readlex(_bucket(
        _rec("shwi", "NN1", "𐑖𐑢𐑦", "SSB")))
    assert _vars(collapsed) == ["SSB"]
    assert not stats


def test_non_rrp_siblings_sharing_shaw_both_survive():
    # The redundancy rule is RRP-relative only: two exceptions agreeing with
    # each other (but not with RRP) both stand, as upstream's shape allows.
    collapsed, _ = collapse_readlex(_bucket(
        _rec("dance", "NN1", "𐑛𐑭𐑯𐑕", "RRP"),
        _rec("dance", "NN1", "𐑛𐑨𐑯𐑕", "GenAm"),
        _rec("dance", "NN1", "𐑛𐑨𐑯𐑕", "RRP", mergers=["trap-bath"])))
    assert sorted(_vars(collapsed)) == ["GenAm", "RRP", "TrapBath"]


# --- failure and stability ---------------------------------------------------

def _expect_value_error(published, fragment):
    try:
        collapse_readlex(published)
    except ValueError as error:
        assert fragment in str(error), error
        return
    raise AssertionError(f"expected ValueError mentioning {fragment!r}")


def test_unknown_var_fails_loud():
    _expect_value_error(
        _bucket(_rec("word", "NN1", "𐑢𐑻𐑛", "Klingon")), "Klingon")


def test_empty_var_fails_loud():
    _expect_value_error(_bucket(_rec("word", "NN1", "𐑢𐑻𐑛", "")), "word")


def test_supplement_flag_rides_through():
    collapsed, _ = collapse_readlex(_bucket(
        _rec("newword", "NN1", "𐑯𐑿𐑢𐑻𐑛", "RRP", supplement=True)))
    (records,) = collapsed.values()
    assert records[0]["supplement"] is True


def _mixed_fixture():
    return _bucket(
        _rec("bath", "NN1", "𐑚𐑭𐑔", "RRP"),
        _rec("bath", "NN1", "𐑚𐑨𐑔", "RRP", mergers=["trap-bath"]),
        _rec("gaol", "NN1", "𐑡𐑱𐑤", "RRP", variant=True),
        _rec("gaol", "NN1", "𐑡𐑱𐑤𐑤", "RRP"),
        _rec("better", "AJC", "𐑚𐑧𐑑𐑼", "RRP"),
        _rec("better", "AJC", "𐑚𐑧𐑑𐑻", "RSSB"),
        _rec("vaper", "NN1", "𐑝𐑱𐑐𐑻", "RSSB"),
        _rec("tomato", "NN1", "𐑑𐑩𐑥𐑭𐑑𐑴", "RRP"),
        _rec("tomato", "NN1", "𐑑𐑩𐑥𐑱𐑑𐑴", "GenAm"),
        _rec("word", "NN1", "𐑢𐑻𐑛", "RRP"),
        _rec("word", "NN1", "𐑢𐑳𐑮𐑛", "GenCan"),
        _rec("koru", "NN1", "𐑒𐑹𐑵", "NZ"))


def test_caller_input_is_not_mutated():
    published = _mixed_fixture()
    snapshot = {k: [dict(r) for r in v] for k, v in published.items()}
    collapse_readlex(published)
    assert published == snapshot


def test_collapse_is_deterministic():
    first, _ = collapse_readlex(_mixed_fixture())
    second, _ = collapse_readlex(_mixed_fixture())
    assert first == second
    assert list(first) == list(second)


def test_collapse_is_idempotent():
    once, _ = collapse_readlex(_mixed_fixture())
    twice, stats = collapse_readlex(once)
    assert twice == once
    assert list(twice) == list(once)
    assert not stats


def test_order_is_preserved():
    published = _mixed_fixture()
    collapsed, _ = collapse_readlex(published)
    kept_keys = [k for k in published if k in collapsed]
    assert list(collapsed) == kept_keys


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
