#!/usr/bin/env python3
"""
Apply the editorial patch store to the computed basis, producing data/readlex.json.

The model (see docs/editorial-overlay-design.md, "The patch record (settled
model)"):

  - The BASIS is the combined supplement pool, computed on-demand. Upstream
    ReadLex (external/readlex/readlex.json) rides IN the pool — collated at
    combine time under the `readlex` source label, carried through the pruning
    chain untouched — so the pool is the basis's single union point and every
    upstream anchor appears exactly once. Every candidate, including the
    unreviewed supplemental ones, is a record in the basis. Nothing is frozen.

  - A PATCH (data/patches/patches.jsonl) is {anchor, op, changes, meta}:
      anchor   the natural key {word, pos, shaw, var, lemma?} of the ONE basis
               record it reviews, or null for a manual record. Immutable identity —
               never changed when the record is edited.
      op       accept (sanction the anchored basis record) / drop (remove it) /
               flag (production no-op) / edit (DIRTY — carries changes, ships
               nothing). A manual-record ACCEPT has op null; a manual row can
               also be flagged or dirty (op flag/edit with anchor null).
      changes  the intrinsic edits {word, shaw, pos, ipa, var, mergers, variant}
               an accept lays over the LIVE basis record (empty = accept as-is);
               or, for a manual patch, the whole self-contained record.

  - The OUTPUT starts as upstream ReadLex (an unreviewed candidate has no patch,
    so it never enters the output) and is mutated patch by patch. Each patch is
    resolved over the LIVE basis (basis.resolve_patch): an accept removes the
    anchored source record and re-emits it sanctioned with `changes` laid over
    it; a drop removes it; a flag leaves it untouched. A manual patch (anchor null)
    emits `changes` as a standalone record.

  - SOFT-FAIL on an orphaned decision: an anchor that resolves against NOTHING in
    the basis (upstream drifted since the decision was made) is LOGGED and SKIPPED
    (it contributes nothing to the output), but the build still succeeds. The
    patch is RETAINED in the store (this applicator never rewrites it) and surfaced
    in the editor via the `orphaned` filter, where the owner re-anchors or discards
    it. An orphan is a recoverable, visible state — never a fatal error, and never
    a silent lost verdict.

  - FREQUENCY IS UPSTREAM PROCESSING, applied BEFORE the patches: the corpus
    derivation (apply_frequency_data.enrich_all) runs over the pre-patch record
    set — the upstream output plus the manual wing of the pool (see
    enrich_upstream / basis.manual_pool) — and anchored accepts inherit the
    basis pool's enriched freq. Nothing recomputes freq after the overlay, so a
    patched freq is simply the last word, like any other intrinsic field.

Determinism: patches are applied in a total order over their anchor identity and
id, so identical inputs yield an identical readlex.json.

Usage:
    python3 src/tools/apply_patches.py
"""

import json
import os
import sys
from pathlib import Path

from basis import (
    DATA_ROOT,
    PATCH_NOOP,
    PATCH_ORPHAN,
    UPSTREAM_SOURCE,
    anchor_from_key,
    anchor_key,
    anchor_of,
    manual_entry,
    manual_freq,
    manual_pool,
    build_basis,
    collapse_readlex,
    frequency_pool,
    load_upstream,
    published_entry,
    reanchor_index,
    reanchor_patch,
    resolve_patch,
)
from apply_frequency_data import enrich_all, load_corpus, report_enrichment
from lrw_frequencies import load_lrw

DEFAULT_PATCHES_PATH = DATA_ROOT / "patches" / "patches.jsonl"
OUTPUT_PATH = DATA_ROOT / "readlex.json"

# The upstream_removal_missed explanation, shared with the daemon's publish log
# so the two producers never phrase the mixed-state diagnosis apart.
IDENTITY_MISMATCH_WARNING = (
    "upstream-anchored removal(s) found no output twin — the store and raw "
    "upstream disagree on identity (accepts duplicate, drops zombie). "
    "Regenerate the pool and run migrate_patch_lemmas in one sitting.")


def patches_path():
    """The patch store to apply — the SHAW_SPELL_PATCH_STORE env var if set, else
    the live store. Resolved at call time so a migrated scratchpad store can be
    applied without touching the live one (mirrors patchstore._store_path)."""
    env = os.environ.get("SHAW_SPELL_PATCH_STORE")
    return Path(env) if env else DEFAULT_PATCHES_PATH

# Valid Shavian chars — a record whose Shaw contains anything else (e.g. an
# unconverted IPA fragment) is skipped, matching the legacy applicator.
KNOWN_SHAW = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘"
                 "𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")


def load_patches():
    patches = []
    with open(patches_path(), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                patches.append(json.loads(line))
    return patches


def bucket_locations(output):
    """Natural key -> the output bucket keys holding an entry with that key, in
    output order. Built once per apply so remove_anchored resolves its bucket in
    O(1) instead of scanning every bucket per patch — the old full scan made the
    applicator O(patches × buckets), minutes at current store size."""
    locations = {}
    for bucket_key, entries in output.items():
        for entry in entries:
            locations.setdefault(anchor_of(entry), []).append(bucket_key)
    return locations


def remove_anchored(output, key, locations=None):
    """Remove from the output the single entry whose natural key matches,
    returning whether one was found. A miss is NORMAL for a supplement anchor
    (the output starts as upstream only) but a mixed-state signature for an
    upstream one — the caller tallies that case. `locations` (see
    bucket_locations) resolves the bucket directly; without it the buckets are
    scanned in order — same result, linear cost."""
    if locations is None:
        bucket_keys = list(output.keys())
    else:
        bucket_keys = locations.get(key, ())
    for bucket_key in bucket_keys:
        kept = [e for e in output.get(bucket_key, ()) if anchor_of(e) != key]
        if len(kept) != len(output.get(bucket_key, ())):
            if kept:
                output[bucket_key] = kept
            else:
                del output[bucket_key]
            if locations is not None:
                locations[key] = [bk for bk in locations[key] if bk != bucket_key]
            return True
    return False


def insert_entry(output, entry, stats, locations=None):
    """Insert an output record under its ReadLex key, skipping an exact-identity
    duplicate already present (e.g. the same natural key from two sources, or a
    word edit that moved a record onto an existing identity). A skip DROPS the
    entry, so it is tallied (skipped_duplicate) — never a silent vanish.
    `locations` (see bucket_locations), when given, is kept in step."""
    key = f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"
    bucket = output.setdefault(key, [])
    identity = anchor_of(entry)
    if any(anchor_of(existing) == identity for existing in bucket):
        stats["skipped_duplicate"] += 1
        return
    bucket.append(entry)
    if locations is not None:
        locations.setdefault(identity, []).append(key)


def is_emittable(word, shaw, stats):
    """Whether a record survives the numeral / bad-Shavian output filters,
    tallying the reason when it does not."""
    if word and word[0].isdigit():
        stats["skipped_numeral"] += 1
        return False
    if set(shaw) - KNOWN_SHAW:
        stats["skipped_shaw"] += 1
        return False
    return True


def patch_order_key(patch):
    """Total, deterministic apply order over anchor identity then patch id. A
    manual patch (anchor null) is ordered by its record's natural key, which
    for a manual patch IS its `changes`."""
    anchor = patch["anchor"] or patch["changes"]
    return (*anchor_key(anchor), patch["id"])


# The var/variants and lemma of a record are NOT part of a decision's identity:
# the owner reviews (word, pos, shaw) and the dialect var or stated lemma can
# drift under it (a non-deterministic supplement respell relabels the var, a
# var-collapse moves it, a lemma restatement re-files it) WITHOUT changing what
# was reviewed. So an orphaned patch whose weaker key (word_lower, pos, shaw)
# still resolves to EXACTLY ONE basis record is anchored to that same record —
# the shaw (spelling) is unchanged, only var/lemma drifted — and the owner's
# decision (whatever its op) still applies verbatim. This kills "zombie"
# records: a drop the owner made re-emerging live under a drifted var is re-dropped.
#
# The rule is deliberately conservative on the two ways it could go wrong:
#   - shaw CHANGED (no weak-key match): the spelling the owner reviewed is gone.
#     A respell deserves fresh review, so leave it ORPHANED (never auto-apply a
#     verdict to a different spelling).
#   - AMBIGUOUS (weak key matches >1 record — multiple live vars or lemmas share
#     the word/pos/shaw, e.g. `axes` under both `ax` and `axe`): which record the
#     owner meant is unrecoverable, so do NOT guess. Leave orphaned and surface
#     it (safer than dropping/accepting the wrong one).
def weak_reanchor_index(basis_index):
    """Map the weak key (word_lower, pos, shaw) -> the list of full basis keys that
    share it. A single-element list is an unambiguous var/lemma-only match a patch
    can re-anchor onto; a multi-element list is ambiguous and left orphaned."""
    weak = {}
    for full_key in basis_index:
        word, pos, shaw, _var, _lemma = full_key
        weak.setdefault((word, pos, shaw), []).append(full_key)
    return weak


def weak_reanchor_patch(patch, weak_map):
    """A copy of an orphaned `patch` re-pointed at the CURRENT full key of the ONE
    basis record whose (word_lower, pos, shaw) matches — var and lemma ignored —
    or None when the weak key matches zero records (shaw drifted: re-review) or
    more than one (ambiguous: don't guess). Same op/changes/id/meta; only the
    anchor's var/lemma move, and only in memory for this apply (the store is
    never rewritten)."""
    word, pos, shaw, _var, _lemma = anchor_key(patch["anchor"])
    matches = weak_map.get((word, pos, shaw))
    if matches is None or len(matches) != 1:
        return None
    return {**patch, "anchor": anchor_from_key(matches[0])}


def enrich_upstream(output, manual_bases, corpus, lrw):
    """The UPSTREAM frequency stage of a publish: every record the overlay will
    act on — the upstream `output` plus the manual wing of the pool — put on
    the corpus scale in ONE enrich_all pass, BEFORE any patch applies. Nothing
    recomputes freq after the overlay, so a patched freq is the last word.
    Anchored accepts are not enriched here: they resolve through the basis,
    which the pool pass (basis.enrich_pool_frequency) already put on the same
    scale. Returns the enrichment tally. Shared by both producers (the editor's
    _publish_readlex and main below)."""
    entries = [entry for bucket in output.values() for entry in bucket]
    entries.extend(manual_bases.values())
    return enrich_all({None: entries}, corpus, lrw)


def apply_patches(output, basis_index, basis_source, patches, manual_bases):
    stats = {"manual": 0, "update": 0, "removal": 0, "flag": 0, "orphaned": 0,
             "reanchored": 0, "reanchored_var": 0,
             "skipped_numeral": 0, "skipped_shaw": 0, "skipped_duplicate": 0,
             "upstream_removal_missed": 0}
    orphans = []

    # The auto-re-anchor lookup: an OLD natural key a key-moving transform rewrote
    # -> the CURRENT key of the record now carrying it (via orig_*). Built once so
    # the FIRST resort for an orphaned anchor is to follow the record to its new
    # key, ahead of the soft-fail below. Empty (and free) when no basis record
    # carries orig_* — the pre-convention behaviour.
    reanchor_map = reanchor_index(basis_index)
    weak_map = weak_reanchor_index(basis_index)
    locations = bucket_locations(output)

    for patch in sorted(patches, key=patch_order_key):
        entry = resolve_patch(patch, basis_index, basis_source)

        # A flag carries no editorial change ("looked at, no verdict yet"): it is
        # a pure no-op for production. The record leaves the output exactly as
        # upstream had it — no removal, no re-emit.
        if entry is PATCH_NOOP:
            stats["flag"] += 1
            continue

        # Is this anchored patch orphaned — its anchor no longer resolving against
        # the basis? resolve_patch signals this with PATCH_ORPHAN for an ACCEPT, but
        # a DROP short-circuits to None (drop = "emit nothing") BEFORE the anchor
        # lookup, so its orphan state is invisible in `entry`. An orphaned drop whose
        # record has re-emerged under a drifted var is a ZOMBIE: the removal below
        # would target the stale anchor and no-op, leaving the record the owner
        # deleted live. So detect the drop-orphan explicitly here and route it
        # through the SAME re-anchor cascade as an accept-orphan.
        is_orphan = entry is PATCH_ORPHAN or (
            patch["anchor"] is not None
            and anchor_key(patch["anchor"]) not in basis_index)

        if is_orphan:
            # FIRST resort: follow an orig_* pre-image to the record's new key
            # (a key-moving transform preserved the old key — see reanchor_index).
            moved = reanchor_patch(patch, reanchor_map)
            reresolved = (resolve_patch(moved, basis_index, basis_source)
                          if moved is not None else None)
            if moved is not None and reresolved is not PATCH_ORPHAN:
                # Auto-re-anchored via orig_*: apply against the record's current
                # key. The removal below must target the CURRENT anchor (where the
                # record now lives), so carry the moved patch forward.
                patch, entry = moved, reresolved
                stats["reanchored"] += 1
            else:
                # SECOND resort (any op): the var/variants are not part of a
                # decision's identity, so if the WEAKER key (word, pos, shaw) still
                # resolves to exactly one record — shaw unchanged, only var drifted —
                # re-anchor onto it and re-apply the SAME op. See weak_reanchor_index
                # for why this is safe (var-only holds intent; shaw-drift and
                # multi-var stay orphaned). This is what re-kills zombie drops.
                moved = weak_reanchor_patch(patch, weak_map)
                reresolved = (resolve_patch(moved, basis_index, basis_source)
                              if moved is not None else None)
                if moved is None or reresolved is PATCH_ORPHAN:
                    # Still orphaned: shaw drifted (deserves re-review) or the weak
                    # key is ambiguous (don't guess the var), and no orig_* covered
                    # it. Collect to log below and skip — it contributes nothing to
                    # the output. The patch stays in the store (this applicator never
                    # rewrites it) and is surfaced via the editor's `orphaned` filter.
                    orphans.append(patch)
                    stats["orphaned"] += 1
                    continue
                patch, entry = moved, reresolved
                stats["reanchored_var"] += 1

        if patch["anchor"] is None:
            # A manual record: a standalone record no source attests. Its freq is
            # derived pre-overlay on its enriched pool base (the manual wing);
            # the patch's own non-zero freq is the last word (see manual_freq).
            entry["freq"] = manual_freq(
                patch["changes"], manual_bases[anchor_of(entry)])
            if is_emittable(entry["Latn"], entry["Shaw"], stats):
                insert_entry(output, entry, stats, locations)
                stats["manual"] += 1
            continue

        # Accept or drop: the anchored source record leaves the output first.
        # An upstream-attested anchor MUST have an output twin, so a miss there
        # means the store and the raw-upstream side disagree on identity (the
        # basis/store lemma migration has not run in step) — tallied loudly, or
        # a drop would silently zombie and an accept silently duplicate.
        key = anchor_key(patch["anchor"])
        removed = remove_anchored(output, key, locations)
        if not removed and UPSTREAM_SOURCE in basis_source.get(key, ()):
            stats["upstream_removal_missed"] += 1

        if entry is None:
            stats["removal"] += 1
            continue

        if is_emittable(entry["Latn"], entry["Shaw"], stats):
            insert_entry(output, entry, stats, locations)
        stats["update"] += 1

    return stats, orphans


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Derive readlex.json offline: the corpus frequency stage "
                    "over the pre-patch pool, then the patch store, then the "
                    "publish shape")
    ap.add_argument("--out", dest="out_path", default=str(OUTPUT_PATH),
                    help="where to write the merged readlex (default: data/readlex.json)")
    out_path = Path(ap.parse_args().out_path)

    output = load_upstream()
    print(f"Upstream: {len(output):,} keys, {sum(len(v) for v in output.values()):,} entries")

    basis_index, basis_source = build_basis()
    print(f"Basis:    {len(basis_index):,} records "
          f"(the combined pool; ReadLex core rides in it as upstream records)")

    patches = load_patches()
    print(f"Patches:  {len(patches):,}")

    # FREQUENCY BEFORE PATCHES. Both corpora load loud (sys.exit with fetch
    # instructions when absent). Two pool passes, mirroring the editor daemon
    # exactly: the basis pool (what an anchored accept inherits — the daemon's
    # startup pass), then the pre-patch output (what upstream pass-throughs and
    # manual records ship — the daemon's publish pass; the manual wing rides
    # in both, the second pass idempotently settling it on the publish value).
    manual_bases = manual_pool(patches)
    corpus = load_corpus()
    lrw = load_lrw()
    enrich_all(frequency_pool(basis_index, manual_bases), corpus, lrw)
    enrich_stats = enrich_upstream(output, manual_bases, corpus, lrw)

    stats, orphans = apply_patches(output, basis_index, basis_source, patches,
                                   manual_bases)

    # Soft-fail on orphaned decisions: an anchor that no longer resolves means
    # upstream drifted out from under an editorial decision. LOG each one (so it is
    # never silently lost) and SKIP it (it applied nothing above), but still write
    # the output and exit 0 — an orphan is a recoverable, surfaced state, not a
    # blocked build. The patch stays in the store (this applicator never rewrites
    # it); the owner finds and fixes it via the editor's `orphaned` filter.
    if orphans:
        print(f"WARNING: {len(orphans)} orphaned decision(s) skipped — an anchor no "
              f"longer resolves against the basis (upstream drifted). Retained in the "
              f"store; surface via the editor 'orphaned' filter to re-anchor or drop.",
              file=sys.stderr)
        for patch in orphans:
            anchor = patch["anchor"]
            print(f"    {anchor['word']!r} pos={anchor['pos']} shaw={anchor['shaw']} "
                  f"var={anchor['var']} (id={patch['id']})", file=sys.stderr)

    # The publish shape: the per-record whitelist (basis.PUBLISH_FIELDS) then
    # the ReadLex-compatibility collapse — the same export boundary the editor's
    # commit path runs, so the offline artifact matches the committed one.
    published = {
        bucket_key: [published_entry(entry) for entry in entries]
        for bucket_key, entries in output.items()}
    published, collapse_stats = collapse_readlex(published)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(published, f, ensure_ascii=False, indent=4)

    print()
    report_enrichment(enrich_stats)
    if collapse_stats:
        print("\nReadLex-compatibility collapse:")
        for action, count in sorted(collapse_stats.items()):
            print(f"  {action}: {count:,}")

    print(f"\nMerged:   {len(published):,} keys, {sum(len(v) for v in published.values()):,} entries")
    print(f"  manual (added):      {stats['manual']:,}")
    print(f"  update/respell:      {stats['update']:,}")
    print(f"  removal:             {stats['removal']:,}")
    print(f"  flag (no-op):        {stats['flag']:,}")
    print(f"  auto-re-anchored:    {stats['reanchored']:,}"
          + ("  — orphaned anchor followed to its transformed record via orig_*"
             if stats['reanchored'] else ""))
    print(f"  re-anchored (var-only): {stats['reanchored_var']:,}"
          + ("  — orphaned anchor re-anchored on (word,pos,shaw); only var/variants "
             "drifted, so the decision still applies (re-kills zombie drops)"
             if stats['reanchored_var'] else ""))
    print(f"  orphaned (skipped):  {stats['orphaned']:,}"
          + ("  — see log above; retained in store, surface via editor 'orphaned' filter"
             if stats['orphaned'] else ""))
    print(f"  skipped (numeral):   {stats['skipped_numeral']:,}")
    print(f"  skipped (bad shaw):  {stats['skipped_shaw']:,}")
    print(f"  skipped (dup identity): {stats['skipped_duplicate']:,}"
          + ("  — an emitted record's identity already exists in the output "
             "(e.g. a word edit landed on an existing record); the entry was dropped"
             if stats['skipped_duplicate'] else ""))
    if stats["upstream_removal_missed"]:
        print(f"\nWARNING: {stats['upstream_removal_missed']} "
              f"{IDENTITY_MISMATCH_WARNING}", file=sys.stderr)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
