# Shaw-Spell

![Shaw-Spell](src/images/shaw-spell.png)

**Comprehensive Shavian spelling support for macOS**

Shaw-Spell provides dictionaries for Dictionary.app and system-wide spell checking for the Shavian alphabet. 
106,000+ Shavian words with definitions, pronunciations, and intelligent spell checking that works in all macOS apps.

**Download and learn more about the project at [joro.io/shaw-spell](https://joro.io/shaw-spell)**

## Building from Source

### Prerequisites

```bash
# Install Xcode Command Line Tools
xcode-select --install

# Install dependencies via Homebrew
brew install hunspell      # Spell checking library
brew install python@3      # For build scripts

# Install Python dependencies
pip3 install PyYAML

# Install shave tool (for Shavian transliteration)
# See: https://github.com/Shavian-info/shave
```

You'll also need the [Apple Dictionary Development Kit](https://github.com/SebastianSzturo/apple-dictionary-dev-kit) installed at `/Library/Developer/Dictionary Development Kit`.

### Build

```bash
git clone https://github.com/cozmic72/shaw-spell.git
cd shaw-spell
git submodule update --init --recursive
make install
```

This builds and installs the spell checker and the dictionaries under ~/Library.

## Supplement Data Pipeline

Shaw-Spell supplements the core ReadLex dictionary with pronunciation and definition data from three open-source datasources, adding ~29,000 new words.

### Data Sources

| Source | Words | What it provides |
|--------|-------|-----------------|
| [ReadLex](https://github.com/shavian-info/readlex) | 77,342 | Core Shavian dictionary (IPA, Shavian, POS, frequency) |
| [Britfone](https://github.com/JoseLlarena/Britfone) | +764 new | British (SSB) IPA pronunciations |
| [Open English WordNet](https://github.com/globalwordnet/english-wordnet) | +6,500 new | GB+US IPA, POS, definitions |
| [Wiktionary](https://kaikki.org/dictionary/English/) | +24,000 new | IPA with dialect labels (RP, GenAm), definitions |

### Generating Supplements

```bash
# Generate all supplements from source data, rescore, and merge
make supplements-from-source

# Or step by step:
python3 src/tools/generate_britfone_supplement.py
python3 src/tools/generate_wordnet_supplement.py
python3 src/tools/generate_wiktionary_supplement.py

# Re-score confidence with shave consultation (fast, no source re-parsing)
python3 src/tools/rescore_supplements.py --full-shave

# Merge supplements into data/readlex.json
python3 src/tools/generate_merged_readlex.py

# Generate review files for human inspection
python3 src/tools/generate_review_files.py
```

### Make Targets

| Target | Description |
|--------|------------|
| `make supplements` | Ensure merged readlex is up to date |
| `make supplements-from-source` | Full rebuild from source data |
| `make rescore-full` | Re-score confidence with full shave consultation |
| `make review-files` | Generate review TSVs for human inspection |
| `make transliterations` | Rebuild Shavian definition caches (requires shave) |
| `make dictionaries` | Build all Apple Dictionary bundles |
| `make spellcheck` | Build all Hunspell dictionaries |
| `make site` | Build web dictionary frontend |

### Confidence Scoring

Each supplement entry has an empirically calibrated confidence percentage:

| Confidence | Meaning |
|-----------|---------|
| 97% | IPA conversion + shave morphological tool agree |
| 95% | Shave rescued from lower confidence |
| 89% | Clean IPA conversion, shave disagrees (dialect difference) |
| ≤30% | Known issues (missing r, unknown characters) |

### Dialect Variants

Following ReadLex conventions, the `var` field tags dialect-specific entries:

| `var` | Meaning |
|-------|---------|
| `RRP` | Rhotic Received Pronunciation (canonical, universal default) |
| `RSSB` | Rhotic Standard Southern British (supplement data) |
| `GenAm` | General American (exceptions + supplement data) |
| `TrapBath` | TRAP-BATH unsplit alternative (𐑭→𐑨 in BATH words) |
| `CotCaught` | Cot-caught merger alternative (𐑪→𐑷 in LOT words) |

### Regenerating Caches

```bash
# Regenerate transliteration caches (requires shave tool)
make transliterations

# Regenerate comprehensive WordNet cache (~2 minutes)
make wordnet-cache

# Extract Wiktionary definitions for supplement words
python3 src/tools/extract_wiktionary_definitions.py
```

## Copyright

Shaw-Spell © 2025 joro.io • [MIT License](LICENSE.md)

Includes:
- **[ReadLex](https://github.com/shavian-info/readlex)** (Shavian word data) • MIT License
- **[Open English WordNet 2024](https://github.com/globalwordnet/english-wordnet)** (definitions) • CC BY 4.0
- **[Britfone](https://github.com/JoseLlarena/Britfone)** (British pronunciations) • MIT License
- **[Wiktionary](https://en.wiktionary.org/)** (pronunciations, definitions) • CC BY-SA 3.0

See [LICENSE.md](LICENSE.md) for complete details.
