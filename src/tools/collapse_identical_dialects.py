#!/usr/bin/env python3
"""
Collapse identical-spelling dialect variants of a supplement candidate down the
dialect hierarchy before the candidate reaches the editorial basis.

The merger classifier leaves a (word, pos) group carrying one record per
(dialect var, spelling). When two or more DIFFERENT dialects spell the word the
SAME way, that identical spelling is not a real dialect difference — it is the
same fact stated per dialect — so the group collapses onto the highest-precedence
dialect's var.

  RRP > RSSB > GenAm  (RRP highest; any other var ranks below GenAm)

  RSSB 𐑖𐑦𐑑𐑦 + GenAm 𐑖𐑦𐑑𐑦  -> one RSSB record (the GenAm is relabelled onto it)
  RRP + RSSB + GenAm (same shaw) -> one RRP record
  RSSB 𐑓𐑷𐑤𐑕 vs GenAm 𐑓𐑪𐑤𐑕 (different shaw) -> both kept (real difference)

RELABEL, don't drop. Because the pool is now source-combined (see
combine_supplements.py), a lower-precedence var and its higher-precedence twin
may come from DIFFERENT sources — e.g. wordnet's GenAm 𐑖𐑦𐑑𐑦 and wiktionary's
RSSB 𐑖𐑦𐑑𐑦. Dropping the loser would discard its source attestation. Instead
every record in a collapsing group is REWRITTEN to the winning var, then records
that now share the full anchor (word, pos, shaw, var) MERGE into one whose
`source` is the UNION of the merged records' source lists. So the multi-source
agreement signal survives the collapse rather than being thrown away.

  wordnet GenAm 𐑖𐑦𐑑𐑦 (source=[wordnet]) relabels to RSSB
  wiktionary RSSB 𐑖𐑦𐑑𐑦 (source=[wiktionary]) stays RSSB
  -> one RSSB 𐑖𐑦𐑑𐑦 record, source=[wordnet, wiktionary]

Payload tie-break when relabelled records merge: the record that was ALREADY the
winning var keeps its payload (ipa/freq/confidence/mergers/...); a record that
was merely relabelled contributes ONLY its source labels. If several records were
already the winning var (a genuine within-var duplicate), the first-seen keeps
the payload. The winning var's own record is the authentic spelling for that
accent, so its content — not a lower-precedence var's — is the one to keep.

The collapse is per distinct spelling within a (word.lower(), pos) group. Only a
spelling carried by 2+ distinct dialect vars collapses; a spelling unique to one
var is that var's own fact and is left alone. A spelling whose records disagree
on the additive `mergers` flag is NOT collapsed — a merger flag is a real
within-accent difference, so every record stays.

This stage is patch-unaware: it collapses purely on the dialect hierarchy. If a
lower-precedence var the owner anchored is relabelled away, its patch orphans and
apply_patches.py fails loud — that is intentional and handled downstream.

This is a pruning-chain stage between the RRP reclassifier and the contamination
filter: combined-reclassified -> HERE (collapsed) -> decontaminated -> filtered
-> basis. Downstream stages read the collapsed output verbatim.

Inputs:  data/supplement-combined-reclassified.json.
Outputs: data/supplement-combined-collapsed.json.

Usage:
    python3 src/tools/collapse_identical_dialects.py
"""

import json
from collections import Counter, defaultdict

from basis import PROJECT_ROOT, mark_original
from generate_wiktionary_supplement import KEEP_ACCENTS, UNTAGGED_VAR

# (generated input, collapsed output) — one combined pool. The RRP reclassifier
# then the RRP generator run immediately upstream: the reclassifier canonicalizes
# non-merger candidates to RRP, and the generator mints RRP proposals ALONGSIDE
# no-RRP candidates and gates merger/variant flags on canonical confidence (it
# adds proposal fields + strips gated flags, never changing a record's own Shaw or
# var). So a candidate the rules allowed and an original-RRP twin share the RRP var
# and this stage merges their identical spellings; the propose-alongside
# generated_* fields ride through on the winning-var payload.
INPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-generated.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-combined-collapsed.json"

# Dialect precedence: lower rank wins. Any var not listed ranks below every
# listed var (UNKNOWN_RANK), so it always loses an identical-spelling collision.
# This governs ONLY the flat spelling-collision collapse among the three legacy
# vars (see collapse_group). The multi-accent harvest vars are governed by the
# dialect HIERARCHY below, not by this flat precedence.
PRECEDENCE = {"RRP": 0, "RSSB": 1, "GenAm": 2}
UNKNOWN_RANK = len(PRECEDENCE)

# The three legacy vars the flat spelling-collision collapse operates on. A group
# with more than one of these carrying an identical spelling merges to the
# highest-precedence one (RRP > RSSB > GenAm), unioning sources — this preserves
# the combined-pool multi-source union (e.g. wordnet GenAm + wiktionary RSSB of
# the same spelling). The harvest accents are deliberately EXCLUDED so a harvest
# accent that legitimately diverges from its hierarchy parent is never merged away
# just because it happens to spell the same as a sibling legacy var.
COLLISION_VARS = frozenset(PRECEDENCE)

# ---------------------------------------------------------------------------
# DIALECT HIERARCHY (owner-authoritative). A harvested-accent record is kept only
# where its Shaw DIVERGES from its PARENT accent's Shaw within the same (word,pos)
# group; if it spells the word the same as its parent, that is not a dialect fact
# of its own — it inherits the parent — so the child record collapses (relabels)
# onto the nearest present ancestor.
#
#     GenCan -> GenAm -> RRP        (Canada inherits American, which inherits RP)
#     GenAus -> RRP
#     NZ     -> RRP
#     SthAfr -> RRP
#     IrEng  -> RRP
#     SSB    -> RRP                 (untagged "general British" bucket)
#     GenAm -> RRP                  (parent EDGE only; see below)
#
# RRP is the root (no parent — always kept). RSSB is deliberately NOT in the
# hierarchy: it is the reclassifier's "unresolved British" bucket, not a national
# accent, so it keeps its flat-precedence handling unchanged.
#
# GenAm is BOTH the parent of GenCan AND a member of the legacy flat-collapse set
# {RRP, RSSB, GenAm}. Its GenAm-vs-RRP collapse is the PRE-EXISTING behaviour of
# the flat stage (collapse_group) and must stay there unchanged — moving it into
# the hierarchy stage would reorder the flat stage's within-var duplicate merges
# and change which orig_var pre-image a patch re-anchors against. So the hierarchy
# stage READS GenAm's spellings (to judge GenCan) but never itself relabels a GenAm
# record: GenAm appears in PARENT purely as an edge target, and is EXCLUDED from
# HIERARCHY_COLLAPSE_VARS. The flat stage owns GenAm->RRP exactly as before.
PARENT = {
    "GenCan": "GenAm",
    "GenAus": "RRP",
    "NZ": "RRP",
    "SthAfr": "RRP",
    "IrEng": "RRP",
    UNTAGGED_VAR: "RRP",
    "GenAm": "RRP",  # edge only — GenAm is collapsed by the flat legacy stage
}
ROOT_VAR = "RRP"

# The vars the HIERARCHY stage actively relabels: the truly-new harvested accents.
# GenAm and RSSB are excluded — GenAm is owned by the flat legacy collapse (see
# above), RSSB is outside the hierarchy. A var here that equals its parent's Shaw
# is dropped/inherited; one that diverges is kept.
HIERARCHY_COLLAPSE_VARS = frozenset(set(PARENT) - COLLISION_VARS)

# Fail loud if a harvested accent exists that the hierarchy forgot to place: every
# KEEP_ACCENT (bar RRP root and the legacy-owned GenAm) and the untagged bucket
# MUST be collapsed by the hierarchy stage, or a divergent record of that accent
# would silently escape collapse.
_harvest_vars = {var for var, _sel, _ns in KEEP_ACCENTS
                 if var != ROOT_VAR and var not in COLLISION_VARS}
_harvest_vars.add(UNTAGGED_VAR)
_missing = _harvest_vars - HIERARCHY_COLLAPSE_VARS
if _missing:
    raise SystemExit(
        f"collapse_identical_dialects: harvested accents {sorted(_missing)} are "
        f"not in HIERARCHY_COLLAPSE_VARS — their divergent records would escape "
        f"the hierarchy collapse")
# GenCan's parent GenAm must be resolvable as a parent EDGE even though GenAm is
# not hierarchy-collapsed, or the GenCan-vs-GenAm comparison silently degrades.
if PARENT.get("GenCan") not in PARENT and PARENT.get("GenCan") != ROOT_VAR:
    raise SystemExit(
        "collapse_identical_dialects: GenCan's parent edge is unresolvable")

SAMPLE_LIMIT = 12


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def output_bucket_key(entry):
    """The `word_pos_shaw` JSON key a supplement file buckets records under."""
    return f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"


def mergers_of(entry):
    """The record's mergers as a hashable, order-independent signature."""
    return tuple(sorted(entry.get("mergers") or ()))


def var_rank(entry):
    """Precedence rank of a record's dialect var; unlisted vars rank lowest."""
    return PRECEDENCE.get(entry.get("var", ""), UNKNOWN_RANK)


def union_sources(into, extra):
    """Fold `extra` into `into` at a merge: append its source labels (deduped,
    order-stable) and OR its `has_definition` in. `has_definition` is a per-source
    provenance OR, so a merge that unions sources must union the flag alongside —
    a relabelled record whose source has a definition makes the merged record
    has_definition=true even when the winning-var payload's source did not."""
    sources = into.setdefault("source", [])
    for label in extra.get("source", ()):
        if label not in sources:
            sources.append(label)
    if extra.get("has_definition"):
        into["has_definition"] = True


def relabel_onto(loser, winner):
    """Fold `loser` into the merged `winner` record in place: union its source
    (and has_definition), then record the loser's pre-relabel var so a patch
    anchored to the loser's old (word,pos,shaw,var) key auto-re-anchors onto the
    winner rather than orphaning (see basis.mark_original / reanchor_index).
    SET-ONCE means only the first loser's pre-image is kept per field; a rarer
    multi-loser collision leaves the later ones to surface via the 'orphaned'
    filter."""
    union_sources(winner, loser)
    mark_original(winner, "var", loser.get("var", ""))


def collapse_group(entries):
    """The collapsed records for one same-(word,pos) set of identical-spelling
    records, and the tally reason.

    Flat LEGACY collapse only — the harvest accents are handled by the dialect
    hierarchy before this runs (see hierarchy_relabel_group), so this stage sees
    only spellings not already claimed by the hierarchy and collapses among the
    legacy vars {RRP, RSSB, GenAm}.

    Collapses iff 2+ distinct LEGACY vars carry the spelling and every record
    agrees on the mergers flag: every legacy record is relabelled to the winning
    (highest-precedence) var, then records sharing that var merge into one whose
    payload is the winning-var record's (a relabelled record contributes only its
    source). Any non-legacy (harvest-accent) records in the partition — a harvest
    record that DIVERGED from its parent and legitimately spells the same as a
    legacy sibling — pass through UNTOUCHED: the hierarchy already ruled it a real
    fact, and merging it onto a legacy var would erase that. Records disagreeing on
    the mergers flag are left intact (a real within-accent difference)."""
    legacy = [e for e in entries if e.get("var", "") in COLLISION_VARS]
    passthrough = [e for e in entries if e.get("var", "") not in COLLISION_VARS]

    legacy_vars = {entry.get("var", "") for entry in legacy}
    if len(legacy_vars) < 2:
        return entries, "single-dialect"
    if len({mergers_of(entry) for entry in legacy}) > 1:
        return entries, "mergers-differ"

    winning_rank = min(var_rank(entry) for entry in legacy)
    winning_var = next(entry.get("var", "") for entry in legacy
                       if var_rank(entry) == winning_rank)

    # The already-winning-var records keep the payload (first-seen wins on a
    # within-var duplicate); the relabelled losers only feed their source in.
    merged = None
    for entry in legacy:
        if entry.get("var", "") == winning_var:
            if merged is None:
                merged = dict(entry)
            else:
                union_sources(merged, entry)
    for entry in legacy:
        if entry.get("var", "") != winning_var:
            relabel_onto(entry, merged)
    return [merged] + passthrough, "collapsed"


def spell_sig(entry):
    """A record's (Shaw, mergers) identity within a (word,pos) group. The mergers
    flag rides the signature so a child that carries a merger flag its parent lacks
    counts as a divergent fact (consistent with the flat collapse's mergers guard),
    not an inherited spelling."""
    return (entry["Shaw"], mergers_of(entry))


def parent_shaw_sigs(var, sig_by_var):
    """The set of (Shaw, mergers) signatures the nearest PRESENT ancestor of `var`
    carries in this group — the spellings `var` would inherit. Walks PARENT up the
    chain, skipping absent ancestors (an absent parent contributes nothing; the
    walk falls through to its own parent), until a present ancestor or the root.
    Returns an empty set if no ancestor is present (then nothing to inherit → the
    child is kept)."""
    ancestor = PARENT.get(var)
    while ancestor is not None:
        if sig_by_var.get(ancestor):
            return sig_by_var[ancestor]
        ancestor = PARENT.get(ancestor)
    return set()


def hierarchy_relabel_group(entries, tallies, samples):
    """Apply the dialect hierarchy to one (word,pos) group: drop each harvested-accent
    record (a var in HIERARCHY_COLLAPSE_VARS) whose (Shaw,mergers) equals a signature
    its nearest present ancestor carries — it inherits the parent, so relabel it onto
    that ancestor's matching record (unioning source + preserving orig_var). Records
    that DIVERGE from their parent stay. Returns the surviving records.

    Only the harvested accents are actively relabelled here. RRP (root), RSSB
    (outside the hierarchy) and GenAm (owned by the flat legacy collapse) pass
    THROUGH untouched — but their spellings ARE read, so a GenCan can compare against
    GenAm and a GenAus against RRP.

    Processed PARENT-BEFORE-CHILD (by depth) so a child compares against a parent
    whose divergent spellings are already recorded; the fallback chain GenCan ->
    GenAm -> RRP is honoured by walking PARENT to the nearest present ancestor."""
    # Records keyed by var; a var may carry several spellings (distinct Shaw, or a
    # merger-flagged twin).
    by_var = defaultdict(list)
    for entry in entries:
        by_var[entry.get("var", "")].append(entry)

    # Signature -> the record carrying it, per var. Seeded with EVERY var the
    # hierarchy stage does not relabel (RRP/RSSB/GenAm and anything unlisted) so
    # those serve as parent references and flow on to the flat stage intact. The
    # relabelled harvested accents add their divergent survivors as we go.
    survivors = defaultdict(list)
    record_by_sig = defaultdict(dict)  # var -> {sig: record}
    for var, recs in by_var.items():
        if var not in HIERARCHY_COLLAPSE_VARS:
            survivors[var].extend(recs)
            for rec in recs:
                record_by_sig[var].setdefault(spell_sig(rec), rec)

    sig_by_var = {var: set(record_by_sig[var]) for var in record_by_sig}

    # Parent-before-child: order the collapsed vars by depth (distance to root) so
    # every var is processed after its parent. Deterministic within a depth by name.
    def depth(var):
        d, cur = 0, var
        while cur in PARENT:
            d += 1
            cur = PARENT[cur]
        return d

    for var in sorted((v for v in by_var if v in HIERARCHY_COLLAPSE_VARS),
                      key=lambda v: (depth(v), v)):
        parent_sigs = parent_shaw_sigs(var, sig_by_var)
        for rec in by_var[var]:
            sig = spell_sig(rec)
            if sig in parent_sigs:
                # Inherit: relabel onto the ancestor record carrying this signature.
                target = _ancestor_record(var, sig, record_by_sig)
                target_var = target.get("var", "")
                relabel_onto(rec, target)
                tallies["hierarchy-collapsed"] += 1
                tallies[f"hierarchy-collapsed-{var}->{target_var}"] += 1
                # "Intermediate" = collapsed onto a non-root parent it actually
                # reached (GenCan -> GenAm), i.e. the target is not RRP. A GenCan
                # that walked PAST an absent GenAm to RRP is a root collapse, not
                # intermediate — the metric the brief asks for is the GenCan==GenAm
                # case specifically.
                if target_var != ROOT_VAR:
                    tallies["hierarchy-collapsed-intermediate"] += 1
                if len(samples["hierarchy"]) < SAMPLE_LIMIT:
                    samples["hierarchy"].append((rec.get("Latn", ""), rec.get("pos", ""),
                                                 var, target_var, rec["Shaw"]))
            else:
                # Diverges from parent: keep as its own accent fact.
                survivors[var].append(rec)
                record_by_sig[var].setdefault(sig, rec)
                sig_by_var.setdefault(var, set()).add(sig)

    return [rec for recs in survivors.values() for rec in recs]


def _ancestor_record(var, sig, record_by_sig):
    """The nearest present ancestor's record carrying `sig` — the record `var`'s
    inheriting child relabels onto. Walks PARENT; fails loud if no ancestor carries
    the signature (the caller only calls this when parent_shaw_sigs said one does)."""
    ancestor = PARENT.get(var)
    while ancestor is not None:
        rec = record_by_sig.get(ancestor, {}).get(sig)
        if rec is not None:
            return rec
        ancestor = PARENT.get(ancestor)
    raise SystemExit(
        f"collapse_identical_dialects: no ancestor record for {var} sig={sig} — "
        f"parent_shaw_sigs and _ancestor_record disagree (hierarchy bug)")


def collapse_supplement(supplement, tallies, samples):
    """A copy of a supplement dict with dialect variants collapsed down the dialect
    hierarchy. Two composed stages per (word,pos) group:

      1. HIERARCHY collapse (hierarchy_relabel_group): a harvest-accent record whose
         spelling equals its nearest present ancestor's inherits that ancestor and
         is relabelled away; a divergent one is kept. This is the multi-accent
         harvest's dedup — it governs GenAus/GenCan/NZ/SthAfr/IrEng/SSB (NOT GenAm,
         which the flat stage owns; the hierarchy only READS GenAm as GenCan's
         parent).
      2. FLAT legacy collapse (collapse_group): the surviving records are partitioned
         by spelling and any spelling carried by 2+ legacy vars {RRP,RSSB,GenAm}
         merges to the highest-precedence one, unioning sources (the combined-pool
         multi-source union, and the pre-existing GenAm-vs-RRP collapse). Harvest
         records pass through this stage untouched.

    `samples` is a dict of sample lists ({"hierarchy": [...], "flat": [...]}); the
    caller seeds it (see main)."""
    groups = defaultdict(list)
    for entries in supplement.values():
        for entry in entries:
            groups[(entry["Latn"].lower(), entry["pos"])].append(entry)

    collapsed = defaultdict(list)
    for group_entries in groups.values():
        surviving = hierarchy_relabel_group(group_entries, tallies, samples)

        by_shaw = defaultdict(list)
        for entry in surviving:
            by_shaw[entry["Shaw"]].append(entry)

        for shaw_entries in by_shaw.values():
            kept, reason = collapse_group(shaw_entries)
            if reason == "collapsed":
                tallies["collapsed-groups"] += 1
                tallies["records-merged"] += len(shaw_entries) - len(kept)
                if len(samples["flat"]) < SAMPLE_LIMIT:
                    samples["flat"].append((shaw_entries, kept))
            else:
                tallies[reason] += len(shaw_entries)
            for entry in kept:
                collapsed[output_bucket_key(entry)].append(entry)

    return {key: collapsed[key] for key in sorted(collapsed)}


def new_samples():
    """The sample container collapse_supplement fills: one list per collapse stage."""
    return {"hierarchy": [], "flat": []}


def report(tallies, samples):
    print("\n=== dialect collapse report ===")
    print("--- hierarchy (harvest accent inherits parent) ---")
    print(f"Records collapsed to parent:  {tallies['hierarchy-collapsed']:,}")
    print(f"  of which intermediate (child -> non-root parent, e.g. GenCan->GenAm): "
          f"{tallies['hierarchy-collapsed-intermediate']:,}")
    for key in sorted(k for k in tallies if k.startswith("hierarchy-collapsed-")
                      and "->" in k):
        edge = key[len("hierarchy-collapsed-"):]
        print(f"  {edge}: {tallies[key]:,}")
    print("--- flat legacy collapse (identical spelling across RRP/RSSB/GenAm) ---")
    print(f"Groups collapsed:             {tallies['collapsed-groups']:,}")
    print(f"Records merged away:          {tallies['records-merged']:,}")
    print(f"Left (single dialect):        {tallies['single-dialect']:,}")
    print(f"Left (mergers differ):        {tallies['mergers-differ']:,}")

    print("\nSample hierarchy collapses (child inherits parent, dropped):")
    for latn, pos, child_var, parent_var, shaw in samples["hierarchy"]:
        print(f"  {latn} [{pos}] {shaw}: {child_var} == {parent_var} -> dropped")

    print("\nSample flat collapses (identical spelling across legacy dialects -> "
          "relabel to highest, union source):")
    for shaw_entries, kept in samples["flat"]:
        vars_seen = ", ".join(sorted(entry.get("var", "") for entry in shaw_entries))
        rep = kept[0]
        print(f"  {rep['Latn']} [{rep['pos']}] {rep['Shaw']}: "
              f"{{{vars_seen}}} -> {rep.get('var', '')} "
              f"source={rep.get('source', [])}")


def main():
    tallies = Counter()
    samples = new_samples()

    supplement = load_json(INPUT_PATH)
    collapsed = collapse_supplement(supplement, tallies, samples)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(collapsed, f, ensure_ascii=False, indent=4)
    print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}: "
          f"{sum(len(v) for v in collapsed.values()):,} records")

    report(tallies, samples)


if __name__ == "__main__":
    main()
