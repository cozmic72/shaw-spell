Shavian Dictionary for macOS
============================

This project generates bilingual dictionaries for translating between English
and Shavian script for macOS.

PROJECT STRUCTURE
=================

- src/                          - Source files
  - generate_dictionaries.py    - Dictionary generation script
- build/                        - Generated dictionary XML files
  - shavian-english.xml         - Shavian → English dictionary
  - english-shavian.xml         - English → Shavian dictionary
- dictionaries/                 - Dictionary build configurations
  - shavian-english/            - Shavian → English build files
  - english-shavian/            - English → Shavian build files
- build.sh                      - Master build and install script

GENERATED DICTIONARIES
======================

Two dictionaries are generated in the build/ directory:

1. shavian-english.xml - Look up Shavian words to find English equivalents
2. english-shavian.xml - Look up English words to find Shavian equivalents

REQUIREMENTS
============

- Apple Dictionary Development Kit installed at:
  /Library/Developer/Dictionary Development Kit
- Python 3
- macOS

BUILDING
========

To build both dictionaries:

    ./build.sh

This will:
1. Generate XML files from ../shavian-info/readlex/readlex.json
2. Build both Shavian-English and English-Shavian dictionaries
3. Create .dictionary bundles in dictionaries/*/objects/

To build and install:

    ./build.sh install

This will build and copy the dictionaries to ~/Library/Dictionaries/
and make them available in Dictionary.app (restart Dictionary.app to use them).

To clean build artifacts:

    ./build.sh clean

MANUAL BUILDING
===============

You can also build each dictionary individually:

1. Generate XML files:
   ./src/generate_dictionaries.py

2. Build Shavian-English:
   cd dictionaries/shavian-english
   make
   make install  # optional

3. Build English-Shavian:
   cd dictionaries/english-shavian
   make
   make install  # optional

FUTURE ENHANCEMENTS
===================

- Addition of actual definitions from open-source dictionaries
  (currently only provides translations)
- Improved formatting and presentation
- Example sentences
- Pronunciation guides

ABOUT
=====

Source data: ../shavian-info/readlex/readlex.json
Current entries: ~55,000+ word translations

The dictionaries currently provide simple translations between English and
Shavian, showing the romanized spelling and Shavian script equivalent.
Part-of-speech tags are included where available.
