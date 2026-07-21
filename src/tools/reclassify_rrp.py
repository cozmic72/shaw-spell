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

⚠ SOURCE-VAR PROMOTION RULE (the owner's dialect-promotion rule). Passing is
necessary but not sufficient: WHICH source vars may promote is gated too.
RSSB always promotes (within-British). GenAm and the other national accents
promote ONLY when a pre-existing RRP record spells the same word with the same
Shaw in another pos — otherwise they are NOT promoted and keep their source
var (SKIP_NONBRITISH). See PROMOTABLE_VARS / may_promote for the full
rationale. At most one candidate promotes onto a given (word, pos, Shaw)
anchor (national_overpromotions): a held twin folds onto the promoted record
downstream instead of minting a duplicate RRP anchor.

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

# WHICH source vars may promote to RRP (the owner's dialect-promotion rule).
# RSSB is rhotic-restored unconfirmed British, so canonicalizing it to RRP is a
# same-accent move that cannot smuggle in a foreign vowel — it ALWAYS may
# promote. GenAm and the harvested national accents (GenAus/GenCan/NZ/SthAfr/
# IrEng) are DIFFERENT accents: the classifier judges a spelling's structural
# RRP-plausibility against the record's OWN ipa, but that ipa is the source
# accent's — so a faithful transcription of a GenAm vowel (e.g. oddball
# /ˈɑːdˌbɒl/ -> 𐑭𐑛𐑚𐑪𐑤, "ahdball" to a British ear) PASSes structurally yet is no
# RP spelling. So a national-accent candidate promotes ONLY when a pre-existing
# RRP record already spells the SAME word with the SAME resulting Shaw in
# ANOTHER pos (rrp_sibling_pos_index / may_promote): RP itself vouches for the
# spelling, so extending it to this pos invents nothing. With no such sibling
# the candidate is NOT promoted — it keeps its source var, recorded as
# SKIP_NONBRITISH. (A same-pos same-Shaw RRP twin is deliberately NOT a voucher:
# promoting onto it would mint a duplicate RRP anchor — the downstream collapse
# stage instead FOLDS that candidate onto the existing RRP record, which is the
# same-spelling promotion path for the same-pos case.)
PROMOTABLE_VARS = {"RSSB", CANONICAL_VAR}
NONBRITISH_HELD_BACK = "SKIP_NONBRITISH"

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


def rrp_sibling_pos_index(records):
    """(word_lower, Shaw) -> set of pos carried by the INPUT pool's RRP-labelled
    records (upstream core and born-RRP supplement records alike) — the
    pre-existing RRP spellings that can vouch for a national-accent candidate
    (see PROMOTABLE_VARS). Seeded purely from the input pool, never extended by
    this stage's own promotions: a promotion cannot vouch for another."""
    idx = defaultdict(set)
    for r in records:
        if r.get("var") == CANONICAL_VAR:
            idx[(r["Latn"].lower(), r["Shaw"])].add(r.get("pos", ""))
    return idx


def may_promote(entry, judgment, rrp_siblings):
    """Whether a PASS / PASS_RESPELL candidate's SOURCE var is allowed to promote
    to RRP. A within-British source (PROMOTABLE_VARS) always may. A national-
    accent source may only when a pre-existing RRP record spells the same word
    with the same resulting Shaw in ANOTHER pos — and none occupies THIS pos
    with that Shaw (then the collapse-stage fold owns the merge; promoting here
    would duplicate the anchor). See PROMOTABLE_VARS for the rationale."""
    if entry.get("var", "") in PROMOTABLE_VARS:
        return True
    poses = rrp_siblings.get(
        (entry["Latn"].lower(), promoted_shaw(entry, judgment)), ())
    return bool(poses) and entry.get("pos", "") not in poses


def national_overpromotions(judged, eligible):
    """Indexes to DROP from the eligible set so at most ONE candidate promotes
    onto any (word_lower, pos, resulting Shaw) anchor. Two eligible candidates
    landing on the same anchor would mint DUPLICATE RRP records: the downstream
    collapse folds a source-var record onto an identically-spelt RRP twin, but
    never merges two same-var RRP records. So within an anchor cell the
    within-British candidates win — if any RSSB candidate claims the anchor,
    every national-accent candidate is dropped (it keeps its source var and the
    collapse stage folds it onto the promoted twin, source-unioned — exactly
    the behaviour before the sibling rule existed). A cell holding only
    national candidates promotes exactly one — best tier, then var, then input
    order (byte-stable) — and the rest fold downstream. Within-British
    candidates are never dropped here (RSSB promotion is unchanged baseline
    behaviour; a same-pos born-RRP anchor already disqualified the national in
    may_promote)."""
    brit_anchors = set()
    cells = defaultdict(list)
    for i in sorted(eligible):
        entry, j = judged[i]
        var = entry.get("var", "")
        if var == CANONICAL_VAR:
            continue
        anchor = (entry["Latn"].lower(), entry.get("pos", ""),
                  promoted_shaw(entry, j))
        if var in PROMOTABLE_VARS:
            brit_anchors.add(anchor)
        else:
            cells[anchor].append((j.tier, var, i))

    drop = set()
    for anchor, cands in cells.items():
        keep = 0 if anchor in brit_anchors else 1
        for _, _, i in sorted(cands)[keep:]:
            drop.add(i)
    return drop


def blocked_promotions(judged, promotable):
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
    guarded — they are the lane, not a promotion into it. Only candidates in
    `promotable` (the source-var rule's yes-set, see may_promote) participate:
    a candidate whose source var may not promote can never occupy the lane, so
    it neither claims a spelling nor is counted blocked — it must not phantom-
    block a genuinely promotable sibling."""
    lanes = defaultdict(set)
    for entry, _ in judged:
        if entry.get("var") == CANONICAL_VAR:
            lanes[(entry["Latn"].lower(), entry.get("pos", ""))].add(entry["Shaw"])

    groups = defaultdict(list)
    for i in sorted(promotable):
        entry, judgment = judged[i]
        if entry.get("var") != CANONICAL_VAR:
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


def reclassify_record(entry, judgment, lane_blocked, promotable, tallies,
                      samples):
    """A copy of one candidate with the reclassifier's per-record verdict applied.

    A merger-flagged record (judgment None) is held back untouched (it is spelt
    differently from its RRP sibling — the downstream collapse owns it), as are
    one the source-var rule refuses (`promotable` False — a national-accent
    candidate with no same-spelling RRP sibling in another pos) and a
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

    # The source-var rule refused the promotion (a national-accent candidate
    # with no same-spelling RRP sibling in another pos — see PROMOTABLE_VARS /
    # may_promote): NOT promoted, the record keeps its source var. Recorded so
    # the editor can still surface "the rules judged this a valid RRP SHAPE".
    if j.outcome in ("PASS", "PASS_RESPELL") and not promotable:
        record["rrp_outcome"] = NONBRITISH_HELD_BACK
        record["rrp_tier"] = j.tier
        tallies[NONBRITISH_HELD_BACK] += 1
        tallies[f"held-nonbritish-{record.get('var', '')}"] += 1
        return record

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
    # apply the source-var promotion rule (may_promote), then resolve RRP-lane
    # occupancy across each (word, pos) group among the promotable, then apply.
    judged = [(r, UPSTREAM_LANE if is_upstream(r)
               else None if r.get("mergers") else judge_record(r, ctx))
              for r in records]
    rrp_siblings = rrp_sibling_pos_index(records)
    eligible = {i for i, (entry, j) in enumerate(judged)
                if j is not None and j is not UPSTREAM_LANE
                and j.outcome in ("PASS", "PASS_RESPELL")
                and may_promote(entry, j, rrp_siblings)}
    promotable = eligible - national_overpromotions(judged, eligible)
    blocked = blocked_promotions(judged, promotable)

    reclassified = defaultdict(list)
    for i, (entry, judgment) in enumerate(judged):
        out = reclassify_record(entry, judgment, i in blocked, i in promotable,
                                tallies, samples)
        reclassified[output_bucket_key(out)].append(out)

    return {key: reclassified[key] for key in sorted(reclassified)}, len(records)


def report(tallies, samples):
    print("\n=== RRP reclassification report ===")
    total = sum(tallies[o] for o in ("PASS", "PASS_RESPELL", "STAY", "REVIEW",
                                     MERGER_HELD_BACK, LANE_HELD_BACK,
                                     NONBRITISH_HELD_BACK))
    print(f"Records judged:            {total:,}")
    print(f"  PASS (relabel RRP):      {tallies['PASS']:,}")
    print(f"  PASS_RESPELL (+respell): {tallies['PASS_RESPELL']:,}")
    print(f"  STAY (source dialect):   {tallies['STAY']:,}")
    print(f"  REVIEW (flagged):        {tallies['REVIEW']:,}")
    print(f"  SKIP (merger-flagged):   {tallies[MERGER_HELD_BACK]:,}")
    print(f"  PASS blocked (RRP lane occupied): {tallies[LANE_HELD_BACK]:,}")
    print(f"  PASS not promoted (national accent, no same-spelling RRP sibling "
          f"in another pos): {tallies[NONBRITISH_HELD_BACK]:,}")
    for src in ("GenAm", "GenAus", "GenCan", "NZ", "SthAfr", "IrEng"):
        n = tallies.get(f"held-nonbritish-{src}", 0)
        if n:
            print(f"      {src:7}: {n:,}")
    print(f"  upstream core (the lane; passed through verbatim): "
          f"{tallies['upstream-lane']:,}")
    relabelled = tallies["PASS"] + tallies["PASS_RESPELL"]
    print(f"Relabelled to RRP:         {relabelled:,}")
    for src in ("RSSB", "GenAm", "GenAus", "GenCan", "NZ", "SthAfr", "IrEng",
                "RRP"):
        n = tallies.get(f"relabelled-from-{src}", 0)
        if n or src in ("RSSB", "GenAm", "RRP"):
            print(f"    from {src:6}:           {n:,}")

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
