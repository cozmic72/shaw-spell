#!/usr/bin/env python3
"""
Salvage verdicted rows from the legacy editorial CSVs into the new patch store.

Emits data/patches/patches.jsonl — one JSON patch per line — from the human
decisions recorded in the CSV editorial process. Unreviewed rows (the ~84K
blank-verdict candidates) are NOT migrated: in the new model they have no
persistence footprint; they are re-derived live from the basis (upstream +
supplements) and only acquire a patch once a human rules on them.

Patch shape (see docs/editorial-overlay-design.md):

    {
      "id":  "p_<hash>",                            # deterministic, content-derived
      "old": {"word","pos","shaw","var"} | null,    # basis record acted on; null = authorship
      "new": {"word","pos","shaw","var","ipa","freq",
              "source","status","confidence","note"} | null,   # null = removal
      "meta": {"author","origin","note"}
    }

Identity key = (word, pos, shaw, var). ipa/freq/source/status are payload, not identity.

Salvaged sources:
  editorial.csv         verdict in {keep, drop, "mistake in ml and shave"}  (+ overrides)
  editorial-pos-gaps.csv  verdict == keep
  editorial-manual.csv    all rows  (authorship: old = null)

NOT salvaged:
  editorial-drops.csv   machine-dropped affixes/fragments — re-derivable
  editorial-duplicates.csv  reference only

Usage:
    python3 src/tools/migrate_csv_to_patches.py
"""

import csv
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
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


def patch_id(old, new):
    """Deterministic, content-derived id so re-running is idempotent (no clock/random)."""
    basis = json.dumps({"old": old, "new": new}, ensure_ascii=False, sort_keys=True)
    return "p_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def identity(word, pos, shaw, var):
    return {"word": word, "pos": pos, "shaw": shaw, "var": var}


def record(word, pos, shaw, var, ipa, freq, source, status, confidence, note):
    """Full record payload for a patch's `new` side."""
    rec = {"word": word, "pos": pos, "shaw": shaw, "var": var,
           "ipa": ipa, "freq": freq,
           "source": source, "status": status}
    if confidence != "":
        rec["confidence"] = int(confidence)
    if note:
        rec["note"] = note
    return rec


def make_patch(old, new, author, origin, note):
    meta = {"author": author, "origin": origin}
    if note:
        meta["note"] = note
    return {"id": patch_id(old, new), "old": old, "new": new, "meta": meta}


def salvage_editorial(rows):
    """keep / drop / mistake rows from editorial.csv. Overrides fold into `new`."""
    out = []
    for r in rows:
        verdict = r.get("verdict", "")
        if verdict not in ("keep", "drop", MISTAKE_VERDICT):
            continue

        word, pos, var = r["word"], r["pos"], (r.get("var") or "RRP")
        reviewed_shaw = r["shaw"]           # what the human saw / anchored to
        # Overrides fold into the authoritative `new` fields.
        new_pos = r.get("pos_override") or pos
        new_var = r.get("var_override") or var
        new_shaw = r.get("shaw_override") or reviewed_shaw
        new_ipa = r.get("ipa_override") or r.get("ipa", "")

        old = identity(word, pos, reviewed_shaw, var)

        if verdict == "drop":
            new = None
        else:  # keep or mistake-correction
            new = record(word, new_pos, new_shaw, new_var, new_ipa,
                         int(r.get("freq") or 0), r.get("source", ""), r.get("status", ""),
                         r.get("confidence", ""), r.get("notes", ""))

        out.append(make_patch(old, new, DEFAULT_AUTHOR,
                              origin="editorial",
                              note=(r.get("notes", "") if verdict == MISTAKE_VERDICT else "")))
    return out


def salvage_pos_gaps(rows):
    """verdict==keep rows from editorial-pos-gaps.csv."""
    out = []
    for r in rows:
        if r.get("verdict") != "keep":
            continue
        word = r["word"]
        pos = r.get("pos_override") or r["pos"]
        var = r.get("var_override") or (r.get("var") or "RRP")
        shaw = r.get("shaw_override") or r["shaw"]
        ipa = r.get("ipa_override") or r.get("ipa", "")
        reviewed_shaw = r["shaw"]
        reviewed_var = r.get("var") or "RRP"

        old = identity(word, r["pos"], reviewed_shaw, reviewed_var)
        new = record(word, pos, shaw, var, ipa, int(r.get("freq") or 0),
                     r.get("source", ""), r.get("status", ""),
                     r.get("confidence", ""), r.get("notes", ""))
        out.append(make_patch(old, new, DEFAULT_AUTHOR, origin="pos-gap", note=""))
    return out


def salvage_manual(rows):
    """editorial-manual.csv — authorship: old = null (records no source attests)."""
    out = []
    for r in rows:
        word = r["word"]
        pos = r.get("pos_override") or r["pos"]
        var = r.get("var_override") or (r.get("var") or "RRP")
        shaw = r.get("shaw_override") or r["shaw"]
        ipa = r.get("ipa_override") or r.get("ipa", "")
        new = record(word, pos, shaw, var, ipa, int(r.get("freq") or 0),
                     r.get("source", "manual") or "manual", r.get("status", "manual") or "manual",
                     r.get("confidence", ""), r.get("notes", ""))
        out.append(make_patch(None, new, DEFAULT_AUTHOR, origin="manual", note=""))
    return out


def main():
    editorial_rows = read_csv(EDITORIAL)
    pos_gap_rows = read_csv(POS_GAPS)
    manual_rows = read_csv(MANUAL)

    patches = []
    patches += salvage_editorial(editorial_rows)
    patches += salvage_pos_gaps(pos_gap_rows)
    patches += salvage_manual(manual_rows)

    # Report + integrity checks (fail loud on duplicate ids or malformed patches).
    ids = [p["id"] for p in patches]
    if len(ids) != len(set(ids)):
        dupes = [i for i in set(ids) if ids.count(i) > 1]
        raise SystemExit(f"FATAL: {len(dupes)} duplicate patch ids: {dupes[:5]}")

    n_add = sum(1 for p in patches if p["old"] is None)
    n_remove = sum(1 for p in patches if p["new"] is None)
    n_respell = sum(1 for p in patches
                    if p["old"] and p["new"]
                    and (p["old"]["shaw"], p["old"]["pos"], p["old"]["var"])
                    != (p["new"]["shaw"], p["new"]["pos"], p["new"]["var"]))
    n_update = len(patches) - n_add - n_remove - n_respell

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for p in patches:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"Wrote {len(patches):,} patches → {OUT_PATH.relative_to(PROJECT_ROOT)}")
    print(f"  authorship (old=null):      {n_add:,}")
    print(f"  removal    (new=null):      {n_remove:,}")
    print(f"  respell    (key changes):   {n_respell:,}")
    print(f"  update     (same key):      {n_update:,}")
    print(f"  by origin:")
    for o in sorted(set(p["meta"]["origin"] for p in patches)):
        print(f"    {o:12s} {sum(1 for p in patches if p['meta']['origin']==o):,}")


if __name__ == "__main__":
    main()
