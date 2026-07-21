#!/usr/bin/env python3
"""
Fill missing `ipa` on the generated supplement from the frozen neural G2P
(Latin+Shavian -> RP-IPA seq2seq in data/g2p-model/), as a VOTER.

The generated slice (data/supplement-generated.json) carries Shaw but no IPA:
shave spelled these words Roman->Shavian directly, so no pronunciation exists.
The frozen model predicts house RP-IPA from the Latin spelling PLUS the
record's Shavian (the Shavian disambiguates stress site, BATH, weak vowels —
91.9% held-out word accuracy vs 82.0% from Latin alone).

VOTER GATE — this feeds the dictionary, so a prediction ships ONLY when BOTH:
  (a) ROUND-TRIP: forward-converting the predicted IPA through the repo's
      ipa_to_shavian reproduces the record's exact Shaw (the converter is an
      independent rule system, so agreement means the IPA actually describes
      the spelling — on held-out test, round-trip passers are 94.0% exact /
      98.4% stress-insensitive correct vs 39% among failers); AND
  (b) LIKELIHOOD: the model's mean per-token log-prob of its own prediction is
      >= LIK_MARGINAL. Calibrated on the held-out test set (calibration table
      in the docstring of _confidence_for below).
Records failing either gate keep NO ipa — nothing low-confidence is invented.

Filled records carry ipa_source="model-g2p" and a numeric `confidence` (the
pipeline's 0-99 empirical-accuracy scale, same convention as
ipa_to_shavian.score_confidence): the likelihood band's measured exact-match
accuracy among round-trip passers. High agreement -> high confidence; the
marginal band lands in the 30-79 needs-review range so the editor surfaces it.

Deterministic: greedy decode on CPU (verified byte-identical across runs), no
shave involved — ordinary mtime-triggered make prerequisites are safe. It sits as an additive
pre-combine pass on the generated pool, mirroring fill_names_ipa for names:

    supplement-generated.json -> HERE (generated-ipa) -> combine -> ... -> basis

Inputs:  data/supplement-generated.json, data/g2p-model/{model.pt,meta.json}.
Outputs: data/supplement-generated-ipa.json — the generated pool with gated
         IPA filled. supplement-generated.json is left untouched.

Usage:
    python3 src/tools/fill_generated_ipa.py
"""

import json
import sys
from collections import Counter

from basis import PROJECT_ROOT
from g2p_common import load_model, predict_batch, score_candidates
from ipa_to_shavian import ipa_to_shavian

GENERATED_INPUT = PROJECT_ROOT / "data" / "supplement-generated.json"
GENERATED_IPA_OUTPUT = PROJECT_ROOT / "data" / "supplement-generated-ipa.json"
MODEL_DIR = PROJECT_ROOT / "data" / "g2p-model"

# Model input hygiene — must match the training corpus charset exactly
# (build_corpus.py): predictions outside it would be over UNK tokens.
LATN_ALLOWED = set("abcdefghijklmnopqrstuvwxyz'-")
SHAW_RANGE = (0x10450, 0x1047F)

# Likelihood gate + confidence mapping, calibrated on the model's held-out
# test split (n=4,062; 3,906 round-trip passers), see _confidence_for.
LIK_CONFIDENT = -0.02
LIK_MARGINAL = -0.05
CONF_CONFIDENT = 96
CONF_MARGINAL = 75


def shaw_clean(s):
    """Strip the naming dot and anything outside the Shavian block (the model
    was trained on bare Shavian)."""
    return "".join(c for c in s if SHAW_RANGE[0] <= ord(c) <= SHAW_RANGE[1])


def _confidence_for(likelihood):
    """Map model likelihood (mean per-token log-prob of its own greedy
    prediction) to the pipeline's 0-99 confidence scale, or None = do not fill.

    Empirically calibrated on the held-out test split, among predictions that
    PASS the round-trip gate (the deployed population):

        likelihood band      n      exact  stress-insensitive
        (-0.02,  0.00]     3,546    96.6%       99.2%
        (-0.05, -0.02]       215    75.3%       91.6%
        below -0.05          145    <60%          —     -> NOT dictionary material

    Confidence = the band's measured exact-match accuracy (the same
    empirical-accuracy convention as ipa_to_shavian.score_confidence).
    CONF_MARGINAL=75 deliberately sits below the 80+ high band, in the 30-79
    needs-review range, so marginal fills surface in the editor. The residual
    errors in the confident band are dominated by ReadLex notation residue
    (ae/AE, schwa/'Ə', r/R), not wrong phonemes.
    """
    if likelihood >= LIK_CONFIDENT:
        return CONF_CONFIDENT
    if likelihood >= LIK_MARGINAL:
        return CONF_MARGINAL
    return None


def gather_inputs(supplement, stats):
    """Model inputs for records lacking ipa: unique (latn_lower, shaw) pairs.

    Records sharing spelling+Shaw (POS siblings) get one prediction. Records
    outside the model charset (digits, diacritics, Latin residue in Shaw only)
    are not offered to the model at all.
    """
    keys = {}
    for records in supplement.values():
        for record in records:
            if "ipa" in record:
                stats["already_has_ipa"] += 1
                continue
            latn = record["Latn"].lower()
            shaw = shaw_clean(record["Shaw"])
            if not shaw or not set(latn) <= LATN_ALLOWED:
                stats["skipped_oov_charset"] += 1
                continue
            keys.setdefault((latn, shaw), None)
    return [{"latn": latn, "shaw": shaw} for latn, shaw in keys]


def predict_gated(items, model, src_vocab, tgt_vocab):
    """(latn, shaw) -> (ipa, confidence) for pairs passing BOTH voter gates."""
    predictions = predict_batch(model, src_vocab, tgt_vocab, items,
                                with_shaw=True, device="cpu")
    likelihoods = score_candidates(
        model, src_vocab, tgt_vocab,
        [{**item, "ipa": ipa} for item, ipa in zip(items, predictions)],
        with_shaw=True, device="cpu")

    gate_stats = Counter()
    filled = {}
    for item, ipa, likelihood in zip(items, predictions, likelihoods):
        try:
            round_trip = shaw_clean(ipa_to_shavian(ipa))
        except Exception:
            # The converter refusing the prediction IS a voter rejection.
            gate_stats["convert_error"] += 1
            continue
        if round_trip != item["shaw"]:
            gate_stats["roundtrip_mismatch"] += 1
            continue
        confidence = _confidence_for(likelihood)
        if confidence is None:
            gate_stats["low_likelihood"] += 1
            continue
        gate_stats["confident" if confidence == CONF_CONFIDENT
                   else "marginal"] += 1
        filled[(item["latn"], item["shaw"])] = (ipa, confidence)
    return filled, gate_stats


def fill_supplement(supplement, filled, stats):
    for records in supplement.values():
        for record in records:
            if "ipa" in record:
                continue
            key = (record["Latn"].lower(), shaw_clean(record["Shaw"]))
            hit = filled.get(key)
            if hit is None:
                continue
            ipa, confidence = hit
            record["ipa"] = ipa
            record["ipa_source"] = "model-g2p"
            record["confidence"] = confidence
            stats["filled"] += 1


def report(stats, gate_stats, n_inputs):
    print("\n=== Neural G2P generated IPA fill report ===")
    print(f"Unique (word, shaw) inputs offered:  {n_inputs:,}")
    print(f"  passed both gates (confident):     {gate_stats['confident']:,}")
    print(f"  passed both gates (marginal):      {gate_stats['marginal']:,}")
    print(f"  rejected: round-trip mismatch:     {gate_stats['roundtrip_mismatch']:,}")
    print(f"  rejected: low likelihood:          {gate_stats['low_likelihood']:,}")
    print(f"  rejected: converter error:         {gate_stats['convert_error']:,}")
    print(f"Records filled:                      {stats['filled']:,}")
    print(f"Records skipped (OOV charset):       {stats['skipped_oov_charset']:,}")
    if stats["already_has_ipa"]:
        print(f"Untouched (already had ipa):         {stats['already_has_ipa']:,}")


def main():
    for artifact in (MODEL_DIR / "model.pt", MODEL_DIR / "meta.json"):
        if not artifact.exists():
            print(f"ERROR: frozen G2P artifact missing: {artifact}",
                  file=sys.stderr)
            sys.exit(1)

    model, src_vocab, tgt_vocab, meta = load_model(MODEL_DIR, device="cpu")
    if not meta.get("with_shaw"):
        print("ERROR: data/g2p-model is not the Latin+Shavian model "
              "(meta.with_shaw is false)", file=sys.stderr)
        sys.exit(1)

    with open(GENERATED_INPUT, encoding="utf-8") as f:
        supplement = json.load(f)

    stats = Counter()
    items = gather_inputs(supplement, stats)
    filled, gate_stats = predict_gated(items, model, src_vocab, tgt_vocab)
    fill_supplement(supplement, filled, stats)

    with open(GENERATED_IPA_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(supplement, f, ensure_ascii=False, indent=4)
    print(f"Wrote {GENERATED_IPA_OUTPUT.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in supplement.values()):,} records")

    report(stats, gate_stats, len(items))


if __name__ == "__main__":
    main()
