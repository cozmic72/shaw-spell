#!/usr/bin/env python3
"""
Regenerate data/editorial-pos-gaps.tsv from current supplement + ReadLex state.

Re-runs the gap analysis (a word in ReadLex with POS-tags missing that
supplements can fill) and preserves any verdict/overrides/notes from the
existing editorial-pos-gaps.tsv via (word_lower, pos, var) key.

Usage:
    python3 src/tools/regenerate_pos_gaps.py
"""

import csv
import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.parent
READLEX_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
POS_GAPS_PATH = PROJECT_ROOT / "data" / "editorial-pos-gaps.tsv"
SUPPLEMENTS = [
    ("wordnet",    PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"),
]

COLUMNS = [
    "word","pos","var","shaw","ipa","verdict",
    "shaw_override","pos_override","var_override","ipa_override",
    "source","status","confidence","notes",
]

PRESERVED_FIELDS = [
    "verdict", "shaw_override", "pos_override", "var_override", "ipa_override",
]


def format_field(val):
    s = str(val).replace("\t", " ").replace("\n", " ").replace("\r", "")
    if '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    elif "," in s:
        s = '"' + s + '"'
    return s


def load_existing(path: Path) -> dict[tuple, dict]:
    """Index existing pos-gaps rows by (word_lower, pos, var) → row."""
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        content = f.read().decode("utf-8")
    lines = content.split("\n")
    reader = csv.DictReader(lines, delimiter="\t")
    index: dict[tuple, dict] = {}
    for row in reader:
        cleaned = {}
        for k, v in row.items():
            if k is None:
                continue
            cleaned[k.strip().rstrip("\r")] = v.strip().rstrip("\r") if v else ""
        if not cleaned.get("word"):
            continue
        key = (cleaned["word"].lower(), cleaned["pos"], cleaned["var"])
        index[key] = cleaned
    return index


def index_readlex():
    """word_lower -> {pos -> set of shaw}."""
    rl = json.load(open(READLEX_PATH))
    idx = defaultdict(lambda: defaultdict(set))
    for k, entries in rl.items():
        for e in entries:
            idx[e.get("Latn","").lower()][e.get("pos","")].add(e.get("Shaw",""))
    return idx


def index_supplement(path):
    """word_lower -> pos -> shaw -> {Latn, var, ipa}."""
    sup = json.load(open(path))
    idx = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for k, entries in sup.items():
        for e in entries:
            idx[e.get("Latn","").lower()][e.get("pos","")][e.get("Shaw","")] = {
                "Latn": e.get("Latn",""),
                "var": e.get("var",""),
                "ipa": e.get("ipa",""),
            }
    return idx


def build_candidates(rl_idx, supplements_idx):
    """Return {(word_lower, pos, shaw) -> dict with metadata}."""
    candidates: dict[tuple, dict] = {}

    for src_name, sup_idx in supplements_idx.items():
        for word, pos_map in sup_idx.items():
            if word not in rl_idx:
                continue
            rl_shaws = set().union(*rl_idx[word].values())
            sup_shaws = set()
            for posmap in pos_map.values():
                sup_shaws |= set(posmap.keys())
            agreed = rl_shaws & sup_shaws
            if not agreed:
                continue
            rl_pos = set(rl_idx[word].keys())

            for pos, shaw_map in pos_map.items():
                if pos in rl_pos:
                    continue
                for shaw, meta in shaw_map.items():
                    shifted = shaw not in rl_shaws
                    key = (word, pos, shaw)
                    if key not in candidates:
                        candidates[key] = {
                            "word": meta["Latn"],
                            "pos": pos,
                            "shaw": shaw,
                            "shifted": shifted,
                            "rl_pos": sorted(rl_pos),
                            "rl_shaws": sorted(rl_shaws),
                            "sources": set(),
                            "vars": set(),
                            "ipas": set(),
                        }
                    candidates[key]["sources"].add(src_name)
                    if meta["var"]:
                        candidates[key]["vars"].add(meta["var"])
                    if meta["ipa"]:
                        candidates[key]["ipas"].add(meta["ipa"])
    return candidates


def score(cand):
    rl_pos = set(cand["rl_pos"])
    pos = cand["pos"]
    multi = len(cand["sources"]) >= 2
    shifted = cand["shifted"]

    if shifted:
        if pos == "VVI" and rl_pos & {"VVD","VVN","VVZ","VVG"}:
            return 20 if multi else 10
        if {pos} & {"NN1","VVI","AJ0","AV0"} and rl_pos & {"NN1","VVI","AJ0","AV0"}:
            return 55 if multi else 40
        if pos == "NN1" and "NP0" in rl_pos:
            return 45 if multi else 30
        return 35 if multi else 20

    # agreed-shaw scoring
    if pos == "NN1" and rl_pos == {"NP0"} and multi: return 95
    if pos == "NN1" and "NP0" in rl_pos: return 75 if multi else 60
    if {pos} & {"NN1","AJ0","AV0"} and rl_pos & {"NN1","AJ0","AV0"}:
        return 70 if multi else 50
    if pos == "AJ0" and rl_pos & {"VVN","VVD"}: return 65 if multi else 45
    if pos == "AJ0" and rl_pos & {"AJC","AJS"}: return 40 if multi else 25
    if pos == "VVI" and rl_pos & {"VVD","VVN","VVZ","VVG"}: return 30 if multi else 15
    return 50 if multi else 35


def main():
    existing = load_existing(POS_GAPS_PATH)
    print(f"Existing pos-gaps: {len(existing):,} rows")

    rl_idx = index_readlex()
    sup_idx = {name: index_supplement(p) for name, p in SUPPLEMENTS}
    cands = build_candidates(rl_idx, sup_idx)
    print(f"Candidates found: {len(cands):,}")

    rows = []
    preserved = 0
    high_conf_keeps = 0
    for cand in cands.values():
        conf = score(cand)
        shifted = cand["shifted"]
        var = sorted(cand["vars"])[0] if cand["vars"] else "RRP"
        ipa = sorted(cand["ipas"])[0] if cand["ipas"] else ""
        srcs = "+".join(sorted(cand["sources"]))
        status = "pos-gap-shifted" if shifted else "pos-gap"
        note_prefix = "SHIFTED" if shifted else "agreed"
        rl_shaws_summary = "/".join(cand["rl_shaws"][:3])
        note = f"rl_pos={','.join(cand['rl_pos'])}; rl_shaw={rl_shaws_summary}; {note_prefix} via {srcs}"

        # Default verdict: keep for conf>=90 (the high-confidence NP0→NN1 pattern)
        default_verdict = "keep" if conf >= 90 else ""
        if default_verdict == "keep":
            high_conf_keeps += 1

        row = {
            "word": cand["word"],
            "pos": cand["pos"],
            "var": var,
            "shaw": cand["shaw"],
            "ipa": ipa,
            "verdict": default_verdict,
            "shaw_override": "",
            "pos_override": "",
            "var_override": "",
            "ipa_override": "",
            "source": "pos-gap",
            "status": status,
            "confidence": str(conf),
            "notes": note,
        }

        # Left-join preserve from existing
        exist_key = (cand["word"].lower(), cand["pos"], var)
        if exist_key in existing:
            old = existing[exist_key]
            has_user_edit = any(old.get(f) for f in PRESERVED_FIELDS) or old.get("notes","") not in ("", note)
            if has_user_edit:
                for f in PRESERVED_FIELDS:
                    if old.get(f):
                        row[f] = old[f]
                # Preserve user notes on verdicted rows
                if old.get("verdict") and old.get("notes"):
                    row["notes"] = old["notes"]
                preserved += 1
        rows.append(row)

    rows.sort(key=lambda r: (r["word"].lower(), r["pos"], r["shaw"]))

    out_lines = ["\t".join(COLUMNS)]
    for r in rows:
        out_lines.append("\t".join(format_field(r.get(c, "")) for c in COLUMNS))
    with open(POS_GAPS_PATH, "wb") as f:
        f.write("\r\n".join(out_lines).encode("utf-8"))

    print(f"Wrote {POS_GAPS_PATH}: {len(rows):,} rows")
    print(f"  Preserved edits from prior version: {preserved:,}")
    print(f"  Default-verdict=keep (conf>=90):   {high_conf_keeps:,}")


if __name__ == "__main__":
    main()
