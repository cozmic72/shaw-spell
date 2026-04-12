#!/usr/bin/env python3
"""
Extract pronunciation data from Wiktionary JSONL dump and produce
ReadLex-format JSON supplement files.

Two output files:
  - data/supplement-wiktionary-reliable.json: entries with dialect-labelled IPA
  - data/supplement-wiktionary-speculative.json: entries with IPA but no dialect label

Usage:
    python3 src/tools/generate_wiktionary_supplement.py
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from collections import Counter

# Add tools directory to path for ipa_to_shavian
sys.path.insert(0, str(Path(__file__).parent))
from ipa_to_shavian import ipa_to_shavian, normalize_ipa
from ml_ipa_normalizer import ml_normalize_ipa, load_model, strip_stress

PROJECT_ROOT = Path(__file__).parent.parent.parent
WIKTIONARY_JSONL = PROJECT_ROOT / "external" / "wiktionary" / "kaikki.org-dictionary-English.jsonl"
RELIABLE_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json"
SPECULATIVE_OUTPUT = PROJECT_ROOT / "data" / "supplement-wiktionary-speculative.json"

# POS mapping: Wiktionary → CLAWS C5
POS_MAP = {
    "noun": "NN1",
    "verb": "VVI",
    "adj": "AJ0",
    "adv": "AV0",
    "prep": "PRP",
    "conj": "CJC",
    "pron": "PNP",
    "det": "DT0",
    "intj": "ITJ",
    "name": "NP0",
    "particle": "AV0",
    "num": "CRD",
    "phrase": "UNC",
    "prefix": "UNC",
    "suffix": "UNC",
    "infix": "UNC",
    "affix": "UNC",
    "abbrev": "UNC",
    "contraction": "UNC",
    "character": "UNC",
    "symbol": "UNC",
    "punct": "UNC",
}

def _batch_shave(words: list[str]) -> dict[str, str]:
    """Run words through the `shave` tool and return word->shavian mapping."""
    try:
        input_text = "\n".join(words)
        result = subprocess.run(
            ["shave", "-q"],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=120,
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
                      dialect: str, have_ml: bool, ml_model) -> tuple[str, str]:
    """Score conversion confidence based on multiple signals.

    For RSSB entries: check ML model agreement, r_gap, and unknown chars.
    For RGAM entries: only check r_gap and unknown chars (ML is UK-trained).

    Returns (confidence_level, review_notes).
    """
    notes = []

    # Signal 1: ML model disagrees with rules (RSSB only)
    if dialect == "RSSB" and have_ml and ml_model:
        ipa_stripped = strip_stress(ipa)
        ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
        shaw_ml = ipa_to_shavian(ml_ipa)
        if shaw_ml != shaw_rules:
            notes.append(f"ml_disagrees:{shaw_ml}")

    # Signal 2: word has 'r' in spelling — r-restoration may be incomplete
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

    # Determine confidence level
    if not notes:
        return "high", ""
    elif any(n.startswith("unknown_chars") for n in notes):
        return "low", "; ".join(notes)
    elif any(n.startswith("ml_disagrees") for n in notes) and any(n.startswith("r_gap") for n in notes):
        return "low", "; ".join(notes)
    else:
        return "medium", "; ".join(notes)


# Dialect tag classification
RSSB_TAGS = {"Received-Pronunciation", "UK", "British"}
RGAM_TAGS = {"General-American", "US"}


def classify_dialect(tags: list[str]) -> str | None:
    """Classify a list of tags into a dialect variant.

    Returns "RSSB", "RGAM", or None if no recognizable dialect tag.
    """
    tag_set = set(tags) if tags else set()
    has_rssb = bool(tag_set & RSSB_TAGS)
    has_rgam = bool(tag_set & RGAM_TAGS)
    if has_rssb and not has_rgam:
        return "RSSB"
    if has_rgam and not has_rssb:
        return "RGAM"
    if has_rssb and has_rgam:
        # Both — ambiguous, treat as unlabelled
        return None
    return None


def strip_ipa_delimiters(ipa: str) -> str:
    """Strip surrounding /.../ or [...] from IPA string."""
    ipa = ipa.strip()
    if len(ipa) >= 2:
        if (ipa[0] == '/' and ipa[-1] == '/') or (ipa[0] == '[' and ipa[-1] == ']'):
            ipa = ipa[1:-1]
    return ipa


def clean_ipa(ipa: str) -> str:
    """Clean Wiktionary IPA for use with ipa_to_shavian converter.

    Strips delimiters, removes syllable dots, and handles common
    Wiktionary conventions.
    """
    ipa = strip_ipa_delimiters(ipa)
    # Remove syllable boundary dots
    ipa = ipa.replace('.', '')
    # Remove tie bars
    ipa = ipa.replace('͡', '')
    # Remove parenthesized optional segments like (ə) — keep the content
    ipa = re.sub(r'\(([^)]*)\)', r'\1', ipa)
    return ipa


def is_broad_transcription(ipa_raw: str) -> bool:
    """Check if this is a broad (phonemic) transcription in slashes."""
    ipa_raw = ipa_raw.strip()
    return ipa_raw.startswith('/') and ipa_raw.endswith('/')


def make_key(word: str, pos: str, shaw: str) -> str:
    """Create a ReadLex-format key: word_POS_shaw"""
    return f"{word}_{pos}_{shaw}"


def process_entry(entry: dict, reliable: dict, speculative: dict, stats: Counter,
                   have_ml: bool = False, ml_model=None):
    """Process a single Wiktionary entry, adding to reliable or speculative dicts."""
    word = entry.get("word", "")
    pos_raw = entry.get("pos", "")
    sounds = entry.get("sounds", [])

    if not word or not sounds:
        return

    pos = POS_MAP.get(pos_raw, "UNC")
    stats["total_entries"] += 1

    # Collect IPA entries, preferring broad transcriptions
    for sound in sounds:
        ipa_raw = sound.get("ipa")
        if not ipa_raw:
            continue

        tags = sound.get("tags", [])

        # Prefer broad transcription (slashes) over narrow (brackets)
        # but accept narrow if that's all we have
        is_broad = is_broad_transcription(ipa_raw)

        ipa_clean = clean_ipa(ipa_raw)
        if not ipa_clean:
            continue

        stats["with_ipa"] += 1

        # Determine dialect for normalization source
        dialect = classify_dialect(tags)
        if dialect == "RSSB":
            norm_source = "wiktionary_rp"
        elif dialect == "RGAM":
            norm_source = "wiktionary_gam"
        else:
            norm_source = "wiktionary_rp"  # default guess for unlabelled

        # Normalize IPA to ReadLex conventions
        ipa_normalized = normalize_ipa(ipa_clean, word=word, source=norm_source)

        # Generate Shavian
        try:
            shaw = ipa_to_shavian(ipa_normalized)
        except Exception:
            stats["shavian_errors"] += 1
            continue

        if not shaw:
            continue

        var = dialect if dialect else "UNC"

        # Score confidence
        confidence, review_notes = _score_confidence(
            word, ipa_normalized, shaw, var, have_ml, ml_model
        )

        entry_data = {
            "Latn": word,
            "Shaw": shaw,
            "pos": pos,
            "ipa": ipa_normalized,
            "freq": 0,
            "var": var,
            "confidence": confidence,
        }
        if review_notes:
            entry_data["review"] = review_notes

        stats[f"confidence_{confidence}"] += 1

        key = make_key(word, pos, shaw)

        if dialect:
            stats[f"dialect_{dialect}"] += 1
            stats["reliable_entries"] += 1
            if key not in reliable:
                reliable[key] = []
            # Avoid exact duplicates
            if entry_data not in reliable[key]:
                reliable[key].append(entry_data)
        else:
            stats["speculative_entries"] += 1
            if key not in speculative:
                speculative[key] = []
            if entry_data not in speculative[key]:
                speculative[key].append(entry_data)


def main():
    if not WIKTIONARY_JSONL.exists():
        print(f"ERROR: Input file not found: {WIKTIONARY_JSONL}", file=sys.stderr)
        sys.exit(1)

    reliable = {}
    speculative = {}
    stats = Counter()

    # Load ML model for confidence comparison
    ml_model = None
    have_ml = False
    try:
        ml_model = load_model()
        have_ml = True
        print("Loaded ML model for confidence scoring.")
    except FileNotFoundError:
        print("Warning: ML model not found, skipping ML confidence comparison.")

    print(f"Processing {WIKTIONARY_JSONL}...")
    print("This may take a few minutes for ~1.45M lines.")
    print()

    with open(WIKTIONARY_JSONL, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i > 0 and i % 200000 == 0:
                print(f"  ...processed {i:,} lines ({stats['total_entries']:,} English entries with sounds)")

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                stats["json_errors"] += 1
                continue

            # Only English
            if entry.get("lang_code") != "en":
                stats["non_english"] += 1
                continue

            process_entry(entry, reliable, speculative, stats,
                          have_ml=have_ml, ml_model=ml_model)

    total_lines = i + 1
    print(f"  ...done. {total_lines:,} total lines.")
    print()

    print(f"  Initial confidence: high={stats['confidence_high']:,}, "
          f"medium={stats['confidence_medium']:,}, low={stats['confidence_low']:,}")

    # Consult `shave` tool for medium/low confidence RSSB entries in reliable dict
    review_words = set()
    for key, entries in reliable.items():
        for e in entries:
            if e.get("confidence") in ("medium", "low") and e.get("var") == "RSSB":
                review_words.add(e["Latn"])

    if review_words:
        print(f"\n  Consulting `shave` tool for {len(review_words):,} RSSB review words...")
        # Batch in chunks to avoid overwhelming subprocess
        review_list = sorted(review_words)
        shave_results = {}
        BATCH_SIZE = 5000
        for batch_start in range(0, len(review_list), BATCH_SIZE):
            batch = review_list[batch_start:batch_start + BATCH_SIZE]
            batch_results = _batch_shave(batch)
            shave_results.update(batch_results)
            if batch_start > 0 and batch_start % 10000 == 0:
                print(f"    ...shave processed {batch_start:,}/{len(review_list):,}")

        print(f"  Got shave results for {len(shave_results):,} words.")

        shave_upgraded = 0
        shave_overridden = 0
        for key, entries in reliable.items():
            for e in entries:
                if e.get("confidence") not in ("medium", "low"):
                    continue
                if e.get("var") != "RSSB":
                    continue
                w = e["Latn"]
                if w not in shave_results:
                    continue
                shave_shaw = shave_results[w]
                review = e.get("review", "")

                if shave_shaw == e["Shaw"]:
                    # shave agrees with our rules — upgrade confidence
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

        # Fix keys for overridden entries in reliable dict
        new_reliable = {}
        for key, entries in reliable.items():
            new_key = make_key(entries[0]["Latn"], entries[0]["pos"], entries[0]["Shaw"])
            new_reliable[new_key] = entries
        reliable = new_reliable

        print(f"  Upgraded {shave_upgraded:,} entries based on shave agreement")
        print(f"  Overrode {shave_overridden:,} entries based on shave+ML consensus")

    # Recount confidence across both dicts
    final_confidence = Counter()
    for d in (reliable, speculative):
        for key, entries in d.items():
            for e in entries:
                final_confidence[e.get("confidence", "high")] += 1

    print(f"\n  Final confidence: high={final_confidence['high']:,}, "
          f"medium={final_confidence['medium']:,}, low={final_confidence['low']:,}")

    # Write outputs
    print(f"Writing reliable supplement ({len(reliable):,} keys)...")
    RELIABLE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(RELIABLE_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(reliable, f, ensure_ascii=False, indent=2)
    print(f"  -> {RELIABLE_OUTPUT}")

    print(f"Writing speculative supplement ({len(speculative):,} keys)...")
    with open(SPECULATIVE_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(speculative, f, ensure_ascii=False, indent=2)
    print(f"  -> {SPECULATIVE_OUTPUT}")

    print()
    print("=== Summary ===")
    print(f"Total lines in JSONL:       {total_lines:,}")
    print(f"Non-English skipped:        {stats['non_english']:,}")
    print(f"English entries with sounds: {stats['total_entries']:,}")
    print(f"Sound items with IPA:       {stats['with_ipa']:,}")
    print(f"Shavian conversion errors:  {stats['shavian_errors']:,}")
    print(f"JSON parse errors:          {stats['json_errors']:,}")
    print()
    print(f"Reliable entries (dialect-labelled):")
    print(f"  Total:  {stats['reliable_entries']:,}")
    print(f"  RSSB:   {stats['dialect_RSSB']:,}")
    print(f"  RGAM:   {stats['dialect_RGAM']:,}")
    print(f"  Keys:   {len(reliable):,}")
    print()
    print(f"Speculative entries (no dialect label):")
    print(f"  Total:  {stats['speculative_entries']:,}")
    print(f"  Keys:   {len(speculative):,}")
    print()
    print(f"Confidence breakdown (final):")
    print(f"  High:   {final_confidence['high']:,}")
    print(f"  Medium: {final_confidence['medium']:,}")
    print(f"  Low:    {final_confidence['low']:,}")


if __name__ == "__main__":
    main()
