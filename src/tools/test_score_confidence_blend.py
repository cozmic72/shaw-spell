#!/usr/bin/env python3
"""Focused unit tests for the blended confidence stage.

Tests the blend as a PURE function over synthetic records — no build, no data
file, no shave. Asserts the qualitative properties the owner cares about:
upstream parks at 100, a judge-REJECT drags a clean baseline down, more sources
beat fewer, contamination tanks the score, and all-signals-agree lands top-band.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import score_confidence_blend as sc


def _rec(**kw):
    base = {"Latn": "x", "Shaw": "𐑒𐑨𐑑", "pos": "NN", "source": ["wiktionary"]}
    base.update(kw)
    return base


def score(record):
    return sc.score_record(dict(record))["confidence"]


def test_upstream_parks_at_100():
    r = _rec(source=["readlex"], confidence=None)
    scored = sc.score_record(dict(r))
    assert scored["confidence"] == 100
    assert scored["votes"] == {"upstream": 1.0}


def test_clean_baseline_positive():
    # clean converter record, single source, tier B, judge PASS, IPA
    r = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat")
    s = score(r)
    assert s > 50, s


def test_judge_reject_drags_below_clean():
    clean = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat")
    reject = _rec(confidence=89, rrp_tier="B", rrp_outcome="SKIP_JUDGE_REJECT",
                  ipa="kat")
    assert score(reject) < score(clean), (score(reject), score(clean))


def test_more_sources_beat_fewer():
    one = _rec(confidence=89, rrp_tier="B", ipa="kat", source=["wiktionary"])
    three = _rec(confidence=89, rrp_tier="B", ipa="kat",
                 source=["wiktionary", "wordnet", "names"])
    assert score(three) > score(one), (score(three), score(one))


def test_contamination_tanks():
    good = _rec(confidence=89, rrp_tier="A", rrp_outcome="PASS", ipa="kat",
                Shaw="𐑒𐑨𐑑")
    bad = _rec(confidence=89, rrp_tier="A", rrp_outcome="PASS", ipa="kat",
               Shaw="𐑒a𐑑")  # latin 'a' contaminates
    assert score(bad) < 20, score(bad)
    assert score(bad) < score(good)


def test_all_signals_agree_top_band():
    r = _rec(confidence=89, rrp_tier="A", rrp_outcome="PASS", ipa="kat",
             shaw_source="shave+cmudict-agree", has_definition=True,
             source=["wiktionary", "wordnet", "names"])
    assert score(r) >= 90, score(r)


def test_votes_are_floats_in_unit_interval():
    r = _rec(confidence=89, rrp_tier="C", rrp_outcome="PASS", ipa="kat")
    votes = sc.compute_votes(r)
    assert votes, "expected at least one voter to fire"
    for name, v in votes.items():
        assert isinstance(v, float), (name, v)
        assert 0.0 <= v <= 1.0, (name, v)


def test_deterministic():
    r = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat",
             source=["wiktionary", "wordnet"])
    assert score(dict(r)) == score(dict(r))


def test_no_ipa_generated_demoted():
    # no-IPA generated name: no clean base, no judge, tier B only
    r = _rec(confidence=None, rrp_tier="B", ipa=None, source=["names"])
    lone_clean = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat")
    assert score(r) < score(lone_clean), (score(r), score(lone_clean))


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
