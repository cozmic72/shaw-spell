#!/usr/bin/env python3
"""
Close the definition-transliteration coverage gap.

Every English definition should carry a Shavian transliteration, but the original
transliteration pass (src/dictionaries/build_definition_caches.py) only ever ran
over WordNet single-word synset senses — the ~88K keys shaped `lemma|synset` that
now populate data/definitions-shavian-{gb,us}.json. The English glosses that were
NEVER transliterated are:

  1. WordNet synset senses the original pass MISSED — readlex lemmas that carry a
     definition in data/wordnet-comprehensive.json but whose `lemma|synset` key is
     absent from the existing Shavian corpus (~320 keys). These get a genuine
     WordNet synset id, so the editor's provenance discriminator classes them as
     source="wordnet".
  2. Wiktionary senses — the whole of data/definitions-wiktionary.json, keyed
     `word|wikt-N` (~86,880 keys, disjoint from the WordNet word space). A `wikt-N`
     synset id does NOT match the editor's WordNet-offset regex, so these class as
     source="generated": unreviewed candidates the definition editor can correct.

This pass is GAP-FILL ONLY. It NEVER re-transliterates or rewrites an existing
Shavian entry: the owner's definition-correction patches anchor to those entries by
(word, synset, dialect), and rewriting one would orphan its patch. The acceptance
gate is byte-identity of every pre-existing key after the pass (asserted below).
This mirrors annotate_definitions.py's discipline: to keep patch anchors stable a
rebuild must add missing keys and leave the frozen set untouched. (shave itself is
deterministic — see project_shave_nondeterminism.md — the freeze protects the
anchors, not against drift.)

The gap glosses are transliterated per dialect with the SAME method the original
pass used — batch the glosses into one HTML document, run `shave` once per dialect
(-b British / -a American), and lift each transliteration back out of its
`<div id="tN">`. The English `definition` stored is the RAW source gloss (identical
across gb/us, as in the existing corpus — only the transliteration diverges), and
the POS uses the same static Shavian POS map with pass-through for unmapped tags.

Per generated entry we also carry a `confidence` (0-100): the minimum shave
homograph-resolution confidence over the homograph words appearing in that gloss
(100 when the gloss contains no homograph shave had to resolve). shave emits these
on stderr as `Homograph: word -> shaw NN% / ...`; we build a word->min-confidence
map for the batch and attribute the minimum to each sense. Low-confidence entries
are review candidates — NEVER auto-accepted (standing rule).

Inputs (read-only):
  data/definitions-shavian-gb.json, data/definitions-shavian-us.json  (freeze set)
  data/wordnet-comprehensive.json          (WordNet gap glosses + synset ids)
  external/readlex/readlex.json            (lemma filter, as the original pass)
  data/definitions-wiktionary.json         (Wiktionary gap glosses)
Output (rewritten in place, existing keys byte-identical + gap keys appended):
  data/definitions-shavian-gb.json, data/definitions-shavian-us.json

Usage:
    python3 src/tools/transliterate_definitions_gap.py [--dry-run] [--limit N]

    --dry-run   compute the gap, transliterate, report — but write nothing.
    --limit N   only process the first N gap keys (smoke test); implies --dry-run
                unless --write-partial is also given.
"""

import json
import re
import subprocess
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from basis import PROJECT_ROOT

SHAVIAN_GB_PATH = PROJECT_ROOT / "data" / "definitions-shavian-gb.json"
SHAVIAN_US_PATH = PROJECT_ROOT / "data" / "definitions-shavian-us.json"
WORDNET_CACHE_PATH = PROJECT_ROOT / "data" / "wordnet-comprehensive.json"
READLEX_PATH = PROJECT_ROOT / "external" / "readlex" / "readlex.json"
WIKTIONARY_DEFS_PATH = PROJECT_ROOT / "data" / "definitions-wiktionary.json"

# The static POS -> Shavian map + pass-through, IDENTICAL to build_definition_caches
# so gap entries carry the same transliterated_pos convention as the existing corpus
# (unmapped tags — n-1, name, suffix, ... — pass through unchanged, as they do there).
POS_TO_SHAVIAN = {
    "n": "𐑯𐑬𐑯",
    "v": "𐑝𐑻𐑚",
    "a": "𐑨𐑡𐑩𐑒𐑑𐑦𐑝",
    "r": "𐑨𐑛𐑝𐑻𐑚",
    "s": "𐑨𐑡𐑩𐑒𐑑𐑦𐑝",
}

# A WordNet synset offset (########-x). The editor derives provenance from this: a
# match => source="wordnet"; anything else (e.g. wikt-N) => source="generated".
# Kept in lockstep with src/editor/definitions.py::_WORDNET_SYNSET.
_WORDNET_SYNSET = re.compile(r"[0-9]{8}-[nvasr]$")

# shave's homograph diagnostic on stderr: `Homograph: tear -> 𐑑𐑽 96% / 𐑑𐑺 4%`.
# We take the FIRST percentage (the winning spelling's confidence).
_HOMOGRAPH_RE = re.compile(r"^Homograph:\s+(\S+)\s+->\s+\S+\s+(\d+)%")

# shave's phrase/sentence heuristics scale super-linearly with document size: batches
# up to ~8K glosses stay ~linear (≈5 ms/gloss), but one 87K-gloss document degrades
# badly (measured: >13 min and climbing vs ~7 min extrapolated). Chunking the batch
# into documents of this size keeps shave in its linear regime — each gloss is still
# isolated in its own <div>, so the transliteration is identical to the single-document
# result; only the invocation is split. Startup cost is amortised over the chunk.
SHAVE_CHUNK = 6000


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def readlex_lemmas():
    """The lowercased lemma set, extracted from readlex keys `lemma_pos_shavian`
    exactly as the original pass does (build_definition_caches.extract_lemma_from_key)."""
    raw = load_json(READLEX_PATH)
    lemmas = set()
    for key in raw:
        parts = key.split("_")
        if parts and parts[0]:
            lemmas.add(parts[0].lower())
    return lemmas


def wordnet_gap_glosses(existing_keys, lemmas):
    """The WordNet gap: (key, gloss, pos) for every readlex-lemma `lemma|synset`
    sense carrying a definition in the WordNet cache that is NOT already in the
    Shavian corpus. Reproduces the original pass's (lemma, synset_id) derivation so
    the key space matches exactly (verified: 0 existing keys fail to reproduce)."""
    cache = load_json(WORDNET_CACHE_PATH)
    gap = []
    for lemma, entry in cache.items():
        if lemma.lower() not in lemmas:
            continue
        for pos, pos_entry in entry.get("pos_entries", {}).items():
            for sense in pos_entry.get("sense_variants", []):
                synset_id = sense.get("synset")
                sense_defs = sense.get("definitions", [])
                if not synset_id or not sense_defs:
                    continue
                key = f"{lemma}|{synset_id}"
                if key in existing_keys:
                    continue
                gap.append((key, sense_defs[0], pos))
    return gap


def wiktionary_gap_glosses(existing_keys):
    """The Wiktionary gap: (key, gloss, pos) for every `word|wikt-N` sense not
    already in the Shavian corpus, read from the RAW (un-dialected) Wiktionary
    definitions the Latin generator ingests. Each key holds exactly one sense."""
    wikt = load_json(WIKTIONARY_DEFS_PATH)
    gap = []
    for key, senses in wikt.items():
        if key in existing_keys:
            continue
        for sense in senses:
            gloss = sense.get("definition", "")
            if not gloss:
                continue
            gap.append((key, gloss, sense.get("pos", "")))
    return gap


def format_for_transliteration(text):
    """Capitalise the first letter and add a terminal period, matching the original
    pass so shave sees the same sentence boundaries (better WSD, identical style)."""
    if not text or len(text) < 2:
        return text
    formatted = text[0].upper() + text[1:]
    if formatted[-1] not in ".!?;:":
        formatted += "."
    return formatted


def _shave_chunk(texts, dialect_flag, dialect):
    """Transliterate ONE chunk of glosses in a single `shave` invocation via the
    HTML-div method. Returns (transliterations, homograph_lines). Fails LOUD on a
    non-zero exit or a missing/unterminated div (never silently mis-zip)."""
    html_parts = ["<!DOCTYPE html><html><body>\n"]
    for i, text in enumerate(texts):
        formatted = format_for_transliteration(text)
        html_parts.append(f'<div id="t{i}">{escape(formatted)}</div>\n')
    html_parts.append("</body></html>\n")

    proc = subprocess.run(
        ["shave", dialect_flag, "--confidence", "0"],
        input="".join(html_parts),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"shave exited {proc.returncode} ({dialect}): {proc.stderr[-500:]}")

    output = proc.stdout
    transliterations = []
    search_pos = 0
    for i in range(len(texts)):
        start_tag = f'<div id="t{i}">'
        start_idx = output.find(start_tag, search_pos)
        if start_idx == -1:
            raise RuntimeError(
                f"shave output missing div t{i} ({dialect}) — cannot align "
                f"transliterations to glosses; refusing to mis-zip.")
        start_idx += len(start_tag)
        end_idx = output.find("</div>", start_idx)
        if end_idx == -1:
            raise RuntimeError(f"shave output div t{i} unterminated ({dialect}).")
        transliterations.append(output[start_idx:end_idx])
        search_pos = end_idx + len("</div>")

    return transliterations, proc.stderr.splitlines()


def batch_transliterate(texts, dialect):
    """Transliterate `texts` to Shavian, chunked into SHAVE_CHUNK-sized `shave`
    invocations (see SHAVE_CHUNK — one 87K document degrades super-linearly).
    Returns (transliterations, word_confidence):

      transliterations  the Shavian string per input, in order (from `<div id=tN>`).
      word_confidence    {word_lower: min homograph confidence %} parsed from stderr.

    Clean stdout (no --debug-wsd, which would inject confidence <span>s into the
    text). Dialect flag -b British / -a American. --confidence 0 = silent argmax, so
    stdout never carries a bracket-ambiguity list to corrupt a definition. Fails LOUD
    on any chunk-level div mismatch, and asserts the reassembled count matches the
    input (never silently mis-zip across chunk boundaries)."""
    if not texts:
        return [], {}

    dialect_flag = "-b" if dialect == "gb" else "-a"
    n_chunks = (len(texts) + SHAVE_CHUNK - 1) // SHAVE_CHUNK
    print(f"  Running shave ({dialect.upper()}, {dialect_flag}) over "
          f"{len(texts):,} glosses in {n_chunks} chunk(s) of ≤{SHAVE_CHUNK:,}...")

    transliterations = []
    word_confidence = {}
    for chunk_idx in range(n_chunks):
        chunk = texts[chunk_idx * SHAVE_CHUNK:(chunk_idx + 1) * SHAVE_CHUNK]
        chunk_translits, stderr_lines = _shave_chunk(chunk, dialect_flag, dialect)
        transliterations.extend(chunk_translits)
        # Word-level homograph confidence: keep the MINIMUM confidence seen for a
        # word across ALL chunks (its worst-case resolution anywhere in the corpus).
        for line in stderr_lines:
            m = _HOMOGRAPH_RE.match(line)
            if not m:
                continue
            word = m.group(1).lower()
            conf = int(m.group(2))
            if word not in word_confidence or conf < word_confidence[word]:
                word_confidence[word] = conf
        print(f"    chunk {chunk_idx + 1}/{n_chunks} done "
              f"({len(transliterations):,}/{len(texts):,})")

    if len(transliterations) != len(texts):
        raise RuntimeError(
            f"{dialect}: reassembled {len(transliterations)} transliterations for "
            f"{len(texts)} glosses — chunk misalignment; refusing to mis-zip.")

    return transliterations, word_confidence


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'-]*")


def gloss_confidence(gloss, word_confidence):
    """The per-sense confidence: the minimum homograph confidence over the homograph
    words appearing in the gloss, or 100 when the gloss contains no word shave had to
    disambiguate. A shave homograph decision is the only per-word uncertainty signal
    available; a gloss with no resolved homograph carried no ambiguity for shave."""
    confs = [word_confidence[m.group(0).lower()]
             for m in _WORD_RE.finditer(gloss)
             if m.group(0).lower() in word_confidence]
    return min(confs) if confs else 100


def build_gap_entries(gap, dialect):
    """Transliterate one dialect's gap and return {key: entry}. `entry` matches the
    existing corpus shape (definition, transliterated_definition, pos,
    transliterated_pos, examples, transliterated_examples) plus a `confidence` and a
    `source` the gap adds — examples stay [] (the original pass never transliterated
    examples; owner: "definitions not examples")."""
    glosses = [gloss for (_key, gloss, _pos) in gap]
    transliterations, word_confidence = batch_transliterate(glosses, dialect)

    entries = {}
    for (key, gloss, pos), shaw_def in zip(gap, transliterations):
        entries[key] = {
            "definition": gloss,
            "transliterated_definition": shaw_def,
            "pos": pos,
            "transliterated_pos": POS_TO_SHAVIAN.get(pos, pos),
            "examples": [],
            "transliterated_examples": [],
            "confidence": gloss_confidence(gloss, word_confidence),
            "source": ("wordnet" if _WORDNET_SYNSET.search(key.split("|", 1)[-1])
                       else "generated"),
        }
    return entries


def merge_frozen(existing, gap_entries, dialect):
    """Return existing ∪ gap_entries, asserting the freeze: every pre-existing key is
    byte-identical afterwards and no gap key collides with a frozen key. Fails LOUD on
    any violation — the freeze is the acceptance gate."""
    collisions = [k for k in gap_entries if k in existing]
    if collisions:
        raise RuntimeError(
            f"{dialect}: {len(collisions)} gap keys collide with frozen keys "
            f"(e.g. {collisions[:3]}) — refusing to overwrite a patch-anchored entry.")
    merged = dict(existing)
    merged.update(gap_entries)
    # Prove byte-identity of the frozen slice against a re-serialisation.
    for key, value in existing.items():
        if json.dumps(merged[key], ensure_ascii=False, sort_keys=True) != \
           json.dumps(value, ensure_ascii=False, sort_keys=True):
            raise RuntimeError(f"{dialect}: frozen key {key!r} changed — freeze violated.")
    return merged


def report_confidence(gap_entries, dialect):
    buckets = {"90-100": 0, "70-89": 0, "50-69": 0, "0-49": 0}
    for entry in gap_entries.values():
        c = entry["confidence"]
        if c >= 90:
            buckets["90-100"] += 1
        elif c >= 70:
            buckets["70-89"] += 1
        elif c >= 50:
            buckets["50-69"] += 1
        else:
            buckets["0-49"] += 1
    print(f"  {dialect.upper()} confidence distribution:")
    for label, count in buckets.items():
        print(f"    {label}: {count:,}")


def process_dialect(dialect, gap, dry_run):
    path = SHAVIAN_GB_PATH if dialect == "gb" else SHAVIAN_US_PATH
    existing = load_json(path)
    print(f"[{dialect.upper()}] existing corpus: {len(existing):,} keys")

    gap_entries = build_gap_entries(gap, dialect)
    print(f"[{dialect.upper()}] transliterated gap: {len(gap_entries):,} keys")
    report_confidence(gap_entries, dialect)

    merged = merge_frozen(existing, gap_entries, dialect)
    print(f"[{dialect.upper()}] merged corpus: {len(merged):,} keys "
          f"(frozen {len(existing):,} + gap {len(gap_entries):,})")

    if dry_run:
        print(f"[{dialect.upper()}] --dry-run: not writing {path.name}")
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"[{dialect.upper()}] wrote {path.relative_to(PROJECT_ROOT)}")
    return gap_entries


def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
        if "--write-partial" not in sys.argv:
            dry_run = True

    # The gap key set is identical across dialects (both corpora share their key set,
    # verified), so compute it once against the GB corpus.
    existing_gb = load_json(SHAVIAN_GB_PATH)
    existing_us = load_json(SHAVIAN_US_PATH)
    if set(existing_gb) != set(existing_us):
        raise RuntimeError(
            "gb/us Shavian corpora have divergent key sets — the gap join assumes "
            "identical key sets; refusing to proceed.")
    existing_keys = set(existing_gb)

    lemmas = readlex_lemmas()
    print(f"readlex lemmas: {len(lemmas):,}")

    wn_gap = wordnet_gap_glosses(existing_keys, lemmas)
    wikt_gap = wiktionary_gap_glosses(existing_keys)
    print(f"WordNet gap:    {len(wn_gap):,} senses")
    print(f"Wiktionary gap: {len(wikt_gap):,} senses")

    gap = wn_gap + wikt_gap
    if not gap:
        print("No gap — every English definition already has a Shavian "
              "transliteration. Nothing to do.")
        return
    if limit is not None:
        gap = gap[:limit]
        print(f"--limit {limit}: processing {len(gap):,} gap senses")
    print(f"total gap to transliterate: {len(gap):,} senses\n")

    process_dialect("gb", gap, dry_run)
    print()
    process_dialect("us", gap, dry_run)

    print("\nDone." + (" (dry run — no files written)" if dry_run else ""))


if __name__ == "__main__":
    main()
