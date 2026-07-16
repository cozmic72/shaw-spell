#!/usr/bin/env python3
"""
Salvage verdicted rows from the legacy editorial CSVs into the new patch store.

Emits data/patches/patches.jsonl — one JSON patch per line — from the human
decisions recorded in the CSV editorial process. Unreviewed rows (the ~84K
blank-verdict candidates) are NOT migrated: in the new model they have no
persistence footprint; they are re-derived live from the basis (upstream +
supplements) and only acquire a patch once a human rules on them.

Patch shape (see docs/editorial-overlay-design.md, "The patch record"):

    {
      "id":     "p_<hash>",                                # deterministic, content-derived
      "anchor": {"word","pos","shaw","var"} | null,        # basis record reviewed; null = authorship
      "record": {"word","pos","shaw","var","ipa","freq",
                 "source","status","confidence?","note?"} | null,   # complete record; null = drop
      "meta":   {"author","origin","note?"}
    }

The natural key (word, pos, shaw, var) is identity; ipa/freq/source/status are
payload. The legacy CSV salvage was VAR-INDEPENDENT (one verdict per
(word, pos, shaw)) and edits-only. Each salvaged decision is resolved against
the basis to the full source record(s) it applied to; a decision spanning
several dialect vars fans out to ONE patch per resolved record, each carrying
that var/ipa/freq. FAIL LOUD on any decision that resolves to nothing.

Salvaged sources:
  editorial.csv           verdict in {keep, drop, "mistake in ml and shave"}  (+ overrides)
  editorial-pos-gaps.csv  verdict == keep
  editorial-manual.csv    all rows  (authorship: anchor = null)

NOT salvaged:
  editorial-drops.csv       machine-dropped affixes/fragments — re-derivable
  editorial-duplicates.csv  reference only

Usage:
    python3 src/tools/migrate_csv_to_patches.py
"""

import csv
import hashlib
import json
from pathlib import Path

from basis import PROJECT_ROOT, anchor_key, build_basis, output_to_record

EDITORIAL = PROJECT_ROOT / "data" / "editorial.csv"
POS_GAPS = PROJECT_ROOT / "data" / "editorial-pos-gaps.csv"
MANUAL = PROJECT_ROOT / "data" / "editorial-manual.csv"

OUT_DIR = PROJECT_ROOT / "data" / "patches"
OUT_PATH = OUT_DIR / "patches.jsonl"

# Free-text verdict used on 4 hand-corrected rows (tear gas / teart*). The row's
# `shaw` column already holds the human's corrected spelling; treat as a keep.
MISTAKE_VERDICT = "mistake in ml and shave"

DEFAULT_AUTHOR = "cozmic72@me.com"


def clean_row(row):
    return {(k or "").strip(): (v or "").strip() for k, v in row.items() if k is not None}


def read_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return [clean_row(r) for r in csv.DictReader(f) if (r.get("word") or "").strip()]


def patch_id(anchor, record):
    """Deterministic, content-derived id so re-running is idempotent (no clock/random)."""
    payload = json.dumps({"anchor": anchor, "record": record},
                         ensure_ascii=False, sort_keys=True)
    return "p_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_patch(anchor, record, author, origin, note):
    meta = {"author": author, "origin": origin}
    if note:
        meta["note"] = note
    return {"id": patch_id(anchor, record), "anchor": anchor, "record": record, "meta": meta}


def index_by_var_independent(basis_index, basis_origin):
    """Group basis records by the var-independent (word_lower, pos, shaw) the
    legacy CSV verdicts anchored to — one lookup structure, built once. Each
    grouped record carries its basis origin (the source file that supplied it),
    which becomes the record's `source` — a fact of the basis, not the CSV."""
    grouped = {}
    for key, record in basis_index.items():
        grouped.setdefault(key[:3], []).append((record, basis_origin[key]))
    return grouped


def resolve_sources(var_independent, word, pos, shaw):
    """The (record, origin) pairs a var-independent (word, pos, shaw) decision
    applied to. The new key is var-qualified, so one legacy decision fans out to
    every var whose (word_lower, pos, shaw) matches; each keeps its own
    var/ipa/freq/origin."""
    return var_independent.get((word.lower(), pos, shaw), [])


def apply_edits(record, origin, pos_override, shaw_override, ipa_override, status):
    """Fold a decision's edits onto a resolved source record. Overrides win; an
    absent override leaves the source field intact (its real ipa, not the CSV's
    var-collapsed one). `source` is the basis origin and `confidence` is the
    basis record's own value (both deterministic per var, NOT the CSV columns) —
    so two decisions on one record no longer split into divergent patches. Only
    the decision's `status` and any explicit overrides come from the CSV; the
    reviewer's free-text note is patch metadata, kept in meta (not the record)."""
    edited = dict(record)
    if pos_override:
        edited["pos"] = pos_override
    if shaw_override:
        edited["shaw"] = shaw_override
    if ipa_override:
        edited["ipa"] = ipa_override
    edited["source"] = origin
    if status:
        edited["status"] = status
    return edited


def salvage_edits(rows, var_independent, origin, keep_verdicts, drop_verdicts):
    """keep/drop/mistake rows resolved to full-record patches, one per matched var.

    The anchor is each resolved source record's natural key (word, pos, shaw, var);
    the record is that source record with the decision's edits folded in (a drop
    yields record=null). FAIL LOUD on a decision that resolves to no source."""
    out = []
    for row in rows:
        verdict = row.get("verdict", "")
        if verdict not in keep_verdicts and verdict not in drop_verdicts:
            continue

        word, pos, shaw = row["word"], row["pos"], row["shaw"]
        sources = resolve_sources(var_independent, word, pos, shaw)
        if not sources:
            raise SystemExit(
                f"FATAL: {origin} decision resolves to no basis record: "
                f"{word!r} pos={pos} shaw={shaw} verdict={verdict!r}")

        for source_record, source_origin in sources:
            anchor = {"word": source_record["Latn"], "pos": source_record["pos"],
                      "shaw": source_record["Shaw"], "var": source_record["var"]}
            if verdict in drop_verdicts:
                record = None
            else:
                record = apply_edits(
                    output_to_record(source_record), source_origin,
                    row.get("pos_override", ""), row.get("shaw_override", ""),
                    row.get("ipa_override", ""), row.get("status", ""))
            out.append(make_patch(anchor, record, DEFAULT_AUTHOR, origin,
                                  row.get("notes", "")))
    return out


def salvage_manual(rows):
    """editorial-manual.csv — authorship: anchor = null (records no source
    attests). The record is complete and self-contained; nothing to resolve."""
    out = []
    for row in rows:
        record = {
            "word": row["word"],
            "pos": row.get("pos_override") or row["pos"],
            "shaw": row.get("shaw_override") or row["shaw"],
            "var": row.get("var_override") or (row.get("var") or "RRP"),
            "ipa": row.get("ipa_override") or row.get("ipa", ""),
            "freq": int(row.get("freq") or 0),
            "source": row.get("source", "manual") or "manual",
            "status": row.get("status", "manual") or "manual",
        }
        if row.get("confidence", "") != "":
            record["confidence"] = int(row["confidence"])
        out.append(make_patch(None, record, DEFAULT_AUTHOR, origin="manual",
                              note=row.get("notes", "")))
    return out


def dedup_identical(patches):
    """Coalesce byte-identical patches (same id AND same content) — the legacy
    CSVs record some decisions on the same record twice, which is idempotent, not
    a conflict. FAIL LOUD on a true id collision: same id, DIFFERENT content."""
    seen = {}
    for patch in patches:
        existing = seen.get(patch["id"])
        if existing is None:
            seen[patch["id"]] = patch
        elif existing != patch:
            raise SystemExit(
                f"FATAL: patch id collision with differing content: {patch['id']} "
                f"({existing['anchor']} vs {patch['anchor']})")
    return list(seen.values())


def reject_anchor_conflicts(patches):
    """FAIL LOUD if two distinct patches target the same anchor. One record has
    one decision; two conflicting verdicts on the same natural key mean the source
    CSVs disagree and a human must reconcile them — never silently last-wins."""
    by_anchor = {}
    for patch in patches:
        anchor = patch["anchor"]
        if anchor is None:
            continue
        key = anchor_key(anchor)
        if key in by_anchor:
            raise SystemExit(
                f"FATAL: two conflicting patches on anchor {key}: "
                f"{by_anchor[key]} vs {patch['id']}")
        by_anchor[key] = patch["id"]


def main():
    basis_index, basis_origin = build_basis()
    var_independent = index_by_var_independent(basis_index, basis_origin)

    editorial_rows = read_csv(EDITORIAL)
    pos_gap_rows = read_csv(POS_GAPS)
    manual_rows = read_csv(MANUAL)

    patches = []
    patches += salvage_edits(editorial_rows, var_independent, "editorial",
                             keep_verdicts=("keep", MISTAKE_VERDICT),
                             drop_verdicts=("drop",))
    patches += salvage_edits(pos_gap_rows, var_independent, "pos-gap",
                             keep_verdicts=("keep",), drop_verdicts=())
    patches += salvage_manual(manual_rows)

    patches = dedup_identical(patches)
    reject_anchor_conflicts(patches)

    n_add = sum(1 for p in patches if p["anchor"] is None)
    n_remove = sum(1 for p in patches if p["record"] is None)
    n_edit = len(patches) - n_add - n_remove

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for p in patches:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"Wrote {len(patches):,} patches → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    print(f"  authorship (anchor=null):  {n_add:,}")
    print(f"  drop       (record=null):  {n_remove:,}")
    print(f"  edit       (full record):  {n_edit:,}")
    print(f"  by origin:")
    for origin in sorted(set(p["meta"]["origin"] for p in patches)):
        print(f"    {origin:12s} {sum(1 for p in patches if p['meta']['origin']==origin):,}")


if __name__ == "__main__":
    main()
