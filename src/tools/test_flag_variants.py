#!/usr/bin/env python3
"""Focused tests for variant flagging: a divergent-from-canonical record gains
`variant`; a merger-flagged record never does — the merger names the variation,
so the flags are mutually exclusive (owner ruling, 2026-08-03)."""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flag_variants import flag_supplement

CANONICAL = "𐑚𐑪𐑔"
DIVERGENT = "𐑚𐑧𐑔"
MERGED = "𐑚𐑷𐑔"

UPSTREAM_RRP = {"Latn": "bath", "Shaw": CANONICAL, "pos": "NN1", "var": "RRP"}


def _record(shaw, **kw):
    entry = {"Latn": "bath", "Shaw": shaw, "pos": "NN1", "var": "GenAm",
             "source": ["wiktionary"]}
    entry.update(kw)
    return entry


def _flag(pool):
    supplement = {"bath_NN1": [dict(e) for e in pool]}
    upstream = {"bath_NN1": [dict(UPSTREAM_RRP)]}
    out = flag_supplement(supplement, Counter(), defaultdict(list),
                          upstream=upstream)
    return {r["Shaw"]: r for r in out["bath_NN1"]}


def test_divergent_record_gains_variant():
    out = _flag([_record(DIVERGENT)])
    assert out[DIVERGENT].get("variant") is True


def test_canonical_spelling_not_flagged():
    out = _flag([_record(CANONICAL, var="RRP")])
    assert out[CANONICAL].get("variant") is None


def test_merger_flagged_record_never_gains_variant():
    out = _flag([_record(MERGED, mergers=["cot-caught"])])
    assert out[MERGED].get("variant") is None
    assert out[MERGED]["mergers"] == ["cot-caught"]


def test_stale_variant_cleared_from_merger_record():
    out = _flag([_record(MERGED, mergers=["cot-caught"], variant=True)])
    assert "variant" not in out[MERGED]


def test_upstream_record_passes_verbatim():
    core = _record(MERGED, source=["readlex"], mergers=["trap-bath"],
                   variant=True)
    out = _flag([core])
    assert out[MERGED] == core


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
