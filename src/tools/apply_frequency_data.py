#!/usr/bin/env python3
"""
Fill missing frequency data on data/readlex.json from a subtitle-derived corpus.

ReadLex ships a `freq` field, but ~13.5K of our distinct headwords carry no
ReadLex frequency (freq == 0): inflections, technical terms, rare words, and
every editorial supplement. This step credits those words with a frequency drawn
from an OpenSubtitles-derived word list (external/frequency-words, MIT-licensed).

Policy: FILL-WHERE-MISSING. A record whose freq is already > 0 (an authoritative
ReadLex frequency) is left untouched — the two corpora are scaled differently and
ReadLex is the primary authority where it speaks. Only freq == 0 records are
enriched, and the value written is tagged with `freq_source` so the provenance is
never ambiguous.

UK/US variants: the corpus is a single mixed-dialect "en" list holding both
spellings of a transatlantic pair, each with its own count. For a headword absent
from the corpus we consult its spelling variants (see spelling_variants.py) and
take the maximum count found across the headword and its variants — the dominant
attested form, without double-counting when both spellings coexist.

Idempotent and deterministic: re-running touches only freq == 0 records and reads
a fixed corpus file, so identical inputs yield an identical readlex.json.

Usage:
    python3 src/tools/apply_frequency_data.py
"""

import json
import sys
from pathlib import Path

from basis import PROJECT_ROOT
from spelling_variants import spelling_variants

READLEX_PATH = PROJECT_ROOT / "data" / "readlex.json"
CORPUS_PATH = PROJECT_ROOT / "external" / "frequency-words" / "content" / "2018" / "en" / "en_full.txt"
FREQ_SOURCE_TAG = "opensubtitles-2018"


def load_corpus():
    """Load the subtitle frequency list as {lowercase_word: count}."""
    if not CORPUS_PATH.exists():
        sys.exit(
            f"Corpus not found at {CORPUS_PATH.relative_to(PROJECT_ROOT)}.\n"
            "Check out the frequency-words submodule (lean, ~30 MB) with:\n"
            "  make setup"
        )

    corpus = {}
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) != 2:
                continue
            word, count = parts
            corpus[word] = int(count)
    if not corpus:
        sys.exit(f"Corpus at {CORPUS_PATH.relative_to(PROJECT_ROOT)} is empty.")
    return corpus


def corpus_frequency(word, corpus):
    """Best corpus count for a lowercase word, consulting UK/US variants.

    Returns 0 when neither the word nor any variant appears in the corpus.
    """
    best = corpus.get(word, 0)
    for variant in spelling_variants(word):
        best = max(best, corpus.get(variant, 0))
    return best


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Fill missing freq from the subtitle corpus")
    ap.add_argument("--in", dest="in_path", default=str(READLEX_PATH),
                    help="merged readlex to read (default: data/readlex.json)")
    ap.add_argument("--out", dest="out_path", default=str(READLEX_PATH),
                    help="enriched readlex to write (default: data/readlex.json)")
    args = ap.parse_args()
    in_path, out_path = Path(args.in_path), Path(args.out_path)

    corpus = load_corpus()

    with open(in_path, "r", encoding="utf-8") as f:
        readlex = json.load(f)

    records_filled = 0
    words_filled = set()
    records_unmatched = 0

    for entries in readlex.values():
        for entry in entries:
            if entry.get("freq", 0) > 0:
                continue
            word = entry["Latn"].lower()
            frequency = corpus_frequency(word, corpus)
            if frequency > 0:
                entry["freq"] = frequency
                entry["freq_source"] = FREQ_SOURCE_TAG
                records_filled += 1
                words_filled.add(word)
            else:
                records_unmatched += 1

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(readlex, f, ensure_ascii=False, indent=4)

    print(f"Corpus entries loaded:     {len(corpus)}")
    print(f"Records filled:            {records_filled}")
    print(f"Distinct words filled:     {len(words_filled)}")
    print(f"Records still without freq:{records_unmatched}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
