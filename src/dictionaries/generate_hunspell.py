#!/usr/bin/env python3
"""
Generate Hunspell dictionaries (.dic and .aff) from WordNet comprehensive cache
and Readlex data.

Uses the comprehensive WordNet cache and Readlex to generate high-quality Hunspell
dictionaries with proper dialect filtering and minimal affix rules (since irregular
forms are explicit).

Generates:
  - build/io.joro.shaw-spell.en_GB.dic + .aff
  - build/io.joro.shaw-spell.en_US.dic + .aff

Usage:
    ./src/dictionaries/generate_hunspell.py --dialect gb
    ./src/dictionaries/generate_hunspell.py --dialect us
"""

import json
import sys
from pathlib import Path
from typing import Dict, Set, List
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from dialect_display import (
    spellcheck_vars, is_american, US_GAP_FALLBACK_VARS,
)


# Affix flag definitions
# We keep these minimal since we have explicit irregular forms
AFFIX_FLAGS = {
    'S': 'plural/3rd person singular',  # -s, -es
    'D': 'past tense',                  # -ed
    'G': 'present participle',          # -ing
    'R': 'comparative',                 # -er
    'T': 'superlative',                 # -est
    'Y': 'adverb',                      # -ly
    'M': 'possessive',                  # 's
    'N': 'negation',                    # un-
}


def load_comprehensive_cache(cache_path: Path) -> Dict:
    """Load the comprehensive WordNet cache."""
    print(f"Loading comprehensive cache from {cache_path}...")
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache = json.load(f)
    print(f"Loaded {len(cache)} entries")
    return cache


def load_readlex_data(readlex_path: Path) -> Dict:
    """Load Readlex data."""
    print(f"Loading Readlex data from {readlex_path}...")
    with open(readlex_path, 'r', encoding='utf-8') as f:
        readlex = json.load(f)
    print(f"Loaded {len(readlex)} Readlex entries")
    return readlex


def extract_readlex_words(readlex_data: Dict, target_dialect: str) -> Set[str]:
    """
    Extract Latin alphabet words from Readlex for the target dialect.

    Args:
        readlex_data: The Readlex data dictionary
        target_dialect: 'gb' or 'us'

    Returns:
        Set of lowercase Latin words from Readlex
    """
    words = set()
    dialect = target_dialect.lower()

    # Vars that may become a HEADWORD in THIS dictionary. Foreign national
    # accents (AU/CA/NZ/ZA/IE) are deliberately excluded — they are their own
    # dialect and never pollute gb/us (see dialect_display.spellcheck_vars).
    # trap-bath is a `mergers` flag on an RRP record now, so those forms come
    # in under RRP (British).
    target_variants = spellcheck_vars(dialect)

    # US-gap fallback (us dict only): a lemma with NO native GenAm form falls
    # back to its British Latin form so a US typist isn't flagged for the only
    # spelling that exists. Collect British candidates per lemma; admit after
    # the native pass only for lemmas America has nothing native for.
    lemma_has_american: Dict[str, bool] = defaultdict(bool)
    gap_candidates: List = []  # (lemma, latn) British forms eligible for fallback

    for key, entries in readlex_data.items():
        lemma = key.split('_', 1)[0].lower()
        # Normalize: supplement entries may be single dicts
        if isinstance(entries, dict):
            entries = [entries]
        for entry in entries:
            latn = entry.get('Latn', '').strip()
            var = entry.get('var', '')
            if not latn:
                continue

            if dialect == 'us' and is_american(var):
                lemma_has_american[lemma] = True

            if not var or var in target_variants:
                # Add the word in lowercase (Hunspell is case-insensitive for base words)
                words.add(latn.lower())
            elif dialect == 'us' and var in US_GAP_FALLBACK_VARS:
                gap_candidates.append((lemma, latn.lower()))

    if dialect == 'us':
        gap_admitted = 0
        for lemma, latn in gap_candidates:
            if not lemma_has_american[lemma] and latn not in words:
                words.add(latn)
                gap_admitted += 1
        print(f"US-gap fallback: {gap_admitted} British Latin form(s) admitted "
              f"(words with no native GenAm form)")

    print(f"Extracted {len(words)} unique Latin words from Readlex for {target_dialect.upper()}")
    return words


def should_include_word(entry: Dict, target_dialect: str) -> bool:
    """
    Determine if a word should be included in the target dialect dictionary.

    Rules:
    - If dialect is None (neutral): include in both GB and US
    - If dialect matches target: include
    - If dialect doesn't match: exclude
    """
    word_dialect = entry.get('dialect')

    if word_dialect is None:
        return True  # Neutral words go in both dictionaries

    # Map our dialect codes
    dialect_map = {
        'gb': ['GB', 'CA', 'AU'],  # GB includes Commonwealth
        'us': ['US']
    }

    return word_dialect in dialect_map.get(target_dialect.lower(), [])


def get_affix_flags(lemma: str, pos: str, has_explicit_forms: bool) -> str:
    """
    Determine which affix flags to assign to a word.

    If the word has explicit irregular forms, return empty (we'll add forms separately).
    Otherwise, assign flags based on POS for regular inflections.
    """
    if has_explicit_forms:
        return ''  # Irregular - forms will be added explicitly

    # Regular inflections based on POS
    flags = []

    if pos == 'n':  # Noun
        flags.append('S')  # Plural
        flags.append('M')  # Possessive

    elif pos == 'v':  # Verb
        flags.append('D')  # Past tense (-ed)
        flags.append('G')  # Present participle (-ing)
        flags.append('S')  # 3rd person singular (-s)

    elif pos == 'a':  # Adjective
        flags.append('R')  # Comparative (-er)
        flags.append('T')  # Superlative (-est)
        flags.append('Y')  # Adverb (-ly)

    elif pos == 'r':  # Adverb
        pass  # Most adverbs don't inflect regularly

    return ''.join(sorted(flags))


def generate_dic_file(cache: Dict, target_dialect: str, output_path: Path, readlex_words: Set[str] = None):
    """
    Generate .dic file from comprehensive cache and Readlex words.

    Format:
        <word count>
        word1/FLAGS
        word2/FLAGS
        irregularform1
        irregularform2
    """
    print(f"\nGenerating {target_dialect.upper()} .dic file...")

    word_entries = set()  # Use set to avoid duplicates

    # Add words from WordNet cache
    for lemma, entry in cache.items():
        # Check if this word belongs in this dialect
        if not should_include_word(entry, target_dialect):
            continue

        pos_entries = entry.get('pos_entries', {})

        for pos, pos_data in pos_entries.items():
            forms = pos_data.get('forms', [])
            has_explicit_forms = len(forms) > 0

            # Add the lemma with appropriate flags
            flags = get_affix_flags(lemma, pos, has_explicit_forms)
            if flags:
                word_entries.add(f"{lemma}/{flags}")
            else:
                word_entries.add(lemma)

            # Add explicit irregular forms (no flags)
            for form in forms:
                word_entries.add(form)

    wordnet_count = len(word_entries)
    print(f"Added {wordnet_count:,} entries from WordNet")

    # Add words from Readlex (if provided)
    if readlex_words:
        # Build a set of base words from WordNet for fast lookup
        wordnet_base_words = {entry.split('/')[0] for entry in word_entries}

        readlex_only = 0
        for word in readlex_words:
            # Only add if not already in word_entries (from WordNet)
            # This allows WordNet entries (with their flags) to take precedence
            if word not in wordnet_base_words:
                word_entries.add(word)
                readlex_only += 1

        print(f"Added {readlex_only:,} additional entries from Readlex")

    # Write .dic file
    print(f"Writing {len(word_entries):,} total entries to {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"{len(word_entries)}\n")
        for entry in sorted(word_entries):
            f.write(f"{entry}\n")

    print(f"✓ Generated {output_path}")


def generate_aff_file(target_dialect: str, output_path: Path):
    """
    Generate .aff file with affix rules and common misspellings.

    Based on English grammar, not copied from existing dictionaries.
    """
    print(f"\nGenerating {target_dialect.upper()} .aff file...")

    aff_content = f"""# Affix file for {target_dialect.upper()} English (Shaw-Spell)
# Generated from Open English WordNet data
# Copyright © 2025 joro.io
# Based on linguistic patterns of English morphology

SET UTF-8

# Character suggestion order (based on English letter frequency)
TRY esianrtolcdugmphbyfvkwzESIANRTOLCDUGMPHBYFVKWZ'

# Ligature conversions
ICONV 6
ICONV ' '
ICONV ﬃ ffi
ICONV ﬄ ffl
ICONV ﬀ ff
ICONV ﬁ fi
ICONV ﬂ fl

OCONV 1
OCONV ' '

# Characters considered part of words
WORDCHARS 0123456789'

# No-suggest flag
NOSUGGEST !

# Ordinal numbers support
COMPOUNDMIN 1
ONLYINCOMPOUND c
COMPOUNDRULE 2
COMPOUNDRULE n*1t
COMPOUNDRULE n*mp

"""

    # Add REP entries (common misspellings based on English phonetics)
    aff_content += generate_rep_entries(target_dialect)

    # Add suffix rules
    aff_content += generate_suffix_rules()

    # Add prefix rules
    aff_content += generate_prefix_rules()

    # Write .aff file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(aff_content)

    print(f"✓ Generated {output_path}")


def generate_rep_entries(dialect: str) -> str:
    """
    Generate REP (replacement) entries for common misspellings.

    Based on English phonetics and common errors, not copied from other dictionaries.
    Includes dialect-specific patterns.
    """
    # Common phonetic confusions (dialect-neutral)
    phonetic_reps = [
        ('f', 'ph'), ('ph', 'f'),           # /f/ sound
        ('f', 'gh'), ('gh', 'f'),           # tough, laugh
        ('k', 'c'), ('c', 'k'),             # /k/ sound
        ('k', 'ch'), ('ch', 'k'),           # school, chemistry
        ('s', 'c'), ('c', 's'),             # city, cent
        ('j', 'g'), ('g', 'j'),             # /dʒ/ sound
        ('w', 'wh'), ('wh', 'w'),           # where, were
        ('kw', 'qu'), ('qu', 'kw'),         # queen

        # Vowel confusions
        ('ei', 'ie'), ('ie', 'ei'),         # receive, believe
        ('a', 'ei'), ('ei', 'a'),
        ('a', 'e'), ('e', 'a'),

        # Double letters
        ('l', 'll'), ('ll', 'l'),
        ('s', 'ss'), ('ss', 's'),
        ('t', 'tt'), ('tt', 't'),

        # Silent letters
        ('n', 'kn'), ('kn', 'n'),           # knight, night
        ('n', 'gn'), ('gn', 'n'),           # gnome, nome
        ('w', 'wr'), ('wr', 'w'),           # write, rite

        # Common mistakes
        ('alot', 'a lot'),
        ('eg', 'e.g.'),
        ('ie', 'i.e.'),
    ]

    # Dialect-specific patterns
    dialect_reps = []
    if dialect == 'gb':
        dialect_reps = [
            ('or', 'our'),                   # US color → GB colour
            ('er', 're'),                    # US center → GB centre
            ('og', 'ogue'),                  # US dialog → GB dialogue
            ('ize', 'ise'),                  # US realize → GB realise
            ('yze', 'yse'),                  # US analyze → GB analyse
            ('ense', 'ence'),                # US defense → GB defence
        ]
    elif dialect == 'us':
        dialect_reps = [
            ('our', 'or'),                   # GB colour → US color
            ('re', 'er'),                    # GB centre → US center
            ('ogue', 'og'),                  # GB dialogue → US dialog
            ('ise', 'ize'),                  # GB realise → US realize
            ('yse', 'yze'),                  # GB analyse → US analyze
            ('ence', 'ense'),                # GB defence → US defense
        ]

    # Combine all REP entries
    all_reps = phonetic_reps + dialect_reps

    rep_content = f"\n# Common misspellings and phonetic substitutions\n"
    rep_content += f"REP {len(all_reps)}\n"
    for old, new in all_reps:
        rep_content += f"REP {old} {new}\n"

    return rep_content


def generate_suffix_rules() -> str:
    """
    Generate suffix (SFX) rules for regular inflections.

    These are simplified rules since irregular forms are explicit in the cache.
    """
    return """
# Suffix rules for regular inflections

# S: Plural/3rd person singular (-s, -es)
SFX S Y 4
SFX S   y     ies       [^aeiou]y    # baby → babies
SFX S   0     s         [aeiou]y     # boy → boys
SFX S   0     es        [sxzh]       # box → boxes, wish → wishes
SFX S   0     s         [^sxzhy]     # cat → cats

# D: Past tense (-ed)
SFX D Y 4
SFX D   0     d         e            # love → loved
SFX D   y     ied       [^aeiou]y    # try → tried
SFX D   0     ed        [aeiou]y     # play → played
SFX D   0     ed        [^ey]        # walk → walked

# G: Present participle (-ing)
SFX G Y 3
SFX G   e     ing       e            # love → loving
SFX G   0     ing       [aeiou]y     # play → playing
SFX G   0     ing       [^ey]        # walk → walking

# R: Comparative (-er)
SFX R Y 4
SFX R   0     r         e            # nice → nicer
SFX R   y     ier       [^aeiou]y    # happy → happier
SFX R   0     er        [aeiou]y     # gray → grayer
SFX R   0     er        [^ey]        # tall → taller

# T: Superlative (-est)
SFX T Y 4
SFX T   0     st        e            # nice → nicest
SFX T   y     iest      [^aeiou]y    # happy → happiest
SFX T   0     est       [aeiou]y     # gray → grayest
SFX T   0     est       [^ey]        # tall → tallest

# Y: Adverb (-ly)
SFX Y Y 2
SFX Y   y     ily       y            # happy → happily
SFX Y   0     ly        [^y]         # quick → quickly

# M: Possessive ('s)
SFX M Y 1
SFX M   0     's        .            # cat → cat's
"""


def generate_prefix_rules() -> str:
    """Generate prefix (PFX) rules for common English prefixes."""
    return """
# Prefix rules

# N: Negation (un-)
PFX N Y 1
PFX N   0     un        .            # happy → unhappy

# Other common prefixes could be added here
"""


def print_statistics(cache: Dict, gb_count: int, us_count: int):
    """Print statistics about generated dictionaries."""
    print("\n" + "="*60)
    print("HUNSPELL GENERATION STATISTICS")
    print("="*60)

    total_entries = len(cache)

    # Count entries with explicit forms
    irregular_count = sum(
        1 for entry in cache.values()
        for pos_data in entry.get('pos_entries', {}).values()
        if pos_data.get('forms')
    )

    # Count dialect-specific words
    dialect_specific = sum(
        1 for entry in cache.values()
        if entry.get('dialect') is not None
    )

    print(f"Total WordNet entries:     {total_entries:,}")
    print(f"Entries with irregulars:   {irregular_count:,}")
    print(f"Dialect-specific words:    {dialect_specific:,}")
    print(f"\nGenerated dictionaries:")
    print(f"  en_GB entries:           {gb_count:,}")
    print(f"  en_US entries:           {us_count:,}")
    print("="*60)


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate Hunspell dictionaries from WordNet comprehensive cache and Readlex'
    )
    parser.add_argument(
        '--dialect',
        choices=['gb', 'us'],
        default='gb',
        help='Target dialect (gb or us)'
    )
    parser.add_argument(
        '--cache',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'data/wordnet-comprehensive.json',
        help='Path to comprehensive WordNet cache'
    )
    parser.add_argument(
        '--readlex',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'data/readlex.json',
        help='Path to Readlex data file (supplemented)'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'build',
        help='Output directory for .dic and .aff files'
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.cache.exists():
        print(f"ERROR: Cache file not found: {args.cache}")
        print("Run: ./src/tools/build_wordnet_cache.py")
        sys.exit(1)

    if not args.readlex.exists():
        print(f"WARNING: Readlex file not found: {args.readlex}")
        print("Continuing without Readlex data...")
        readlex_words = None
    else:
        # Load Readlex and extract words
        readlex_data = load_readlex_data(args.readlex)
        readlex_words = extract_readlex_words(readlex_data, args.dialect)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Output paths
    dic_path = args.output_dir / f'io.joro.shaw-spell.en_{args.dialect.upper()}.dic'
    aff_path = args.output_dir / f'io.joro.shaw-spell.en_{args.dialect.upper()}.aff'

    print("="*60)
    print(f"GENERATING HUNSPELL {args.dialect.upper()} DICTIONARY")
    print("="*60)
    print(f"Cache:   {args.cache}")
    print(f"Readlex: {args.readlex}")
    print(f"Output:  {dic_path}")
    print(f"         {aff_path}")
    print()

    # Load cache
    cache = load_comprehensive_cache(args.cache)

    # Generate .aff file
    generate_aff_file(args.dialect, aff_path)

    # Generate .dic file with Readlex words
    generate_dic_file(cache, args.dialect, dic_path, readlex_words)

    # Count entries for both dialects for statistics
    gb_count = sum(1 for e in cache.values() if should_include_word(e, 'gb'))
    us_count = sum(1 for e in cache.values() if should_include_word(e, 'us'))

    # Print statistics
    print_statistics(cache, gb_count, us_count)

    print(f"\n✓ Successfully generated Hunspell {args.dialect.upper()} dictionary")
    print(f"  - {dic_path}")
    print(f"  - {aff_path}")


if __name__ == '__main__':
    main()
