#!/usr/bin/env python3
"""
RRP reclassifier: canonicalize supplement candidates toward RRP.

This is Shaw-Spell Goal 1 (shaw-spell-goals): expand the dictionary with
CONFORMAL, CANONICAL entries. RRP is ReadLex's de-facto canonical dialect
label, so a candidate — sourced as RSSB or GenAm — whose Shavian spelling is
what the Guide's stress-based rules would sanction as the RRP default IS an
RRP entry, and is relabelled as one. A candidate the rules will NOT allow to be
RRP stays in its source dialect (the honest residue). See the rrp_classifier
module for the accent-agnostic "does this pass as RRP?" decision procedure.

WHAT THIS STAGE DOES (and, deliberately, what it does NOT):

  PASS          -> relabel var to RRP; record orig_var (pre-relabel var).
  PASS_RESPELL  -> respell Shaw to the classifier's deterministic, Guide-table-
                   backed spelling AND relabel var to RRP; record orig_shaw and
                   orig_var. A changed spelling correctly re-enters review.
  STAY          -> leave the record untouched (RSSB/GenAm stays). The rules will
                   not canonicalize it (e.g. CURE lowered to FORCE).
  REVIEW        -> leave the record's spelling/var untouched but mark it for
                   review (the classifier could not judge it — a stress-gated
                   site, a neutral-vowel violation, a structural oddity).

  merger-flagged records are NEVER relabelled — see below.

⚠ RRP-LANE OCCUPANCY GUARD. A PASS / PASS_RESPELL is only APPLIED if the
(word_lower, pos) group's RRP lane is free for the candidate's resulting
spelling. The lane is seeded PURELY from the input pool's RRP-labelled records
(born-RRP, var==RRP — which, once ReadLex core is collated into the pool at
combine time, includes the pre-accepted core canonical spellings) and extended
by each promotion this stage itself applies. A candidate
whose resulting RRP spelling DIFFERS from an occupied lane spelling is NOT
promoted — it stays in its source dialect entirely untouched (var, Shaw, no
orig_*), recorded as rrp_outcome=SKIP_OCCUPIED. A candidate whose resulting
spelling is IDENTICAL to an occupied one still relabels as before — the
downstream collapse stage owns same-spelling dedup. When a group has no native
RRP and several differently-spelt candidates pass, the winner is chosen by a
deterministic tie-break — best tier first, then Shaw — and the rest stay in
their source dialect.

Every relabelled/respelled record is an UNREVIEWED REVIEW CANDIDATE — nothing
is auto-accepted, nothing is written to the patch store (never-auto-accept).
The stage also carries a small provenance triple onto every judged record so
the editor can surface + sort the review pool:

  rrp_outcome   PASS | PASS_RESPELL | STAY | REVIEW  (SKIP_MERGER on a flagged
                record — judged but held back, see below)
  rrp_tier      A..F (the classifier's confidence tier)
  rrp_review    present (True) only on REVIEW records — a filterable flag

SCOPE BOUNDARIES (owner-corrected — do NOT exceed; see rrp-classifier-phase0):
  - This is a PASS / no-pass-as-RRP JUDGE. It does NOT collapse-with-deletion,
    does NOT flag variants, does NOT flag mergers. Those are the DOWNSTREAM
    merger/variant tagging stages. A GenAm candidate spelt DIFFERENTLY from its
    RRP form is left as GenAm — no collapse here.
  - Only the PER-RECORD judgment (rrp_classifier.judge_record) is applied. The
    group-level collapse/variant taxonomy (judge_group / apply_group_to_records,
    which computes ABSORB / collapse-pair / national-pair) is the downstream
    stage's concern and is NOT run here. So no candidate is ever dropped or
    absorbed by this stage — every input record appears in the output.

⚠ MERGER-FLAGGED RECORDS ARE HELD BACK (the ordering constraint). A merged form
(GenAm 𐑪 for cot-caught, 𐑨 for trap-bath) is, by definition, spelt DIFFERENTLY
from its non-merged RRP sibling — so per the owner's simple-collapse rule it must
STAY in its source dialect, not be relabelled RRP. But judge_record judges a
record in ISOLATION: the merged 𐑪-spelling of one word is a structurally valid
RRP spelling of some other, so it would PASS and be wrongly canonicalized to RRP
— which also erases the very merger relationship the (already-run) merger
classifier detected. So this stage runs AFTER classify_dialect_mergers and NEVER
relabels a record carrying a `mergers` flag: a merger-flagged record is passed
through untouched (recorded as rrp_outcome=SKIP_MERGER for visibility). This is
the ONLY reliable point to make the "spelt differently -> keep as source dialect"
call, because the merger flag is exactly the "spelt differently as a known merger"
signal, and it exists only after the merger stage. (Verified: reclassify-BEFORE-
merger collapses merged forms to RRP and destroys attestation — 2,629 tags -> 3.)

DETERMINISM: the classifier is a pure, shave-free function of the record, so
this stage is byte-deterministic run-to-run on identical input. shave is NOT
consulted (in the classifier it is only a tier-A/B witness); dropping it costs
only that nuance and buys the determinism the patch model requires — a
non-deterministic respell would orphan the owner's accept/flag patches on every
rebuild (shave-nondeterminism).

PIPELINE PLACEMENT: reclassify runs on the merger-classified, source-combined
pool, canonicalizing every non-merger candidate the rules allow while leaving
merged forms (and their flags) intact for the downstream identical-dialect
collapse.

  combine -> defs -> dedup -> classify_mergers -> HERE (reclassified) ->
  collapse -> decontaminate -> filter -> basis

Inputs:  data/supplement-combined-classified.json
Outputs: data/supplement-combined-reclassified.json

Usage:
    python3 src/tools/reclassify_rrp.py
"""

import json
from collections import Counter, defaultdict

from basis import PROJECT_ROOT, is_upstream, mark_original
from rrp_classifier import judge_record

INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-classified.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-reclassified.json"

# The canonical dialect label a passing candidate is relabelled onto.
CANONICAL_VAR = "RRP"

# The rrp_outcome recorded for a merger-flagged record held back from
# relabelling — a merged form spelt differently from its non-merged RRP sibling
# (see the module docstring's MERGER-FLAGGED section).
MERGER_HELD_BACK = "SKIP_MERGER"

# The rrp_outcome recorded for a passing candidate DENIED relabelling because
# the (word, pos) RRP lane is already occupied by a DIFFERENT spelling (see the
# module docstring's RRP-LANE OCCUPANCY GUARD section).
LANE_HELD_BACK = "SKIP_OCCUPIED"

# Judgment sentinel for an upstream ReadLex record in the pool: core IS the lane,
# never a candidate. It is not judged, not relabelled, not respelled, and not
# even decorated with rrp_* provenance — it passes through verbatim, while its
# var==RRP spellings seed the occupancy lanes by pure existence.
UPSTREAM_LANE = object()

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def output_bucket_key(entry):
    """The `word_pos_shaw` JSON key a supplement file buckets records under. A
    PASS_RESPELL changes Shaw, so the re-bucketing must use the NEW spelling."""
    return f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"


def cross_dialect_set(records):
    """(word_lower, pos, shaw) attested by 2+ distinct vars — the deterministic
    cross-dialect witness, computed from THIS stage's own input pool (a witness
    only raises the tier; it never changes an outcome or a respell)."""
    seen = defaultdict(set)
    for r in records:
        seen[(r["Latn"].lower(), r.get("pos", ""), r["Shaw"])].add(r.get("var"))
    return {k for k, vars_ in seen.items() if len(vars_) >= 2}


def promoted_shaw(entry, judgment):
    """The Shaw a PASS / PASS_RESPELL candidate would occupy the RRP lane with."""
    return judgment.respell if judgment.outcome == "PASS_RESPELL" else entry["Shaw"]


def blocked_promotions(judged):
    """Indexes into `judged` of PASS / PASS_RESPELL candidates whose promotion
    the lane-occupancy guard DENIES: the (word_lower, pos) RRP lane already
    holds a DIFFERENT spelling. Lanes are seeded PURELY from the input pool's
    RRP-labelled records (which, once ReadLex core is collated into the pool at
    combine time, include the pre-accepted core canonical spellings as well as
    supplement-native RRP entries); within a group, promotable candidates claim
    the lane in a deterministic order — best tier first, then Shaw — so the
    winner of a lane-free group is byte-stable run-to-run (the patch model
    requires it). An identically-spelt candidate is never blocked (downstream
    collapse owns same-spelling dedup). RRP records already in the pool are not
    guarded — they are the lane, not a promotion into it."""
    lanes = defaultdict(set)
    for entry, _ in judged:
        if entry.get("var") == CANONICAL_VAR:
            lanes[(entry["Latn"].lower(), entry.get("pos", ""))].add(entry["Shaw"])

    groups = defaultdict(list)
    for i, (entry, judgment) in enumerate(judged):
        if (judgment is not None and judgment is not UPSTREAM_LANE
                and judgment.outcome in ("PASS", "PASS_RESPELL")
                and entry.get("var") != CANONICAL_VAR):
            groups[(entry["Latn"].lower(), entry.get("pos", ""))].append(
                (judgment.tier, promoted_shaw(entry, judgment), i))

    blocked = set()
    for key, candidates in groups.items():
        occupied = lanes[key]
        for _, shaw, i in sorted(candidates):
            if occupied and shaw not in occupied:
                blocked.add(i)
            else:
                occupied.add(shaw)
    return blocked


def reclassify_record(entry, judgment, lane_blocked, tallies, samples):
    """A copy of one candidate with the reclassifier's per-record verdict applied.

    A merger-flagged record (judgment None) is held back untouched (it is spelt
    differently from its RRP sibling — the downstream collapse owns it), as is a
    lane-blocked one (its resulting RRP spelling conflicts with the group's
    occupied RRP lane — it stays in its source dialect). Otherwise PASS /
    PASS_RESPELL relabel var to RRP (and, for a respell, rewrite Shaw), recording
    the pre-transform value(s) via mark_original so the applicator can
    auto-re-anchor an editorial patch anchored to the old key. STAY and REVIEW
    leave the spelling and var untouched. Every judged record carries the
    rrp_outcome / rrp_tier provenance; REVIEW additionally carries rrp_review.
    An upstream ReadLex record (judgment UPSTREAM_LANE) passes through VERBATIM —
    no relabel, no respell, not even rrp_* provenance: core is the pre-accepted
    lane the guard protects, never a review candidate."""
    record = dict(entry)

    if judgment is UPSTREAM_LANE:
        tallies["upstream-lane"] += 1
        return record

    if judgment is None:
        # A merged form is spelt differently from its non-merged RRP sibling:
        # never canonicalize it here (that would both violate "don't collapse
        # differently-spelt forms" and erase the merger attestation). Held back —
        # its spelling/var are untouched.
        record["rrp_outcome"] = MERGER_HELD_BACK
        tallies[MERGER_HELD_BACK] += 1
        return record

    j = judgment

    if lane_blocked:
        # The guard denied the promotion: the record stays in its source dialect
        # entirely untouched (no relabel, no respell, no orig_*).
        record["rrp_outcome"] = LANE_HELD_BACK
        record["rrp_tier"] = j.tier
        tallies[LANE_HELD_BACK] += 1
        return record

    record["rrp_outcome"] = j.outcome
    record["rrp_tier"] = j.tier
    tallies[j.outcome] += 1

    if j.outcome in ("PASS", "PASS_RESPELL"):
        old_var = record.get("var", "")
        if j.outcome == "PASS_RESPELL":
            # A deterministic, Guide-table-backed respell (never shave). Rewrite
            # the spelling, then record the pre-respell Shaw so a patch anchored
            # to it re-anchors rather than orphaning.
            old_shaw = record["Shaw"]
            record["Shaw"] = j.respell
            mark_original(record, "shaw", old_shaw)
        record["var"] = CANONICAL_VAR
        mark_original(record, "var", old_var)
        tallies[f"relabelled-from-{old_var}"] += 1
        if old_var != CANONICAL_VAR and len(samples[j.outcome]) < SAMPLE_LIMIT:
            samples[j.outcome].append((entry, record))
    elif j.outcome == "REVIEW":
        record["rrp_review"] = True
    # STAY: untouched but for the rrp_outcome/rrp_tier provenance.

    return record


def reclassify_supplement(supplement, tallies, samples):
    """A copy of the supplement dict with every candidate reclassified. Records
    are re-bucketed by (word, pos, shaw) because a PASS_RESPELL changes the shaw
    the bucket key encodes. Nothing is dropped: every input record appears once
    in the output (this stage judges + relabels, it never collapses)."""
    records = [r for entries in supplement.values() for r in entries]
    ctx = {"cross_dialect": cross_dialect_set(records), "shave": {}}

    # Judge first (upstream core and merger-flagged records are held back
    # unjudged — core is the lane, a merged form stays in its dialect), then
    # resolve RRP-lane occupancy across each (word, pos) group, then apply.
    judged = [(r, UPSTREAM_LANE if is_upstream(r)
               else None if r.get("mergers") else judge_record(r, ctx))
              for r in records]
    blocked = blocked_promotions(judged)

    reclassified = defaultdict(list)
    for i, (entry, judgment) in enumerate(judged):
        out = reclassify_record(entry, judgment, i in blocked, tallies, samples)
        reclassified[output_bucket_key(out)].append(out)

    return {key: reclassified[key] for key in sorted(reclassified)}, len(records)


def report(tallies, samples):
    print("\n=== RRP reclassification report ===")
    total = sum(tallies[o] for o in ("PASS", "PASS_RESPELL", "STAY", "REVIEW",
                                     MERGER_HELD_BACK, LANE_HELD_BACK))
    print(f"Records judged:            {total:,}")
    print(f"  PASS (relabel RRP):      {tallies['PASS']:,}")
    print(f"  PASS_RESPELL (+respell): {tallies['PASS_RESPELL']:,}")
    print(f"  STAY (source dialect):   {tallies['STAY']:,}")
    print(f"  REVIEW (flagged):        {tallies['REVIEW']:,}")
    print(f"  SKIP (merger-flagged):   {tallies[MERGER_HELD_BACK]:,}")
    print(f"  PASS blocked (RRP lane occupied): {tallies[LANE_HELD_BACK]:,}")
    print(f"  upstream core (the lane; passed through verbatim): "
          f"{tallies['upstream-lane']:,}")
    relabelled = tallies["PASS"] + tallies["PASS_RESPELL"]
    print(f"Relabelled to RRP:         {relabelled:,}")
    for src in ("RSSB", "GenAm", "RRP"):
        n = tallies.get(f"relabelled-from-{src}", 0)
        print(f"    from {src:5}:            {n:,}")

    for outcome in ("PASS", "PASS_RESPELL"):
        if not samples[outcome]:
            continue
        print(f"\nSample [{outcome}] (source -> RRP):")
        for before, after in samples[outcome]:
            respell = (f"  {before['Shaw']} -> {after['Shaw']}"
                       if outcome == "PASS_RESPELL" else "")
            print(f"  {before['Latn']} [{before.get('pos', '')}]: "
                  f"{before.get('var', '')} -> {after['var']} "
                  f"[{after['rrp_tier']}]{respell}")


def main():
    tallies = Counter()
    samples = defaultdict(list)

    supplement = load_json(INPUT_PATH)
    reclassified, n_in = reclassify_supplement(supplement, tallies, samples)
    n_out = sum(len(v) for v in reclassified.values())
    if n_out != n_in:
        raise SystemExit(
            f"reclassify_rrp: record count changed ({n_in} -> {n_out}); this "
            f"stage relabels but never drops or merges — a count change is a bug")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(reclassified, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: {n_out:,} records")

    report(tallies, samples)


if __name__ == "__main__":
    main()
