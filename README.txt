Shaw-Spell - Shavian Dictionaries & Spell Checker for macOS
============================================================

Comprehensive bilingual dictionaries and spell checker for translating
between English and Shavian script on macOS, with full definitions from
Open English WordNet.

FEATURES
========

- Three complete dictionaries:
  1. Shavian-English: Look up Shavian words, get English definitions
  2. English-Shavian: Look up English words, get Shavian translations & definitions
  3. Shavian-Shavian: Pure Shavian dictionary with transliterated definitions

- Hunspell spell-checking dictionary (75K+ Shavian words)
  Works with: hunspell, LibreOffice, Firefox, Emacs, VSCode

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
  - generate_spellcheck.py      - Hunspell dictionary generator
  - build_definition_caches.py  - Shavian definition cache builder
  - parse_wordnet.py            - WordNet definition parser
- build/                        - Generated files
  - shavian-english.xml         - Shavian → English dictionary
  - english-shavian.xml         - English → Shavian dictionary
  - shavian-shavian.xml         - Shavian → Shavian dictionary
  - shaw.dic, shaw.aff          - Hunspell spell-check files
- data/                         - Cached data
  - definitions-shavian.json    - Transliterated definitions cache
- dictionaries/                 - Dictionary build configurations
  - shavian-english/            - Shavian → English build files
  - english-shavian/            - English → Shavian build files
  - shavian-shavian/            - Shavian → Shavian build files
- external/                     - External resources (git submodules)
  - readlex/                    - Shavian word mappings
  - english-wordnet/            - Open English WordNet source
  - english-wordnet-2024.xml    - WordNet 2024 XML file
- build.sh                      - Master build and install script

REQUIREMENTS
============

- Apple Dictionary Development Kit installed at:
  /Library/Developer/Dictionary Development Kit
- Python 3
- Python packages: PyYAML
- shave tool (for Shavian transliteration) - must be in PATH
- macOS
- Git (for submodules)

Install Python dependencies:
    pip3 install -r requirements.txt

SETUP
=====

After cloning the repository, initialize the submodules:

    git submodule update --init --recursive

This will download:
- readlex: Shavian word mappings
- english-wordnet: Open English WordNet 2024 source (YAML files)

The WordNet XML file will be generated from the YAML sources during the build.

DATA SOURCES
============

- Shavian spellings: external/readlex/readlex.json (~56K entries)
- Definitions: Open English WordNet 2024 (161,705 words, 120,630 synsets)
  - Source: https://github.com/globalwordnet/english-wordnet
  - Generated from YAML sources to XML, then parsed to JSON
- Transliteration: shave tool with WSD module

BUILDING
========

Quick start:

    make

This will show all available build targets. To build everything:

    make DIALECT=gb all    # British English (default)
    make DIALECT=us all    # American English

This will:
1. Generate WordNet XML from YAML sources (if needed)
2. Parse WordNet definitions to JSON
3. Generate transliterated Shavian definition caches
4. Generate dictionary XML files from readlex and WordNet
5. Build all three dictionary bundles and spell checker

To build and install:

    make install

This installs to ~/Library/Dictionaries/ and makes them available in
Dictionary.app (restart Dictionary.app to use them).

To clean build artifacts:

    make clean

GRAPHICAL INSTALLER
===================

Shaw-Spell includes a native macOS installer app for easy installation.

To build the installer:

    make installer

This creates "Install Shaw-Spell.app" in installer/build/

To run the installer:

    open "installer/build/Install Shaw-Spell.app"

The installer provides:
- Graphical interface with installation options
- Choice of British English, American English, or both
- User or system-wide installation
- Automatic setup of dictionaries, spell-checking, and spell server
- Post-installation instructions

See installer/README.md for more details.

MANUAL BUILDING
===============

The Makefile handles all dependencies automatically. For manual control:

1. Generate WordNet XML (if not present):
   cd external/english-wordnet && python3 scripts/from_yaml.py
   mv external/english-wordnet/wn.xml build/english-wordnet-2024.xml

2. Parse WordNet to JSON:
   ./src/parse_wordnet.py

3. Generate transliteration caches:
   make transliterations

4. Build individual dictionaries:
   make DIALECT=gb shavian-english
   make DIALECT=gb english-shavian
   make DIALECT=gb shavian-shavian

5. Install dictionaries:
   make DIALECT=gb install

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

SPELL-CHECKING
==============

This project includes Hunspell spell-checking dictionaries for Shavian.

Hunspell Dictionaries (Cross-Platform)
---------------------------------------
Files generated: build/shaw.dic, build/shaw.aff
Word count: 75,432 unique Shavian words from readlex

To build spell-check files:

    ./build.sh spellcheck

To install for command-line use:

    ./build.sh spellcheck install

This installs to ~/Library/Spelling/ for use with:
- hunspell command-line tool (install via: brew install hunspell)
- LibreOffice (if installed)
- Firefox/Thunderbird browsers
- Text editors with Hunspell support (Emacs, VSCode, etc.)

Testing with Hunspell:

    # Test a Shavian word
    echo "𐑐𐑨𐑯𐑛𐑩" | hunspell -d ~/Library/Spelling/shaw

    # Interactive spell-checking
    hunspell -d ~/Library/Spelling/shaw

IMPORTANT: macOS native apps (TextEdit, Pages, Mail, Notes) do NOT use
Hunspell. They use NSSpellChecker which requires a different approach.

Native macOS Spell-Checking (NSSpellServer)
--------------------------------------------
For system-wide spell-checking in native macOS apps (TextEdit, Pages, Mail, etc.),
use our NSSpellServer service implementation.

Location: src/spellserver/
Files: main.m, ShavianSpellChecker.{h,m}, Info.plist, Makefile, README.md

This service registers as an English spell checker that intelligently handles
both Latin and Shavian scripts:
- Shavian text (𐑐-𐑿): Checked against Hunspell dictionary
- Latin text (a-z): Delegated to system spell checker

Supports all English variants: en_US, en_GB, en_AU, en_CA, en_NZ

To build and install:

    cd src/spellserver
    make install

Requirements:
- Hunspell library (brew install hunspell)
- Shavian dictionary at ~/Library/Spelling/shaw.dic (build with: ./build.sh spellcheck install)

After installation, log out and log back in, then configure in:
System Settings > Keyboard > Text Input > Edit... (look for "Shaw-Spell")

See src/spellserver/README.md for full documentation.

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
1. external/readlex/readlex.json - Shavian/English word mappings with IPA
2. Open English WordNet - Comprehensive English definitions
3. shave tool - English to Shavian transliteration

Git submodules:
- external/readlex - Shavian word mappings (https://github.com/Shavian-info/readlex)
- external/english-wordnet - Open English WordNet source (optional, we use XML)

LICENSE
=======

Dictionary content:
- readlex data: https://github.com/Shavian-info/readlex
- Open English WordNet: CC-BY 4.0

Build scripts and configuration: Created for this project

ABOUT
=====

Generated: 2025
Entries: ~75K Shavian entries, ~77K English entries
Definitions: 152,286 words from Open English WordNet 2024
