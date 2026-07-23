#!/usr/bin/env python3
"""
Derive the Shavian definitions cache from the Latin definitions source.

data/definitions-latin-{gb,us}.json is the SOURCE OF TRUTH: the English gloss, POS
tag, examples (and, on gap entries, source/confidence annotations) per `lemma|synset`
key. This script is the single straight-through pass that transliterates EVERY Latin
definition to Shavian and writes the DERIVED cache:

    data/definitions-shavian-{gb,us}.json    {transliterated_definition,
                                              transliterated_pos,
                                              transliterated_examples}

keyed identically. There is no "gap" — every source gloss is transliterated, so the
Shavian file always covers the full Latin key set (the make dependency is the honest
`definitions-shavian-X.json : definitions-latin-X.json`).

Transliteration uses the shave tool on shave's OWN shipped dictionary (-b British /
-a American). Definitions are a PRISTINE external source — shave is never fed our own
readlex/corrections, or the transliterator becomes an echo chamber of our decisions.
shave is deterministic but EXPENSIVE; this is a committed checkpoint rebuilt only
deliberately (see build-rules/dictionaries.mk).

The POS tag is NOT transliterated via shave — it uses the static POS_TO_SHAVIAN map
(pass-through for unmapped tags), matching the source corpus convention. Examples are
carried through empty (the corpus holds none; owner: "definitions not examples").

Usage:
    python3 src/dictionaries/build_definition_caches.py [--gb|--us] [--force]
"""

import json
import subprocess
import sys
from pathlib import Path
from html import escape


# Static WordNet POS -> English word map (used by generate_dictionaries for POS
# labels; NOT transliterated via shave).
POS_TO_ENGLISH = {
    'n': 'noun',
    'v': 'verb',
    'a': 'adjective',
    'r': 'adverb',
    's': 'adjective',  # satellite adjective
}

# Static POS -> Shavian map (POS tags are NOT transliterated via shave).
# Unmapped tags (n-1, name, suffix, wikt POS strings, ...) pass through unchanged.
POS_TO_SHAVIAN = {
    'n': '𐑯𐑬𐑯',
    'v': '𐑝𐑻𐑚',
    'a': '𐑨𐑡𐑩𐑒𐑑𐑦𐑝',
    'r': '𐑨𐑛𐑝𐑻𐑚',
    's': '𐑨𐑡𐑩𐑒𐑑𐑦𐑝',
}

# shave's phrase/sentence heuristics scale super-linearly with document size: one
# ~180K-gloss document degrades badly. Chunk the batch into documents of this size to
# keep shave in its linear regime — each gloss is isolated in its own <div>, so the
# transliteration is identical to a single-document result; only the invocation splits.
SHAVE_CHUNK = 6000


def format_for_transliteration(text):
    """Capitalise the first letter and add a terminal period so shave sees a proper
    sentence boundary (better WSD, consistent style)."""
    if not text or len(text) < 2:
        return text
    formatted = text[0].upper() + text[1:]
    if formatted[-1] not in '.!?;:':
        formatted += '.'
    return formatted


def _shave_chunk(texts, dialect_flag, dialect):
    """Transliterate ONE chunk of glosses in a single `shave` invocation via the
    HTML-div method. Fails LOUD on a non-zero exit or a missing/unterminated div
    (never silently mis-zip)."""
    html_parts = ['<!DOCTYPE html><html><body>\n']
    for i, text in enumerate(texts):
        formatted = format_for_transliteration(text)
        html_parts.append(f'<div id="t{i}">{escape(formatted)}</div>\n')
    html_parts.append('</body></html>\n')

    proc = subprocess.run(
        ['shave', dialect_flag],
        input=''.join(html_parts),
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
        end_idx = output.find('</div>', start_idx)
        if end_idx == -1:
            raise RuntimeError(f"shave output div t{i} unterminated ({dialect}).")
        transliterations.append(output[start_idx:end_idx])
        search_pos = end_idx + len('</div>')

    return transliterations


def batch_transliterate_to_shavian(texts, dialect='gb'):
    """Transliterate `texts` to Shavian, chunked into SHAVE_CHUNK-sized `shave`
    invocations. Returns the Shavian string per input, in order. Fails LOUD on any
    chunk-level div mismatch, and asserts the reassembled count matches the input."""
    if not texts:
        return []

    # Dialect on shave's OWN shipped dictionary (-b/-a, no file arg) — never our
    # readlex/corrections (no --dict, no --readlex-*), or shave becomes an echo
    # chamber of our own decisions.
    dialect_flag = '-b' if dialect == 'gb' else '-a'
    n_chunks = (len(texts) + SHAVE_CHUNK - 1) // SHAVE_CHUNK
    print(f"Transliterating {len(texts):,} texts to Shavian ({dialect.upper()}, "
          f"{dialect_flag}) in {n_chunks} chunk(s) of <={SHAVE_CHUNK:,}...")

    transliterations = []
    for chunk_idx in range(n_chunks):
        chunk = texts[chunk_idx * SHAVE_CHUNK:(chunk_idx + 1) * SHAVE_CHUNK]
        transliterations.extend(_shave_chunk(chunk, dialect_flag, dialect))
        print(f"  chunk {chunk_idx + 1}/{n_chunks} done "
              f"({len(transliterations):,}/{len(texts):,})")

    if len(transliterations) != len(texts):
        raise RuntimeError(
            f"{dialect}: reassembled {len(transliterations)} transliterations for "
            f"{len(texts)} glosses — chunk misalignment; refusing to mis-zip.")

    return transliterations


def build_shavian_definition_cache(latin_defs, output_path, dialect='gb', force=False):
    """Derive the Shavian cache from the Latin source, keyed identically. Every Latin
    definition is transliterated (straight-through, no gap). The transliterated_pos
    uses the static POS map; examples carry through empty (the corpus holds none)."""
    if output_path.exists() and not force:
        print(f"Cache already exists at {output_path}")
        print("Use --force to rebuild")
        with open(output_path, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"Loaded existing cache with {len(cache)} keys")
        return cache

    print(f"\nBuilding Shavian definition cache ({dialect.upper()}) from Latin source...")

    # Deterministic key order so the transliteration batch is stable and the output
    # is byte-idempotent.
    keys = sorted(latin_defs)
    glosses = [latin_defs[key]['definition'] for key in keys]

    transliterations = batch_transliterate_to_shavian(glosses, dialect)

    cache = {}
    for key, shaw_def in zip(keys, transliterations):
        pos_code = latin_defs[key]['pos']
        cache[key] = {
            'transliterated_definition': shaw_def,
            'transliterated_pos': POS_TO_SHAVIAN.get(pos_code, pos_code),
            'transliterated_examples': [],
        }

    print(f"Saving cache to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"Saved transliterations for {len(cache)} keys")
    return cache


def main():
    """Main function."""
    force = '--force' in sys.argv

    dialect = 'gb'  # default
    if '--dialect=us' in sys.argv or '--us' in sys.argv:
        dialect = 'us'
    elif '--dialect=gb' in sys.argv or '--gb' in sys.argv:
        dialect = 'gb'

    script_dir = Path(__file__).parent
    project_dir = script_dir.parent.parent
    data_dir = project_dir / 'data'

    latin_defs_path = data_dir / f'definitions-latin-{dialect}.json'
    shavian_defs_path = data_dir / f'definitions-shavian-{dialect}.json'

    data_dir.mkdir(exist_ok=True)

    print(f"Loading Latin definition source ({dialect.upper()})...")
    with open(latin_defs_path, 'r', encoding='utf-8') as f:
        latin_defs = json.load(f)
    print(f"Loaded {len(latin_defs)} Latin definitions")

    shavian_cache = build_shavian_definition_cache(
        latin_defs, shavian_defs_path, dialect=dialect, force=force
    )

    print("\n" + "=" * 60)
    print("Definition cache build complete!")
    print("=" * 60)
    print(f"Shavian definitions ({dialect.upper()}): {shavian_defs_path}")
    print(f"  {len(shavian_cache)} keys cached")


if __name__ == '__main__':
    main()
