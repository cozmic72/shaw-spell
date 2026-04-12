---
name: readlex
description: ReadLex dataset conventions, dialect model, IPA shorthands, and Shavian spelling principles. Use when working with ReadLex data, supplement generation, IPA-to-Shavian conversion, or any task involving the shaw-spell pronunciation dictionaries.
user-invocable: true
---

# ReadLex Dataset Reference

ReadLex is the Kingsley Read Lexicon — a Shavian pronunciation dictionary. This skill encodes its conventions for agents working with the data.

## Dialect Model (CRITICAL)

**RRP (Rhotic Received Pronunciation) is the default and universal dialect.**

- RRP entries cover ALL English dialects — RP, GenAm, Australian, etc.
- GenAm/TrapBath/GenAus entries are **EXCEPTIONS ONLY** — they exist solely where that dialect genuinely differs from RRP
- If a word has only an RRP entry, that entry IS the GenAm entry, IS the AusE entry, etc.
- Do NOT treat "missing GenAm entries" as a coverage gap
- The ~1,076 GenAm entries spell out exceptions like yod-dropping (`djuː` → `duː`)
- The ~1,688 TrapBath entries spell out BATH-TRAP split alternatives

## Data Formats

### ReadLex JSON (`readlex.json`)
Keys: `{word}_{POS}_{shavian}`, values are arrays of entry objects:
```json
{
    "Latn": "word",        // Latin spelling
    "Shaw": "𐑖𐑱𐑝𐑾𐑯",    // Shavian spelling
    "pos": "NN1",          // CLAWS C5 POS tag
    "ipa": "wɜːRd",        // IPA using ReadLex conventions
    "freq": 1234,          // BNC frequency
    "var": "RRP"           // Dialect variant
}
```

### ReadLex TSV (`kingsleyreadlexicon.tsv`)
Columns: `Latn\tShaw\tPOS\tIPA\tfreq` (tab-separated, no header)

### Supplement JSON (same format as readlex.json)
Additional fields: `"confidence": "high|medium|low"`, `"review": "notes"`

## IPA Conventions (ReadLex-specific)

### Uppercase Shorthands
| Symbol | Meaning | Shavian |
|--------|---------|---------|
| `R` | Linking/intrusive r (rhotic) | Part of r-colored vowel compounds |
| `N` | Word sign for "and" | 𐑯 |
| `T` | Word sign for "to" | 𐑑 |
| `V` | Word sign for "of" | 𐑝 |
| `F` | Word sign for "for" | 𐑓 |
| `Ð` | Word sign for "the" | 𐑞 |
| `Ə` | Uppercase schwa (grammatical suffixes -Əd, -Əz) | 𐑩 |
| `Æ` | TRAP-BATH short variant | 𐑨 |
| `Ɑ` | TRAP-BATH long variant (with or without ː) | 𐑭 |
| `I` | Weak vowel variant | 𐑩 |
| `L` | Voiceless lateral (Welsh ll) | 𐑤 |

### Special Characters
| Symbol | Meaning |
|--------|---------|
| `+` | Affix/morpheme boundary — prevents compound Shavian letters spanning it |
| `ˈ` | Primary stress (before syllable onset) |
| `ˌ` | Secondary stress |
| `ʍ` | Voiceless w (wh- words) |

### Dialect Variant Codes
| Code | Meaning |
|------|---------|
| `RRP` | Rhotic Received Pronunciation (default/universal) |
| `GenAm` | General American (exceptions only) |
| `TrapBath` | TRAP-BATH split alternative |
| `GenAus` | General Australian (exceptions only) |
| `SSB` | Standard Southern British |

### Supplement Variant Codes
| Code | Meaning | Notes |
|------|---------|-------|
| `RSSB` | Rhotic Standard Southern British | SSB made rhotic to align with ReadLex's RRP convention |
| `GAM` | General American | Inherently rhotic — no R prefix needed |
| `UNC` | Unclassified/unknown dialect | |

## POS Tags (CLAWS C5)
ReadLex uses the CLAWS C5 tagset. Common tags:
- `AT0` article, `AV0` adverb, `AJ0` adjective
- `CJC` coordinating conjunction, `CJS` subordinating conjunction
- `DPS` possessive determiner, `DT0` general determiner
- `ITJ` interjection
- `NN0` common noun (number-neutral), `NN1` singular, `NN2` plural, `NP0` proper noun
- `PNI` indefinite pronoun, `PNP` personal pronoun
- `PRP` preposition
- `VBB` base be, `VBD` past be, `VBZ` 3sg be
- `VDB` base do, `VDD` past do
- `VHB` base have, `VM0` modal
- `VVB` base verb, `VVD` past verb, `VVG` -ing, `VVN` past participle, `VVI` infinitive, `VVZ` 3sg
- `ZZ0` letter of alphabet
- `UNC` unclassified (used in supplements)

## Shavian Spelling Principles (from shavian.info and readlex.pythonanywhere.com)

### Core Rules
1. **Phonetic spelling** — follows pronunciation, not English orthography
2. **Stress determines vowel choice**: `ə` (unstressed) vs `ʌ`/`𐑳` (stressed); `əR`/`𐑼` (unstressed) vs `ɜːR`/`𐑻` (stressed)
3. **Single-syllable words always stressed** (except "a" `𐑩` and "an" `𐑩𐑯`)
4. **Final unstressed -y**: always `𐑦` (not `𐑰`)
5. **No apostrophes** in contractions or possessives
6. **Naming dot** `·` precedes proper names
7. **Word signs**: the=`𐑞`, to=`𐑑`, and=`𐑯`, of=`𐑝`, for=`𐑓` (standalone/hyphenated only)
8. **Affix boundary rule**: compound Shavian letters (`𐑼`, `𐑾`, `𐑽`) prohibited at morpheme boundaries
9. **ReadLex prefers `ə` over `ɪ`** in most unstressed syllables ("schwas included to extent possible")
10. **ReadLex uses `ə` where modern pronunciation has shifted from `ʊ`**

### IPA-to-Shavian Mapping
See `docs/shavian-spelling-digest.md` for the complete mapping table.
The converter is at `src/tools/ipa_to_shavian.py` (99% accuracy on ReadLex self-test).

## Supplement Pipeline

### Tools
- `src/tools/ipa_to_shavian.py` — Rule-based IPA→Shavian converter + `normalize_ipa()` for dialect conversion
- `src/tools/ml_ipa_normalizer.py` — ML character substitution model (trained on Britfone↔ReadLex overlap)
- `src/tools/generate_britfone_supplement.py` — Britfone → ReadLex format
- `src/tools/generate_wordnet_supplement.py` — WordNet → ReadLex format
- `src/tools/generate_wiktionary_supplement.py` — Wiktionary → ReadLex format
- `shave` CLI tool — morphological Shavian converter, available at `/usr/local/bin/shave`

### Confidence Pipeline (rules + ML + shave consensus)
1. Convert IPA → Shavian via rules
2. Score confidence based on: ML disagreement, r-gap (spelling vs IPA), unknown chars
3. Batch medium/low entries through `shave -q` for third opinion
4. When shave + ML agree (different from rules) → override with consensus
5. Tag each entry with `confidence: high|medium|low` and `review` notes

### IPA Normalization by Source
| Source | Key transformations |
|--------|-------------------|
| ReadLex | None needed (native format) |
| Britfone (SSB) | `ɹ→r`, `ɐ→ʌ`, `ɛ→e`, join space-separated phonemes, r-restoration, dialect normalization |
| Wiktionary RP | `ɹ→r`, `ɛ→e`, strip slashes, syllabic consonant expansion, r-restoration |
| Wiktionary GenAm | `ɚ→əR`, `ɝ→ɜːR`, `ɾ→t`, `ɑ→ɒ` (LOT), `ɑɹ→ɑːR` (START), `ɔɹ→ɔːR` (FORCE) |

## Build Pipeline
- Dictionary.app XML: `src/dictionaries/generate_dictionaries.py` reads `readlex.json` + definition caches
- Hunspell .dic/.aff: `src/server/generate_spellcheck.py` reads `readlex.json`
- Both need supplement merge point added after loading readlex
