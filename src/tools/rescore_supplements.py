#!/usr/bin/env python3
"""
Re-score confidence on existing supplement JSON files without re-parsing sources.

Reads supplement JSONs, re-runs confidence scoring (including shave consultation
for ALL entries if --full-shave is set), and writes updated files.

Usage:
    python3 src/tools/rescore_supplements.py                  # re-score, shave only for <89%
    python3 src/tools/rescore_supplements.py --full-shave     # consult shave for ALL entries
    python3 src/tools/rescore_supplements.py --britfone-only  # just Britfone (fast)
"""

import json
import subprocess
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ipa_to_shavian import score_confidence, upgrade_confidence_shave
from ml_ipa_normalizer import ml_normalize_ipa, load_model, strip_stress

PROJECT_ROOT = Path(__file__).parent.parent.parent

SUPPLEMENTS = [
    ("britfone", PROJECT_ROOT / "data" / "supplement-britfone.json"),
    ("wordnet", PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"),
]


def batch_shave(words: list[str], chunk_size: int = 5000) -> dict[str, str]:
    """Run words through shave -q in batches."""
    results = {}
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        try:
            proc = subprocess.run(
                ["shave", "-q"],
                input="\n".join(chunk),
                capture_output=True, text=True, timeout=120,
            )
            for word, line in zip(chunk, proc.stdout.strip().split("\n")):
                shaw = line.strip()
                if shaw:
                    results[word] = shaw
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"  Warning: shave error: {e}", file=sys.stderr)
    return results


def rescore_file(filepath: Path, ml_model, full_shave: bool) -> dict:
    """Re-score a single supplement file. Returns stats."""
    print(f"\nProcessing {filepath.name}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    stats = {"total": 0, "rescored": 0, "shave_upgraded": 0, "shave_overridden": 0}

    # Phase 1: re-score all entries
    for key, entries in data.items():
        for e in entries:
            stats["total"] += 1
            word = e.get("Latn", "")
            ipa = e.get("ipa", "")
            shaw = e.get("Shaw", "")
            var = e.get("var", "")

            # Get ML prediction (RSSB only)
            ml_shaw = None
            if var in ("RSSB", "RRP") and ml_model:
                try:
                    ipa_stripped = strip_stress(ipa)
                    ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
                    from ipa_to_shavian import ipa_to_shavian
                    ml_shaw = ipa_to_shavian(ml_ipa)
                except Exception:
                    pass

            new_pct, notes = score_confidence(word, ipa, shaw, ml_shaw)
            e["confidence"] = new_pct
            if notes:
                e["review"] = "; ".join(notes)
            elif "review" in e:
                del e["review"]
            e["_ml_shaw"] = ml_shaw
            stats["rescored"] += 1

    # Phase 2: shave consultation
    shave_threshold = 100 if full_shave else 89
    review_words = set()
    for key, entries in data.items():
        for e in entries:
            if e.get("confidence", 89) < shave_threshold:
                # Only shave RSSB/RRP entries (shave is UK-trained)
                if e.get("var", "") in ("RSSB", "RRP", "UNC"):
                    review_words.add(e["Latn"])

    if review_words:
        print(f"  Consulting shave for {len(review_words):,} words...")
        shave_results = batch_shave(sorted(review_words))
        print(f"  Got {len(shave_results):,} results")

        for key, entries in data.items():
            for e in entries:
                if e.get("confidence", 89) >= shave_threshold:
                    continue
                if e.get("var", "") not in ("RSSB", "RRP", "UNC"):
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue

                shave_shaw = shave_results[w]
                ml_shaw = e.get("_ml_shaw")
                notes = [n for n in e.get("review", "").split("; ") if n]

                new_pct, notes, override = upgrade_confidence_shave(
                    e["confidence"], notes, e["Shaw"], shave_shaw, ml_shaw
                )

                old_pct = e["confidence"]
                e["confidence"] = new_pct
                e["review"] = "; ".join(notes) if notes else ""

                if override:
                    e["Shaw"] = override
                    stats["shave_overridden"] += 1
                elif new_pct > old_pct:
                    stats["shave_upgraded"] += 1

    # Clean up
    new_data = {}
    conf_buckets = {"high (>=80)": 0, "medium (30-79)": 0, "low (<30)": 0}
    for key, entries in data.items():
        for e in entries:
            e.pop("_ml_shaw", None)
            if not e.get("review"):
                e.pop("review", None)
            pct = e.get("confidence", 89)
            if pct >= 80:
                conf_buckets["high (>=80)"] += 1
            elif pct >= 30:
                conf_buckets["medium (30-79)"] += 1
            else:
                conf_buckets["low (<30)"] += 1
        new_key = f"{entries[0]['Latn']}_{entries[0].get('pos','UNC')}_{entries[0]['Shaw']}"
        new_data[new_key] = entries

    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(new_data, f, ensure_ascii=False, indent=2)

    stats["conf_buckets"] = conf_buckets
    print(f"  Rescored: {stats['rescored']:,}")
    print(f"  Shave upgraded: {stats['shave_upgraded']:,}, overridden: {stats['shave_overridden']:,}")
    print(f"  Confidence: {conf_buckets}")
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-shave", action="store_true",
                        help="Consult shave for ALL entries, not just low-confidence")
    parser.add_argument("--britfone-only", action="store_true",
                        help="Only re-score Britfone (fast)")
    args = parser.parse_args()

    try:
        ml_model = load_model()
        print("Loaded ML model")
    except FileNotFoundError:
        ml_model = None
        print("No ML model found, skipping ML scoring")

    supplements = SUPPLEMENTS
    if args.britfone_only:
        supplements = [s for s in supplements if s[0] == "britfone"]

    for name, path in supplements:
        if not path.exists():
            print(f"Skipping {name}: {path} not found")
            continue
        rescore_file(path, ml_model, args.full_shave)


if __name__ == "__main__":
    main()
