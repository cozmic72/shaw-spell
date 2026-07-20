#!/usr/bin/env python3
"""
Flag divergent-from-canonical supplement records as `variant`.

Per (word, pos) group, establish the CANONICAL RRP spelling, then flag every
record whose Shavian DIVERGES from that canonical (and has the canonical present
to contrast against) with the additive boolean `variant`. This is the settled
half of the dialect model: WHICH specific merger a divergent record reflects
(cot-caught / lot-palm direction, one-vs-two) is still frozen/unresolved (see
memory merger-direction-unsettled), but "this record is a non-canonical variant
spelling" is decidable now. The schema carries `variant` and a `mergers` flag
independently (additive booleans/lists), so a record may hold both — this stage
never touches `mergers`, and applying `variant` loses nothing.

THE CANONICAL-SELECTION RULE (per word_lower + pos, EXACTLY):

  1. ReadLex/upstream attests a base-RRP spelling for (word, pos)  → that IS the
     canonical (always trusted — it is real, sanctioned data). If ReadLex attests
     SEVERAL distinct base-RRP spellings, there is no single canonical, so this
     word gets NO flags (we never pick one attested spelling over another).
  2. ELSE the pool has EXACTLY ONE distinct RRP-var spelling for (word, pos) AND
     that sole specimen is HIGH-CONFIDENCE (rrp_tier A or B — a clean RRP pass;
     see below)  → that specimen IS the canonical. (CONFIDENCE-GATED fallback: a
     low-confidence lone RRP spelling is NOT trusted as canonical, because every
     other record's variant decision would be anchored on a possibly-bad generated
     spelling.)
  3. ELSE (no ReadLex base-RRP; AND either the pool has MULTIPLE competing RRP
     spellings, or the lone RRP specimen is low-confidence)  → NO safe canonical
     can be anchored  → this word gets NO variant flags at all.

  A "base-RRP" ReadLex entry is var=RRP carrying NEITHER `mergers` NOR `variant`
  (a reinterpreted TrapBath is a merged 𐑨 form; an RRPVar is itself a variant —
  neither is the canonical it would be measured against). "RRP-var specimen" in
  the pool = a supplement record with var=="RRP".

CONFIDENCE TEST + THRESHOLD (reported): rrp_tier from the RRP reclassifier
(reclassify_rrp / rrp_classifier). Tier A = a clean RRP pass with 2+ witnesses,
B = a clean RRP pass; both are the "passes cleanly as RRP" tiers. C is
pass-AFTER-respell (a rewritten spelling — not trusted to define the canonical),
D..F are merger/stay/review. THRESHOLD: tier in {A, B} = high-confidence. A
record with no rrp_tier (STAY residue, merger-held-back) is NOT high-confidence.

THEN, per record in the group (once a canonical is fixed):
  a. record.shaw == canonical                              → NO flag.
  b. record.shaw != canonical, NO contrasting canonical    → NO flag (isolated
     sibling present in the group AND not ReadLex-attested    sample: nothing to
                                                              vary from).
  c. record.shaw != canonical AND a contrasting canonical  → set variant=True
     sibling exists (the canonical spelling is present         (this record IS
     among the group's records, OR is ReadLex-attested)        the variant).

The canonical spelling's OWN record (case a) is never flagged. A record that is
merely different but ISOLATED — the only spelling of its (word, pos), no canonical
counterpart present — is never flagged (isolated-sample guard). This mirrors the
governing rule the owner set for mergers (anchor to canonical; same=no flag,
different-with-contrast=variant, isolated=no flag).

TRAP-BATH INTERACTION: this stage reads but never writes `mergers`; a trap-bath
record (mergers=[trap-bath]) is judged for `variant` by the SAME rule as any other
record — if it diverges from a present RRP canonical it gains `variant` ALONGSIDE
its existing trap-bath flag (owner: both may coexist, additive). trap-bath's own
detection/flagging is untouched. The disabled cot-caught / lot-palm mergers are
irrelevant here (this stage never consults MERGER_SWAPS).

COUNT-PRESERVING: only ADDS the boolean `variant` to some records; never drops,
splits, merges, or re-buckets. The orchestrator's count guard must pass unchanged.
DETERMINISTIC: a pure function of the pool + upstream (no shave, no randomness).
NEVER writes the patch store; every flagged record is an unreviewed review
candidate (never-auto-accept).

PIPELINE PLACEMENT: runs AFTER collapse_identical_dialects (so the pool is already
spelling-deduplicated and carries the reclassifier's var=RRP labels + rrp_tier)
and before the contamination/phrase prunes:

  ... -> reclassify_rrp -> generate_rrp -> collapse -> HERE (variant-flagged) ->
  decontaminate -> filter -> basis

Inputs:  data/supplement-combined-collapsed.json
Outputs: data/supplement-combined-varflagged.json

Usage:
    python3 src/tools/flag_variants.py
"""

import json
from collections import Counter, defaultdict

from basis import PROJECT_ROOT, is_upstream, load_upstream

INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-collapsed.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-varflagged.json"

# The canonical dialect label. Only var==RRP records are candidate canonicals
# (ReadLex base-RRP) or fallback specimens (a lone high-confidence RRP pool form).
CANONICAL_VAR = "RRP"

# The rrp_tier values that count as HIGH-CONFIDENCE for the lone-specimen fallback
# (rule 2). A = clean RRP pass w/ 2+ witnesses, B = clean RRP pass. C (respell),
# D/E/F and absent (STAY residue, merger-held-back) are NOT trusted to DEFINE the
# canonical a whole word's variant decisions anchor on.
HIGH_CONFIDENCE_TIERS = frozenset({"A", "B"})

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def readlex_canonicals(upstream):
    """(word_lower, pos) -> the set of base-RRP Shavian spellings ReadLex attests.

    A base-RRP entry is var==RRP carrying NEITHER a merger flag NOR the variant
    flag: a reinterpreted TrapBath entry is the merged 𐑨 form, and an RRPVar entry
    is itself a within-RRP alternate — neither is the canonical a divergent record
    is measured against, so both are excluded. (load_upstream has already
    reinterpreted TrapBath -> mergers=[trap-bath] and RRPVar -> variant=True, so
    the exclusion is a simple flag check.)"""
    index = defaultdict(set)
    for entries in upstream.values():
        for entry in entries:
            if entry.get("var") != CANONICAL_VAR:
                continue
            if entry.get("mergers") or entry.get("variant"):
                continue
            key = (entry.get("Latn", "").lower(), entry.get("pos", ""))
            index[key].add(entry.get("Shaw", ""))
    return index


def canonical_for_group(word_lower, pos, records, readlex_index):
    """The single canonical RRP spelling for (word_lower, pos), or None if no safe
    canonical can be anchored. Implements the three-part rule (see module docstring):

      1. ReadLex attests EXACTLY ONE base-RRP spelling -> that spelling.
         (ReadLex attesting several distinct base-RRP spellings is ambiguous ->
         None: we never pick one sanctioned spelling over another.)
      2. else the pool holds EXACTLY ONE distinct RRP-var spelling AND it is
         high-confidence (rrp_tier A/B on any record carrying it) -> that spelling.
      3. else -> None (no ReadLex + competing pool candidates, or a lone low-conf
         specimen -> unsafe to anchor)."""
    attested = readlex_index.get((word_lower, pos))
    if attested:
        # ReadLex is always trusted — but only a SINGLE attested spelling gives an
        # unambiguous canonical. Several distinct RRP spellings upstream = no one
        # canonical to anchor on.
        return next(iter(attested)) if len(attested) == 1 else None

    # No ReadLex base-RRP: the confidence-gated pool fallback. Collect the distinct
    # RRP-var spellings present in the group, and whether each is high-confidence.
    # An upstream core record in the group is skipped: ReadLex's attestation was
    # already consulted through readlex_index (rule 1 — built from the same
    # upstream data), and a core exception form (a reinterpreted TrapBath/RRPVar
    # carries var=RRP too) must not masquerade as a pool RRP specimen.
    rrp_spellings = defaultdict(bool)  # shaw -> any high-confidence witness seen
    for r in records:
        if is_upstream(r) or r.get("var") != CANONICAL_VAR:
            continue
        shaw = r.get("Shaw", "")
        if r.get("rrp_tier") in HIGH_CONFIDENCE_TIERS:
            rrp_spellings[shaw] = True
        else:
            rrp_spellings.setdefault(shaw, False)

    if len(rrp_spellings) != 1:
        return None  # zero, or multiple competing RRP candidates -> no anchor
    (sole_shaw, high_conf), = rrp_spellings.items()
    return sole_shaw if high_conf else None


def flag_group(word_lower, pos, records, readlex_index, tallies, samples):
    """Set `variant` on each record of a (word_lower, pos) group that diverges from
    the group's canonical AND has that canonical present to contrast against.
    Returns new record copies (never mutates input). Count-preserving."""
    canonical = canonical_for_group(word_lower, pos, records, readlex_index)
    readlex_attested = bool(readlex_index.get((word_lower, pos)))

    # A contrasting canonical sibling exists if the canonical spelling is present
    # among THIS group's records, or ReadLex attests it. Without a canonical at all
    # (rule 3) there is nothing to vary from, so no record is flagged.
    pool_spellings = {r.get("Shaw", "") for r in records}
    contrast_present = canonical is not None and (
        canonical in pool_spellings or readlex_attested)

    out = []
    for entry in records:
        record = dict(entry)
        if is_upstream(entry):
            # Core is never flagged: its variant marker (the reinterpreted
            # RRPVar) is ReadLex's own data, and a core GenAm/RSSB exception
            # diverging from the RRP canonical is a dialect fact, not a
            # free-variation alternate. Pass through verbatim.
            tallies["upstream"] += 1
        elif canonical is None:
            tallies["no-canonical"] += 1
        elif record.get("Shaw", "") == canonical:
            tallies["is-canonical"] += 1
        elif not contrast_present:
            tallies["isolated"] += 1
        else:
            already = bool(record.get("variant"))
            record["variant"] = True
            tallies["flagged"] += 1
            if record.get("mergers"):
                tallies["flagged-with-merger"] += 1
            if not already and len(samples["flagged"]) < SAMPLE_LIMIT:
                samples["flagged"].append((record, canonical))
        out.append(record)
    return out


def flag_supplement(supplement, tallies, samples, upstream=None):
    """A copy of the supplement dict with `variant` set on every divergent-from-
    canonical record. Records are grouped by (word_lower, pos) — the same grouping
    the merger classifier uses — because the canonical and its contrast live within
    one (word, pos). `upstream` (reinterpreted ReadLex) is threaded by the
    orchestrator; None loads it. Count-preserving: buckets and record count are
    untouched; only the `variant` field is added."""
    if upstream is None:
        upstream = load_upstream()
    readlex_index = readlex_canonicals(upstream)

    # Group the pool's records by (word_lower, pos), tagging each with its exact
    # SLOT (bucket_key, index within the bucket) so the flagged copy can be scattered
    # back to precisely where it came from — output bucketing and order are the input's
    # (count-preserving), with no reliance on object identity.
    result = {key: [None] * len(entries) for key, entries in supplement.items()}
    groups = defaultdict(list)  # (word_lower, pos) -> [(bucket_key, idx, record), ...]
    for bucket_key, entries in supplement.items():
        for idx, entry in enumerate(entries):
            gkey = (entry.get("Latn", "").lower(), entry.get("pos", ""))
            groups[gkey].append((bucket_key, idx, entry))

    for (word_lower, pos), items in groups.items():
        records = [entry for _bucket, _idx, entry in items]
        flagged = flag_group(word_lower, pos, records, readlex_index,
                             tallies, samples)
        for (bucket_key, idx, _entry), new_record in zip(items, flagged):
            result[bucket_key][idx] = new_record
    return result


def report(tallies, samples):
    print("\n=== variant flagging report ===")
    total = (tallies["flagged"] + tallies["is-canonical"] +
             tallies["isolated"] + tallies["no-canonical"] +
             tallies["upstream"])
    print(f"Records processed:        {total:,}")
    print(f"  upstream (exempt):      {tallies['upstream']:,}")
    print(f"  variant flagged:        {tallies['flagged']:,}")
    print(f"    (also merger-flagged: {tallies['flagged-with-merger']:,})")
    print(f"  is the canonical:       {tallies['is-canonical']:,}")
    print(f"  isolated (no contrast): {tallies['isolated']:,}")
    print(f"  no safe canonical:      {tallies['no-canonical']:,}")

    print("\nSample [variant flagged] (record -> canonical it varies from):")
    for record, canonical in samples["flagged"]:
        cps = " ".join(f"U+{ord(c):04X}" for c in record.get("Shaw", ""))
        merger = f" mergers={record['mergers']}" if record.get("mergers") else ""
        print(f"  {record['Latn']} [{record.get('pos','')}] {record.get('var','')}"
              f" {record['Shaw']} ({cps}){merger} -> canonical {canonical}")


def main():
    tallies = Counter()
    samples = defaultdict(list)

    supplement = load_json(INPUT_PATH)
    n_in = sum(len(v) for v in supplement.values())
    flagged = flag_supplement(supplement, tallies, samples)
    n_out = sum(len(v) for v in flagged.values())
    if n_out != n_in:
        raise SystemExit(
            f"flag_variants: record count changed ({n_in} -> {n_out}); this stage "
            f"only ADDS the variant flag — it never drops or splits a record, so a "
            f"count change is a bug")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(flagged, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: {n_out:,} records, "
          f"{tallies['flagged']:,} variant-flagged")

    report(tallies, samples)


if __name__ == "__main__":
    main()
