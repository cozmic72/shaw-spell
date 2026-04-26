# Data Directory

## Editorial Process

The editorial process reviews all supplement entries before they are merged into `readlex.json`. It produces four files: the editorial-* ones are CSV (LF line endings, minimal quoting — RFC 4180 with Unix newlines), the readlex-reference dump is TSV.

### Files

| File | Purpose | Editable? |
|------|---------|-----------|
| `editorial.csv` | Entries needing editorial review | Yes — this is the working file |
| `editorial-duplicates.csv` | Entries matching ReadLex (word, shaw) | Reference only |
| `editorial-drops.csv` | Fragments, affixes, other rejects | Recoverable — move rows to editorial.csv if wanted |
| `readlex-reference.tsv` | All upstream ReadLex entries | Reference only |

### Column Reference

| Column | Description |
|--------|-------------|
| `word` | Latin spelling |
| `pos` | Part of speech (C5 tagset: NN1, VVI, AJ0, NP0, UNC, etc.) |
| `var` | Pipeline-assigned dialect variant (RSSB, GenAm, RRP, etc.) |
| `shaw` | Pipeline-generated Shavian spelling |
| `ipa` | Source IPA pronunciation |
| `confidence` | Pipeline confidence percentage |
| `source` | Data source: `wordnet`, `wiktionary`, or `wordnet+wiktionary` for collapsed entries |
| `status` | Relationship to ReadLex (see below) |
| `readlex_var` | If this (word, shaw) pair exists in ReadLex, shows ReadLex's var tag(s). Blank if not in ReadLex |
| `shaw_override` | Editorial: corrected Shavian spelling. Blank = accept pipeline `shaw` |
| `pos_override` | Editorial: corrected POS tag. Blank = accept pipeline `pos` |
| `var_override` | Editorial: corrected dialect variant. Blank = accept pipeline `var` |
| `verdict` | Editorial decision (see below) |
| `notes` | Auto-generated flags and/or human notes |

### Status Values

Set at generation time. Describes the entry's relationship to upstream ReadLex.

| Status | Meaning |
|--------|---------|
| `new` | Word does not exist in ReadLex at all |
| `supplement` | Word exists in ReadLex but this is an alternate spelling/pronunciation |
| `fragment` | Partial IPA transcription (e.g. `-di` for "Thursday") |
| `affix` | Affix entry (e.g. `-ity`, `giga-`) |
| `readlex` | Entry from upstream ReadLex (readlex-reference.tsv only) |

### Verdict Values

Set during editorial review. Determines what happens to the entry in the final build.

| Verdict | Meaning |
|---------|---------|
| *(blank)* | Not yet reviewed |
| `keep` | Canonical entry — this is the preferred spelling |
| `supplemental` | Accepted alternative — valid spelling, not the preferred one |
| `drop` | Reject — do not include |
| `duplicate` | Matches upstream ReadLex exactly (editorial-duplicates.csv only) |

### Dialect Collapsing

When RSSB and GenAm entries produce the same Shavian spelling for a word, they are collapsed into a single row with `var=RRP` (since the spelling is universal). The `source` field shows the combined sources (e.g. `britfone+wiktionary`).

### Workflow

1. **Generate**: `python3 src/tools/generate_editorial_csv.py` creates/appends to the CSV files
2. **Review**: Open `editorial.csv` in Numbers (or any IDE / spreadsheet). Filter by `status`, `confidence`, `source`, etc. Fill in `verdict` and any overrides
3. **Export**: Save back as CSV (UTF-8)
4. **Build**: `generate_merged_readlex.py` reads the editorial CSV and applies verdicts when merging into `readlex.json`

New entries from updated data sources are appended to the existing editorial.csv, preserving all previous verdicts.

### Override columns

The `shaw_override`, `pos_override`, and `var_override` columns allow correcting pipeline output without modifying the source data. When building the merged readlex:

- If `shaw_override` is non-blank, it replaces `shaw`
- If `pos_override` is non-blank, it replaces `pos`
- If `var_override` is non-blank, it replaces `var`

This lets you fix IPA-to-Shavian conversion errors, reassign POS tags, or change dialect assignments on a per-entry basis.

### Recovering drops

The `editorial-drops.csv` file contains fragments and affixes pre-tagged with `verdict=drop`. If any of these are actually useful (e.g. a fragment that captures a valid alternative pronunciation), copy the row into `editorial.csv` and change the verdict.

## Other Data Files

| File | Description |
|------|-------------|
| `readlex.json` | Merged ReadLex — the build output used by dictionaries and spell checker |
| `supplement-wordnet-reliable.json` | WordNet supplement (GB+US IPA, definitions) |
| `supplement-wiktionary-reliable.json` | Wiktionary supplement (RP, GenAm IPA, definitions) |
| `definitions-*.json` | Transliterated definition caches for dictionary builds |
