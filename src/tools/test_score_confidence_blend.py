#!/usr/bin/env python3
"""Focused unit tests for the blended confidence stage.

Tests the blend as a PURE function over synthetic records — no build, no data
file, no shave, no torch. The judge likelihood is injected directly (the model
pass is exercised at build time, not here), and a stub clean-base grader avoids
loading the ML normalizer. Asserts the qualitative properties the owner cares
about plus the graded-voter behaviour: judge transform C endpoints/clamping,
clean_base from penalties, a zero-compute tier join, and no-signal -> no-fire
(never a silent mid-value default).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import score_confidence_blend as sc


def _rec(**kw):
    base = {"Latn": "x", "Shaw": "𐑒𐑨𐑑", "pos": "NN", "source": ["wiktionary"]}
    base.update(kw)
    return base


class _StubCleanBase:
    """Clean base is always fully clean — keeps these tests off the ML
    normalizer. The graded-penalty behaviour is tested separately against the
    real CleanBaseGrader."""

    def grade(self, record):
        return 1.0


def score(record, likelihood=None, clean_base_grader=None):
    grader = clean_base_grader or _StubCleanBase()
    return sc.score_record(dict(record), likelihood, grader)["confidence"]


def votes(record, likelihood=None, clean_base_grader=None):
    grader = clean_base_grader or _StubCleanBase()
    return sc.compute_votes(dict(record), likelihood, grader)


# --- upstream + core qualitative properties (unchanged behaviour) -----------

def test_upstream_parks_at_100():
    r = _rec(source=["readlex"], confidence=None)
    scored = sc.score_record(dict(r), None, _StubCleanBase())
    assert scored["confidence"] == 100
    assert scored["votes"] == {"upstream": 1.0}


def test_clean_baseline_positive():
    r = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat")
    assert score(r, likelihood=-0.1) > 50


def test_judge_reject_drags_below_clean():
    clean = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat")
    reject = _rec(confidence=89, rrp_tier="B", rrp_outcome="SKIP_JUDGE_REJECT",
                  ipa="kat")
    assert score(reject, likelihood=-2.0) < score(clean, likelihood=-0.1)


def test_more_sources_beat_fewer():
    one = _rec(confidence=89, rrp_tier="B", ipa="kat", source=["wiktionary"])
    three = _rec(confidence=89, rrp_tier="B", ipa="kat",
                 source=["wiktionary", "wordnet", "names"])
    assert score(three) > score(one)


def test_contamination_tanks():
    good = _rec(confidence=89, rrp_tier="A", rrp_outcome="PASS", ipa="kat",
                Shaw="𐑒𐑨𐑑")
    bad = _rec(confidence=89, rrp_tier="A", rrp_outcome="PASS", ipa="kat",
               Shaw="𐑒a𐑑")  # latin 'a' contaminates
    assert score(bad, likelihood=0.0) < 20
    assert score(bad, likelihood=0.0) < score(good, likelihood=0.0)


def test_all_signals_agree_top_band():
    r = _rec(confidence=89, rrp_tier="A", rrp_outcome="PASS", ipa="kat",
             shaw_source="shave+cmudict-agree", has_definition=True,
             source=["wiktionary", "wordnet", "names"])
    assert score(r, likelihood=0.0) >= 90


def test_votes_are_floats_in_unit_interval():
    r = _rec(confidence=89, rrp_tier="C", rrp_outcome="PASS", ipa="kat")
    v = votes(r, likelihood=-1.0)
    assert v, "expected at least one voter to fire"
    for name, value in v.items():
        assert isinstance(value, float), (name, value)
        assert 0.0 <= value <= 1.0, (name, value)


def test_deterministic():
    r = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat",
             source=["wiktionary", "wordnet"])
    assert score(dict(r), -0.7) == score(dict(r), -0.7)


def test_no_ipa_generated_demoted():
    r = _rec(confidence=None, rrp_tier="B", ipa=None, source=["names"])
    lone_clean = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat")
    assert score(r) < score(lone_clean, likelihood=-0.1)


# --- graded judge: TRANSFORM C endpoints, clamping, symmetry ----------------

def test_judge_grade_endpoints():
    assert sc._judge_grade(0.0) == 1.0                      # near-certain -> full
    assert sc._judge_grade(-sc.LIKELIHOOD_FLOOR) == 0.0     # floor -> zero
    assert sc._judge_grade(-sc.LIKELIHOOD_FLOOR / 2) == 0.5  # linear midpoint


def test_judge_grade_clamps_both_ends():
    assert sc._judge_grade(5.0) == 1.0                      # positive L clamps to 1
    assert sc._judge_grade(-100.0) == 0.0                   # far-negative clamps to 0


def test_judge_grade_rejects_non_finite():
    for bad in (float("nan"), float("inf"), float("-inf")):
        try:
            sc._judge_grade(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_judge_pass_vote_graded_by_likelihood():
    plausible = _rec(rrp_outcome="PASS", ipa="kat")
    implausible = _rec(rrp_outcome="PASS", ipa="kat")
    assert (votes(plausible, -0.2)["judge_pass"]
            > votes(implausible, -3.0)["judge_pass"])


def test_judge_reject_is_one_minus_grade():
    # transform C: a REJECT whose IPA the model finds plausible drags LESS than
    # a confidently-wrong one, so its judge_reject vote is SMALLER.
    plausible_reject = _rec(rrp_outcome="SKIP_JUDGE_REJECT", ipa="kat")
    wrong_reject = _rec(rrp_outcome="SKIP_JUDGE_REJECT", ipa="kat")
    assert (votes(plausible_reject, -0.2)["judge_reject"]
            < votes(wrong_reject, -3.5)["judge_reject"])


def test_judge_no_ipa_keeps_binary_vote():
    # judged (needs only Latn) but no ipa to score -> binary 1.0, no crash.
    r = _rec(rrp_outcome="PASS", ipa=None)
    assert votes(r, None)["judge_pass"] == 1.0


# --- graded clean_base from real penalties (no ML normalizer needed) --------

def _stub_grader(ml_shaw=None):
    """A CleanBaseGrader with the ML branch stubbed out (returns `ml_shaw`),
    so grade() exercises detect_penalties without loading the ML normalizer."""
    grader = sc.CleanBaseGrader.__new__(sc.CleanBaseGrader)
    grader._normalizer = None
    grader._cache = {}
    grader._ml_shaw = lambda word, ipa, var: ml_shaw
    return grader


def test_clean_base_no_penalty_is_one():
    grader = _stub_grader()
    assert grader.grade(_rec(Latn="cat", ipa="kat", Shaw="𐑒𐑨𐑑", var="RRP")) == 1.0


def test_clean_base_unknown_chars_zero():
    grader = _stub_grader()
    dirty = grader.grade(_rec(Latn="cat", ipa="kat", Shaw="𐑒Z𐑑", var="RRP"))
    assert dirty == sc.PENALTY_VOTE["unknown_chars"] == 0.0


def test_clean_base_numeral_rung():
    grader = _stub_grader()
    vote = grader.grade(_rec(Latn="3d", ipa="θriːdiː", Shaw="𐑔𐑮𐑰𐑛𐑰", var="RRP"))
    assert vote == sc.PENALTY_VOTE["numeral"] == 0.1


def test_clean_base_ml_disagrees_rung():
    # ml_shaw differs from the record's Shaw -> ml_disagrees fires.
    grader = _stub_grader(ml_shaw="𐑒𐑪𐑑")
    vote = grader.grade(_rec(Latn="cat", ipa="kat", Shaw="𐑒𐑨𐑑", var="RRP"))
    assert vote == sc.PENALTY_VOTE["ml_disagrees"] == 0.15


def test_clean_base_r_gap_rung():
    # 'carrier' has 2 r-groups, ipa 'kæriə' has 1 -> r_gap:spelling=2,ipa=1.
    grader = _stub_grader()
    vote = grader.grade(_rec(Latn="carrier", ipa="kæriə",
                             Shaw="𐑒𐑨𐑮𐑦𐑩", var="RRP"))
    assert vote == 0.5  # 1 - (2-1)/2


def test_clean_base_multi_penalty_takes_min():
    # 'car' vs 'kɑ' fires BOTH r_gap (0.3-floored) AND missing_r (0.0); the
    # grader takes the min, so missing_r wins.
    grader = _stub_grader()
    vote = grader.grade(_rec(Latn="car", ipa="kɑ", Shaw="𐑒𐑭", var="RRP"))
    assert vote == sc.PENALTY_VOTE["missing_r"] == 0.0


def test_ml_shaw_skips_non_rrp_rssb_without_touching_normalizer():
    # The var gate lives in the REAL _ml_shaw: a non-RRP/RSSB record returns None
    # BEFORE the (here None) normalizer is consulted. If the gate regressed, the
    # None normalizer would raise instead of returning None.
    grader = sc.CleanBaseGrader.__new__(sc.CleanBaseGrader)
    grader._normalizer = None
    grader._cache = {}
    assert grader._ml_shaw("cat", "kat", "GenAm") is None


# --- _r_gap_vote: the riskiest new parse/arithmetic path ---------------------

def test_r_gap_vote_grades_by_gap():
    assert sc._r_gap_vote(["r_gap:spelling=2,ipa=1"]) == 0.5    # 1 - (2-1)/2
    assert sc._r_gap_vote(["r_gap:spelling=3,ipa=2"]) == 1 - 1 / 3  # small gap


def test_r_gap_vote_floor_clamp():
    # spelling=1,ipa=0 -> 1 - 1/1 = 0.0, floored to R_GAP_FLOOR.
    assert sc._r_gap_vote(["r_gap:spelling=1,ipa=0"]) == sc.R_GAP_FLOOR
    assert sc._r_gap_vote(["r_gap:spelling=4,ipa=0"]) == sc.R_GAP_FLOOR


def test_r_gap_vote_ignores_other_notes():
    assert sc._r_gap_vote(["numeral", "r_gap:spelling=2,ipa=1"]) == 0.5


def test_r_gap_vote_missing_note_is_loud():
    try:
        sc._r_gap_vote(["numeral"])
    except ValueError:
        return
    raise AssertionError("expected ValueError when no r_gap note is present")


# --- zero-compute join: generated_tier de-saturates rrp_tier ----------------

def test_generated_tier_averaged_into_rrp_tier():
    both = _rec(rrp_tier="B", generated_tier="C")   # (0.75 + 0.5) / 2 = 0.625
    only_rrp = _rec(rrp_tier="B")                    # 0.75
    assert votes(both)["rrp_tier"] == 0.625
    assert votes(only_rrp)["rrp_tier"] == 0.75


# --- no silent 0.5: an absent signal does NOT fire its voter ----------------

def test_no_shave_signal_does_not_fire():
    # neither names `tier` nor shaw_source present -> shave_agree absent entirely
    # (not a mid-value default).
    assert "shave_agree" not in votes(_rec(rrp_tier="B", ipa="kat"))


def test_no_tier_signal_does_not_fire():
    # neither rrp_tier nor generated_tier -> rrp_tier absent (no 0.5 fallback).
    assert "rrp_tier" not in votes(_rec(ipa="kat"))


def test_names_tier_takes_precedence_over_shaw_source():
    r = _rec(tier="high-agree", shaw_source="shave-g2p")
    assert votes(r)["shave_agree"] == sc.NAMES_TIER_VOTE["high-agree"]


def test_unknown_names_tier_is_loud():
    r = _rec(tier="not-a-real-tier")
    try:
        votes(r)
    except KeyError:
        return
    raise AssertionError("expected KeyError for an unknown names tier")


# --- cmudict disagreement is a red flag -------------------------------------

def test_cmudict_disagreement_drags_down():
    with_flag = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat",
                     cmudict_shaw="𐑒𐑪𐑑")
    without = _rec(confidence=89, rrp_tier="B", rrp_outcome="PASS", ipa="kat")
    assert votes(with_flag)["cmudict_disagree"] == 1.0
    assert score(with_flag, -0.1) < score(without, -0.1)


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
