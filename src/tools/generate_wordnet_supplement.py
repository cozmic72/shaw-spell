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
from ipa_to_shavian import ipa_to_shavian, normalize_ipa, check_missing_r
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


def _score_confidence(word: str, ipa: str, shaw_rules: str,
                      have_ml: bool, ml_model) -> tuple[str, str]:
    """Score conversion confidence based on multiple signals.

    Returns (confidence_level, review_notes) where:
        confidence_level: "high", "medium", or "low"
        review_notes: human-readable explanation of concerns (empty if high)
    """
    notes = []

    # Signal 1: ML model disagrees with rules
    if have_ml and ml_model:
        ipa_stripped = strip_stress(ipa)
        ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
        shaw_ml = ipa_to_shavian(ml_ipa)
        if shaw_ml != shaw_rules:
            notes.append(f"ml_disagrees:{shaw_ml}")

    # Signal 2: word has 'r' in spelling -- r-restoration may be incomplete
    word_lower = word.lower()
    if 'r' in word_lower:
        spelling_r_count = word_lower.count('r')
        ipa_r_count = ipa.count('r') + ipa.count('R')
        if spelling_r_count > ipa_r_count:
            notes.append(f"r_gap:spelling={spelling_r_count},ipa={ipa_r_count}")

    # Signal 3: unknown characters passed through
    known_shaw = set("𐑐𐑚𐑑𐑛𐑒𐑜𐑓𐑝𐑔𐑞𐑕𐑟𐑖𐑠𐑗𐑡𐑥𐑯𐑙𐑤𐑮𐑢𐑣𐑘𐑨𐑧𐑦𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿 -.'")
    unknown = set(shaw_rules) - known_shaw
    if unknown:
        notes.append(f"unknown_chars:{''.join(unknown)}")

    # Signal 4: word has 'r' in spelling but Shavian has NO r-sound at all
    missing_r = check_missing_r(word, shaw_rules)
    if missing_r:
        notes.append(missing_r)

    # Determine confidence level
    if not notes:
        return "high", ""
    elif any(n.startswith("unknown_chars") for n in notes):
        return "low", "; ".join(notes)
    elif any(n.startswith("missing_r") for n in notes):
        return "low", "; ".join(notes)
    elif any(n.startswith("ml_disagrees") for n in notes) and any(n.startswith("r_gap") for n in notes):
        return "low", "; ".join(notes)
    else:
        return "medium", "; ".join(notes)


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
    confidence_counts = {"high": 0, "medium": 0, "low": 0}

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
                        # Score confidence
                        confidence, review_notes = _score_confidence(
                            word_lower, ipa, shaw, have_ml, ml_model
                        )
                        confidence_counts[confidence] += 1

                        key = f"{word_lower}_{c5_pos}_{shaw}"
                        entry = {
                            "Latn": word_lower,
                            "Shaw": shaw,
                            "pos": c5_pos,
                            "ipa": ipa,
                            "freq": 0,
                            "var": "RRP",
                            "confidence": confidence,
                        }
                        if review_notes:
                            entry["review"] = review_notes
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

    # Consult `shave` tool for medium/low confidence entries
    review_words = set()
    for key, entries in reliable.items():
        for e in entries:
            if e.get("confidence") in ("medium", "low"):
                review_words.add(e["Latn"])

    if review_words:
        print(f"\n  Consulting `shave` tool for {len(review_words)} review words...")
        shave_results = _batch_shave(sorted(review_words))
        shave_upgraded = 0
        shave_overridden = 0
        for key, entries in reliable.items():
            for e in entries:
                if e.get("confidence") not in ("medium", "low"):
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue
                shave_shaw = shave_results[w]
                review = e.get("review", "")

                if shave_shaw == e["Shaw"]:
                    # shave agrees with our rules -- upgrade confidence
                    e["confidence"] = "medium" if e["confidence"] == "low" else "high"
                    e["review"] = review + "; shave_agrees"
                    shave_upgraded += 1
                else:
                    # Check if shave agrees with ML
                    ml_shaw = None
                    if "ml_disagrees:" in review:
                        ml_shaw = review.split("ml_disagrees:")[1].split(";")[0].strip()

                    if ml_shaw and shave_shaw == ml_shaw:
                        # shave + ML consensus overrides rules
                        old_shaw = e["Shaw"]
                        e["Shaw"] = shave_shaw
                        e["confidence"] = "high"
                        e["review"] = f"overridden:was={old_shaw}; shave+ml_consensus"
                        shave_overridden += 1
                    else:
                        e["review"] = review + f"; shave_says:{shave_shaw}"

        # Fix keys for overridden entries
        new_reliable = {}
        for key, entries in reliable.items():
            new_key = f"{entries[0]['Latn']}_{entries[0]['pos']}_{entries[0]['Shaw']}"
            new_reliable[new_key] = entries
        reliable = new_reliable

        print(f"  Upgraded {shave_upgraded} entries based on shave agreement")
        print(f"  Overrode {shave_overridden} entries based on shave+ML consensus")

        # Recount confidence after shave adjustments
        confidence_counts = {"high": 0, "medium": 0, "low": 0}
        for key, entries in reliable.items():
            for e in entries:
                confidence_counts[e.get("confidence", "high")] += 1

    print(f"\n  Confidence: high={confidence_counts['high']}, "
          f"medium={confidence_counts['medium']}, low={confidence_counts['low']}")

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


if __name__ == "__main__":
    main()
