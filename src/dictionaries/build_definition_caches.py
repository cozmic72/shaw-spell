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


# Static mapping for WordNet POS tags
# These should NOT be transliterated via shave tool
POS_TO_ENGLISH = {
    'n': 'noun',
    'v': 'verb',
    'a': 'adjective',
    'r': 'adverb',
    's': 'adjective',  # satellite adjective
}

POS_TO_SHAVIAN = {
    'n': '𐑯𐑬𐑯',
    'v': '𐑝𐑻𐑚',
    'a': '𐑨𐑡𐑩𐑒𐑑𐑦𐑝',
    'r': '𐑨𐑛𐑝𐑻𐑚',
    's': '𐑨𐑡𐑩𐑒𐑑𐑦𐑝',
}


def format_for_transliteration(text):
    """
    Format text for transliteration - capitalize and add period if needed.
    This helps shave work faster by providing proper sentence boundaries.
    """
    if not text or len(text) < 2:
        return text

    # Capitalize first letter
    formatted = text[0].upper() + text[1:]

    # Add period if not already there and text looks like a sentence
    if formatted and formatted[-1] not in '.!?;:':
        formatted += '.'

    return formatted


def batch_transliterate_to_shavian(texts, dialect='gb'):
    """
    Batch transliterate texts to Shavian using shave tool.

    Args:
        texts: List of texts to transliterate
        dialect: 'gb' for British English, 'us' for American English

    Returns a list of transliterated texts in the same order.
    """
    if not texts:
        return []

    # Choose readlex flag based on dialect
    readlex_flag = '--readlex-british' if dialect == 'gb' else '--readlex-american'

    print(f"Transliterating {len(texts)} texts to Shavian ({dialect.upper()})...")
    print("Preparing HTML document...")

    try:
        # Build complete HTML document
        html_parts = ['<!DOCTYPE html><html><body>\n']
        for i, text in enumerate(texts):
            # Format text with capitalization and period for better WSD
            formatted_text = format_for_transliteration(text)
            div_html = f'<div id="t{i}">{escape(formatted_text)}</div>\n'
            html_parts.append(div_html)

            # Progress update while building
            if (i + 1) % 5000 == 0:
                print(f"  Prepared: {i + 1}/{len(texts)}")

        html_parts.append('</body></html>\n')
        html_input = ''.join(html_parts)

        print(f"Sending {len(texts)} texts to shave tool with {readlex_flag}...")

        # Run shave process with dialect flag
        proc = subprocess.Popen(
            ['shave', readlex_flag],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # Let stderr pass through to terminal
            text=True
        )

        # Send all HTML and get output
        print(f"Waiting for shave...")
        output_html, _ = proc.communicate(input=html_input)

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


def build_shavian_definition_cache(readlex_data, wordnet_defs, output_path, dialect='gb', force=False, test_batch=False):
    """
    Build cache of Shavian transliterated definitions.

    Args:
        readlex_data: Processed readlex data with lemma information
        wordnet_defs: WordNet definitions dictionary
        output_path: Path to save the cache
        dialect: 'gb' for British English, 'us' for American English
        force: Force rebuild even if cache exists
        test_batch: If True, only process first 10 lemmas for testing

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

    print(f"\nBuilding Shavian definition cache ({dialect.upper()})...")

    # Find all unique lemmas with WordNet definitions
    lemmas_with_defs = set()
    for key, data in readlex_data.items():
        lemma = data['lemma']
        if lemma in wordnet_defs:
            lemmas_with_defs.add(lemma)

    print(f"Found {len(lemmas_with_defs)} lemmas with WordNet definitions")

    if test_batch:
        print("TEST BATCH MODE: Processing only first 10 lemmas")
        lemmas_with_defs = set(sorted(lemmas_with_defs)[:10])

    # Collect all texts to transliterate
    all_texts_to_transliterate = []
    lemma_list = sorted(lemmas_with_defs)

    print("Collecting texts for transliteration...")
    for lemma in lemma_list:
        for def_data in wordnet_defs[lemma]:
            all_texts_to_transliterate.append(def_data['definition'])
            # NOTE: POS tags are NOT transliterated - we use static POS_TRANSLATIONS mapping
            all_texts_to_transliterate.extend(def_data.get('examples', []))

    print(f"Total texts to transliterate: {len(all_texts_to_transliterate)}")

    # Transliterate all texts
    transliterated_texts = batch_transliterate_to_shavian(all_texts_to_transliterate, dialect)

    # Map transliterations back to lemmas
    print("Building lemma cache...")
    lemma_cache = {}
    text_idx = 0

    for lemma in lemma_list:
        lemma_defs = []

        for def_data in wordnet_defs[lemma]:
            # Use static POS translation instead of transliterating
            pos_code = def_data['pos']
            transliterated_pos = POS_TO_SHAVIAN.get(pos_code, pos_code)

            transliterated_def = {
                'definition': def_data['definition'],
                'transliterated_definition': transliterated_texts[text_idx],
                'pos': pos_code,
                'transliterated_pos': transliterated_pos,
                'examples': def_data.get('examples', []),
                'transliterated_examples': []
            }
            text_idx += 1  # Only increment by 1 now (just the definition)

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
    test_batch = '--test-batch' in sys.argv

    # Parse dialect argument
    dialect = 'gb'  # default
    if '--dialect=us' in sys.argv or '--us' in sys.argv:
        dialect = 'us'
    elif '--dialect=gb' in sys.argv or '--gb' in sys.argv:
        dialect = 'gb'

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent.parent
    readlex_path = project_dir / 'external/readlex/readlex.json'
    wordnet_cache_path = project_dir / 'data/wordnet-comprehensive.json'
    data_dir = project_dir / 'data'

    # Output path includes dialect
    shavian_defs_path = data_dir / f'definitions-shavian-{dialect}.json'

    # Ensure directories exist
    data_dir.mkdir(exist_ok=True)

    # Load data
    print("Loading readlex data...")
    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex_raw = json.load(f)
    print(f"Loaded {len(readlex_raw)} readlex entries")

    print("\nLoading WordNet comprehensive cache...")
    with open(wordnet_cache_path, 'r', encoding='utf-8') as f:
        wordnet_cache = json.load(f)
    print(f"Loaded cache with {len(wordnet_cache)} lemmas")

    # Extract definitions from comprehensive cache
    wordnet_defs = {}
    for lemma, entry in wordnet_cache.items():
        all_defs = []
        for pos_entry in entry.get('pos_entries', {}).values():
            if 'definitions' in pos_entry:
                all_defs.extend(pos_entry['definitions'])
        if all_defs:
            wordnet_defs[lemma] = all_defs
    print(f"Extracted definitions for {len(wordnet_defs)} words")

    # Process readlex
    readlex_data = process_readlex_with_lemmas(readlex_raw)

    # Build Shavian definition cache
    shavian_cache = build_shavian_definition_cache(
        readlex_data, wordnet_defs, shavian_defs_path,
        dialect=dialect, force=force, test_batch=test_batch
    )

    print("\n" + "="*60)
    print("Definition cache build complete!")
    print("="*60)
    print(f"Shavian definitions ({dialect.upper()}): {shavian_defs_path}")
    print(f"  {len(shavian_cache)} lemmas cached")
    print("\nYou can now run ./build.sh to generate dictionaries (no transliteration needed)")


if __name__ == '__main__':
    main()
