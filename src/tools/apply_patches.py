#!/usr/bin/env python3
"""
Apply the editorial patch store to the computed basis, producing data/readlex.json.

This replaces generate_merged_readlex.py. The model (see
docs/editorial-overlay-design.md):

  - The BASIS is the raw combination of all upstream sources — upstream ReadLex
    (external/readlex/readlex.json) plus the wordnet and wiktionary supplement
    candidates — computed on-demand. Every candidate, including the ~85K
    unreviewed supplemental ones, is a record in the basis. Nothing is frozen.

  - A PATCH (data/patches/patches.jsonl) is a record rewrite {old, new}:
      old   is a var-INDEPENDENT anchor {word, pos, shaw} — it matches every
            basis candidate with that (word.lower(), pos, shaw), regardless of
            var. Each matched candidate keeps its own var and freq.
      new   is one of:
              edits-only {pos, shaw, ipa, source, status, confidence?, note?}
                  — keep / respell / pos-gap; var and freq are inherited from
                    each matched candidate (one output record per matched var).
              standalone {word, pos, shaw, var, ipa, freq, source, status, ...}
                  — authorship (old is null); a record no source attests.
              null
                  — removal; the matched candidates are dropped.

  - The OUTPUT starts as upstream ReadLex (which flows through untouched — an
    unreviewed candidate has no patch, so it never enters the output) and is
    mutated patch by patch. An unpatched upstream record is emitted verbatim;
    a patched record carries whichever of {confidence, source, status} the
    patch's `new` specifies, emitted verbatim.

  - FAIL LOUD on an orphaned decision: an `old` anchor that resolves against
    NOTHING in the basis (upstream drifted since the decision was made) is
    surfaced, not silently dropped.

Determinism: patches are applied in a total order over their anchor identity
and id, so identical inputs yield an identical readlex.json.

Usage:
    python3 src/tools/apply_patches.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
UPSTREAM_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
PATCHES_PATH = PROJECT_ROOT / "data" / "patches" / "patches.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "data" / "readlex.json"

# Supplement candidate sources that make up the basis alongside upstream ReadLex.
SUPPLEMENT_PATHS = [
    PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json",
    PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json",
]

# Valid Shavian chars — a record whose Shaw contains anything else (e.g. an
# unconverted IPA fragment) is skipped, matching the legacy applicator.
KNOWN_SHAW = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘"
                 "𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")

# Extra provenance fields an edited/authored entry may carry, in output order.
# `note` is patch metadata and is deliberately NOT emitted to the dictionary.
PROVENANCE_FIELDS = ["confidence", "source", "status"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_patches():
    patches = []
    with open(PATCHES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                patches.append(json.loads(line))
    return patches


def anchor_of(entry):
    """The var-independent basis anchor of a record: (word_lower, pos, shaw)."""
    return (entry.get("Latn", "").lower(), entry.get("pos", ""), entry.get("Shaw", ""))


def build_basis_index():
    """Index the basis (upstream + supplements) by var-independent anchor.

    Maps (word_lower, pos, shaw) -> list of candidate entries, each retaining
    its own var and freq. This is the pool a patch's `old` anchor resolves
    against; it is never emitted directly.
    """
    index = {}
    for source_path in [UPSTREAM_PATH, *SUPPLEMENT_PATHS]:
        for entries in load_json(source_path).values():
            for entry in entries:
                index.setdefault(anchor_of(entry), []).append(entry)
    return index


def slot_of(entry):
    """Full record identity (word_lower, pos, shaw, var) — used for dedup."""
    return (entry.get("Latn", "").lower(), entry.get("pos", ""),
            entry.get("Shaw", ""), entry.get("var", ""))


def edited_record(new, candidate):
    """Build an output record for a keep/respell/pos-gap patch applied to a
    matched candidate. The patch's `new` supplies the edits (pos/shaw/ipa/
    provenance); word, var and freq are inherited from the candidate — its
    Latn is the authoritative surface form (e.g. proper-noun casing)."""
    return _output_entry(candidate.get("Latn", ""), new,
                         candidate.get("var", ""), candidate.get("freq", 0))


def authored_record(new):
    """Build an output record from a standalone authorship patch (`old` null),
    which carries its own word, var and freq."""
    return _output_entry(new["word"], new, new["var"], new.get("freq", 0))


def _output_entry(word, new, var, freq):
    entry = {
        "Latn": word,
        "Shaw": new["shaw"],
        "pos": new["pos"],
        "ipa": new.get("ipa", ""),
        "freq": freq,
        "var": var,
    }
    for field in PROVENANCE_FIELDS:
        if field in new and new[field] != "":
            entry[field] = new[field]
    return entry


def remove_matched(output, matched_slots):
    """Remove from the output every entry whose identity is in matched_slots."""
    for key in list(output.keys()):
        kept = [e for e in output[key] if slot_of(e) not in matched_slots]
        if kept:
            output[key] = kept
        else:
            del output[key]


def insert_entry(output, entry):
    """Insert an output record under its ReadLex key, skipping an exact-identity
    duplicate already present (e.g. the same var supplied by two sources)."""
    key = f"{entry['Latn']}_{entry['pos']}_{entry['Shaw']}"
    bucket = output.setdefault(key, [])
    identity = slot_of(entry)
    if any(slot_of(existing) == identity for existing in bucket):
        return
    bucket.append(entry)


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
    """Total, deterministic apply order over anchor identity then patch id."""
    reference = patch["old"] or patch["new"]
    return (reference["word"].lower(), reference["pos"], reference["shaw"], patch["id"])


def apply_patches(output, basis_index, patches):
    stats = {"authorship": 0, "update": 0, "removal": 0, "orphaned": 0,
             "skipped_numeral": 0, "skipped_shaw": 0}
    orphans = []

    for patch in sorted(patches, key=patch_order_key):
        old, new = patch["old"], patch["new"]

        if old is None:
            # Authorship: a standalone record no source attests.
            if is_emittable(new["word"], new["shaw"], stats):
                insert_entry(output, authored_record(new))
                stats["authorship"] += 1
            continue

        # Resolve the anchor against the basis: all candidates sharing
        # (word, pos, shaw), each with its own var/freq.
        candidates = basis_index.get((old["word"].lower(), old["pos"], old["shaw"]))
        if not candidates:
            # Upstream drifted: the record this decision was made against no
            # longer exists. Surface it loudly rather than dropping it.
            orphans.append(patch)
            stats["orphaned"] += 1
            continue

        # Remove the matched records from the output, then (unless this is a
        # removal) re-insert one edited record per matched var.
        remove_matched(output, {slot_of(c) for c in candidates})

        if new is None:
            stats["removal"] += 1
            continue

        for candidate in candidates:
            record = edited_record(new, candidate)
            if is_emittable(record["Latn"], record["Shaw"], stats):
                insert_entry(output, record)
        stats["update"] += 1

    return stats, orphans


def main():
    output = load_json(UPSTREAM_PATH)
    print(f"Upstream: {len(output):,} keys, {sum(len(v) for v in output.values()):,} entries")

    basis_index = build_basis_index()
    print(f"Basis:    {len(basis_index):,} anchors "
          f"(upstream + {len(SUPPLEMENT_PATHS)} supplements)")

    patches = load_patches()
    print(f"Patches:  {len(patches):,}")

    stats, orphans = apply_patches(output, basis_index, patches)

    # Fail loud on orphaned decisions BEFORE writing anything. An `old` anchor
    # that no longer resolves means upstream drifted out from under an editorial
    # decision; shipping a dictionary that silently dropped it is the exact
    # "lost verdicts" failure this system exists to prevent. No output written.
    if orphans:
        print(f"FATAL: {len(orphans)} orphaned decision(s) — an `old` anchor no "
              f"longer resolves against the basis. Re-anchor or remove them.",
              file=sys.stderr)
        for patch in orphans:
            old = patch["old"]
            print(f"    {old['word']!r} pos={old['pos']} shaw={old['shaw']} "
                  f"(id={patch['id']})", file=sys.stderr)
        raise SystemExit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f"\nMerged:   {len(output):,} keys, {sum(len(v) for v in output.values()):,} entries")
    print(f"  authorship (added):  {stats['authorship']:,}")
    print(f"  update/respell:      {stats['update']:,}")
    print(f"  removal:             {stats['removal']:,}")
    print(f"  skipped (numeral):   {stats['skipped_numeral']:,}")
    print(f"  skipped (bad shaw):  {stats['skipped_shaw']:,}")
    print(f"\nWrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
