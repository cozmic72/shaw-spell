#!/usr/bin/env python3
"""
Analyze word coverage across different dictionary sources.

This tool analyzes the overlap between ReadLex (Shavian pronunciation),
Open English WordNet (definitions), and Hunspell dictionaries (spell checking).

Usage:
    ./analyze_word_coverage.py              # Full analysis with summary
    ./analyze_word_coverage.py --json       # Output as JSON
    ./analyze_word_coverage.py --csv        # Output as CSV
    ./analyze_word_coverage.py --verbose    # Show more details
"""

import json
import yaml
import argparse
import sys
from pathlib import Path

def load_readlex_words(readlex_path):
    """Load all English words from ReadLex."""
    try:
        with open(readlex_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: ReadLex file not found at {readlex_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing ReadLex JSON: {e}", file=sys.stderr)
        sys.exit(1)

    words = set()
    # ReadLex is a dict where keys map to lists of entries
    for key, entries in data.items():
        for entry in entries:
            if 'Latn' in entry:
                # Latn field contains the Latin (English) form
                word = entry['Latn']
                words.add(word.lower())

    return words

def load_wordnet_words(wordnet_yaml_dir):
    """Load all lemmas from Open English WordNet YAML files."""
    if not wordnet_yaml_dir.exists():
        print(f"Error: WordNet YAML directory not found at {wordnet_yaml_dir}", file=sys.stderr)
        sys.exit(1)

    words = set()

    # Load all entries-*.yaml files
    yaml_files = sorted(wordnet_yaml_dir.glob('entries-*.yaml'))

    for yaml_file in yaml_files:
        with open(yaml_file, 'r', encoding='utf-8') as f:
            entries = yaml.safe_load(f)

        if entries:
            # Each YAML file contains: {lemma: {pos: data}}
            for lemma in entries.keys():
                words.add(lemma.lower())

    return words

def load_hunspell_words(dic_path):
    """Load all words from a Hunspell .dic file."""
    try:
        with open(dic_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Skip first line (word count)
            next(f)
            words = set()
            for line in f:
                # Strip affixes (everything after /)
                word = line.strip().split('/')[0]
                if word:
                    words.add(word.lower())
    except FileNotFoundError:
        print(f"Error: Hunspell dictionary not found at {dic_path}", file=sys.stderr)
        sys.exit(1)

    return words

def format_percentage(value, total):
    """Format a percentage string, handling zero division."""
    if total == 0:
        return "0.0%"
    return f"{value/total*100:.1f}%"

def print_summary(readlex, wordnet, hunspell_gb, hunspell_us, verbose=False):
    """Print a human-readable summary of the analysis."""

    print("\n" + "="*70)
    print("WORD COVERAGE ANALYSIS - Shaw-Spell")
    print("="*70)

    print("\n" + "="*70)
    print("DATASET SIZES")
    print("="*70)
    print(f"ReadLex (Shavian):      {len(readlex):>8,} words")
    print(f"Open English WordNet:   {len(wordnet):>8,} words")
    print(f"Hunspell GB:            {len(hunspell_gb):>8,} words")
    print(f"Hunspell US:            {len(hunspell_us):>8,} words")

    print("\n" + "="*70)
    print("OVERLAP ANALYSIS")
    print("="*70)

    # ReadLex vs WordNet
    rl_wn_overlap = readlex & wordnet
    print(f"\nReadLex ∩ WordNet:      {len(rl_wn_overlap):>8,} words", end="")
    print(f" ({format_percentage(len(rl_wn_overlap), len(readlex))} of ReadLex)")
    if verbose:
        print(f"  In ReadLex only:      {len(readlex - wordnet):>8,} words")
        print(f"  In WordNet only:      {len(wordnet - readlex):>8,} words")

    # ReadLex vs Hunspell GB
    rl_hgb_overlap = readlex & hunspell_gb
    print(f"\nReadLex ∩ Hunspell GB:  {len(rl_hgb_overlap):>8,} words", end="")
    print(f" ({format_percentage(len(rl_hgb_overlap), len(readlex))} of ReadLex)")
    if verbose:
        print(f"  In ReadLex only:      {len(readlex - hunspell_gb):>8,} words")
        print(f"  In Hunspell GB only:  {len(hunspell_gb - readlex):>8,} words")

    # ReadLex vs Hunspell US
    rl_hus_overlap = readlex & hunspell_us
    print(f"\nReadLex ∩ Hunspell US:  {len(rl_hus_overlap):>8,} words", end="")
    print(f" ({format_percentage(len(rl_hus_overlap), len(readlex))} of ReadLex)")
    if verbose:
        print(f"  In ReadLex only:      {len(readlex - hunspell_us):>8,} words")
        print(f"  In Hunspell US only:  {len(hunspell_us - readlex):>8,} words")

    # WordNet vs Hunspell GB
    wn_hgb_overlap = wordnet & hunspell_gb
    print(f"\nWordNet ∩ Hunspell GB:  {len(wn_hgb_overlap):>8,} words", end="")
    print(f" ({format_percentage(len(wn_hgb_overlap), len(wordnet))} of WordNet)")
    if verbose:
        print(f"  In WordNet only:      {len(wordnet - hunspell_gb):>8,} words")
        print(f"  In Hunspell GB only:  {len(hunspell_gb - wordnet):>8,} words")

    # Three-way overlap
    all_three = readlex & wordnet & hunspell_gb
    print(f"\nAll three (RL∩WN∩HGB): {len(all_three):>8,} words")

    # Coverage
    print("\n" + "="*70)
    print("COVERAGE ANALYSIS")
    print("="*70)
    union_all = readlex | wordnet | hunspell_gb | hunspell_us
    print(f"\nTotal unique words (union of all):     {len(union_all):>8,}")
    print(f"  ReadLex covers:                       {format_percentage(len(readlex), len(union_all)):>7}")
    print(f"  WordNet covers:                       {format_percentage(len(wordnet), len(union_all)):>7}")
    print(f"  Hunspell GB covers:                   {format_percentage(len(hunspell_gb), len(union_all)):>7}")
    print(f"  Hunspell US covers:                   {format_percentage(len(hunspell_us), len(union_all)):>7}")

    if verbose:
        # Sample words unique to each
        print("\n" + "="*70)
        print("SAMPLE UNIQUE WORDS (first 20)")
        print("="*70)

        rl_only = readlex - wordnet - hunspell_gb - hunspell_us
        if rl_only:
            print(f"\nReadLex only ({len(rl_only):,} words):")
            print("  " + ", ".join(sorted(rl_only)[:20]))

        wn_only = wordnet - readlex - hunspell_gb - hunspell_us
        if wn_only:
            print(f"\nWordNet only ({len(wn_only):,} words):")
            print("  " + ", ".join(sorted(wn_only)[:20]))

        hgb_only = hunspell_gb - readlex - wordnet - hunspell_us
        if hgb_only:
            print(f"\nHunspell GB only ({len(hgb_only):,} words):")
            print("  " + ", ".join(sorted(hgb_only)[:20]))

        hus_only = hunspell_us - readlex - wordnet - hunspell_gb
        if hus_only:
            print(f"\nHunspell US only ({len(hus_only):,} words):")
            print("  " + ", ".join(sorted(hus_only)[:20]))

    print()

def export_json(readlex, wordnet, hunspell_gb, hunspell_us):
    """Export analysis results as JSON."""
    results = {
        "dataset_sizes": {
            "readlex": len(readlex),
            "wordnet": len(wordnet),
            "hunspell_gb": len(hunspell_gb),
            "hunspell_us": len(hunspell_us)
        },
        "overlaps": {
            "readlex_wordnet": len(readlex & wordnet),
            "readlex_hunspell_gb": len(readlex & hunspell_gb),
            "readlex_hunspell_us": len(readlex & hunspell_us),
            "wordnet_hunspell_gb": len(wordnet & hunspell_gb),
            "all_three": len(readlex & wordnet & hunspell_gb)
        },
        "unique_counts": {
            "readlex_only": len(readlex - wordnet - hunspell_gb - hunspell_us),
            "wordnet_only": len(wordnet - readlex - hunspell_gb - hunspell_us),
            "hunspell_gb_only": len(hunspell_gb - readlex - wordnet - hunspell_us),
            "hunspell_us_only": len(hunspell_us - readlex - wordnet - hunspell_gb)
        },
        "total_unique": len(readlex | wordnet | hunspell_gb | hunspell_us)
    }
    print(json.dumps(results, indent=2))

def export_csv(readlex, wordnet, hunspell_gb, hunspell_us):
    """Export analysis results as CSV."""
    print("metric,count")
    print(f"readlex_total,{len(readlex)}")
    print(f"wordnet_total,{len(wordnet)}")
    print(f"hunspell_gb_total,{len(hunspell_gb)}")
    print(f"hunspell_us_total,{len(hunspell_us)}")
    print(f"readlex_wordnet_overlap,{len(readlex & wordnet)}")
    print(f"readlex_hunspell_gb_overlap,{len(readlex & hunspell_gb)}")
    print(f"readlex_hunspell_us_overlap,{len(readlex & hunspell_us)}")
    print(f"wordnet_hunspell_gb_overlap,{len(wordnet & hunspell_gb)}")
    print(f"all_three_overlap,{len(readlex & wordnet & hunspell_gb)}")
    print(f"total_unique,{len(readlex | wordnet | hunspell_gb | hunspell_us)}")

def main():
    parser = argparse.ArgumentParser(
        description="Analyze word coverage across Shaw-Spell dictionary sources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Default summary output
  %(prog)s --verbose          # Detailed analysis with samples
  %(prog)s --json             # Machine-readable JSON output
  %(prog)s --csv              # CSV format for spreadsheets
        """
    )
    parser.add_argument('--json', action='store_true',
                       help='Output results as JSON')
    parser.add_argument('--csv', action='store_true',
                       help='Output results as CSV')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed analysis including sample words')

    args = parser.parse_args()

    # Determine paths relative to repo root
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent

    readlex_path = repo_root / 'external' / 'readlex' / 'readlex.json'
    wordnet_yaml_dir = repo_root / 'external' / 'english-wordnet' / 'src' / 'yaml'
    hunspell_gb_path = repo_root / 'external' / 'hunspell-en' / 'en_GB (Marco Pinto) (-ise -ize) (2025+)' / 'en_GB.dic'
    hunspell_us_path = repo_root / 'external' / 'hunspell-en' / 'en_US (Kevin Atkinson)' / 'en_US.dic'

    # Load all datasets
    if not args.json and not args.csv:
        print("Loading datasets...", file=sys.stderr)
        print(f"  - ReadLex from {readlex_path.relative_to(repo_root)}", file=sys.stderr)
        print(f"  - WordNet from {wordnet_yaml_dir.relative_to(repo_root)}", file=sys.stderr)
        print(f"  - Hunspell GB from {hunspell_gb_path.relative_to(repo_root)}", file=sys.stderr)
        print(f"  - Hunspell US from {hunspell_us_path.relative_to(repo_root)}", file=sys.stderr)

    readlex = load_readlex_words(readlex_path)
    wordnet = load_wordnet_words(wordnet_yaml_dir)
    hunspell_gb = load_hunspell_words(hunspell_gb_path)
    hunspell_us = load_hunspell_words(hunspell_us_path)

    # Output in requested format
    if args.json:
        export_json(readlex, wordnet, hunspell_gb, hunspell_us)
    elif args.csv:
        export_csv(readlex, wordnet, hunspell_gb, hunspell_us)
    else:
        print_summary(readlex, wordnet, hunspell_gb, hunspell_us, verbose=args.verbose)

if __name__ == '__main__':
    main()
