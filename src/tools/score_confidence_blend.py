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
  is binary today (e.g. shave-agrees) emits 1.0 or 0.0; a voter with a magnitude
  (a tier, a probability) emits that magnitude. This uniform [0,1] shape is
  REQUIRED so a currently-boolean voter can be upgraded to graded LATER by just
  writing a different float — no schema/blend change. Boolean and graded voters
  are the SAME float field; nothing special-cases them.
* Weights carry the trust. POSITIVE weight = trust signal; NEGATIVE weight =
  red flag. A red flag is JUST a voter with a negative weight — there is no
  separate penalty axis/facet, it is one weighted sum.
* The sum starts from 0 and is dragged UP by corroboration, DOWN by red flags,
  then clamped to a 0..100 integer for display.

Each voter's [0,1] vote is also persisted onto the record under `votes` so the
score is explainable (owner can see WHY a record scored what it did) and a future
phase can swap a boolean vote for a graded one by writing a different float.

DETERMINISM: pure function of fields already on the record. No shave subprocess,
no RNG, no dict-order dependence in the arithmetic. Keeps the build reproducible
and patch anchors stable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from basis import is_upstream
from ipa_to_shavian import contains_non_shavian


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
# so it never competes on this scale. If the owner later wants the positive band
# to fill exactly to 100, scale POS_CEILING below instead of touching weights.
WEIGHTS = {
    # --- trust signals (positive) ---
    "clean_base":       40.0,   # converter fired with no penalty flag (the 89-mass anchor)
    "judge_pass":       25.0,   # RP-IPA neural judge PASS — real corroboration
    "rrp_tier":         15.0,   # ordinal A..F quality (vote carries the gradient)
    "shave_agree":      35.0,   # shave+cmudict concurrence (v1 proxy — see below)
    "source_agree":     15.0,   # independent multi-source corroboration
    "ipa_present":       8.0,   # record has real IPA (firmer than shave-only guess)
    "has_definition":    2.0,   # weak near-free prior
    # --- red flags (negative) ---
    "judge_reject":    -30.0,   # judge SKIP_JUDGE_REJECT (98%-precision reject — drags down)
    "contamination":   -90.0,   # non-Shavian char in Shaw — garbage, must bury the record
}

# Non-upstream positive ceiling used only for the OPTIONAL renormalisation hook
# (unused by default; documented in WEIGHTS scaling note above).
POS_CEILING = sum(w for w in WEIGHTS.values() if w > 0)

# Upstream ReadLex core is gold reference data (pre-accepted, not a review
# candidate). Rather than trying to make the additive sum reach 100 for it, we
# SHORT-CIRCUIT: any upstream record scores 100 with a single explanatory vote.
# Justified because core must always park at the top of the queue regardless of
# which supplement-oriented voters happen to fire on it.
UPSTREAM_SCORE = 100


def _tier_vote(tier):
    """rrp_tier A..F -> [0,1] ordinal. None => no signal (0 contribution).

    F maps to 0.0 (contributes nothing under a positive weight). If the owner
    wants F to actively PENALISE, give it a small negative via a dedicated
    voter / weight — that's a table tweak, noted, not done here."""
    return {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.35, "E": 0.2, "F": 0.0}.get(tier)


def _shave_vote(shaw_source):
    """v1 shave-agreement PROXY from shaw_source.

    'shave+cmudict-agree' -> 1.0  (two independent G2Ps concur — strong)
    'shave-g2p' alone      -> 0.5  (present but uncorroborated)
    anything else / None   -> no signal

    CAVEAT (v1): the real "converter vs shave top-candidate agree" boolean is
    computed-then-DISCARDED in upgrade_confidence_shave and is not persisted on
    the record, so we cannot read it here. shaw_source is the best available
    proxy. When that vote is surfaced as a field, replace this with the real
    graded/boolean agree signal — no blend change, just a different float."""
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


def compute_votes(record):
    """Return the {voter: [0,1] vote} dict for a record. Only voters that have
    a signal are included (an absent voter contributes 0 to the sum). Pure and
    deterministic. Does NOT handle the upstream short-circuit — that is a
    scoring-level decision in score_record()."""
    votes = {}

    # judge (rrp_outcome). PASS is a positive voter; SKIP_JUDGE_REJECT is its
    # OWN voter with a NEGATIVE weight (a reject DRAGS DOWN, it does not merely
    # fail to add). OOV / None / other outcomes => no judge signal (neither
    # rewarded nor penalised). REVIEW => low positive judge signal is not
    # warranted, so it contributes nothing here (the tier F / rrp_review path
    # already demotes it).
    outcome = record.get("rrp_outcome")
    if outcome in ("PASS", "PASS_RESPELL"):
        votes["judge_pass"] = 1.0
    elif outcome == "SKIP_JUDGE_REJECT":
        votes["judge_reject"] = 1.0  # 1.0 * negative weight = the drag

    # rrp_tier ordinal
    tv = _tier_vote(record.get("rrp_tier"))
    if tv is not None:
        votes["rrp_tier"] = tv

    # shave agreement (v1 proxy)
    sv = _shave_vote(record.get("shaw_source"))
    if sv is not None:
        votes["shave_agree"] = sv

    # source agreement (always present — 0.0 means "1 source", still informative)
    votes["source_agree"] = _source_agreement_vote(record.get("source"))

    # IPA present
    votes["ipa_present"] = 1.0 if record.get("ipa") else 0.0

    # has_definition weak prior
    votes["has_definition"] = 1.0 if record.get("has_definition") else 0.0

    # clean base: the converter produced this Shaw with no penalty flag. We use
    # the stage-stamped `confidence` constant purely as a READ-ONLY witness of
    # the clean branch (89 == "clean, no flag"); we do not rewrite that stage.
    # A record that carries a real IPA-derived Shaw and is not contaminated gets
    # the clean base. Contamination is handled by its own negative voter below,
    # so the base can fire and then be overpowered.
    if record.get("confidence") == 89 or (
            record.get("ipa") and record.get("shaw_source") is None):
        votes["clean_base"] = 1.0

    # contamination red flag (safety net). filter_contamination may already have
    # dropped these, so this rarely fires in the shipped pool — kept so a
    # contaminated record that slips through is buried rather than trusted.
    shaw = record.get("Shaw") or ""
    if shaw and contains_non_shavian(shaw):
        votes["contamination"] = 1.0

    return votes


def blend(votes):
    """Weighted sum of votes -> clamped 0..100 integer. Pure arithmetic; the
    iteration is over WEIGHTS (fixed order) so it is dict-order independent."""
    total = 0.0
    for name, weight in WEIGHTS.items():
        total += weight * votes.get(name, 0.0)
    return max(0, min(100, round(total)))


def score_record(record):
    """Score ONE fully-assembled record: overwrite record['confidence'] with the
    blended 0..100 value and attach record['votes'] with the per-voter [0,1]
    votes. Upstream core short-circuits to UPSTREAM_SCORE."""
    if is_upstream(record):
        record["votes"] = {"upstream": 1.0}
        record["confidence"] = UPSTREAM_SCORE
        return record
    votes = compute_votes(record)
    record["votes"] = votes
    record["confidence"] = blend(votes)
    return record


def score_supplement(supplement, counter=None):
    """Stage entry point. Scores every record in the bucketed
    {word_pos_shaw: [record, ...]} dict IN PLACE and returns it. Count-preserving
    (only mutates `confidence` + adds `votes`; never drops/splits/re-buckets).

    Slotted LAST in the build chain (after flag_variants, filter_contamination
    and filter_phrases) so every field a voter reads — source, rrp_*, shaw_source,
    ipa, has_definition, the variant flag, and the pruned contamination survivors
    — is fully populated and final before the blend runs."""
    for records in supplement.values():
        for record in records:
            score_record(record)
            if counter is not None:
                counter[record["confidence"]] += 1
    return supplement
