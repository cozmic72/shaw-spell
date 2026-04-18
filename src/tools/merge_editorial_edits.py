#!/usr/bin/env python3
"""
Left-join existing editorial.tsv edits onto a freshly-generated editorial.tsv.

Used after regenerating editorial.tsv from updated supplement data. Preserves
the user's verdict, shaw_override/pos_override/var_override/ipa_override, and
(for verdicted rows) notes. Also emits an audit file listing rows where the
regenerated shaw or ipa differs from the version the user originally reviewed.

Usage:
    python3 src/tools/merge_editorial_edits.py \
        --old data/editorial-preregen.tsv \
        --new data/editorial.tsv \
        --audit data/editorial-review-changes.tsv
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path


COLUMNS = [
    "word","pos","var","shaw","ipa","verdict",
    "shaw_override","pos_override","var_override","ipa_override",
    "source","status","confidence","notes",
]

PRESERVED_FIELDS = [
    "verdict", "shaw_override", "pos_override", "var_override", "ipa_override",
]


def read_tsv(path: Path) -> list[dict]:
    """Read a TSV into a list of clean dicts, tolerating CRLF."""
    with open(path, "rb") as f:
        content = f.read().decode("utf-8")
    lines = content.split("\n")
    reader = csv.DictReader(lines, delimiter="\t")
    rows = []
    for row in reader:
        cleaned = {}
        for k, v in row.items():
            if k is None:
                continue
            k = k.strip().rstrip("\r")
            cleaned[k] = v.strip().rstrip("\r") if v else ""
        if not cleaned.get("word"):
            continue
        for c in COLUMNS:
            if c not in cleaned:
                cleaned[c] = ""
        rows.append(cleaned)
    return rows


def format_field(val):
    s = str(val).replace("\t", " ").replace("\n", " ").replace("\r", "")
    if '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    elif "," in s:
        s = '"' + s + '"'
    return s


def write_tsv(path: Path, rows: list[dict]):
    out_lines = ["\t".join(COLUMNS)]
    for r in rows:
        out_lines.append("\t".join(format_field(r.get(c, "")) for c in COLUMNS))
    with open(path, "wb") as f:
        f.write("\r\n".join(out_lines).encode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="editorial.tsv BEFORE regeneration (the user's edits)")
    ap.add_argument("--new", required=True, help="editorial.tsv AFTER regeneration (fresh from supplements)")
    ap.add_argument("--audit", required=True, help="where to write the audit file for changed rows")
    args = ap.parse_args()

    old_path = Path(args.old)
    new_path = Path(args.new)
    audit_path = Path(args.audit)

    print(f"Reading old (pre-regen): {old_path}")
    old_rows = read_tsv(old_path)
    print(f"  {len(old_rows):,} rows")

    print(f"Reading new (post-regen): {new_path}")
    new_rows = read_tsv(new_path)
    print(f"  {len(new_rows):,} rows")

    # Index old rows by (word_lower, pos, var) — survives shaw/ipa changes
    # but keeps multiple entries distinct by dialect. Any verdict/override on
    # an old row is preserved onto the matching new row.
    #
    # When multiple old rows share the same (word, pos, var) — e.g. when the
    # user accepted one alternative spelling and dropped another — we prefer
    # the KEPT row (verdict=keep/supplemental) over dropped/blank rows, so
    # the merge keeps the verdicted decision.
    def _preference(row):
        v = row.get("verdict", "")
        if v in ("keep", "supplemental"):
            return 3
        if v == "drop":
            return 2
        if v:  # any other non-blank verdict (e.g. user comment)
            return 1
        return 0

    old_index: dict[tuple[str,str,str], list[dict]] = defaultdict(list)
    old_by_wps: dict[tuple[str,str,str], list[dict]] = defaultdict(list)  # word,pos,shaw
    for r in old_rows:
        key = (r["word"].lower(), r["pos"], r["var"])
        old_index[key].append(r)
        old_by_wps[(r["word"].lower(), r["pos"], r["shaw"])].append(r)
    for key in old_index:
        old_index[key].sort(key=_preference, reverse=True)
    for key in old_by_wps:
        old_by_wps[key].sort(key=_preference, reverse=True)

    # Build new key-index too, so we can find old rows that have no new match
    new_keys = {(r["word"].lower(), r["pos"], r["var"]) for r in new_rows}
    new_keys_wps = {(r["word"].lower(), r["pos"], r["shaw"]) for r in new_rows}

    # Track which old rows we've matched so we can report true lost verdicts
    matched_ids = set()

    # Apply merge
    preserved = 0
    changed_shaw = 0
    changed_ipa = 0
    lost_verdicts = []
    audit_rows = []

    for nr in new_rows:
        key = (nr["word"].lower(), nr["pos"], nr["var"])
        wps_key = (nr["word"].lower(), nr["pos"], nr["shaw"])
        match = None

        # First preference: same shaw via (word,pos,shaw) lookup — this picks up
        # the user's verdicted row even when its var collapsed or split during
        # regeneration. Top-ranked (by preference) within the bucket wins.
        if wps_key in old_by_wps:
            cand = old_by_wps[wps_key][0]
            if cand.get("verdict") or any(cand.get(f) for f in PRESERVED_FIELDS[1:]):
                match = cand

        # Second preference: same (word,pos,var), then match shaw if possible.
        if match is None and key in old_index:
            candidates = old_index[key]
            for c in candidates:
                if c["shaw"] == nr["shaw"]:
                    match = c
                    break
            if match is None:
                # No shaw match — use the top-ranked candidate
                match = candidates[0]

        if match is None:
            continue

        had_decision = bool(match.get("verdict") or any(match.get(f) for f in PRESERVED_FIELDS[1:]))
        if not had_decision and not match.get("notes", "").strip():
            continue  # nothing to preserve on this row
        matched_ids.add(id(match))

        # Preserve fields
        for f in PRESERVED_FIELDS:
            if match.get(f):
                nr[f] = match[f]
        if match.get("verdict") and match.get("notes"):
            # User notes on verdicted rows preserved as-is (machine notes
            # from regen get dropped).
            nr["notes"] = match["notes"]

        if had_decision:
            preserved += 1
            shaw_diff = match["shaw"] != nr["shaw"]
            ipa_diff = match["ipa"] != nr["ipa"]
            if shaw_diff:
                changed_shaw += 1
            if ipa_diff:
                changed_ipa += 1
            if shaw_diff or ipa_diff:
                audit_rows.append({
                    "word": nr["word"],
                    "pos": nr["pos"],
                    "var": nr["var"],
                    "verdict": match.get("verdict", ""),
                    "old_shaw": match["shaw"],
                    "new_shaw": nr["shaw"],
                    "old_ipa": match["ipa"],
                    "new_ipa": nr["ipa"],
                    "shaw_override": nr.get("shaw_override", ""),
                    "ipa_override": nr.get("ipa_override", ""),
                    "notes": nr.get("notes", ""),
                })

    # Find verdicted old rows that we failed to preserve onto any new row.
    for r in old_rows:
        if not r.get("verdict"):
            continue
        if id(r) not in matched_ids:
            lost_verdicts.append(r)

    # Write the merged new.tsv back in place
    write_tsv(new_path, new_rows)
    print(f"Wrote merged {new_path}")
    print(f"  Preserved decisions:     {preserved:,}")
    print(f"  Shaw changed under edit: {changed_shaw:,}")
    print(f"  IPA changed under edit:  {changed_ipa:,}")
    print(f"  Verdicted rows lost (no new match): {len(lost_verdicts):,}")

    # Write audit
    audit_cols = ["word","pos","var","verdict","old_shaw","new_shaw","old_ipa","new_ipa","shaw_override","ipa_override","notes"]
    with open(audit_path, "wb") as f:
        f.write("\t".join(audit_cols).encode("utf-8"))
        f.write(b"\r\n")
        for r in audit_rows:
            f.write("\t".join(format_field(r.get(c, "")) for c in audit_cols).encode("utf-8"))
            f.write(b"\r\n")
        # Also dump lost verdicts as a second section (prefix with #)
        if lost_verdicts:
            f.write("\r\n# LOST VERDICTS - existed in pre-regen with a verdict but not in post-regen\r\n".encode("utf-8"))
            f.write("\t".join(audit_cols).encode("utf-8"))
            f.write(b"\r\n")
            for r in lost_verdicts:
                lost_row = {
                    "word": r["word"], "pos": r["pos"], "var": r["var"],
                    "verdict": r["verdict"],
                    "old_shaw": r["shaw"], "new_shaw": "(MISSING)",
                    "old_ipa": r["ipa"], "new_ipa": "(MISSING)",
                    "shaw_override": r.get("shaw_override",""),
                    "ipa_override": r.get("ipa_override",""),
                    "notes": r.get("notes",""),
                }
                f.write("\t".join(format_field(lost_row.get(c, "")) for c in audit_cols).encode("utf-8"))
                f.write(b"\r\n")
    print(f"Wrote audit: {audit_path}")
    print(f"  Rows where reviewed shaw/ipa differs from post-regen: {len(audit_rows):,}")
    print(f"  Lost verdicts:                                        {len(lost_verdicts):,}")


if __name__ == "__main__":
    main()
