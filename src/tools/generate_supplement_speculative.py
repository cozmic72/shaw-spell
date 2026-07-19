#!/usr/bin/env python3
"""
Generate a shave-spelled supplement source from the words WordNet KNOWS but
could NOT pronounce.

WordNet ships tens of thousands of headwords with a gloss + POS but no IPA. The
WordNet generator drops these into data/supplement-wordnet-speculative.json (no
Shaw, no IPA, var=UNC) and the combine step never pulls that bucket — so they
are silently absent from the dictionary. This script RESCUES the useful slice:
the words that are NET-NEW (not already in ReadLex nor the wired reliable/neardot
buckets) AND attested in the OpenSubtitles frequency corpus (non-zero freq),
shave-generates their Shavian, and writes a NEW tracked pipeline source
(data/supplement-generated.json) mirroring supplement-names.json's shape.

This is "the names import, but for common vocabulary WordNet couldn't pronounce":
shave is the Roman->Shavian G2P, WordNet supplies the gloss + POS (attached later
by annotate_definitions, which matches these headwords against the WordNet YAML).
Every record lands as an UNREVIEWED review candidate — NEVER auto-accepted. The
editor review surface is the sieve; we do NO upstream junk-filtering (fragments,
abbreviations and short tokens pass through as candidates by design).

TARGET SET (net-new AND non-zero corpus freq):
  - net-new  = Latn.lower() NOT in external/readlex.json NOR in the three wired
    buckets (wordnet-reliable, wiktionary-reliable, wiktionary-neardot).
  - non-zero = corpus_frequency(word) > 0 against external/frequency-words
    (word + UK/US spelling variants, max — identical to apply_frequency_data).

ONE RECORD PER (word, pos): the speculative file already models each headword as
one record per POS (verified: no duplicate word+pos, no sense-splitting within a
POS), and the combined pool is keyed word+pos+shaw. So we emit one record per
(word, pos) — faithful to the pool and cleanest for review (each POS's Shavian is
adjudicated independently). A word with N POS yields N records.

SHAVE: `shave -b --confidence 0` (British/RRP, silent argmax), inputs BLANK-LINE
separated in ONE batch subprocess (fixed startup cost + isolates each word so its
spelling is judged out of context — see reference_shave_invocation). Echoed blank
separators are filtered; a count mismatch fails LOUD. Words shave cannot spell
(it echoes the Roman unchanged — no Shavian letters, ~5%) are SKIPPED with a
logged count; they carry no reliable Shavian so there is nothing to review.

RECORD SHAPE (mirrors supplement-names.json — bucketed word_pos_shaw -> [record]):
  Latn, pos, Shaw (shave-generated), var="RRP" (base; goes through the same
  merger/reclassifier stages as any candidate), freq (corpus freq for visibility;
  apply_frequency_data re-derives it downstream anyway), synthetic=True,
  shaw_source="shave-g2p", origin="shave-g2p from wordnet-speculative" (explicit
  provenance the owner asked for), tier="shave-g2p-speculative". The combine step
  sets source=["generated"] from this file's SOURCES label.

FAIL-FAST: missing corpus / missing shave / count mismatch all abort. This writes
ONLY data/supplement-generated.json; it NEVER touches patches.jsonl or any other
tracked artifact.

Usage:
    python3 src/tools/generate_supplement_speculative.py [--out PATH]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from basis import PROJECT_ROOT
from ipa_to_shavian import contains_shavian
from apply_frequency_data import load_corpus, corpus_frequency

SPECULATIVE_PATH = PROJECT_ROOT / "data" / "supplement-wordnet-speculative.json"
WIRED_SOURCE_PATHS = [
    PROJECT_ROOT / "external" / "readlex" / "readlex.json",
    PROJECT_ROOT / "data" / "supplement-wordnet-reliable.json",
    PROJECT_ROOT / "data" / "supplement-wiktionary-reliable.json",
    PROJECT_ROOT / "data" / "supplement-wiktionary-neardot.json",
]
OUTPUT_PATH = PROJECT_ROOT / "data" / "supplement-generated.json"

SHAVE_BATCH = 2000  # words per shave subprocess (fixed startup cost amortised)

ORIGIN = "shave-g2p from wordnet-speculative"
SHAW_SOURCE = "shave-g2p"
TIER = "shave-g2p-speculative"


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def headwords_of(path):
    """The set of lowercased headwords a supplement/ReadLex file attests."""
    words = set()
    for entries in load_json(path).values():
        for entry in entries:
            words.add(entry["Latn"].lower())
    return words


def select_targets(corpus):
    """The net-new AND non-zero-freq speculative records, as (word, pos, freq).

    net-new = word not in any wired bucket; non-zero = corpus_frequency > 0.
    One tuple per (word, pos) — the speculative file already carries one record
    per POS, so this preserves its granularity."""
    wired = set()
    for path in WIRED_SOURCE_PATHS:
        wired |= headwords_of(path)

    targets = []
    spec = load_json(SPECULATIVE_PATH)
    for entries in spec.values():
        for entry in entries:
            word = entry["Latn"]
            lw = word.lower()
            if lw in wired:
                continue
            freq = corpus_frequency(lw, corpus)
            if freq <= 0:
                continue
            targets.append((word, entry["pos"], freq))
    return targets


def batch_shave(words):
    """shave -b --confidence 0 over `words` in blank-line-separated batches.

    Returns {word: shavian} for the words shave actually spelled (a word absent
    from the map is one shave echoed unchanged — could not spell). Fails LOUD on
    a per-batch output/input count mismatch so words never mis-align."""
    mapping = {}
    for start in range(0, len(words), SHAVE_BATCH):
        chunk = words[start:start + SHAVE_BATCH]
        # BLANK lines isolate each word (see reference_shave_invocation): plain
        # newlines make shave read the batch as a sentence and contaminate
        # context-sensitive spellings across word boundaries.
        input_text = "\n\n".join(chunk)
        result = subprocess.run(
            ["shave", "-b", "--confidence", "0"],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"shave exited {result.returncode}: {result.stderr[:500]}")
        # shave echoes the blank separators — drop empty lines before zipping so
        # one non-blank output line lines up with one input word.
        lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
        if len(lines) != len(chunk):
            raise RuntimeError(
                f"shave output/input count mismatch: {len(lines)} output lines "
                f"for {len(chunk)} input words (batch at {start})")
        for word, shaw_line in zip(chunk, lines):
            shaw = shaw_line.strip()
            # A line with no Shavian letters is shave echoing the Roman input —
            # its unknown-word signal, not a spelling. Skip it.
            if shaw and contains_shavian(shaw):
                mapping[word] = shaw
        print(f"  shave batch {start}-{start + len(chunk)}: "
              f"{len(chunk)} in", file=sys.stderr)
    return mapping


def build_record(word, pos, shaw, freq):
    return {
        "Latn": word,
        "Shaw": shaw,
        "pos": pos,
        "var": "RRP",
        "freq": freq,
        "synthetic": True,
        "shaw_source": SHAW_SOURCE,
        "origin": ORIGIN,
        "tier": TIER,
    }


def bucket(records):
    """Group records into word_pos_shaw buckets, buckets sorted, records stable —
    the shape supplement-names.json uses and combine_supplements reads."""
    buckets = {}
    for r in records:
        key = f"{r['Latn']}_{r['pos']}_{r['Shaw']}"
        buckets.setdefault(key, []).append(r)
    return {key: buckets[key] for key in sorted(buckets)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUTPUT_PATH)
    args = ap.parse_args()

    print("Loading frequency corpus...", file=sys.stderr)
    corpus = load_corpus()

    print("Selecting net-new + non-zero-freq speculative targets...",
          file=sys.stderr)
    targets = select_targets(corpus)
    print(f"  {len(targets):,} (word, pos) targets", file=sys.stderr)

    # One shave call per DISTINCT word (spelling is POS-independent under
    # --confidence 0 argmax on an isolated word), reused across that word's POS.
    distinct_words = sorted({w for w, _pos, _freq in targets})
    print(f"Shave-generating {len(distinct_words):,} distinct words...",
          file=sys.stderr)
    shaw_of = batch_shave(distinct_words)

    records = []
    failed = 0
    for word, pos, freq in targets:
        shaw = shaw_of.get(word)
        if not shaw:
            failed += 1
            continue
        records.append(build_record(word, pos, shaw, freq))

    buckets = bucket(records)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(buckets, f, ensure_ascii=False, indent=4)

    spelled_words = len({r["Latn"] for r in records})
    print(f"\nWrote {args.out.relative_to(PROJECT_ROOT)}: "
          f"{len(records):,} records ({spelled_words:,} words) in "
          f"{len(buckets):,} buckets")
    print(f"Targets: {len(targets):,} (word,pos)  |  "
          f"distinct words: {len(distinct_words):,}  |  "
          f"shave failed (no Shavian): {len(distinct_words) - len(shaw_of):,} "
          f"words -> {failed:,} dropped (word,pos) records")


if __name__ == "__main__":
    main()
