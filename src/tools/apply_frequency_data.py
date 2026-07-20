#!/usr/bin/env python3
"""
Set every record's frequency from a subtitle-derived corpus, one coherent scale.

ReadLex ships a `freq` field, but its counts are on ReadLex's own corpus scale —
not comparable to the OpenSubtitles-derived list (external/frequency-words,
MIT-licensed) we use for the ~13.5K headwords ReadLex leaves at freq 0. A mixed
dictionary (some words on ReadLex's scale, some on ours) cannot be sorted or
thresholded meaningfully. So we put EVERY word on ONE scale — ours.

Policy: REPLACE-ALL-FROM-CORPUS. Each record's `freq` becomes its OpenSubtitles
count (via the word and its UK/US variants, taking the max). Records the corpus
does not cover drop to freq 0. To honour "don't throw away data", a record that
HAD a non-zero ReadLex freq keeps it in `freq_readlex` before we overwrite `freq`;
records that never had a ReadLex freq gain no such field. Corpus-sourced freq is
tagged `freq_source` so provenance is never ambiguous.

UK/US variants: the corpus is a single mixed-dialect "en" list holding both
spellings of a transatlantic pair, each with its own count. We consult a
headword's spelling variants (see spelling_variants.py) and take the maximum
count across the headword and its variants — the dominant attested form, without
double-counting when both spellings coexist.

The enrichment logic (enrich_all) is shared: the editor's basis (src/tools/basis.py)
applies the SAME replace-all pass to its review-pool candidates, so a candidate and
the readlex record it eventually becomes carry an identical freq.

Idempotent and deterministic: the value written depends only on the fixed corpus,
so identical inputs yield an identical readlex.json.

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

# Contraction-fragment blocklist.
#
# The OpenSubtitles corpus was tokenised by splitting on the apostrophe, so every
# contraction contributes an inflated fake "word": a bare STEM (isn't -> isn) plus
# a leading-apostrophe TAIL (isn't -> 't, you're -> 're). These fragments carry
# enormous counts ('s = 14.3M, 't = 9.6M, isn = 429K, ...) that our freq join
# would otherwise hand to any record whose headword literally spells the fragment
# (isn, ain, shan, the 's/'d pseudo-headwords, and 'em -> Em) — floating pure junk
# to the top of the frequency-sorted review. We drop these tokens from the corpus
# in-memory BEFORE the join so they contribute no frequency to any record.
#
# Only PURE non-words are listed. Real English words that merely collide with a
# fragment are deliberately KEPT with their (over-counted) frequency:
#   - don   (put on)          — dominant sense is don't -> don, but a real word
#   - won   (past of win / KRW)
#   - haven (harbour)
#   - can, em                  — genuinely frequent / real, minor over-count only
# `ain` is arguably a rare dialectal word, but per the owner its 166K count is the
# isn't/ain't fragment share, not the word, so it is blocklisted.
FRAGMENT_BLOCKLIST = frozenset({
    # Leading-apostrophe clitic tails
    "'s", "'t", "'m", "'re", "'ll", "'ve", "'d",
    # Apostrophe-stripped contraction stems that are NOT real words
    "isn", "ain", "doesn", "didn", "wasn", "wouldn", "couldn",
    "hadn", "hasn", "weren", "aren", "shouldn", "mustn", "needn",
    "shan", "mightn", "oughtn", "daren",
})
# The corpus stores tokens lowercase and the headword join lowercases too, so the
# blocklist must be lowercase to match. Verified once at import.
assert all(t == t.lower() for t in FRAGMENT_BLOCKLIST), "blocklist tokens must be lowercase"


def load_corpus():
    """Load the subtitle frequency list as {lowercase_word: count}.

    Contraction-fragment tokens (see FRAGMENT_BLOCKLIST) are dropped so they
    contribute no inflated frequency to the join.
    """
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
            if word in FRAGMENT_BLOCKLIST:
                continue
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


def enrich_entry(entry, corpus, stats):
    """Set `entry["freq"]` to its corpus frequency, replacing any prior value.

    A non-zero ReadLex freq being overwritten is preserved in `freq_readlex`
    first. The corpus value (including 0 when uncovered) becomes `freq`; a covered
    record is tagged `freq_source`. Mutates `entry` in place and tallies `stats`.
    """
    # A record already carrying our tag holds a prior corpus value, not a ReadLex
    # one — re-running must not mistake it for a ReadLex freq to stash. So the
    # original ReadLex freq is captured only on the first pass (no tag yet).
    was_readlex = entry.get("freq_source") != FREQ_SOURCE_TAG
    prior = entry.get("freq", 0)
    if was_readlex and prior > 0 and "freq_readlex" not in entry:
        entry["freq_readlex"] = prior

    frequency = corpus_frequency(entry["Latn"].lower(), corpus)
    entry["freq"] = frequency
    if frequency > 0:
        entry["freq_source"] = FREQ_SOURCE_TAG
        stats["gained"] += prior == 0
        stats["replaced"] += prior > 0
    else:
        entry.pop("freq_source", None)
        stats["dropped_to_zero"] += prior > 0
        stats["uncovered"] += prior == 0


def enrich_all(readlex, corpus):
    """Apply the replace-all frequency pass to every record in a canonical
    {key: [entry, ...]} structure, in place. Returns the tally."""
    stats = {"replaced": 0, "gained": 0, "dropped_to_zero": 0, "uncovered": 0}
    for entries in readlex.values():
        for entry in entries:
            enrich_entry(entry, corpus, stats)
    return stats


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Set freq from the subtitle corpus (replace-all)")
    ap.add_argument("--in", dest="in_path", default=str(READLEX_PATH),
                    help="merged readlex to read (default: data/readlex.json)")
    ap.add_argument("--out", dest="out_path", default=str(READLEX_PATH),
                    help="enriched readlex to write (default: data/readlex.json)")
    args = ap.parse_args()
    in_path, out_path = Path(args.in_path), Path(args.out_path)

    corpus = load_corpus()

    with open(in_path, "r", encoding="utf-8") as f:
        readlex = json.load(f)

    stats = enrich_all(readlex, corpus)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(readlex, f, ensure_ascii=False, indent=4)

    print(f"Corpus entries loaded:      {len(corpus):,}")
    print(f"ReadLex freq replaced:      {stats['replaced']:,}")
    print(f"Newly gained (was freq 0):  {stats['gained']:,}")
    print(f"Dropped to 0 (had ReadLex): {stats['dropped_to_zero']:,}")
    print(f"Still 0 (never had freq):   {stats['uncovered']:,}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
