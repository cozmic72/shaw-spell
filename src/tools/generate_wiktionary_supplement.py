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
from ipa_to_shavian import ipa_to_shavian, normalize_ipa, score_confidence, upgrade_confidence_shave
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

def _batch_shave(words: list[str], dialect: str = "british") -> dict[str, str]:
    """Run words through the `shave` tool and return word->shavian mapping.

    Args:
        words: list of words to transliterate
        dialect: "british" or "american" — selects the shave readlex dialect
    """
    try:
        input_text = "\n".join(words)
        flag = "--readlex-british" if dialect == "british" else "--readlex-american"
        result = subprocess.run(
            ["shave", "-q", flag],
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


def _compute_ml_shaw(word: str, ipa: str, dialect: str,
                     have_ml: bool, ml_model) -> str | None:
    """Get ML model's Shavian prediction, or None if unavailable.

    Only applies ML to RSSB entries (the model is UK-trained).
    For GenAm, returns None.
    """
    if dialect != "RSSB" or not have_ml or not ml_model:
        return None
    ipa_stripped = strip_stress(ipa)
    ml_ipa = ml_normalize_ipa(ipa_stripped, word, ml_model)
    return ipa_to_shavian(ml_ipa)


# Dialect tag classification
RSSB_TAGS = {"Received-Pronunciation", "UK", "British"}
GENAM_TAGS = {"General-American", "US"}


def classify_dialect(tags: list[str]) -> str | None:
    """Classify a list of tags into a dialect variant.

    Returns "RSSB", "GenAm", or None if no recognizable dialect tag.
    """
    tag_set = set(tags) if tags else set()
    has_rssb = bool(tag_set & RSSB_TAGS)
    has_genam = bool(tag_set & GENAM_TAGS)
    if has_rssb and not has_genam:
        return "RSSB"
    if has_genam and not has_rssb:
        return "GenAm"
    if has_rssb and has_genam:
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

    # Skip affix entries (e.g. "-ity", "giga-") — these aren't real words
    if word.startswith("-") or word.endswith("-"):
        stats["skipped_affix"] += 1
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

        # Skip fragment IPA (e.g. "-di", "ə-", "-ˌbiːoʊ-") — Wiktionary uses
        # leading/trailing hyphens to indicate partial pronunciations
        ipa_stripped = strip_ipa_delimiters(ipa_raw)
        if ipa_stripped.startswith("-") or ipa_stripped.endswith("-"):
            stats["skipped_fragment_ipa"] += 1
            continue

        ipa_clean = clean_ipa(ipa_raw)
        if not ipa_clean:
            continue

        stats["with_ipa"] += 1

        # Determine dialect for normalization source
        dialect = classify_dialect(tags)
        if dialect == "RSSB":
            norm_source = "wiktionary_rp"
        elif dialect == "GenAm":
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

        # Get ML prediction for confidence comparison (RSSB only)
        ml_shaw = _compute_ml_shaw(word, ipa_normalized, var, have_ml, ml_model)

        # Score confidence as percentage
        conf_pct, notes = score_confidence(word, ipa_normalized, shaw, ml_shaw)

        entry_data = {
            "Latn": word,
            "Shaw": shaw,
            "pos": pos,
            "ipa": ipa_normalized,
            "freq": 0,
            "var": var,
            "confidence": conf_pct,
        }
        if notes:
            entry_data["review"] = "; ".join(notes)
        # Stash ml_shaw for shave consultation later
        entry_data["_ml_shaw"] = ml_shaw

        # Bucket for initial stats
        if conf_pct >= 80:
            stats["confidence_high"] += 1
        elif conf_pct >= 30:
            stats["confidence_medium"] += 1
        else:
            stats["confidence_low"] += 1

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

    # Consult `shave` tool for entries below 89% confidence in reliable dict
    review_british = set()
    review_american = set()
    for key, entries in reliable.items():
        for e in entries:
            if e.get("confidence", 89) < 89:
                if e.get("var") == "RSSB":
                    review_british.add(e["Latn"])
                elif e.get("var") == "GenAm":
                    review_american.add(e["Latn"])

    shave_results_british = {}
    shave_results_american = {}

    if review_british:
        print(f"\n  Consulting `shave` tool for {len(review_british):,} RSSB review words...")
        review_list = sorted(review_british)
        BATCH_SIZE = 5000
        for batch_start in range(0, len(review_list), BATCH_SIZE):
            batch = review_list[batch_start:batch_start + BATCH_SIZE]
            batch_results = _batch_shave(batch, dialect="british")
            shave_results_british.update(batch_results)
            if batch_start > 0 and batch_start % 10000 == 0:
                print(f"    ...shave processed {batch_start:,}/{len(review_list):,}")
        print(f"  Got shave results for {len(shave_results_british):,} RSSB words.")

    if review_american:
        print(f"\n  Consulting `shave` tool for {len(review_american):,} GenAm review words...")
        review_list = sorted(review_american)
        BATCH_SIZE = 5000
        for batch_start in range(0, len(review_list), BATCH_SIZE):
            batch = review_list[batch_start:batch_start + BATCH_SIZE]
            batch_results = _batch_shave(batch, dialect="american")
            shave_results_american.update(batch_results)
            if batch_start > 0 and batch_start % 10000 == 0:
                print(f"    ...shave processed {batch_start:,}/{len(review_list):,}")
        print(f"  Got shave results for {len(shave_results_american):,} GenAm words.")

    if review_british or review_american:
        shave_upgraded = 0
        shave_overridden = 0
        for key, entries in reliable.items():
            for e in entries:
                if e.get("confidence", 89) >= 89:
                    continue
                var = e.get("var")
                if var == "RSSB":
                    shave_results = shave_results_british
                elif var == "GenAm":
                    shave_results = shave_results_american
                else:
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

        # Fix keys for overridden entries in reliable dict
        new_reliable = {}
        for key, entries in reliable.items():
            new_key = make_key(entries[0]["Latn"], entries[0]["pos"], entries[0]["Shaw"])
            new_reliable[new_key] = entries
        reliable = new_reliable

        print(f"  Upgraded {shave_upgraded:,} entries based on shave agreement")
        print(f"  Overrode {shave_overridden:,} entries based on shave+ML consensus")

    # Clean up internal fields and compute final stats
    conf_buckets = {"high (>=80)": 0, "medium (30-79)": 0, "low (<30)": 0}
    for d in (reliable, speculative):
        for key, entries in d.items():
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

    print(f"\n  Final confidence: {conf_buckets}")

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
    print(f"Skipped affix words:        {stats['skipped_affix']:,}")
    print(f"Skipped fragment IPA:       {stats['skipped_fragment_ipa']:,}")
    print(f"Shavian conversion errors:  {stats['shavian_errors']:,}")
    print(f"JSON parse errors:          {stats['json_errors']:,}")
    print()
    print(f"Reliable entries (dialect-labelled):")
    print(f"  Total:  {stats['reliable_entries']:,}")
    print(f"  RSSB:   {stats['dialect_RSSB']:,}")
    print(f"  GenAm:   {stats['dialect_GenAm']:,}")
    print(f"  Keys:   {len(reliable):,}")
    print()
    print(f"Speculative entries (no dialect label):")
    print(f"  Total:  {stats['speculative_entries']:,}")
    print(f"  Keys:   {len(speculative):,}")
    print()
    print(f"Confidence breakdown (final):")
    print(f"  {conf_buckets}")


if __name__ == "__main__":
    main()
