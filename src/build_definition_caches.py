#!/usr/bin/env python3
"""
Build definition caches for Shavian dictionaries.

This script is a preprocessing step that:
1. Loads WordNet definitions (English)
2. Transliterates all definitions to Shavian
3. Saves both caches to data/

The dictionary generators then simply load from these caches.
"""

import json
import subprocess
import sys
from pathlib import Path
from html import escape


def batch_transliterate_to_shavian(texts):
    """
    Batch transliterate texts to Shavian using shave tool.
    Returns a list of transliterated texts in the same order.
    """
    if not texts:
        return []

    print(f"Transliterating {len(texts)} texts to Shavian...")
    print("Preparing HTML document...")

    try:
        # Build complete HTML document
        html_parts = ['<!DOCTYPE html><html><body>\n']
        for i, text in enumerate(texts):
            div_html = f'<div id="t{i}">{escape(text)}</div>\n'
            html_parts.append(div_html)

            # Progress update while building
            if (i + 1) % 5000 == 0:
                print(f"  Prepared: {i + 1}/{len(texts)}")

        html_parts.append('</body></html>\n')
        html_input = ''.join(html_parts)

        print(f"Sending {len(texts)} texts to shave tool...")

        # Run shave process
        proc = subprocess.Popen(
            ['shave'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # Let stderr pass through to terminal
            text=True
        )

        # Send all HTML and get output
        # Timeout scales with batch size: ~1 second per 100 texts
        timeout_seconds = max(60, len(texts) // 50)
        print(f"Waiting for shave (timeout: {timeout_seconds}s)...")
        output_html, _ = proc.communicate(input=html_input, timeout=timeout_seconds)

        print("Parsing transliteration results...")

        # Extract transliterated texts from output
        transliterated = []
        search_pos = 0  # Track position in output to avoid re-finding earlier divs
        for i in range(len(texts)):
            start_tag = f'<div id="t{i}">'
            end_tag = '</div>'

            start_idx = output_html.find(start_tag, search_pos)
            if start_idx != -1:
                start_idx += len(start_tag)
                end_idx = output_html.find(end_tag, start_idx)
                if end_idx != -1:
                    transliterated_text = output_html[start_idx:end_idx]
                    transliterated.append(transliterated_text)
                    search_pos = end_idx + len(end_tag)  # Move search position forward
                else:
                    transliterated.append(texts[i])
            else:
                transliterated.append(texts[i])

            # Progress update while parsing
            if (i + 1) % 5000 == 0:
                print(f"  Parsed: {i + 1}/{len(texts)}")

        print(f"Transliteration complete! ({len(transliterated)} items)")
        return transliterated

    except (subprocess.TimeoutExpired, FileNotFoundError, BrokenPipeError) as e:
        print(f"Warning: shave tool error: {e}")
        if 'proc' in locals():
            proc.kill()
        return texts  # Return original texts on error


def extract_lemma_from_key(key):
    """Extract lemma from readlex key format: {lemma}_{pos}_{shavian}"""
    parts = key.split('_')
    if len(parts) >= 1:
        return parts[0].lower()
    return None


def process_readlex_with_lemmas(readlex_data):
    """
    Process readlex data to include lemma information.
    Returns: dict mapping readlex keys to (lemma, entries) tuples
    """
    print("Processing readlex with lemma information...")
    processed = {}

    for key, entries in readlex_data.items():
        # Extract lemma from key
        lemma = extract_lemma_from_key(key)
        if not lemma and entries:
            # Fallback to first entry's Latn field
            lemma = entries[0]['Latn'].lower()

        processed[key] = {
            'lemma': lemma,
            'entries': entries
        }

    print(f"Processed {len(processed)} lemma groups")
    return processed


def build_shavian_definition_cache(readlex_data, wordnet_defs, output_path, force=False):
    """
    Build cache of Shavian transliterated definitions.

    Cache structure:
    {
      "lemma": [
        {
          "definition": "original English definition",
          "transliterated_definition": "Shavian definition",
          "pos": "original POS tag",
          "transliterated_pos": "Shavian POS",
          "examples": ["English example 1", ...],
          "transliterated_examples": ["Shavian example 1", ...]
        }
      ]
    }
    """
    # Check if cache already exists
    if output_path.exists() and not force:
        print(f"Cache already exists at {output_path}")
        print("Use --force to rebuild")
        with open(output_path, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"Loaded existing cache with {len(cache)} lemmas")
        return cache

    print("\nBuilding Shavian definition cache...")

    # Find all unique lemmas with WordNet definitions
    lemmas_with_defs = set()
    for key, data in readlex_data.items():
        lemma = data['lemma']
        if lemma in wordnet_defs:
            lemmas_with_defs.add(lemma)

    print(f"Found {len(lemmas_with_defs)} lemmas with WordNet definitions")

    # Collect all texts to transliterate
    all_texts_to_transliterate = []
    lemma_list = sorted(lemmas_with_defs)

    print("Collecting texts for transliteration...")
    for lemma in lemma_list:
        for def_data in wordnet_defs[lemma]:
            all_texts_to_transliterate.append(def_data['definition'])
            all_texts_to_transliterate.append(def_data['pos'])
            all_texts_to_transliterate.extend(def_data.get('examples', []))

    print(f"Total texts to transliterate: {len(all_texts_to_transliterate)}")

    # Transliterate in batches to avoid timeout
    BATCH_SIZE = 5000  # Process 5000 texts at a time
    transliterated_texts = []

    for i in range(0, len(all_texts_to_transliterate), BATCH_SIZE):
        batch = all_texts_to_transliterate[i:i+BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(all_texts_to_transliterate) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\nTransliterating batch {batch_num}/{total_batches} ({len(batch)} texts)...")
        transliterated_batch = batch_transliterate_to_shavian(batch)
        transliterated_texts.extend(transliterated_batch)

    # Map transliterations back to lemmas
    print("Building lemma cache...")
    lemma_cache = {}
    text_idx = 0

    for lemma in lemma_list:
        lemma_defs = []

        for def_data in wordnet_defs[lemma]:
            transliterated_def = {
                'definition': def_data['definition'],
                'transliterated_definition': transliterated_texts[text_idx],
                'pos': def_data['pos'],
                'transliterated_pos': transliterated_texts[text_idx + 1],
                'examples': def_data.get('examples', []),
                'transliterated_examples': []
            }
            text_idx += 2

            # Add transliterated examples
            for ex in def_data.get('examples', []):
                transliterated_def['transliterated_examples'].append(transliterated_texts[text_idx])
                text_idx += 1

            lemma_defs.append(transliterated_def)

        lemma_cache[lemma] = lemma_defs

    # Save cache
    print(f"Saving cache to {output_path}...")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(lemma_cache, f, ensure_ascii=False, indent=2)

    print(f"Saved transliterations for {len(lemma_cache)} lemmas")
    return lemma_cache


def main():
    """Main function."""
    force = '--force' in sys.argv

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    readlex_path = project_dir / '../shavian-info/readlex/readlex.json'
    wordnet_path = project_dir / 'build/wordnet-definitions.json'
    data_dir = project_dir / 'data'

    shavian_defs_path = data_dir / 'definitions-shavian.json'

    # Ensure directories exist
    data_dir.mkdir(exist_ok=True)

    # Load data
    print("Loading readlex data...")
    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex_raw = json.load(f)
    print(f"Loaded {len(readlex_raw)} readlex entries")

    print("\nLoading WordNet definitions...")
    with open(wordnet_path, 'r', encoding='utf-8') as f:
        wordnet_defs = json.load(f)
    print(f"Loaded definitions for {len(wordnet_defs)} words")

    # Process readlex
    readlex_data = process_readlex_with_lemmas(readlex_raw)

    # Build Shavian definition cache
    shavian_cache = build_shavian_definition_cache(
        readlex_data, wordnet_defs, shavian_defs_path, force=force
    )

    print("\n" + "="*60)
    print("Definition cache build complete!")
    print("="*60)
    print(f"Shavian definitions: {shavian_defs_path}")
    print(f"  {len(shavian_cache)} lemmas cached")
    print("\nYou can now run ./build.sh to generate dictionaries (no transliteration needed)")


if __name__ == '__main__':
    main()
