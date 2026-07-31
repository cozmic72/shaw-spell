#!/usr/bin/env python3
"""
Set every record's frequency from a subtitle-derived corpus, one coherent scale,
then apportion each shared count across a word's POS records using the BNC1994
Leech/Rayson/Wilson (LRW) per-POS frequencies.

PASS 1 — REPLACE-ALL-FROM-CORPUS. ReadLex ships a `freq` field, but its counts
are on ReadLex's own corpus scale — not comparable to the OpenSubtitles-derived
list (external/frequency-words, MIT-licensed) we use for the ~13.5K headwords
ReadLex leaves at freq 0. A mixed dictionary (some words on ReadLex's scale,
some on ours) cannot be sorted or thresholded meaningfully. So we put EVERY word
on ONE scale — ours. Each record's `freq` becomes its OpenSubtitles count (via
the word and its UK/US variants, taking the max). Records the corpus does not
cover drop to freq 0. To honour "don't throw away data", a record that HAD a
non-zero ReadLex freq keeps it in `freq_readlex` before we overwrite `freq`;
records that never had a ReadLex freq gain no such field. Corpus-sourced freq is
tagged `freq_source` so provenance is never ambiguous. Both are RUNTIME
bookkeeping: main() serializes through the publish whitelist (basis.
PUBLISH_FIELDS, the same shape the editor's commit path emits), so neither —
nor the pass-2 info annotations — ever reaches data/readlex.json.

UK/US variants: the corpus is a single mixed-dialect "en" list holding both
spellings of a transatlantic pair, each with its own count. We consult a
headword's spelling variants (see spelling_variants.py) and take the maximum
count across the headword and its variants — the dominant attested form, without
double-counting when both spellings coexist.

Contractions: the corpus tokeniser split on the apostrophe, so whole
contractions (don't, it's) never appear — only the halves do (don + 't). When
the direct lookup misses and the headword has an internal apostrophe, we derive
freq = min(stem, clitic): a contraction cannot occur more often than either
half, so the min is an UPPER bound — tight when one half is dominated by the
contraction (don't ≈ don's count), inflated when both halves are independently
common (a shared clitic like 're hands its whole count to every rare member of
its family). Records so derived are tagged "frequency from parts" and excluded
from pass 2 — a synthesized bound must not be multiplexed.

PASS 2 — POS SPLIT. The OpenSubtitles list is token-level: every record of a
word inherits the word's WHOLE count in pass 1, so `i` the pronoun, the letter,
and the numeral all claim 27M. The LRW list (data/bncfreq, per-million,
per-POS; see lrw_frequencies.py) tells us how a surface's occurrences divide
between coarse POS classes, so pass 2 apportions each word's pass-1 count:

  RULE 1 (surface split): a record resolves when its C5 tag maps to LRW tags
  the surface actually attests (weight = the summed informative readings).
  With >= 2 DISTINCT resolved classes, each resolved record gets its class's
  share of the pass-1 count. Records whose effective LRW-tag sets are identical
  share one class; if two DIFFERENT effective sets overlap, the evidence is
  ambiguous and the whole word is skipped (no rule-2 fallthrough). Unresolved
  records keep their pass-1 value — we never invent, never zero.

  RULE 2 (lemma inheritance): LRW files -s inflections under ONE lemma's POS,
  so a surface like `hopes` cannot split at surface level. When rule 1 finds
  fewer than 2 distinct classes (or its denominator is below the attestation
  floor), the ratio is inherited from the SUMMED readings of the word's parent
  lemmas — attested at lemma scale where rounding hasn't destroyed the ratio —
  and applied to the word's OWN pass-1 count.

Split records are annotated in the `info` field ("frequency by POS split" /
"frequency from lemma"); the three tags this stage owns are stripped up front
each run, so a changed outcome never leaves a stale tag behind.

SPELLING-VARIANT GATE: the OS lookup keeps its spelling_variants max logic; the
LRW join uses EXACT keys only — no spelling_variants rescue, no hyphen/space/
concat bridging. The variant rules have 0.864 precision (an unanchored `oe`
rule fabricates cross-lexeme matches like stoep->step) and contribute only
~0.18% coverage; a false LRW match would synthesize a wrong RATIO, which is
worse than no split — and bridged multiword forms have no direct OS count to
split anyway.

HIGH-FREQUENCY SAFETY: OS<->LRW POS agreement INVERTS with frequency (80.3% at
>=1M OS count vs 96.6% at 1k-10k). We do NOT blanket-ban top-end multiplexing
(the flagship i/a/may/us cases live there); the protection is structural — only
readings that individually resolve against LRW get split, everything else keeps
its value — plus reporting: main() prints every multiplexed word at >= 1M so no
shaky top-end split is ever silent.

The enrichment logic (enrich_all) is shared: the editor's basis (src/tools/basis.py)
applies the SAME passes to its review-pool candidates, so a candidate and the
readlex record it eventually becomes carry an identical freq.

Idempotent and deterministic: the value written depends only on the two fixed
corpora, so identical inputs yield an identical readlex.json.

Usage:
    python3 src/tools/apply_frequency_data.py
"""

import json
import sys
from pathlib import Path

from basis import DATA_ROOT, INFO_FIELD, PROJECT_ROOT, published_entry
from lrw_frequencies import C5_TO_LRW, UNINFORMATIVE_LRW_TAGS, load_lrw, lrw_key
from spelling_variants import spelling_variants

READLEX_PATH = DATA_ROOT / "readlex.json"
CORPUS_PATH = PROJECT_ROOT / "external" / "frequency-words" / "content" / "2018" / "en" / "en_full.txt"
FREQ_SOURCE_TAG = "opensubtitles-2018"

# --- POS-split attestation floors (LRW values are per-million, ROUNDED) ------
#
# A reading resolves only at >= 1/M: an LRW 0 means "<0.5 per million" and
# carries no magnitude, so a ratio built on it is rounding noise, not evidence.
MIN_READING_PER_MILLION = 1
# The resolved readings' summed weight must reach 10/M or the whole split is
# skipped: below ~10/M the ±0.5 rounding per reading can swing shares by tens
# of points (a 1-vs-1 "split" is meaningless).
MIN_SPLIT_TOTAL_PER_MILLION = 10
# Every split of a word this frequent is printed by main() — the OS<->LRW POS
# agreement is at its weakest at the top of the frequency scale (see the module
# docstring), so no top-end split may pass silently.
HIGH_FREQUENCY_REPORT_THRESHOLD = 1_000_000

# The `info` annotations this stage owns (and strips on re-run — idempotency;
# see _strip_frequency_info). Foreign info entries are never touched.
INFO_POS_SPLIT = "frequency by POS split"
INFO_FROM_LEMMA = "frequency from lemma"
INFO_FROM_PARTS = "frequency from parts"
FREQUENCY_INFO_TAGS = frozenset({INFO_POS_SPLIT, INFO_FROM_LEMMA, INFO_FROM_PARTS})


def _strip_frequency_info(entry):
    """Remove this stage's own info tags, preserving foreign entries and their
    order. A prior run's tag must not survive a changed outcome. If nothing
    remains, the key is dropped entirely (absent means "no info")."""
    info = entry.get(INFO_FIELD)
    if not info:
        return
    kept = [tag for tag in info if tag not in FREQUENCY_INFO_TAGS]
    if kept:
        entry[INFO_FIELD] = kept
    else:
        del entry[INFO_FIELD]


def _append_frequency_info(entry, tag):
    entry.setdefault(INFO_FIELD, []).append(tag)

# Contraction-fragment blocklist.
#
# The OpenSubtitles corpus was tokenised by splitting on the apostrophe, so every
# contraction contributes an inflated fake "word": a bare STEM (isn't -> isn) plus
# a leading-apostrophe TAIL (isn't -> 't, you're -> 're). These fragments carry
# enormous counts ('s = 14.3M, 't = 9.6M, isn = 429K, ...) that our freq join
# would otherwise hand to any record whose headword literally spells the fragment
# (isn, ain, shan, the 's/'d pseudo-headwords, and 'em -> Em) — floating pure junk
# to the top of the frequency-sorted review. The blocklist is enforced at the
# JOIN (corpus_frequency) so no record receives a fragment's count as its own;
# the tokens stay loaded in the corpus because contraction_frequency reads them
# deliberately to derive min-of-parts bounds for whole contractions.
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

    Contraction-fragment tokens (see FRAGMENT_BLOCKLIST) are kept — they are
    barred from the headword join in corpus_frequency, but contraction_frequency
    needs their counts to derive whole-contraction frequencies.
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
            corpus[word] = int(count)
    if not corpus:
        sys.exit(f"Corpus at {CORPUS_PATH.relative_to(PROJECT_ROOT)} is empty.")
    return corpus


def corpus_frequency(word, corpus):
    """Best corpus count for a lowercase word, consulting UK/US variants.

    Returns 0 when neither the word nor any variant appears in the corpus, and
    for blocklisted contraction fragments — a fragment's inflated count must
    never become a headword's own frequency.
    """
    if word in FRAGMENT_BLOCKLIST:
        return 0
    best = corpus.get(word, 0)
    for variant in spelling_variants(word):
        best = max(best, corpus.get(variant, 0))
    return best


def contraction_frequency(word, corpus):
    """Derived count for a contraction the corpus never saw whole.

    The corpus tokeniser split on the apostrophe, so `don't` exists only as
    `don` + `'t`. A contraction cannot occur more often than either half, so
    min(stem, clitic) is an upper bound (tight only when one half is dominated
    by the contraction; see the module docstring). Both halves are read
    straight from the corpus — including blocklisted fragments, intentionally:
    the blocklist stops a fragment becoming a headword's OWN freq, not this
    deliberate derivation.

    Applies only to a single INTERNAL apostrophe. Leading/trailing-apostrophe
    forms ('cause, goin') survived tokenisation whole and match directly, and
    multi-apostrophe shapes have no whole half to look up. If either half is
    unattested there is no evidence to bound with — returns 0 rather than
    inventing a number from half the parts.
    """
    if word.count("'") != 1:
        return 0
    stem, _, tail = word.partition("'")
    if not stem or not tail:
        return 0
    stem_count = corpus.get(stem, 0)
    clitic_count = corpus.get("'" + tail, 0)
    if stem_count == 0 or clitic_count == 0:
        return 0
    return min(stem_count, clitic_count)


def enrich_entry(entry, corpus, stats):
    """Set `entry["freq"]` to its corpus frequency, replacing any prior value.

    A non-zero ReadLex freq being overwritten is preserved in `freq_readlex`
    first. The corpus value (including 0 when uncovered) becomes `freq`; a covered
    record is tagged `freq_source`. Mutates `entry` in place and tallies `stats`.

    Returns True when the freq is a contraction min-of-parts bound — the caller
    excludes those words from the POS-split pass, because a synthesized upper
    bound must not be multiplexed as if it were an observed count.
    """
    _strip_frequency_info(entry)

    # A record already carrying our tag holds a prior corpus value, not a ReadLex
    # one — re-running must not mistake it for a ReadLex freq to stash. So the
    # original ReadLex freq is captured only on the first pass (no tag yet).
    was_readlex = entry.get("freq_source") != FREQ_SOURCE_TAG
    prior = entry.get("freq", 0)
    if was_readlex and prior > 0 and "freq_readlex" not in entry:
        entry["freq_readlex"] = prior

    word = entry["Latn"].lower()
    frequency = corpus_frequency(word, corpus)
    from_parts = False
    if frequency == 0:
        # The corpus never saw whole contractions (tokenised split on the
        # apostrophe) — derive a min-of-parts bound for them instead.
        frequency = contraction_frequency(word, corpus)
        from_parts = frequency > 0
    entry["freq"] = frequency
    if frequency > 0:
        entry["freq_source"] = FREQ_SOURCE_TAG
        stats["gained"] += prior == 0
        stats["replaced"] += prior > 0
    else:
        entry.pop("freq_source", None)
        stats["dropped_to_zero"] += prior > 0
        stats["uncovered"] += prior == 0
    if from_parts:
        _append_frequency_info(entry, INFO_FROM_PARTS)
        stats["from_parts"] += 1
    return from_parts


def _resolve_reading(pos, readings):
    """Resolve one record's C5 tag against a surface's LRW readings.

    Returns (effective_set, weight) — the informative LRW tags this record's
    count evidence lives in, and their summed per-million weight — or None when
    the record cannot resolve: a portmanteau tag (LRW never tags contractions
    as units), a degenerate/unmapped tag, no informative reading, or a weight
    below the attestation floor.
    """
    if not pos or "+" in pos:
        return None
    acceptable = C5_TO_LRW.get(pos)
    if not acceptable:
        return None
    informative = [tag for tag in acceptable
                   if tag in readings and tag not in UNINFORMATIVE_LRW_TAGS]
    weight = sum(readings[tag] for tag in informative)
    if weight < MIN_READING_PER_MILLION:
        return None
    # Zero readings contribute no weight, so any record with this effective set
    # has exactly this weight — a class is (effective_set, weight).
    return frozenset(tag for tag in informative if readings[tag] > 0), weight


def _plan_split(group, readings):
    """Plan how a word's pass-1 count divides between its records, per the
    given readings. Returns (resolved, denominator) where resolved is a list of
    (entry, weight); "overlap" when two different effective sets intersect (the
    evidence is ambiguous — the caller must skip the word outright); or None
    when there is no meaningful split here (fewer than 2 distinct classes, or
    total attestation below the floor) and a fallback may be tried."""
    resolved = []
    class_weights = {}
    for entry in group:
        resolution = _resolve_reading(entry.get("pos"), readings)
        if resolution is None:
            continue
        effective_set, weight = resolution
        resolved.append((entry, weight))
        class_weights[effective_set] = weight
    if len(class_weights) < 2:
        return None
    classes = list(class_weights)
    for i, first in enumerate(classes):
        if any(first & second for second in classes[i + 1:]):
            return "overlap"
    denominator = sum(class_weights.values())
    if denominator < MIN_SPLIT_TOTAL_PER_MILLION:
        return None
    return resolved, denominator


def _split_word_group(word, group, lrw, stats):
    """Apportion one word's shared pass-1 count across its POS records, in
    place: rule 1 (surface readings) preferred, rule 2 (parent-lemma ratio)
    as fallback — except on overlap-conflict, which disqualifies the word.
    Records that resolve get their share; the rest KEEP the pass-1 value.

    A resolved reading whose share is below 0.5 of the word's count rounds to
    freq 0 (a handful of rule-2 inflections on real data, e.g. righting/greyed).
    freq_source is deliberately retained there — the word IS corpus-covered,
    its reading's share merely falls below the rounding floor — and the info
    tag preserves the provenance of the 0."""
    # Pass 1 keys freq purely off the lowercased word, so the group shares one
    # pre-split count.
    pass1_freq = group[0]["freq"]
    key = lrw_key(word)
    readings = lrw.surface_readings.get(key)
    plan = _plan_split(group, readings) if readings else None
    info_tag, counter = INFO_POS_SPLIT, "multiplexed"

    if plan is None:
        # RULE 2: inherit the lemma-scale ratio (see the module docstring),
        # applied to this word's own OS count.
        parents = lrw.parent_lemmas.get(key)
        if not parents:
            return
        summed = {}
        for parent in parents:
            for tag, per_million in lrw.surface_readings[parent].items():
                summed[tag] = summed.get(tag, 0) + per_million
        plan = _plan_split(group, summed)
        if plan is None:
            return
        info_tag, counter = INFO_FROM_LEMMA, "inherited"
    if plan == "overlap":
        stats["overlap_conflict_words"] += 1
        return

    resolved, denominator = plan
    for entry, weight in resolved:
        entry["freq"] = round(pass1_freq * weight / denominator)
        _append_frequency_info(entry, info_tag)
        stats[counter] += 1
        if pass1_freq >= HIGH_FREQUENCY_REPORT_THRESHOLD:
            stats["high_freq_report"].append(
                (word, entry.get("pos"), pass1_freq, entry["freq"]))
    leftover = len(group) - len(resolved)
    if leftover:
        stats["split_words_with_leftover"] += 1
        stats["leftover_records"] += leftover


def enrich_all(readlex, corpus, lrw):
    """Apply both frequency passes to every record in a canonical
    {key: [entry, ...]} structure, in place: the replace-all OS pass, then the
    LRW POS split grouped by lowercased headword across ALL buckets (the basis
    passes everything in one bucket). Returns the tally."""
    stats = {"replaced": 0, "gained": 0, "dropped_to_zero": 0, "uncovered": 0,
             "from_parts": 0, "multiplexed": 0, "inherited": 0,
             "overlap_conflict_words": 0, "split_words_with_leftover": 0,
             "leftover_records": 0, "high_freq_report": []}
    groups = {}
    parts_derived_words = set()
    for entries in readlex.values():
        for entry in entries:
            from_parts = enrich_entry(entry, corpus, stats)
            word = entry["Latn"].lower()
            groups.setdefault(word, []).append(entry)
            if from_parts:
                parts_derived_words.add(word)
    for word, group in groups.items():
        if word in parts_derived_words or group[0]["freq"] == 0:
            continue
        _split_word_group(word, group, lrw, stats)
    return stats


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Set freq from the subtitle corpus (replace-all), "
                    "then split each word's count per POS from the LRW list")
    ap.add_argument("--in", dest="in_path", default=str(READLEX_PATH),
                    help="merged readlex to read (default: data/readlex.json)")
    ap.add_argument("--out", dest="out_path", default=str(READLEX_PATH),
                    help="enriched readlex to write (default: data/readlex.json)")
    args = ap.parse_args()
    in_path, out_path = Path(args.in_path), Path(args.out_path)

    corpus = load_corpus()
    lrw = load_lrw()

    with open(in_path, "r", encoding="utf-8") as f:
        readlex = json.load(f)

    stats = enrich_all(readlex, corpus, lrw)

    # The CLI writes the production artifact, so it ships ONLY the publish
    # whitelist (basis.PUBLISH_FIELDS) — the same shape the editor's commit
    # path emits. Enrichment bookkeeping (freq_source/freq_readlex) and the
    # info annotations stay in-memory runtime state; the input's own
    # `supplement: true` flags pass through the shaper untouched.
    published = {
        bucket_key: [published_entry(entry) for entry in entries]
        for bucket_key, entries in readlex.items()}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(published, f, ensure_ascii=False, indent=4)

    print(f"Corpus entries loaded:        {len(corpus):,}")
    print(f"LRW surfaces loaded:          {len(lrw.surface_readings):,}")
    print(f"ReadLex freq replaced:        {stats['replaced']:,}")
    print(f"Newly gained (was freq 0):    {stats['gained']:,}")
    print(f"Dropped to 0 (had ReadLex):   {stats['dropped_to_zero']:,}")
    print(f"Still 0 (never had freq):     {stats['uncovered']:,}")
    print(f"Contraction min-of-parts:     {stats['from_parts']:,}")
    print(f"POS-split records (rule 1):   {stats['multiplexed']:,}")
    print(f"Lemma-split records (rule 2): {stats['inherited']:,}")
    print(f"Overlap-conflict words:       {stats['overlap_conflict_words']:,}")
    print(f"Split words with leftover:    {stats['split_words_with_leftover']:,} "
          f"({stats['leftover_records']:,} records keep the whole count)")

    report = stats["high_freq_report"]
    if report:
        print(f"\nSplit words at >= {HIGH_FREQUENCY_REPORT_THRESHOLD:,} "
              f"pre-split count (weakest OS<->LRW agreement band — audit these):")
        for word, pos, before, after in report:
            print(f"  {word:20s} {pos or '-':8s} {before:>12,} -> {after:>12,}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
