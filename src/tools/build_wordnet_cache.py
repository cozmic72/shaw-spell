#!/usr/bin/env python3
"""
Build comprehensive WordNet cache from YAML source files.

Parses all WordNet YAML files to extract:
- Lemmas and part-of-speech tags
- Irregular inflected forms (explicit in 'form:' field)
- Pronunciations (US/GB variants)
- Senses with synset IDs
- Derivation relationships
- Dialect markers (US/GB/CA/AU)

Output: data/wordnet-comprehensive.json

This is EXPENSIVE preprocessing (73 YAML files, ~150K lemmas).
Run once and commit the output to data/.

Usage:
    ./src/tools/build_wordnet_cache.py [--output PATH]
"""

import sys
import json
import yaml
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Optional, Any

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'dictionaries'))
from wordnet_dialect import load_wordnet_dialect_data


def parse_synset_files(yaml_dir: Path) -> Dict[str, Dict]:
    """
    Parse synset YAML files to extract definitions.

    Returns:
        Dict mapping synset_id → {'definition': str, 'pos': str}
    """
    print("Parsing synset files for definitions...")

    # Synset files: adj.all.yaml, adv.all.yaml, noun.*.yaml, verb.*.yaml
    synset_files = []
    for pattern in ['adj.*.yaml', 'adv.*.yaml', 'noun.*.yaml', 'verb.*.yaml']:
        synset_files.extend(yaml_dir.glob(pattern))

    synset_files = sorted(synset_files)
    print(f"Found {len(synset_files)} synset files")

    synsets = {}

    for i, yaml_file in enumerate(synset_files, 1):
        if i % 5 == 0:
            print(f"  Processing synset file {i}/{len(synset_files)}: {yaml_file.name}")

        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                continue

            # Each synset file contains: {synset_id: synset_data}
            for synset_id, synset_data in data.items():
                if not isinstance(synset_data, dict):
                    continue

                # Extract definition (can be string or list)
                definition = synset_data.get('definition')
                if definition:
                    if isinstance(definition, list):
                        definition = ' '.join(definition)

                    synsets[synset_id] = {
                        'definition': definition,
                        'pos': synset_data.get('partOfSpeech', '')
                    }

        except Exception as e:
            print(f"Warning: Error parsing {yaml_file.name}: {e}")
            continue

    print(f"Loaded {len(synsets)} synset definitions")
    return synsets


def parse_all_yaml_files(yaml_dir: Path, overrides_path: Path = None) -> Dict[str, Dict]:
    """
    Parse all WordNet YAML files and merge entries by lemma.
    Optionally load overrides file last to override/extend entries.

    Returns:
        Dict mapping lemma → {pos → data}
    """
    print("Parsing WordNet YAML files...")

    yaml_files = sorted(yaml_dir.glob('*.yaml'))

    # Add overrides file to the end if it exists
    if overrides_path and overrides_path.exists():
        yaml_files.append(overrides_path)
        print(f"Found {len(yaml_files)-1} WordNet YAML files + 1 overrides file")
    else:
        print(f"Found {len(yaml_files)} YAML files to process")

    lemma_data = defaultdict(lambda: defaultdict(lambda: {
        'forms': set(),
        'pronunciations': {},
        'senses': []
    }))

    for i, yaml_file in enumerate(yaml_files, 1):
        if i % 10 == 0:
            print(f"  Processing file {i}/{len(yaml_files)}: {yaml_file.name}")

        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                continue

            # Each YAML file contains: {lemma: {pos: data}}
            for lemma, pos_dict in data.items():
                if not isinstance(pos_dict, dict):
                    continue

                for pos, pos_data in pos_dict.items():
                    if not isinstance(pos_data, dict):
                        continue

                    # Extract forms (irregular inflections)
                    if 'form' in pos_data and pos_data['form']:
                        forms = pos_data['form']
                        if isinstance(forms, list):
                            lemma_data[lemma][pos]['forms'].update(forms)

                    # Extract pronunciations
                    if 'pronunciation' in pos_data:
                        pron_list = pos_data['pronunciation']
                        if isinstance(pron_list, list):
                            for pron in pron_list:
                                if isinstance(pron, dict) and 'value' in pron:
                                    # Simple pronunciation (no variety specified)
                                    lemma_data[lemma][pos]['pronunciations']['default'] = pron['value']
                                elif isinstance(pron, str):
                                    lemma_data[lemma][pos]['pronunciations']['default'] = pron
                        elif isinstance(pron_list, str):
                            lemma_data[lemma][pos]['pronunciations']['default'] = pron_list

                    # Extract senses
                    if 'sense' in pos_data and isinstance(pos_data['sense'], list):
                        for sense in pos_data['sense']:
                            if isinstance(sense, dict):
                                sense_entry = {
                                    'id': sense.get('id', ''),
                                    'synset': sense.get('synset', '')
                                }

                                # Include custom definition if present (from overrides)
                                if 'definition' in sense:
                                    sense_entry['definition'] = sense['definition']

                                # Include derivation info if present
                                if 'derivation' in sense:
                                    sense_entry['derivation'] = sense['derivation']

                                # Include pertainym info if present
                                if 'pertainym' in sense:
                                    sense_entry['pertainym'] = sense['pertainym']

                                lemma_data[lemma][pos]['senses'].append(sense_entry)

        except Exception as e:
            print(f"  WARNING: Error parsing {yaml_file.name}: {e}")
            continue

    # Convert sets to lists for JSON serialization
    result = {}
    for lemma, pos_dict in lemma_data.items():
        result[lemma] = {}
        for pos, data in pos_dict.items():
            result[lemma][pos] = {
                'forms': sorted(list(data['forms'])),
                'pronunciations': data['pronunciations'],
                'senses': data['senses']
            }

    print(f"Parsed {len(result)} unique lemmas")
    return result


def load_existing_definitions(definitions_path: Path) -> Dict[str, List[Dict]]:
    """Load existing WordNet definitions cache."""
    if not definitions_path.exists():
        print(f"WARNING: Definitions cache not found at {definitions_path}")
        return {}

    print("Loading existing WordNet definitions...")
    with open(definitions_path, 'r', encoding='utf-8') as f:
        defs = json.load(f)
    print(f"Loaded definitions for {len(defs)} words")
    return defs


def merge_comprehensive_cache(
    lemma_data: Dict[str, Dict],
    dialect_data,
    definitions: Dict[str, List[Dict]],
    synsets: Dict[str, Dict]
) -> Dict[str, Dict]:
    """
    Merge all data sources into comprehensive cache.

    Structure:
    {
      "lemma": {
        "lemma": "word",
        "pos_entries": {
          "v": {
            "forms": ["walked", "walking"],  # empty if regular
            "pronunciations": {"default": "wɔk"},
            "senses": [...],
            "definitions": [...]  # from existing cache
          }
        },
        "dialect": "US" | "GB" | null,
        "variants": {"GB": "colour", "US": "color"}
      }
    }
    """
    print("\nMerging comprehensive cache...")

    cache = {}
    processed = 0

    for lemma, pos_dict in lemma_data.items():
        processed += 1
        if processed % 10000 == 0:
            print(f"  Processed {processed}/{len(lemma_data)} lemmas")

        # Get dialect info
        dialects = dialect_data.get_dialects(lemma)
        primary_dialect = None
        if dialects:
            # Priority: US, GB, CA, AU
            if 'US' in dialects:
                primary_dialect = 'US'
            elif 'GB' in dialects:
                primary_dialect = 'GB'
            elif 'CA' in dialects:
                primary_dialect = 'CA'
            elif 'AU' in dialects:
                primary_dialect = 'AU'

        # Get variants as lists (sorted for deterministic output)
        variants_raw = dialect_data.get_all_variants(lemma)
        # Sort both the dialect keys and the variant lists within each dialect
        variants = {k: sorted(variants_raw[k]) for k in sorted(variants_raw.keys())}

        # Get definitions for this lemma
        lemma_defs = definitions.get(lemma.lower(), [])

        # Build pos_entries
        pos_entries = {}
        for pos, data in pos_dict.items():
            pos_entry = {
                'forms': data['forms'],
                'pronunciations': data['pronunciations'],
                'senses': data['senses']
            }

            # Collect definitions from multiple sources
            all_defs = []

            # 1. Add definitions from existing cache that match this POS
            if lemma_defs:
                matching_defs = [
                    d for d in lemma_defs
                    if matches_pos(d.get('pos', ''), pos)
                ]
                if matching_defs:
                    all_defs.extend(matching_defs)
                elif not pos_entries:  # First POS, add all definitions
                    all_defs.extend(lemma_defs)

            # 2. Extract definitions from senses (from overrides)
            for sense in data['senses']:
                if 'definition' in sense:
                    all_defs.append({
                        'definition': sense['definition'],
                        'pos': pos
                    })

            # 3. Extract definitions from synsets based on synset IDs
            for sense in data['senses']:
                synset_id = sense.get('synset')
                if synset_id and synset_id in synsets:
                    synset_data = synsets[synset_id]
                    all_defs.append({
                        'definition': synset_data['definition'],
                        'pos': pos
                    })

            if all_defs:
                pos_entry['definitions'] = all_defs

            pos_entries[pos] = pos_entry

        cache[lemma] = {
            'lemma': lemma,
            'pos_entries': pos_entries,
            'dialect': primary_dialect,
            'variants': variants
        }

    print(f"Created comprehensive cache with {len(cache)} entries")
    return cache


def matches_pos(definition_pos: str, wordnet_pos: str) -> bool:
    """
    Check if a definition POS matches a WordNet POS tag.

    WordNet POS: n, v, a, r, s
    Definition POS: noun, verb, adjective, adverb, etc.
    """
    pos_map = {
        'n': ['noun'],
        'v': ['verb'],
        'a': ['adjective'],
        'r': ['adverb'],
        's': ['adjective']  # satellite adjective
    }

    wordnet_pos_types = pos_map.get(wordnet_pos, [])
    return any(wt in definition_pos.lower() for wt in wordnet_pos_types)


def write_cache(cache: Dict, output_path: Path):
    """Write comprehensive cache to JSON file."""
    print(f"\nWriting cache to {output_path}...")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Cache written: {file_size_mb:.1f} MB")


def print_statistics(cache: Dict):
    """Print statistics about the cache."""
    print("\n" + "="*60)
    print("CACHE STATISTICS")
    print("="*60)

    total_lemmas = len(cache)
    total_forms = sum(
        len(pos_data.get('forms', []))
        for entry in cache.values()
        for pos_data in entry['pos_entries'].values()
    )

    dialect_counts = defaultdict(int)
    for entry in cache.values():
        if entry['dialect']:
            dialect_counts[entry['dialect']] += 1

    pos_counts = defaultdict(int)
    for entry in cache.values():
        for pos in entry['pos_entries'].keys():
            pos_counts[pos] += 1

    irregular_count = sum(
        1 for entry in cache.values()
        for pos_data in entry['pos_entries'].values()
        if pos_data.get('forms')
    )

    print(f"Total lemmas:          {total_lemmas:,}")
    print(f"Total irregular forms: {total_forms:,}")
    print(f"Entries with irregulars: {irregular_count:,}")
    print(f"\nDialect distribution:")
    for dialect, count in sorted(dialect_counts.items()):
        print(f"  {dialect}: {count:,}")
    print(f"\nPOS distribution:")
    for pos, count in sorted(pos_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {pos}: {count:,}")
    print("="*60)


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Build comprehensive WordNet cache from YAML sources'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'data/wordnet-comprehensive.json',
        help='Output path for cache (default: data/wordnet-comprehensive.json)'
    )

    args = parser.parse_args()

    # Paths
    project_dir = Path(__file__).parent.parent.parent
    yaml_dir = project_dir / 'external/english-wordnet/src/yaml'
    definitions_path = project_dir / 'build/wordnet-definitions.json'
    overrides_path = project_dir / 'src/dictionaries/wordnet-overrides.yaml'

    # Validate inputs
    if not yaml_dir.exists():
        print(f"ERROR: YAML directory not found: {yaml_dir}")
        print("Please ensure external/english-wordnet submodule is initialized")
        sys.exit(1)

    print("="*60)
    print("BUILDING COMPREHENSIVE WORDNET CACHE")
    print("="*60)
    print(f"YAML source: {yaml_dir}")
    print(f"Overrides: {overrides_path}")
    print(f"Output: {args.output}")
    print()

    # Step 1: Parse synset files for definitions
    synsets = parse_synset_files(yaml_dir)

    # Step 2: Parse entry files (includes overrides if present)
    lemma_data = parse_all_yaml_files(yaml_dir, overrides_path)

    # Step 3: Load dialect data from YAML
    dialect_data = load_wordnet_dialect_data(yaml_dir)

    # Step 4: Load existing definitions (for backwards compatibility)
    definitions = load_existing_definitions(definitions_path)

    # Step 5: Merge everything
    cache = merge_comprehensive_cache(lemma_data, dialect_data, definitions, synsets)

    # Step 6: Write cache
    write_cache(cache, args.output)

    # Step 7: Print statistics
    print_statistics(cache)

    print(f"\n✓ Cache successfully built: {args.output}")
    print(f"  This file should be committed to git for reuse.")


if __name__ == '__main__':
    main()
