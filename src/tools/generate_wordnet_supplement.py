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
from pathlib import Path
from glob import glob

import yaml

# Add tools dir so we can import the IPA-to-Shavian converter
sys.path.insert(0, str(Path(__file__).parent))
from ipa_to_shavian import ipa_to_shavian, normalize_ipa

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
                        key = f"{word_lower}_{c5_pos}_{shaw}"
                        entry = {
                            "Latn": word_lower,
                            "Shaw": shaw,
                            "pos": c5_pos,
                            "ipa": ipa,
                            "freq": 0,
                            "var": "RRP",
                        }
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
