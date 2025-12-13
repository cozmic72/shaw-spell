#!/usr/bin/env python3
"""
Generate Hunspell spell-check files for Shavian script.

Creates:
  - shaw.dic: Word list (all Shavian words from readlex)
  - shaw.aff: Affix rules (basic configuration)

Install to ~/Library/Spelling/ for macOS spell-checking.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict


def extract_lemma_from_key(key):
    """Extract lemma from readlex key format: {lemma}_{pos}_{shavian}"""
    parts = key.split('_')
    if len(parts) >= 1:
        return parts[0].lower()
    return None


def generate_simple_wordlist(readlex_data, output_dic, output_aff):
    """
    Generate simple Hunspell dictionary (all word forms as separate entries).

    This is the simplest approach - just list every Shavian word.
    No affix rules, but works immediately.
    """
    print("Generating Hunspell spell-check files...")
    print("Using simple word list approach (no affix compression)")

    # Collect all unique Shavian words
    shavian_words = set()

    for key, entries in readlex_data.items():
        for entry in entries:
            shaw = entry.get('Shaw', '')
            if shaw:
                shavian_words.add(shaw)

    # Sort words
    sorted_words = sorted(shavian_words)

    print(f"Found {len(sorted_words)} unique Shavian words")

    # Write .dic file
    print(f"Writing {output_dic}...")
    with open(output_dic, 'w', encoding='utf-8') as f:
        # First line is word count
        f.write(f"{len(sorted_words)}\n")
        # Then one word per line
        for word in sorted_words:
            f.write(f"{word}\n")

    # Write minimal .aff file
    print(f"Writing {output_aff}...")
    with open(output_aff, 'w', encoding='utf-8') as f:
        f.write("# Hunspell affix file for Shavian script\n")
        f.write("# Simple configuration - no affix rules\n\n")
        f.write("SET UTF-8\n")
        f.write("TRY 𐑐𐑑𐑒𐑓𐑔𐑕𐑖𐑗𐑘𐑙𐑚𐑛𐑜𐑝𐑞𐑟𐑠𐑡𐑢𐑣𐑤𐑥𐑦𐑧𐑨𐑩𐑪𐑫𐑬𐑭𐑮𐑯𐑰𐑱𐑲𐑳𐑴𐑵𐑶𐑷𐑸𐑹𐑺𐑻𐑼𐑽𐑾𐑿\n\n")
        f.write("# No affixes defined yet - all words are in .dic file\n")

    print("Hunspell files generated successfully!")
    print(f"  - {output_dic} ({len(sorted_words)} words)")
    print(f"  - {output_aff} (basic configuration)")


def generate_with_affixes(readlex_data, output_dic, output_aff):
    """
    Generate Hunspell dictionary with affix rules.

    TODO: This would analyze readlex to extract morphological patterns
    and generate proper affix rules, significantly reducing file size.

    For now, falls back to simple word list.
    """
    print("Advanced affix generation not yet implemented.")
    print("Falling back to simple word list...")
    generate_simple_wordlist(readlex_data, output_dic, output_aff)


def main():
    """Main function."""
    # Check for --with-affixes flag (future enhancement)
    use_affixes = '--with-affixes' in sys.argv

    # Paths
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    readlex_path = project_dir / '../shavian-info/readlex/readlex.json'
    build_dir = project_dir / 'build'

    dic_path = build_dir / 'shaw.dic'
    aff_path = build_dir / 'shaw.aff'

    # Ensure build directory exists
    build_dir.mkdir(exist_ok=True)

    # Load readlex data
    print("Loading readlex data...")
    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex_data = json.load(f)
    print(f"Loaded {len(readlex_data)} readlex entries")

    # Generate spell-check files
    if use_affixes:
        generate_with_affixes(readlex_data, dic_path, aff_path)
    else:
        generate_simple_wordlist(readlex_data, dic_path, aff_path)

    print("\nSpell-check files ready!")
    print(f"To install: cp {dic_path} {aff_path} ~/Library/Spelling/")
    print("Or run: ./build.sh spellcheck install")


if __name__ == '__main__':
    main()
