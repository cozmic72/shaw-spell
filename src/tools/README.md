# Shaw-Spell Development Tools

This directory contains utilities for analyzing and developing Shaw-Spell.

## Available Tools

### `analyze_word_coverage.py`

Analyzes word coverage across the different dictionary sources used in Shaw-Spell.

**Purpose**: Understand the overlap and unique contributions of each source:
- ReadLex (Shavian pronunciation data)
- Open English WordNet (word definitions and spell-checking word lists)
- Hunspell dictionaries (generated from WordNet for spell checking)

**Usage**:
```bash
# Basic summary
./src/tools/analyze_word_coverage.py

# Detailed analysis with sample words
./src/tools/analyze_word_coverage.py --verbose

# Export to JSON for further analysis
./src/tools/analyze_word_coverage.py --json > coverage.json

# Export to CSV for spreadsheets
./src/tools/analyze_word_coverage.py --csv > coverage.csv
```

**Example Output**:
```
======================================================================
DATASET SIZES
======================================================================
ReadLex (Shavian):        77,342 words
Open English WordNet:    152,286 words
Hunspell GB:              95,837 words
Hunspell US:              48,262 words

======================================================================
OVERLAP ANALYSIS
======================================================================
ReadLex ∩ WordNet:        39,221 words (50.7% of ReadLex)
ReadLex ∩ Hunspell GB:    29,693 words (38.4% of ReadLex)
...
```

**Key Insights**:
- Only 50.7% of ReadLex words have WordNet definitions
- 38,121 Shavian words need definitions from other sources
- WordNet provides the most comprehensive coverage at 62.2% of all unique words
