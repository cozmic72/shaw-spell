#!/usr/bin/env python3
"""Generate review TSV files from supplement data compared against ReadLex."""

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Shavian Unicode block: U+10450 to U+1047F, plus common punctuation/spaces
SHAVIAN_RE = re.compile(r'^[\U00010450-\U0001047F\s\-\'\u00B7]+$')


def is_pure_shavian(shaw: str) -> bool:
    """Check that Shaw string contains only Shavian characters (no Latin/IPA leaks)."""
    if not shaw:
        return False
    return bool(SHAVIAN_RE.match(shaw))


def starts_with_digit(word: str) -> bool:
    """Filter out words starting with a digit or that are only digits."""
    return bool(word) and word[0].isdigit()


def load_readlex():
    """Load ReadLex and build word -> set of Shaw spellings + IPA mappings."""
    path = os.path.join(BASE_DIR, 'external', 'readlex', 'readlex.json')
    readlex = json.load(open(path))
    rl_shaws = {}
    rl_ipas = {}
    for key, entries in readlex.items():
        for e in entries:
            w = e['Latn'].lower()
            if w not in rl_shaws:
                rl_shaws[w] = set()
            rl_shaws[w].add(e['Shaw'])
            if w not in rl_ipas:
                rl_ipas[w] = e.get('ipa', '')
    return rl_shaws, rl_ipas


def load_supplement(name):
    """Load a supplement JSON file and return its entries flattened."""
    path = os.path.join(BASE_DIR, 'data', f'supplement-{name}.json')
    data = json.load(open(path))
    entries = []
    for key, entry_list in data.items():
        for e in entry_list:
            entries.append(e)
    return entries


def generate_disagreements(entries, rl_shaws, rl_ipas, output_path):
    """Generate disagreement TSV: entries where our Shaw differs from ALL ReadLex variants."""
    seen = set()
    rows = []
    for e in entries:
        word = e['Latn'].lower()
        shaw = e['Shaw']
        ipa = e.get('ipa', '')

        # Filters
        if starts_with_digit(word):
            continue
        if not is_pure_shavian(shaw):
            continue

        # Must be in ReadLex to be a "disagreement"
        if word not in rl_shaws:
            continue

        # Check if our Shaw matches ANY ReadLex variant
        if shaw in rl_shaws[word]:
            continue

        # Deduplicate by word+shaw
        dedup_key = (word, shaw)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        rl_shaw_str = ', '.join(sorted(rl_shaws[word]))
        rl_ipa_str = rl_ipas.get(word, '')
        confidence = e.get('confidence', '')
        notes = e.get('review', '')

        rows.append(f"{word}\t{shaw}\t{ipa}\t{rl_shaw_str}\t{rl_ipa_str}\t{confidence}\t{notes}")

    rows.sort()
    with open(output_path, 'w') as f:
        f.write("word\tour_shaw\tour_ipa\treadlex_shaw\treadlex_ipa\tconfidence\tnotes\n")
        for row in rows:
            f.write(row + '\n')

    return len(rows)


def generate_new_words(entries, rl_shaws, output_path):
    """Generate new words TSV: high-confidence entries not in ReadLex at all."""
    seen = set()
    rows = []
    for e in entries:
        word = e['Latn'].lower()
        shaw = e['Shaw']
        ipa = e.get('ipa', '')
        pos = e.get('pos', '')
        var = e.get('var', '')
        confidence = e.get('confidence', '')

        # Filters
        if starts_with_digit(word):
            continue
        if not is_pure_shavian(shaw):
            continue
        if confidence != 'high':
            continue

        # Must NOT be in ReadLex at all
        if word in rl_shaws:
            continue

        # Deduplicate by word+shaw
        dedup_key = (word, shaw)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        rows.append(f"{word}\t{shaw}\t{ipa}\t{pos}\t{var}\t{confidence}")

    rows.sort()
    with open(output_path, 'w') as f:
        f.write("word\tshaw\tipa\tpos\tvar\tconfidence\n")
        for row in rows:
            f.write(row + '\n')

    return len(rows)


def main():
    print("Loading ReadLex...")
    rl_shaws, rl_ipas = load_readlex()
    print(f"  ReadLex: {len(rl_shaws)} unique words")

    data_dir = os.path.join(BASE_DIR, 'data')

    # Source configs: (supplement_name, disagreement_output, new_words_output)
    sources = [
        ('britfone', 'review-britfone-disagreements.tsv', 'new-words-britfone.tsv'),
        ('wordnet-reliable', 'review-wordnet-disagreements.tsv', 'new-words-wordnet-reliable.tsv'),
        ('wiktionary-reliable', 'review-wiktionary-rssb-disagreements.tsv', 'new-words-wiktionary-reliable.tsv'),
    ]

    for supp_name, disagree_file, new_file in sources:
        print(f"\nProcessing supplement-{supp_name}.json...")
        entries = load_supplement(supp_name)
        print(f"  Loaded {len(entries)} entries")

        disagree_path = os.path.join(data_dir, disagree_file)
        n_disagree = generate_disagreements(entries, rl_shaws, rl_ipas, disagree_path)
        print(f"  Disagreements: {n_disagree} rows -> {disagree_file}")

        new_path = os.path.join(data_dir, new_file)
        n_new = generate_new_words(entries, rl_shaws, new_path)
        print(f"  New words (high confidence): {n_new} rows -> {new_file}")


if __name__ == '__main__':
    main()
