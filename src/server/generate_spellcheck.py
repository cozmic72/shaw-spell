#!/usr/bin/env python3
"""
Generate Hunspell spell-check files for Shavian script.

Creates dialect-specific dictionaries:
  - shaw-gb.dic: British English (RRP) variant
  - shaw-us.dic: American English (GA) variant
  - shaw.aff: Affix rules (basic configuration)

Supports:
  - Proper nouns with namer dot (·) prefix
  - Hyphenated compounds
  - Dialect-specific word filtering using WordNet cache

Install to ~/Library/Spelling/ for macOS spell-checking.
"""

import json
import sys
import argparse
from pathlib import Path
from collections import defaultdict


def extract_lemma_from_key(key):
    """Extract lemma from readlex key format: {lemma}_{pos}_{shavian}"""
    parts = key.split('_')
    if len(parts) >= 1:
        return parts[0].lower()
    return None


def is_proper_noun(pos):
    """Check if POS tag indicates a proper noun."""
    if not pos:
        return False
    # WordNet POS tags: proper nouns typically marked as 'n' with capitalization
    # or specific markers. We'll check for common proper noun indicators.
    return pos.startswith('NNP') or pos == 'PROPN'


def should_include_word(lemma, preferred_dialect, wordnet_cache):
    """
    Determine if a word should be included in the dialect-specific dictionary
    using WordNet cache for authoritative dialect information.

    Symmetric logic:
      - US dictionary: include words with US variants OR words with no dialect marker
      - GB dictionary: include words with GB variants OR words with no dialect marker

    Args:
        lemma: Latin lemma (base form of the word)
        preferred_dialect: 'gb' or 'us'
        wordnet_cache: WordNet comprehensive cache

    Returns:
        True if word should be included
    """
    if not wordnet_cache or lemma.lower() not in wordnet_cache:
        # Not in WordNet cache - include in both dictionaries (common word)
        return True

    entry = wordnet_cache[lemma.lower()]
    variants = entry.get('variants', {})

    # Check if this word has variants for the preferred dialect
    target_dialect = 'US' if preferred_dialect == 'us' else 'GB'

    if target_dialect in variants:
        # Word has variants in target dialect - include it
        return True

    # Word doesn't have variants for this dialect
    # Include it if it has NO dialect-specific variants at all (i.e., it's common to both)
    if not variants:
        return True

    # Word has variants, but not for this dialect - exclude it
    # (This means it's specific to the other dialect)
    return False


def generate_simple_wordlist(readlex_data, output_dic, output_aff, dialect='gb', wordnet_cache=None):
    """
    Generate simple Hunspell dictionary (all word forms as separate entries).

    This is the simplest approach - just list every Shavian word.
    No affix rules, but works immediately.

    Args:
        readlex_data: Dictionary of readlex entries
        output_dic: Output path for .dic file
        output_aff: Output path for .aff file
        dialect: 'gb' or 'us' to filter words by dialect
        wordnet_cache: WordNet comprehensive cache for dialect filtering
    """
    dialect_name = "British (GB)" if dialect == 'gb' else "American (US)"
    print(f"Generating Hunspell spell-check files for {dialect_name}...")
    print("Using simple word list approach (no affix compression)")

    # Collect all unique Shavian words, filtering by dialect
    shavian_words = set()
    namer_dot = '·'  # U+00B7 MIDDLE DOT

    for key, entries in readlex_data.items():
        # Extract lemma from key for dialect filtering
        lemma = extract_lemma_from_key(key)
        if not lemma:
            continue

        # Check if this lemma should be included in this dialect
        if not should_include_word(lemma, dialect, wordnet_cache):
            continue

        for entry in entries:
            shaw = entry.get('Shaw', '')
            if not shaw:
                continue

            # Add the base word
            shavian_words.add(shaw)

            # For proper nouns, also add version with namer dot
            pos = entry.get('pos', '')
            if is_proper_noun(pos):
                # Add namer dot prefix if not already present
                if not shaw.startswith(namer_dot):
                    shavian_words.add(namer_dot + shaw)

    # Sort words
    sorted_words = sorted(shavian_words)

    print(f"Found {len(sorted_words)} unique Shavian words for {dialect_name}")

    # Write .dic file
    print(f"Writing {output_dic}...")
    with open(output_dic, 'w', encoding='utf-8') as f:
        # First line is word count
        f.write(f"{len(sorted_words)}\n")
        # Then one word per line
        for word in sorted_words:
            f.write(f"{word}\n")

    # Write .aff file with word character configuration
    print(f"Writing {output_aff}...")

    # Load replacement rules from external file
    replacements_file = Path(__file__).parent / 'hunspell-replacements.txt'
    replacement_rules = ""
    if replacements_file.exists():
        with open(replacements_file, 'r', encoding='utf-8') as rep_file:
            replacement_rules = rep_file.read().strip() + "\n\n"

    with open(output_aff, 'w', encoding='utf-8') as f:
        f.write("# Hunspell affix file for Shavian script\n")
        f.write(f"# Configuration for {dialect_name}\n\n")
        f.write("SET UTF-8\n")
        f.write("TRY 𐑐𐑑𐑒𐑓𐑔𐑕𐑖𐑗𐑘𐑙𐑚𐑛𐑜𐑝𐑞𐑟𐑠𐑡𐑢𐑣𐑤𐑥𐑦𐑧𐑨𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿\n\n")
        f.write("# Word characters include Shavian letters, hyphen, and namer dot\n")
        f.write("WORDCHARS 𐑐𐑑𐑒𐑓𐑔𐑕𐑖𐑗𐑘𐑙𐑚𐑛𐑜𐑝𐑞𐑟𐑠𐑡𐑢𐑣𐑤𐑥𐑦𐑧𐑨𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿-·\n\n")

        # Include replacement rules from external file
        if replacement_rules:
            f.write(replacement_rules)

        f.write("# No affixes defined yet - all words are in .dic file\n")

    print("Hunspell files generated successfully!")
    print(f"  - {output_dic} ({len(sorted_words)} words)")
    print(f"  - {output_aff} (basic configuration)")


def generate_with_affixes(readlex_data, output_dic, output_aff, dialect='gb', wordnet_cache=None):
    """
    Generate Hunspell dictionary with affix rules.

    TODO: This would analyze readlex to extract morphological patterns
    and generate proper affix rules, significantly reducing file size.

    For now, falls back to simple word list.
    """
    print("Advanced affix generation not yet implemented.")
    print("Falling back to simple word list...")
    generate_simple_wordlist(readlex_data, output_dic, output_aff, dialect, wordnet_cache)


def main():
    """Main function."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Generate Hunspell spell-check files for Shavian script')
    parser.add_argument('--with-affixes', action='store_true',
                        help='Use affix compression (not yet implemented)')
    parser.add_argument('--dialect', choices=['gb', 'us', 'both'], default='both',
                        help='Which dialect(s) to generate: gb (British), us (American), or both')
    args = parser.parse_args()

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent.parent
    readlex_path = project_dir / 'external/readlex/readlex.json'
    wordnet_cache_path = project_dir / 'data/wordnet-comprehensive.json'
    build_dir = project_dir / 'build'

    # Ensure build directory exists
    build_dir.mkdir(exist_ok=True)

    # Load readlex data
    print("Loading readlex data...")
    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex_data = json.load(f)
    print(f"Loaded {len(readlex_data)} readlex entries\n")

    # Load WordNet comprehensive cache (required for dialect filtering)
    wordnet_cache = {}
    if wordnet_cache_path.exists():
        print("Loading comprehensive WordNet cache...")
        with open(wordnet_cache_path, 'r', encoding='utf-8') as f:
            wordnet_cache = json.load(f)
        print(f"Loaded cache with {len(wordnet_cache)} lemmas\n")
    else:
        print(f"WARNING: Comprehensive cache not found at {wordnet_cache_path}")
        print("Dialect filtering will not work properly. Run 'make wordnet-cache' first.\n")

    # Generate spell-check files for requested dialects
    dialects_to_generate = []
    if args.dialect == 'both':
        dialects_to_generate = ['gb', 'us']
    else:
        dialects_to_generate = [args.dialect]

    for dialect in dialects_to_generate:
        dic_path = build_dir / f'io.joro.shaw-spell.shavian-{dialect}.dic'
        aff_path = build_dir / f'io.joro.shaw-spell.shavian-{dialect}.aff'

        if args.with_affixes:
            generate_with_affixes(readlex_data, dic_path, aff_path, dialect, wordnet_cache)
        else:
            generate_simple_wordlist(readlex_data, dic_path, aff_path, dialect, wordnet_cache)
        print()  # Blank line between dialects

    print("All spell-check files ready!")
    print(f"To install GB: cp {build_dir}/io.joro.shaw-spell.shavian-gb.* ~/Library/Spelling/")
    print(f"To install US: cp {build_dir}/io.joro.shaw-spell.shavian-us.* ~/Library/Spelling/")
    print("Or run: make spellcheck install")


if __name__ == '__main__':
    main()
