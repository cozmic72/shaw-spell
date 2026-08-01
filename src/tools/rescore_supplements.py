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
import re
import subprocess
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ipa_to_shavian import (contains_shavian, score_confidence,
                            upgrade_confidence_shave)
from ml_ipa_normalizer import ml_normalize_ipa, load_model, strip_stress

PROJECT_ROOT = Path(__file__).parent.parent.parent

SUPPLEMENTS = [
    ("britfone", PROJECT_ROOT / "data" / "supplement-britfone.json"),
    ("wordnet", PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json"),
    ("wiktionary", PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"),
]


# Shave labels its homograph-disambiguation diagnostics "Homograph:" (older
# builds said "WSD:" — accept both so the protection can't silently die again).
_WSD_RE = re.compile(
    r"^(?:WSD|Homograph):\s+(\S+)\s+->\s+(\S+)\s+(\d+)%\s+/\s+(\S+)\s+(\d+)%")


def _parse_wsd_stderr(stderr_text: str) -> dict[str, int]:
    """Parse shave's homograph (WSD) diagnostic lines from stderr.

    Each line like 'Homograph: tear -> 𐑑𐑺 53% / 𐑑𐑽 47%' tells us shave was uncertain
    about a homograph. Returns {word_lower: top_percent}. Words NOT in the dict
    were unambiguous (shave was confident about that token).
    """
    wsd = {}
    for line in stderr_text.split("\n"):
        m = _WSD_RE.match(line)
        if m:
            word = m.group(1).lower()
            top = int(m.group(3))
            # If a word appears on multiple WSD lines (different callsites),
            # keep the lowest confidence — most conservative.
            if word in wsd:
                wsd[word] = min(wsd[word], top)
            else:
                wsd[word] = top
    return wsd


def batch_shave(words: list[str], dialect: str = "british",
                chunk_size: int = 5000) -> tuple[dict[str, str], dict[str, int]]:
    """Run words through shave in batches.

    Returns (shaw_results, wsd_confidence). WSD values are shave's WSD
    top-choice percentage for homograph tokens; a missing entry means shave
    had no disambiguation doubts.

    Args:
        dialect: "british" or "american" — selects shave's readlex flag
    """
    flag = "-b" if dialect == "british" else "-a"
    # NB: we deliberately do NOT pass -q so that WSD diagnostic lines reach stderr.
    results: dict[str, str] = {}
    wsd: dict[str, int] = {}
    for i in range(0, len(words), chunk_size):
        chunk = words[i:i + chunk_size]
        try:
            # Separate words with BLANK lines so shave treats each as an
            # isolated token. Plain newlines make shave read the batch as a
            # SENTENCE, whose POS/phrase heuristics contaminate homograph
            # disambiguation across word boundaries (e.g. 'bow' 𐑚𐑴↔𐑚𐑬).
            proc = subprocess.run(
                ["shave", flag],
                input="\n\n".join(chunk),
                capture_output=True, text=True, timeout=120,
            )
            # shave ECHOES the blank separators, so filter empty output lines
            # before zipping. One non-blank line per input word — assert so a
            # mismatch fails loud instead of silently mis-aligning every word.
            out_lines = [l for l in proc.stdout.strip().split("\n") if l.strip()]
            if len(out_lines) != len(chunk):
                raise RuntimeError(
                    f"shave output/input count mismatch: {len(out_lines)} "
                    f"output lines for {len(chunk)} input words")
            for word, line in zip(chunk, out_lines):
                shaw = line.strip()
                # A line with no Shavian letters is shave's unknown-word/digit
                # echo, not an opinion — see contains_shavian.
                if shaw and contains_shavian(shaw):
                    results[word] = shaw
            # Merge WSD confidences from this chunk's stderr
            for w, pct in _parse_wsd_stderr(proc.stderr).items():
                if w in wsd:
                    wsd[w] = min(wsd[w], pct)
                else:
                    wsd[w] = pct
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"  Warning: shave error: {e}", file=sys.stderr)
    return results, wsd


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

    # Phase 2: shave consultation — British for RSSB/RRP, American for GenAm/GAM
    shave_threshold = 100 if full_shave else 89

    british_vars = {"RSSB", "RRP", "UNC", "SSB"}
    american_vars = {"GenAm", "GAM"}

    for dialect_label, dialect_flag, target_vars in [
        ("British", "british", british_vars),
        ("American", "american", american_vars),
    ]:
        review_words = set()
        for key, entries in data.items():
            for e in entries:
                if e.get("confidence", 89) < shave_threshold:
                    if e.get("var", "") in target_vars:
                        review_words.add(e["Latn"])

        if not review_words:
            continue

        print(f"  Consulting shave ({dialect_label}) for {len(review_words):,} words...")
        shave_results, wsd_confidence = batch_shave(sorted(review_words), dialect=dialect_flag)
        print(f"  Got {len(shave_results):,} results "
              f"({len(wsd_confidence):,} WSD-ambiguous words)")

        for key, entries in data.items():
            for e in entries:
                if e.get("confidence", 89) >= shave_threshold:
                    continue
                if e.get("var", "") not in target_vars:
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue

                shave_shaw = shave_results[w]
                ml_shaw = e.get("_ml_shaw")
                notes = [n for n in e.get("review", "").split("; ") if n]

                # WSD confidence: lookup by each token in the multi-word phrase
                # and take the MINIMUM (any ambiguous token taints the phrase).
                phrase_wsd = None
                for token in w.lower().split():
                    pct = wsd_confidence.get(token)
                    if pct is not None:
                        phrase_wsd = pct if phrase_wsd is None else min(phrase_wsd, pct)

                new_pct, notes, override = upgrade_confidence_shave(
                    e["confidence"], notes, e["Shaw"], shave_shaw, ml_shaw,
                    wsd_confidence=phrase_wsd,
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
