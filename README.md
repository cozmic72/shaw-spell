# Shaw-Spell

![Shaw-Spell](src/images/shaw-spell.png)

**Comprehensive Shavian spelling support for macOS**

Shaw-Spell provides dictionaries for Dictionary.app and system-wide spell checking for the Shavian alphabet. 
114,000+ Shavian dictionary entries with definitions, pronunciations, and intelligent spell checking that works in all macOS apps.

**Download and learn more about the project at [joro.io/shaw-spell](https://joro.io/shaw-spell)**

## Building from Source

### Prerequisites

```bash
# Install Xcode Command Line Tools
xcode-select --install

# Install dependencies via Homebrew
brew install hunspell      # Spell checking library (also needed by the web-UI daemon)
brew install python@3      # For build scripts

# Homebrew installs libhunspell as libhunspell-1.7.dylib. The `hunspell`
# (aka pyhunspell) Python binding used by the web-UI daemon links against an
# unversioned `-lhunspell`, so add an unversioned symlink so it builds.
# Production Linux hosts don't need this — `apt install libhunspell-dev`
# already ships libhunspell.so.
ln -sf "$(brew --prefix hunspell)/lib/libhunspell-1.7.dylib" \
       "$(brew --prefix hunspell)/lib/libhunspell.dylib"

# Install Python dependencies (PyYAML for the build system, hunspell/pyhunspell
# for the web-UI backing daemon — see src/site-daemon/README.md).
CPPFLAGS="-I$(brew --prefix hunspell)/include/hunspell" \
LDFLAGS="-L$(brew --prefix hunspell)/lib" \
pip3 install -r requirements.txt

# Install shave tool (for Shavian transliteration)
# See: https://github.com/Shavian-info/shave
```

You'll also need the [Apple Dictionary Development Kit](https://github.com/SebastianSzturo/apple-dictionary-dev-kit) installed at `/Library/Developer/Dictionary Development Kit`.

#### The bootstrap cycle

**This project needs a `shave` binary that must already exist, because `shave` builds its own dictionaries from what this project publishes.**

Seven call sites shell out to `shave` — six supplement generators under `src/tools/`, plus `src/dictionaries/build_definition_caches.py`. `shave`, in turn, regenerates its dictionaries from `readlex.json`, which it takes from the `shaw-spell-data` repository that this project's editor publishes into.

**A fresh clone of both repositories cannot bootstrap either one.** The cycle is broken by time, not by architecture: whichever artefact already happens to be on the machine seeds the next build. That works on a machine with a history and nowhere else.

Get a `shave` binary first, by any means — it need not be current, only present. This is survivable because the expensive outputs are committed checkpoints: a plain build consults `shave` not at all, and only a deliberate regeneration (`make rescore-full`, `make transliterations`, `make supplements-from-source`) invokes it.

⚠ **A missing `shave` does not reliably fail loudly.** Four of the seven call sites — in `generate_britfone_supplement.py`, `generate_wordnet_supplement.py`, `generate_wiktionary_supplement.py` and `rescore_supplements.py` — catch `FileNotFoundError` alongside a timeout and return an empty result. That is the right response to a timeout and the wrong one to an absent binary: every batch takes that branch, the generator warns on stderr but exits 0, and it writes a pool with every `shave` consultation dropped, in a file nothing distinguishes from a good one. Confirm `shave` is on `$PATH` before regenerating anything.

The cycle is stated from `shave`'s side in that repository's README.

### Build

```bash
git clone https://github.com/cozmic72/shaw-spell.git
cd shaw-spell
make setup
make install
```

This builds and installs the spell checker and the dictionaries under ~/Library.

`make setup` initialises the git submodules. The `frequency-words` submodule
(hermitdave/FrequencyWords) ships every language at ~1.4 GB, but Shaw-Spell uses
only `content/2018/en/en_full.txt`. `make setup` checks it out with a
sparse-checkout so the tree stays ~30 MB instead of 1.4 GB; the other submodules
init normally. The target is re-runnable and safe to run on an existing tree.

### Version

The version is a single hand-maintained line in `current-version` at the repository root. It is
read into the `VERSION` Make variable by `build-rules/common.mk`, exported, and reaches three
kinds of output: the DMG filename, the `$VERSION$` placeholders that `src/site/deploy_site.py`
substitutes when staging the web frontend, and the dictionary bundles built by
`build-rules/dictionaries.mk`. The `Info.plist.template` files under `src/installer/`,
`src/server/` and `src/uninstaller/` carry the same placeholder.

⚠ **Bumping `current-version` regenerates nothing.** It is not a prerequisite of any rule that
consumes it — verified against Make's own expanded rule database, in which no target lists it. Make
tracks file prerequisites, not variable values, and `VERSION` is a variable assigned at parse time
by `$(shell cat current-version)`. So editing the file changes what the *next* rebuild would stamp,
while leaving every already-built artifact holding the version it was built with, until something
unrelated forces it to rebuild. The site rule is the clearest case: it lists an exhaustive
prerequisite set, down to the `Makefile` itself, and still not `current-version`.

**After a version bump, force the affected outputs to rebuild rather than trusting the graph.**
A release built without doing so ships artifacts stamped with the previous version, and nothing
in the build reports it.

## Supplement Data Pipeline

Shaw-Spell supplements the core ReadLex dictionary with pronunciation and definition data from several open-source datasources. See [`docs/pipeline-architecture.md`](docs/pipeline-architecture.md) for the full pipeline.

### Data Sources

| Source | What it provides |
|--------|-----------------|
| [ReadLex](https://github.com/shavian-info/readlex) | Core Shavian dictionary (IPA, Shavian, POS, frequency) |
| [Open English WordNet](https://github.com/globalwordnet/english-wordnet) | GB+US IPA, POS, definitions |
| [Wiktionary](https://kaikki.org/dictionary/English/) | IPA with dialect labels (RP, GenAm), definitions |
| Curated names / generated | Proper names (shave + CMUdict voters) and shave-generated no-IPA WordNet words |

(Britfone was dropped from the pipeline — marginal value, no POS, r-restoration quality issues. See [`docs/data-files.md`](docs/data-files.md).)

### Generating Supplements

The supplement build is a single in-memory orchestrator (`build_supplement.py`) that loads
the sources once and writes `data/supplement-combined-filtered.json`. The shipping
`data/readlex.json` is published by the EDITOR on Commit; the offline equivalent is the
single command `apply_patches.py`, which runs the corpus frequency pass over the
pre-patch record set (frequency is upstream processing), then applies the patch store
(the editorial last word), then writes the publish shape.

`data/readlex.json` is not a private build artefact. It is published into the `shaw-spell-data` repository and taken from there by `shave`, which regenerates its own `shavian.csv` from it — so a field dropped from the publish shape can break a build outside this repository. `src/tools/basis.py` `PUBLISH_FIELDS` is the whole of what is published.

It is also a different dataset from the upstream ReadLex under `external/readlex/`, despite sharing the filename. The export adds `lemma` and `mergers` over upstream's `Latn`/`Shaw`/`pos`/`ipa`/`freq`/`var`, and `shave` reads the enriched shape. Upstream is not a drop-in substitute for it — `shaw-type`, `pangram` and `shcrabble` vendor upstream directly and consume something else.

```bash
# Regenerate the supplement pool, re-score, apply editorial patches, build review files
make supplements-from-source

# Check the shipping readlex.json is present (a committed file the editor publishes)
make supplements

# Generate review files for human inspection
python3 src/tools/generate_review_files.py
```

### Make Targets

| Target | Description |
|--------|------------|
| `make supplements` | Ensure the committed readlex.json is present + not stale w.r.t. the patch store (runs `check-readlex`) |
| `make supplements-from-source` | Full rebuild from source data |
| `make rescore-full` | Re-score confidence with full shave consultation |
| `make review-files` | Generate review TSVs for human inspection |
| `make transliterations` | Rebuild Shavian definition caches (requires shave) |
| `make dictionaries` | Build all Apple Dictionary bundles |
| `make spellcheck` | Build all Hunspell dictionaries |
| `make site` | Build web dictionary frontend |

### Confidence Scoring

Each supplement entry carries a `confidence` in the range 0–100, computed by the final
build stage (`score_confidence_blend.py`) as a clamped weighted sum of voter signals
(positive weight = trust, negative = red flag). The per-voter contributions are persisted
on the record under `votes` so a score is explainable. It is an ordering the editor can
sort/filter on, not a fixed-tier ladder.

### Dialect Variants

The dialect model separates a record's **base accent** (scalar `var`) from the
**within-accent vowel mergers** its spelling reflects (an additive `mergers` list). See
[`docs/dialect-mergers.md`](docs/dialect-mergers.md) and [`docs/record-schema.md`](docs/record-schema.md).

| `var` | Meaning |
|-------|---------|
| `RRP` | Rhotic Received Pronunciation (canonical, universal default) |
| `RSSB` | Rhotic Standard Southern British (supplement data; collapses to RRP at export) |
| `GenAm` | General American (exceptions + supplement data) |
| `GenAus` `GenCan` `SthAfr` `NZ` `IrEng` | regional lanes harvested from Wiktionary accent tags (review pool; lanes with no upstream ReadLex counterpart are held back from readlex.json at export) |

Mergers are NOT `var` values — they live in `mergers`, e.g. `["trap-bath"]` (PALM 𐑭→TRAP 𐑨 in
BATH words). All three — `trap-bath`, `cot-caught`, `lot-palm` — are enabled; each stays
individually gated by `MERGER_ENABLED` in `src/tools/dialect_mergers.py`.

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
- **[Wiktionary](https://en.wiktionary.org/)** (pronunciations, definitions) • CC BY-SA 3.0

See [LICENSE.md](LICENSE.md) for complete details.
