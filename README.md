# Shaw-Spell

**Complete Shavian language support for macOS**

Shaw-Spell brings the Shavian alphabet to your Mac with comprehensive dictionaries and intelligent spell checking. Look up words, check spelling, and work seamlessly in both English and Shavian script.

## What You Get

- **Three dictionaries for Dictionary.app**
  - Shavian → English (look up Shavian words)
  - English → Shavian (look up English words)
  - Shavian → Shavian (pure Shavian dictionary)

- **System-wide spell checking**
  - Works in TextEdit, Pages, Mail, and all native macOS apps
  - Automatically detects Shavian vs English text
  - Intelligent suggestions for misspelled words
  - Available in British and American English variants

- **Comprehensive word data**
  - 75,000+ Shavian words from readlex
  - 152,000+ definitions from Open English WordNet 2024
  - IPA pronunciations
  - Usage examples
  - Part-of-speech information

## Installation

### Quick Install (Recommended)

1. Download `ShawSpellInstaller.dmg` from releases
2. Open the DMG and run **Install Shaw-Spell.app**
3. Choose your dialect (British English, American English, or both)
4. Click Install
5. Restart Dictionary.app and any text editors

The installer handles everything: dictionaries, spell checking, and system integration.

### Uninstalling

Run **Uninstall Shaw-Spell.app** from the DMG, or use the included `uninstall.sh` script.

## Building from Source

### Requirements

- macOS with Xcode Command Line Tools
- Python 3 with PyYAML: `pip3 install PyYAML`
- Apple Dictionary Development Kit (installed at `/Library/Developer/Dictionary Development Kit`)
- Hunspell: `brew install hunspell`
- shave tool (for Shavian transliteration - must be in PATH)

### Quick Build

Clone and build everything:

```bash
git clone https://github.com/your-username/shaw-dict.git
cd shaw-dict
git submodule update --init --recursive
make
```

This creates a complete installer DMG at `build/ShawSpellInstaller.dmg`.

### Build Options

```bash
# Build British English (default)
make

# Build American English
make DIALECT=us all

# Build just the dictionaries
make DIALECT=gb shavian-english
make DIALECT=gb english-shavian
make DIALECT=gb shavian-shavian

# Build spell checker only
make spellcheck
make server

# Build installer
make installer

# Build DMG for distribution
make dmg

# Install directly to your Mac
make install

# Clean build artifacts
make clean
```

### What Gets Built

- `build/dictionaries/` - Dictionary bundles for Dictionary.app
- `build/shaw-{gb,us}.{dic,aff}` - Hunspell spell checking dictionaries
- `build/Shaw-Spell.service` - Spell checking service
- `build/Install Shaw-Spell.app` - Graphical installer
- `build/Uninstall Shaw-Spell.app` - Graphical uninstaller
- `build/ShawSpellInstaller.dmg` - Distribution package

## Using the Dictionaries

### Dictionary.app

After installation, restart Dictionary.app. You'll find three new dictionaries:

- **Shavian-English** - Look up Shavian words to see English spelling and definitions
- **English-Shavian** - Look up English words to see Shavian spelling and transliterated definitions
- **Shavian** - Pure Shavian dictionary with all content in Shavian script

### Spell Checking

The spell checker appears as "ShawDict" in:

**System Settings → Keyboard → Text Input → Edit (in Input Sources section)**

Or in individual apps:

**Edit → Spelling and Grammar → Show Spelling and Grammar** (language dropdown at bottom)

Select "Shaw-Spell" as your spell checker. It intelligently handles both Shavian and English text:
- Shavian text (𐑐-𐑿) is checked against the Shavian dictionary
- English text (a-z) uses the system spell checker

## Project Structure

```
shaw-dict/
├── src/                    # Source code
│   ├── dictionaries/       # Dictionary generation scripts
│   ├── installer/          # Installer app (Swift)
│   ├── uninstaller/        # Uninstaller app (Swift)
│   └── spellserver/        # Spell checking service (Swift)
├── build/                  # Build outputs
├── data/                   # Cached transliterations
└── external/               # External dependencies (git submodules)
    ├── readlex/            # Shavian word mappings
    └── english-wordnet/    # Open English WordNet source
```

## Data Sources

- **Shavian spellings**: [readlex](https://github.com/Shavian-info/readlex) (~56,000 entries)
- **Definitions**: [Open English WordNet 2024](https://github.com/globalwordnet/english-wordnet) (CC-BY 4.0)
- **Transliteration**: shave tool with WSD module

## Technical Details

### How It Works

1. **Dictionary Generation**
   - Loads Shavian-English word mappings from readlex
   - Extracts definitions from Open English WordNet
   - Transliterates English definitions to Shavian using the shave tool
   - Generates XML files for Apple's Dictionary Development Kit
   - Builds .dictionary bundles for Dictionary.app

2. **Spell Checking**
   - Hunspell dictionaries provide the Shavian word list
   - NSSpellServer service integrates with macOS spell checking
   - LaunchAgent keeps service running in background
   - Service registers as English spell checker but handles Shavian

3. **Installer**
   - Native Swift app with graphical interface
   - Bundles all dictionaries, spell checker, and service
   - Installs to user or system directories
   - Sets up LaunchAgent for spell server
   - Handles both GB and US variants

### Build Performance

The build system uses several optimizations:

- Incremental builds with timestamp tracking
- Cached Shavian transliterations (avoid re-transliterating)
- Batch transliteration for efficiency
- Parallel dictionary builds
- Separate build directories for GB/US variants

Typical clean build time: 5-10 minutes (depending on hardware)

## Development

### Making Changes

The build system automatically handles dependencies:

- Change a source file → affected components rebuild
- Update readlex → dictionaries rebuild
- Modify spell server → installer rebuilds

### Testing

```bash
# Build and run tests
make test

# Test spell server directly
build/test/test_spell

# Test in TextEdit
open build/Install\ Shaw\ Spell.app
# Install, then test typing in TextEdit
```

## Contributing

This is a personal project, but suggestions and bug reports are welcome.

## License

Shaw-Spell is licensed under the **MIT License**.

This project bundles several open-source components with different licenses:
- **Readlex** (Shavian word data): MIT License
- **Open English WordNet** (definitions): CC BY 4.0
- **Princeton WordNet 3.0**: WordNet License
- **Hunspell** (spell checking library): Tri-licensed GPL-2.0/LGPL-2.1/MPL-1.1 (used under LGPL-2.1)

See [LICENSE.md](LICENSE.md) for complete license information and attribution requirements.

## About

Created 2025

- ~75,000 Shavian dictionary entries
- ~77,000 English dictionary entries
- 152,000+ definitions from Open English WordNet 2024
- British English and American English variants
