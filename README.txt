Shavian Dictionaries for macOS
===============================

Comprehensive bilingual dictionaries for translating between English and
Shavian script for macOS, with full definitions from Open English WordNet.

FEATURES
========

- Three complete dictionaries:
  1. Shavian-English: Look up Shavian words, get English definitions
  2. English-Shavian: Look up English words, get Shavian translations & definitions
  3. Shavian-Shavian: Pure Shavian dictionary with transliterated definitions

- Word definitions from Open English WordNet 2024 (152,000+ words)
- IPA pronunciations for all entries
- Multiple spelling/pronunciation variants with language labels (RP, Gen-Am, etc.)
- Root word grouping - related forms shown together
- Human-readable part-of-speech tags
- Example sentences
- Dark mode support

PROJECT STRUCTURE
=================

- src/                          - Source files
  - generate_dictionaries.py    - Main dictionary generation script
  - parse_wordnet.py            - WordNet definition parser
- build/                        - Generated files
  - shavian-english.xml         - Shavian → English dictionary
  - english-shavian.xml         - English → Shavian dictionary
  - shavian-shavian.xml         - Shavian → Shavian dictionary
  - wordnet-definitions.json    - Parsed WordNet definitions
- dictionaries/                 - Dictionary build configurations
  - shavian-english/            - Shavian → English build files
  - english-shavian/            - English → Shavian build files
  - shavian-shavian/            - Shavian → Shavian build files
- external/                     - External resources
  - english-wordnet/            - Open English WordNet (git submodule)
  - english-wordnet-2024.xml    - WordNet 2024 XML file
- build.sh                      - Master build and install script

REQUIREMENTS
============

- Apple Dictionary Development Kit installed at:
  /Library/Developer/Dictionary Development Kit
- Python 3
- shave tool (for Shavian transliteration) - must be in PATH
- macOS
- Git (for submodules)

DATA SOURCES
============

- Shavian spellings: ../shavian-info/readlex/readlex.json (~56K entries)
- Definitions: Open English WordNet 2024 (161,705 words, 120,630 synsets)
- Transliteration: shave tool with WSD module

BUILDING
========

Quick start:

    ./build.sh

This will:
1. Generate XML files from readlex and WordNet
2. Transliterate definitions to Shavian (batch process)
3. Build all three dictionary bundles
4. Place .dictionary bundles in dictionaries/*/objects/

To build and install:

    ./build.sh install

This installs to ~/Library/Dictionaries/ and makes them available in
Dictionary.app (restart Dictionary.app to use them).

To clean build artifacts:

    ./build.sh clean

MANUAL BUILDING
===============

Step-by-step process:

1. Parse WordNet (one-time setup):
   ./src/parse_wordnet.py

2. Generate dictionary XML files:
   ./src/generate_dictionaries.py

3. Build individual dictionaries:
   cd dictionaries/shavian-english && make && make install
   cd dictionaries/english-shavian && make && make install
   cd dictionaries/shavian-shavian && make && make install

DICTIONARY DETAILS
==================

Shavian-English Dictionary
--------------------------
- Headword: Shavian script
- Shows: English spelling(s), IPA, POS, variant labels
- Definitions: English (from WordNet)
- Examples: English

English-Shavian Dictionary
--------------------------
- Headword: English
- Shows: Shavian spelling(s), IPA, POS, variant labels
- Definitions: Transliterated to Shavian
- Examples: Transliterated to Shavian

Shavian-Shavian Dictionary
--------------------------
- Headword: Shavian script
- Shows: IPA, variant labels
- Definitions: Transliterated to Shavian
- Examples: Transliterated to Shavian
- Pure Shavian experience

PERFORMANCE
===========

The build uses batch transliteration for efficiency:
- Collects all text needing transliteration
- Sends to shave tool in single HTML-structured call
- Dramatically faster than individual calls
- Typical build time: ~5-10 minutes (depending on hardware)

FUTURE ENHANCEMENTS
===================

- Additional open-source dictionary integration
- Etymology information
- Audio pronunciations
- Cross-references between related words
- Frequency information
- More dialect variants

DEVELOPMENT
===========

The dictionaries are generated from:
1. readlex.json - Shavian/English word mappings with IPA
2. Open English WordNet - Comprehensive English definitions
3. shave tool - English to Shavian transliteration

Git submodules:
- external/english-wordnet - Open English WordNet source (optional, we use XML)

LICENSE
=======

Dictionary content:
- readlex data: (from ../shavian-info)
- Open English WordNet: CC-BY 4.0

Build scripts and configuration: Created for this project

ABOUT
=====

Generated: 2025
Entries: ~75K Shavian entries, ~77K English entries
Definitions: 152,286 words from Open English WordNet 2024
