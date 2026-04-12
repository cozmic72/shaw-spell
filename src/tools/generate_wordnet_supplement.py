#!/usr/bin/env python3
"""
Extract words from Open English WordNet YAML entries and produce
ReadLex-format JSON supplement files.

Outputs:
  data/supplement-wordnet-reliable.json   -- entries with IPA (Shavian generated)
  data/supplement-wordnet-speculative.json -- entries without IPA (empty Shaw/ipa)
"""

import sys
import json
import re
import subprocess
from pathlib import Path
from glob import glob

import yaml

# Add tools dir so we can import the IPA-to-Shavian converter
sys.path.insert(0, str(Path(__file__).parent))
from ipa_to_shavian import ipa_to_shavian, normalize_ipa, score_confidence, upgrade_confidence_shave
from ml_ipa_normalizer import ml_normalize_ipa, load_model, strip_stress

ROOT = Path(__file__).resolve().parent.parent.parent
YAML_DIR = ROOT / "external" / "english-wordnet" / "src" / "yaml"
READLEX_PATH = ROOT / "external" / "readlex" / "readlex.json"
OUT_RELIABLE = ROOT / "data" / "supplement-wordnet-reliable.json"
OUT_SPECULATIVE = ROOT / "data" / "supplement-wordnet-speculative.json"

# WordNet POS -> CLAWS C5
POS_MAP = {
    "n": "NN1",
    "v": "VVI",
    "a": "AJ0",
    "s": "AJ0",
    "r": "AV0",
}


def is_single_word(word: str) -> bool:
    """Return True if word contains no spaces (single-word entry)."""
    return " " not in word


def strip_ipa(raw: str) -> str:
    """Strip surrounding slashes and whitespace from IPA value."""
    raw = raw.strip()
    if raw.startswith("/") and raw.endswith("/"):
        raw = raw[1:-1]
    return raw


def pick_pronunciation(pron_list: list) -> str | None:
    """Pick the best IPA pronunciation from a list of pronunciation dicts.

    Prefer GB variety, then no-variety, then US, then first available.
    """
    if not pron_list:
        return None

    gb = None
    us = None
    plain = None

    for p in pron_list:
        val = p.get("value")
        if not val:
            continue
        variety = p.get("variety")
        if variety == "GB":
            gb = val
        elif variety == "US":
            us = val
        elif variety is None:
            plain = val

    # Prefer GB (closer to RP which ReadLex targets), then plain, then US
    chosen = gb or plain or us
    if chosen is None and pron_list:
        # Fallback: first entry with a value
        for p in pron_list:
            if p.get("value"):
                return strip_ipa(p["value"])
    if chosen is not None:
        return strip_ipa(chosen)
    return None


def load_readlex_keys() -> set[str]:
    """Load ReadLex and return set of (word_lower, pos) tuples."""
    keys = set()
    with open(READLEX_PATH) as f:
        readlex = json.load(f)
    for entries in readlex.values():
        for entry in entries:
            keys.add((entry["Latn"].lower(), entry["pos"]))
    return keys


def _batch_shave(words: list[str]) -> dict[str, str]:
    """Run words through the `shave` tool and return word->shavian mapping."""
    try:
        input_text = "\n".join(words)
        result = subprocess.run(
            ["shave", "-q"],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=60,
        )
        lines = result.stdout.strip().split("\n")
        mapping = {}
        for word, shaw_line in zip(words, lines):
            shaw = shaw_line.strip()
            if shaw:
                mapping[word] = shaw
        return mapping
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  Warning: shave tool unavailable: {e}", file=sys.stderr)
        return {}


def _compute_ml_shaw(word: str, ipa: str, have_ml: bool, ml_model) -> str | None:
    """Get ML model's Shavian prediction, or None if unavailable."""
    if not have_ml or not ml_model:
        return None
    ipa_stripped = strip_stress(ipa)
    ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
    return ipa_to_shavian(ml_ipa)


def main():
    yaml_files = sorted(glob(str(YAML_DIR / "entries-*.yaml")))
    if not yaml_files:
        print(f"ERROR: No YAML files found in {YAML_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(yaml_files)} YAML entry files")

    readlex_keys = load_readlex_keys()
    print(f"ReadLex has {len(readlex_keys)} (word, pos) pairs")

    reliable = {}   # word+pos+shaw -> entry list
    speculative = {}
    total_entries = 0
    with_ipa_count = 0
    without_ipa_count = 0
    skipped_multi = 0
    overlap_count = 0
    conversion_errors = 0
    conf_buckets = {"high (>=80)": 0, "medium (30-79)": 0, "low (<30)": 0}

    # Load ML model for confidence comparison
    try:
        ml_model = load_model()
        have_ml = True
        print("Loaded ML model for confidence scoring")
    except FileNotFoundError:
        ml_model = None
        have_ml = False
        print("  Warning: ML model not found, skipping ML confidence comparison")

    for yf in yaml_files:
        print(f"  Processing {Path(yf).name}...")
        with open(yf) as f:
            data = yaml.safe_load(f)
        if not data:
            continue

        for word, pos_dict in data.items():
            if not is_single_word(word):
                skipped_multi += 1
                continue

            for wn_pos, pos_data in pos_dict.items():
                c5_pos = POS_MAP.get(wn_pos)
                if c5_pos is None:
                    continue

                pron_list = pos_data.get("pronunciation", [])
                ipa = pick_pronunciation(pron_list) if pron_list else None

                total_entries += 1
                word_lower = word.lower()

                if ipa:
                    # Normalize IPA to ReadLex conventions (GB = non-rhotic RP-like)
                    ipa = normalize_ipa(ipa, word=word_lower, source="wiktionary_rp")
                    # Try Shavian conversion
                    try:
                        shaw = ipa_to_shavian(ipa)
                    except Exception as e:
                        conversion_errors += 1
                        shaw = ""
                        ipa = ""

                    if shaw:
                        # Get ML prediction for confidence comparison
                        ml_shaw = _compute_ml_shaw(word_lower, ipa, have_ml, ml_model)

                        # Score confidence as percentage
                        conf_pct, notes = score_confidence(word_lower, ipa, shaw, ml_shaw)

                        key = f"{word_lower}_{c5_pos}_{shaw}"
                        entry = {
                            "Latn": word_lower,
                            "Shaw": shaw,
                            "pos": c5_pos,
                            "ipa": ipa,
                            "freq": 0,
                            "var": "RRP",
                            "confidence": conf_pct,
                        }
                        if notes:
                            entry["review"] = "; ".join(notes)
                        # Stash ml_shaw for shave consultation later
                        entry["_ml_shaw"] = ml_shaw
                        if key not in reliable:
                            reliable[key] = [entry]
                            with_ipa_count += 1
                        # else: duplicate, skip
                    else:
                        # Conversion produced empty string, treat as speculative
                        key = f"{word_lower}_{c5_pos}_"
                        entry = {
                            "Latn": word_lower,
                            "Shaw": "",
                            "pos": c5_pos,
                            "ipa": "",
                            "freq": 0,
                            "var": "UNC",
                        }
                        if key not in speculative:
                            speculative[key] = [entry]
                            without_ipa_count += 1
                else:
                    key = f"{word_lower}_{c5_pos}_"
                    entry = {
                        "Latn": word_lower,
                        "Shaw": "",
                        "pos": c5_pos,
                        "ipa": "",
                        "freq": 0,
                        "var": "UNC",
                    }
                    if key not in speculative:
                        speculative[key] = [entry]
                        without_ipa_count += 1

                if (word_lower, c5_pos) in readlex_keys:
                    overlap_count += 1

    # Consult `shave` tool for entries below 89% confidence
    review_words = set()
    for key, entries in reliable.items():
        for e in entries:
            if e.get("confidence", 89) < 89:
                review_words.add(e["Latn"])

    if review_words:
        print(f"\n  Consulting `shave` tool for {len(review_words)} review words...")
        shave_results = _batch_shave(sorted(review_words))
        shave_upgraded = 0
        shave_overridden = 0
        for key, entries in reliable.items():
            for e in entries:
                if e.get("confidence", 89) >= 89:
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue
                shave_shaw = shave_results[w]
                ml_shaw = e.pop("_ml_shaw", None)
                notes = [n for n in e.get("review", "").split("; ") if n]

                new_pct, notes, override = upgrade_confidence_shave(
                    e["confidence"], notes, e["Shaw"], shave_shaw, ml_shaw
                )
                e["confidence"] = new_pct
                e["review"] = "; ".join(notes) if notes else ""
                if override:
                    e["Shaw"] = override
                    shave_overridden += 1
                elif new_pct > e.get("confidence", 0):
                    shave_upgraded += 1

        # Fix keys for overridden entries
        new_reliable = {}
        for key, entries in reliable.items():
            new_key = f"{entries[0]['Latn']}_{entries[0]['pos']}_{entries[0]['Shaw']}"
            new_reliable[new_key] = entries
        reliable = new_reliable

        print(f"  Upgraded {shave_upgraded} entries based on shave agreement")
        print(f"  Overrode {shave_overridden} entries based on shave+ML consensus")

    # Clean up internal fields and compute stats
    for key, entries in reliable.items():
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

    print(f"\n  Confidence: {conf_buckets}")

    # Write outputs
    OUT_RELIABLE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUT_RELIABLE, "w") as f:
        json.dump(reliable, f, ensure_ascii=False, indent=4)
    print(f"\nWrote {len(reliable)} reliable entries to {OUT_RELIABLE}")

    with open(OUT_SPECULATIVE, "w") as f:
        json.dump(speculative, f, ensure_ascii=False, indent=4)
    print(f"Wrote {len(speculative)} speculative entries to {OUT_SPECULATIVE}")

    print(f"\n--- Summary ---")
    print(f"Total single-word entries processed: {total_entries}")
    print(f"  With IPA (reliable):    {with_ipa_count}")
    print(f"  Without IPA (speculative): {without_ipa_count}")
    print(f"  Shavian conversion errors: {conversion_errors}")
    print(f"Skipped multi-word phrases: {skipped_multi}")
    print(f"Overlap with ReadLex (word+pos): {overlap_count}")
    print(f"Confidence: {conf_buckets}")


if __name__ == "__main__":
    main()
