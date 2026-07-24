#!/usr/bin/env python3
"""
Blended confidence scoring — the FINAL supplement-build stage.

WHAT THIS REPLACES
------------------
The `confidence` field the ~8 scattered stages stamp is near-useless: it is a
decision-tree over penalty flags emitting one of ~9 hard-coded integers, so
152,601 clean records pile on a flat 89 ("no penalty flag fired" — NOT a
probability) and 116,748 (upstream + no-IPA) carry None. This stage OVERWRITES
that constant with a graded blend so the flat 89-spike spreads into a usable
ordering the editor can sort/filter on.

THE MODEL (owner-settled — do not re-litigate)
----------------------------------------------
    confidence = clamp_0_100( Σ_i  WEIGHTS[i] * vote_i )

* Every voter emits a FLOAT vote in [0.0, 1.0] — never a boolean. A voter that
  is binary today emits 1.0 or 0.0; a voter with a magnitude (a tier, a
  probability) emits that magnitude. This uniform [0,1] shape lets a voter be
  upgraded to graded by just writing a different float — no schema/blend change.
* Weights carry the trust. POSITIVE weight = trust signal; NEGATIVE weight =
  red flag. A red flag is JUST a voter with a negative weight — there is no
  separate penalty axis, it is one weighted sum.
* The sum starts from 0 and is dragged UP by corroboration, DOWN by red flags,
  then clamped to a 0..100 integer for display.

GRADED VOTERS (the votes are magnitudes, not near-binary spikes)
----------------------------------------------------------------
* judge  — the RP-IPA neural judge no longer votes 1-bit. `score_supplement`
  runs a ONE-TIME batched pass of g2p_common.score_candidates (mean per-token
  log-prob of the record's own `ipa` given `Latn`, under the frozen Latin-only
  judge model) and grades the PASS/REJECT vote from the likelihood via
  TRANSFORM C (two-sided linear map, symmetric, clamped both ends). Judged
  records lacking `ipa` cannot be graded and keep a binary 1.0 vote.
* clean_base — `1 - penalty_magnitude` from ipa_to_shavian.detect_penalties
  (a pure function of on-record fields), replacing the flat 1.0.
* rrp_tier — de-saturated by averaging in the generator's own `generated_tier`
  where it persisted one (the blend used to ignore it).
* shave_agree — the names pipeline's finer 4-level `tier` where present, else
  the shaw_source proxy.
* cmudict_disagree — a NEW negative voter: `cmudict_shaw` is stored only when
  CMUdict's rendering DISAGREES with the record's Shaw — a red flag.

NO SILENT FALLBACKS: a voter fires only when its signal is on the record;
otherwise it simply does not contribute (an unknown/unmapped signal VALUE is a
loud error, never a mid-value default).

DETERMINISM: pure function of fields already on the record plus the frozen judge
model. The judge pass sorts its unique (Latn, ipa) items before batching (fixed
batch composition), scores teacher-forced on CPU (no sampling), and rejects any
non-finite likelihood — so the stage is reproducible and patch anchors stay
stable. No shave subprocess, no RNG, no dict-order dependence in the arithmetic.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from basis import PROJECT_ROOT, is_upstream
from ipa_to_shavian import (contains_non_shavian, detect_penalties,
                            ipa_to_shavian)
from ml_ipa_normalizer import load_model as load_normalizer_model
from ml_ipa_normalizer import ml_normalize_ipa, strip_stress


# ---------------------------------------------------------------------------
# WEIGHTS TABLE  (owner-tunable — this is the whole tuning surface)
# ---------------------------------------------------------------------------
# Each entry is the weight multiplied by that voter's [0,1] vote. Positive =
# trust, negative = red flag. Starting values are adapted from the
# accuracy-anchored voter-weights report (Clean +40, consensus +35, judge
# PASS +25 / REJECT -30, tier A +15 .. F -15, source-agree +10/+15,
# contamination -90, upstream = short-circuit to 100).
#
# SCALING / how the sum maps to 0..100
# ------------------------------------
# Votes are in [0,1] and weights are raw points, so the sum is already in
# "points" comparable to the report's additive scheme. The realistic positive
# ceiling for a stars-aligned non-upstream record (clean base + tier A + judge
# PASS + 3-source + IPA + has-def) is ~40+15+25+15+8+2 = 105, so a bare clamp
# to [0,100] lands the best supplement candidates in the high-90s and buries the
# red-flagged ones at 0 — the spread the owner asked for. We therefore DO NOT
# renormalise; we clamp. Upstream core is handled separately (short-circuit 100)
# so it never competes on this scale.
WEIGHTS = {
    # --- trust signals (positive) ---
    "clean_base":       40.0,   # converter fired with no penalty flag (the 89-mass anchor)
    "judge_pass":       25.0,   # RP-IPA neural judge PASS — real corroboration (graded)
    "rrp_tier":         15.0,   # ordinal A..F quality (vote carries the gradient)
    "shave_agree":      35.0,   # shave+cmudict concurrence (names tier / shaw_source proxy)
    "source_agree":     15.0,   # independent multi-source corroboration
    "ipa_present":       8.0,   # record has real IPA (firmer than shave-only guess)
    "has_definition":    2.0,   # weak near-free prior
    # --- red flags (negative) ---
    "judge_reject":    -30.0,   # judge SKIP_JUDGE_REJECT (98%-precision reject — drags down)
    "cmudict_disagree":-10.0,   # CMUdict's rendering disagrees with our Shaw (only stored on disagreement)
    "contamination":   -90.0,   # non-Shavian char in Shaw — garbage, must bury the record
}

# Upstream ReadLex core is gold reference data (pre-accepted, not a review
# candidate). We SHORT-CIRCUIT: any upstream record scores 100 with a single
# explanatory vote, so core always parks at the top of the queue.
UPSTREAM_SCORE = 100

JUDGE_MODEL_DIR = PROJECT_ROOT / "data" / "g2p-judge-model"

JUDGE_PASS_OUTCOMES = ("PASS", "PASS_RESPELL")
JUDGE_REJECT_OUTCOME = "SKIP_JUDGE_REJECT"

# Judge TRANSFORM C (owner-approved): a two-sided linear map of the mean
# per-token log-likelihood L into [0,1]. L=0 (model near-certain of the IPA) ->
# 1.0; L <= -LIKELIHOOD_FLOOR (model disbelieves the IPA) -> 0.0. On PASS the
# vote is this grade; on REJECT the vote is 1 - grade, so a reject whose IPA the
# model finds plausible drags LESS than a confidently-wrong one.
LIKELIHOOD_FLOOR = 4.0

# names-pipeline 4-level tier -> shave_agree vote (finer than the shaw_source
# proxy). Rungs from the confidence-regrade report.
NAMES_TIER_VOTE = {
    "high-agree": 1.0,
    "high-agree-merger-tolerant": 0.85,
    "medium-shave-only": 0.5,
    "shave-g2p-speculative": 0.35,
}

# clean_base := 1 - penalty magnitude. A flag's rung is how much it demotes the
# clean base (min wins when several fire). r_gap is graded by gap size below.
PENALTY_VOTE = {
    "unknown_chars": 0.0,
    "missing_r":     0.0,
    "ml_disagrees":  0.15,
    "numeral":       0.1,
}
R_GAP_FLOOR = 0.3

FLOAT_DECIMALS = 6  # round stored votes (FP-noise guard for a stable serialization)


def _tier_vote(tier):
    """rrp_tier / generated_tier A..F -> [0,1] ordinal. None => no signal.

    F maps to 0.0 (contributes nothing under a positive weight)."""
    return {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.35, "E": 0.2, "F": 0.0}.get(tier)


def _rrp_tier_vote(record):
    """De-saturate the tier vote by averaging in `generated_tier` where the
    generator persisted its own grade (the blend used to ignore it). Both are
    on-record ordinals; if neither is present there is no tier signal."""
    grades = [grade for grade in (_tier_vote(record.get("rrp_tier")),
                                  _tier_vote(record.get("generated_tier")))
              if grade is not None]
    if not grades:
        return None
    return sum(grades) / len(grades)


def _shave_vote(record):
    """shave-agreement vote.

    Prefer the names pipeline's finer 4-level `tier` where present; otherwise
    fall back to the coarse shaw_source proxy:
        'shave+cmudict-agree' -> 1.0  (two independent G2Ps concur — strong)
        'shave-g2p' alone      -> 0.5  (present but uncorroborated)
    anything else / None on both => no signal.

    An UNKNOWN names-tier label is a loud KeyError, not a silent default: the
    names pipeline emits a fixed vocabulary and a new label is a wiring change
    that must be graded explicitly, never mid-valued away."""
    names_tier = record.get("tier")
    if names_tier is not None:
        return NAMES_TIER_VOTE[names_tier]
    shaw_source = record.get("shaw_source")
    if shaw_source == "shave+cmudict-agree":
        return 1.0
    if shaw_source == "shave-g2p":
        return 0.5
    return None


def _source_agreement_vote(source):
    """Independent corroboration from the count of distinct source labels.

    1 source -> 0.0 (no corroboration), 2 -> 0.5, 3+ -> 1.0. This is the core
    "amplify on agreement" signal — the one thing that can legitimately lift a
    record above any single model's opinion."""
    n = len(set(source or ()))
    if n >= 3:
        return 1.0
    if n == 2:
        return 0.5
    return 0.0


def _judge_grade(likelihood):
    """TRANSFORM C forward half: log-likelihood L -> [0,1] via a clamped linear
    map. L=0 -> 1.0, L <= -LIKELIHOOD_FLOOR -> 0.0."""
    if not math.isfinite(likelihood):
        raise ValueError(
            f"judge likelihood is not finite ({likelihood!r}); refusing to emit "
            f"a NaN/inf confidence")
    return min(1.0, max(0.0, 1.0 + likelihood / LIKELIHOOD_FLOOR))


def _judge_votes(record, likelihood):
    """The graded judge_pass/judge_reject vote pair for one record.

    `likelihood` is the mean per-token log-prob of the record's own ipa under
    the judge model, or None when the record carries no ipa (the judge needs
    only Latn at judge time, so such a record was still judged but cannot be
    likelihood-graded — it keeps a binary 1.0 vote). Non-judged outcomes emit
    nothing."""
    outcome = record.get("rrp_outcome")
    if outcome in JUDGE_PASS_OUTCOMES:
        if likelihood is None:
            return {"judge_pass": 1.0}
        return {"judge_pass": _judge_grade(likelihood)}
    if outcome == JUDGE_REJECT_OUTCOME:
        if likelihood is None:
            return {"judge_reject": 1.0}
        return {"judge_reject": 1.0 - _judge_grade(likelihood)}
    return {}


class CleanBaseGrader:
    """clean_base := 1 - penalty magnitude, recomputed per record via
    ipa_to_shavian.detect_penalties (pure function of on-record fields).

    The ml_disagrees check mirrors the source-generation path: for RSSB/RRP
    records the ML normalizer's prediction is rendered through the converter and
    compared to the record's Shaw. Cached on (word, ipa, shaw, var) so repeated
    conversions of the same conversion are scored once."""

    def __init__(self):
        self._normalizer = load_normalizer_model()
        self._cache = {}

    def _ml_shaw(self, word, ipa, var):
        # Mirrors generate_wordnet_supplement._compute_ml_shaw exactly: no guard,
        # so a normalizer/converter failure PROPAGATES and aborts the build (a
        # genuine bug must not be masked as a clean base). Only RSSB/RRP records
        # carry an ML opinion; others contribute none.
        if var not in ("RSSB", "RRP"):
            return None
        ml_ipa = ml_normalize_ipa(strip_stress(ipa), word, self._normalizer)
        return ipa_to_shavian(ml_ipa)

    def grade(self, record):
        key = (record["Latn"], record.get("ipa") or "", record["Shaw"],
               record.get("var"))
        vote = self._cache.get(key)
        if vote is None:
            word, ipa, shaw, var = key
            ml_shaw = self._ml_shaw(word, ipa, var)
            penalties, notes = detect_penalties(word, ipa, shaw, ml_shaw)
            vote = 1.0
            for penalty in set(penalties):
                if penalty == "r_gap":
                    vote = min(vote, _r_gap_vote(notes))
                else:
                    vote = min(vote, PENALTY_VOTE[penalty])
            self._cache[key] = vote
        return vote


def _r_gap_vote(notes):
    """Grade the r_gap penalty by gap size from its note
    ('r_gap:spelling=N,ipa=M'): 1 - gap/spelling_r, floored. A missing note is a
    contract violation between detect_penalties and this grader — a loud error,
    not a guessed default."""
    for note in notes:
        if note.startswith("r_gap:"):
            spelling_r, ipa_r = (int(part.split("=")[1])
                                 for part in note[len("r_gap:"):].split(","))
            return max(R_GAP_FLOOR, 1.0 - (spelling_r - ipa_r) / spelling_r)
    raise ValueError(
        f"r_gap penalty fired without an r_gap note: {notes}")


def _clean_base_eligible(record):
    """Same eligibility gate the blend has always used: the converter produced
    this Shaw on its clean branch. The build-time stage-stamped `confidence`
    (89 == "clean, no flag") is the primary witness; a record carrying IPA-
    derived Shaw with no shave_source is the secondary one. Contamination is a
    separate negative voter, so the base may fire and then be overpowered."""
    return record.get("confidence") == 89 or (
        record.get("ipa") and record.get("shaw_source") is None)


def compute_votes(record, likelihood, clean_base_grader):
    """Return the {voter: [0,1] vote} dict for a record. Only voters with a
    signal are included (an absent voter contributes 0 to the sum). Pure given
    the likelihood + grader passed in; does NOT handle the upstream
    short-circuit (that is score_record's job)."""
    votes = {}

    votes.update(_judge_votes(record, likelihood))

    tier = _rrp_tier_vote(record)
    if tier is not None:
        votes["rrp_tier"] = tier

    shave = _shave_vote(record)
    if shave is not None:
        votes["shave_agree"] = shave

    votes["source_agree"] = _source_agreement_vote(record.get("source"))
    votes["ipa_present"] = 1.0 if record.get("ipa") else 0.0
    votes["has_definition"] = 1.0 if record.get("has_definition") else 0.0

    if _clean_base_eligible(record):
        votes["clean_base"] = clean_base_grader.grade(record)

    # cmudict_shaw is stored ONLY when CMUdict disagrees with our Shaw, so its
    # mere presence is the red flag. Absent -> the voter does not fire.
    if record.get("cmudict_shaw"):
        votes["cmudict_disagree"] = 1.0

    # contamination safety net. filter_contamination may already have dropped
    # these, so this rarely fires — kept so a contaminated record that slips
    # through is buried rather than trusted.
    shaw = record.get("Shaw") or ""
    if shaw and contains_non_shavian(shaw):
        votes["contamination"] = 1.0

    return {name: round(vote, FLOAT_DECIMALS) for name, vote in votes.items()}


def blend(votes):
    """Weighted sum of votes -> clamped 0..100 integer. Pure arithmetic; the
    iteration is over WEIGHTS (fixed order) so it is dict-order independent."""
    total = 0.0
    for name, weight in WEIGHTS.items():
        total += weight * votes.get(name, 0.0)
    return max(0, min(100, round(total)))


def score_record(record, likelihood, clean_base_grader):
    """Score ONE fully-assembled record: overwrite record['confidence'] with the
    blended 0..100 value and attach record['votes']. Upstream core
    short-circuits to UPSTREAM_SCORE. `likelihood` is the judge log-prob for this
    record (None if not judge-gradable); `clean_base_grader` supplies the graded
    clean base."""
    if is_upstream(record):
        record["votes"] = {"upstream": 1.0}
        record["confidence"] = UPSTREAM_SCORE
        return record
    votes = compute_votes(record, likelihood, clean_base_grader)
    record["votes"] = votes
    record["confidence"] = blend(votes)
    return record


# ---------------------------------------------------------------------------
# Judge likelihood pass (one batched model call per build, deterministic)
# ---------------------------------------------------------------------------

def _is_judge_gradable(record):
    """A judged (PASS/REJECT) supplement record carrying the ipa the likelihood
    is scored against."""
    outcome = record.get("rrp_outcome")
    return (not is_upstream(record) and bool(record.get("ipa"))
            and (outcome in JUDGE_PASS_OUTCOMES
                 or outcome == JUDGE_REJECT_OUTCOME))


def _collect_judge_items(supplement):
    """Sorted unique (latn_lower, ipa) pairs for every judge-gradable record.
    Sorting fixes batch composition -> deterministic scores."""
    pairs = {(record["Latn"].lower(), record["ipa"])
             for records in supplement.values()
             for record in records
             if _is_judge_gradable(record)}
    return sorted(pairs)


def score_judge_likelihoods(supplement):
    """(latn_lower, ipa) -> mean per-token log-prob under the frozen Latin-only
    judge model, for every judge-gradable record. One batched CPU pass; lazy
    torch import so importing this module (e.g. from unit tests) stays
    torch-free. Fails loud if the wrong model is wired in or a score is
    non-finite."""
    from g2p_common import load_model, score_candidates

    items = _collect_judge_items(supplement)
    if not items:
        return {}
    model, src_vocab, tgt_vocab, meta = load_model(JUDGE_MODEL_DIR)
    if meta.get("with_shaw"):
        raise SystemExit(
            f"score_confidence: {JUDGE_MODEL_DIR} is not the Latin-only judge "
            f"model (meta.with_shaw is true) — grading with the candidate's own "
            f"Shaw would echo the pronunciation being judged")
    batch = [{"latn": latn, "shaw": None, "ipa": ipa} for latn, ipa in items]
    scores = score_candidates(model, src_vocab, tgt_vocab, batch,
                              with_shaw=False, device="cpu")
    likelihoods = {}
    for (latn, ipa), score in zip(items, scores):
        if not math.isfinite(score):
            raise SystemExit(
                f"score_confidence: judge produced a non-finite likelihood "
                f"({score!r}) for ({latn!r}, {ipa!r}) — refusing to emit a "
                f"NaN/inf confidence")
        likelihoods[(latn, ipa)] = round(score, FLOAT_DECIMALS)
    return likelihoods


def _record_likelihood(record, likelihoods):
    """The judge log-prob for one record, or None if it is not judge-gradable."""
    if not _is_judge_gradable(record):
        return None
    return likelihoods[(record["Latn"].lower(), record["ipa"])]


def score_supplement(supplement, counter=None):
    """Stage entry point. Scores every record in the bucketed
    {word_pos_shaw: [record, ...]} dict IN PLACE and returns it. Count-preserving
    (only mutates `confidence` + adds `votes`; never drops/splits/re-buckets).

    Runs the judge likelihood pass ONCE up front, then blends each record.
    Slotted LAST in the build chain (after flag_variants, filter_contamination
    and filter_phrases) so every field a voter reads is fully populated and
    final before the blend runs."""
    likelihoods = score_judge_likelihoods(supplement)
    clean_base_grader = CleanBaseGrader()
    for records in supplement.values():
        for record in records:
            score_record(record, _record_likelihood(record, likelihoods),
                         clean_base_grader)
            if counter is not None:
                counter[record["confidence"]] += 1
    return supplement
