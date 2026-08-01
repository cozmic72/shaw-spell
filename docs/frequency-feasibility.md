# Frequency Data Feasibility — Subtitle Corpus Enrichment

**Status:** GO — analysis complete, pipeline built (2026-07-17).

**Goal:** add frequency data we cannot get from ReadLex, sourced from a public
corpus, with UK/US spelling-variant mapping. Owner's decision rule: GO if it
gives NET MORE distinct words with frequency data than existing ReadLex coverage
AND the corpus license permits redistribution; otherwise NO-GO.

---

## 1. Baseline — current ReadLex freq coverage

Measured against `data/readlex.json` (the merged upstream ReadLex + supplements +
patches output; 112,418 records over 78,688 distinct lowercase Latin headwords).

| Metric | Count |
|---|---|
| Records total | 112,418 |
| Records with `freq > 0` | 90,830 |
| Records with `freq == 0` | 21,588 |
| **Distinct headwords with `freq > 0` (baseline to beat)** | **65,217** |
| Distinct headwords with no `freq` anywhere | 13,471 |

Of the 13,471 fully-uncovered headwords, ~10,168 are single alphabetic tokens
(inflections, technical/rare vocabulary) and ~386 are multiword phrases. As
expected, the editorial supplements (wordnet/wiktionary) carry `freq == 0` almost
universally — they are a large share of the gap.

**Baseline distinct-word coverage: 65,217 / 78,688 = 82.9%.**

---

## 2. Candidate corpus

### Chosen: OpenSubtitles-derived list (hermitdave / FrequencyWords)

- **Source:** `https://github.com/hermitdave/FrequencyWords`, path
  `content/2018/en/en_full.txt`.
- **Format:** plain text, one `word count` pair per line; 1,656,996 entries.
- **License:** **MIT** (verified from the repo's `LICENSE`) — permits copy,
  modification, and redistribution, including as a git submodule or a bundled
  derived list. This is the decisive licensing advantage.
- **Dialect:** a single mixed "en" list (no `en_GB`/`en_US` split exists — checked,
  both 404). It contains *both* spellings of a transatlantic pair, each with its own
  count (e.g. `color 32837` vs `colour 11281`, `center 32146` vs `centre 12782`).
  The list is US-skewed but not US-only, which is exactly why variant mapping is
  needed (see §4).

### Rejected: SUBTLEX-UK / SUBTLEX-US

SUBTLEX (Brysbaert et al., CRR Ghent) is the higher-pedigree psycholinguistic
subtitle norm, but its redistribution terms are ambiguous-to-restrictive: mirrors
carry CC-BY-NC-SA, and non-academic redistribution has historically required the
author's explicit permission. Downstream projects (e.g. `wordfreq`) have dropped or
special-cased SUBTLEX for exactly this reason. Because the owner requires a corpus
we can redistribute as a submodule, SUBTLEX is **not** a safe choice. The
MIT-licensed OpenSubtitles list is comparable in what it gives us here (subtitle
word frequencies) and is unambiguously redistributable.

*Not independently re-verified this session:* the precise current SUBTLEX license
text on the CRR site. The finding above rests on the widely-documented CC-BY-NC-SA /
author-permission situation. The hermitdave MIT license WAS verified directly from
the repo this session.

---

## 3. Coverage delta — the decision number

Measured exactly by running the enrichment against `data/readlex.json` with the
downloaded corpus (not estimated):

| Metric | Value |
|---|---|
| Corpus entries loaded | 1,656,996 |
| Records filled (`freq 0` → corpus freq) | 14,807 |
| **NET NEW distinct headwords gaining frequency** | **+7,617** |
| Records still without any freq (unmatched) | 6,781 |
| Distinct-word coverage: before → after | **82.9% → 92.6%** |
| Distinct headwords with `freq > 0`: before → after | 65,217 → 72,834 |

Of the +7,617 net-new words, 7,566 match the corpus directly and 51 only via a
UK/US spelling variant. (The record-level fill count 14,807 exceeds 7,617 because
some headwords already had `freq` on one POS but `freq == 0` on another; those
secondary records are filled too but do not add a *new* covered word.)

**Result: NET POSITIVE by 7,617 distinct words (+11.7% over baseline).**

---

## 4. UK/US variant strategy

Because the corpus is one mixed "en" list, a US-skewed count for `color` must be
able to credit the UK headword `colour`, and vice versa. Strategy:

- **Transformation ruleset** (`src/tools/spelling_variants.py`), not a hand-listed
  pairs table: a set of conservative bidirectional regex rules for the systematic
  correspondences — `-our/-or`, `-ise/-ize`, `-isation/-ization`, `-yse/-yze`,
  `-re/-er`, `-ogue/-og`, `-lled/-led` (and `-lling`/`-ller`), `-ae-/-oe-` → `-e-`,
  `-ence/-ense`, `-aemia/-emia`, `-mme/-m`. Each rule that changes the word yields a
  candidate spelling.
- **Combination rule:** for a headword we take the **maximum** count found across
  the headword itself and all its variant spellings. Max (not sum) is correct here:
  the mixed corpus already aggregates dialects into separate entries, so we want the
  dominant attested form without double-counting when both spellings coexist.
- Variant mapping contributes only 51 extra words to coverage precisely *because*
  the corpus already contains both spellings — but it remains necessary for
  correctness (a UK-only headword absent from a US-skewed corpus is credited its
  US twin's frequency).

---

## 5. Verdict

**GO.**

- **License:** MIT (redistributable as a submodule) — verified.
- **Baseline:** 65,217 distinct headwords with ReadLex freq (82.9%).
- **Delta:** **+7,617 net new distinct headwords** with frequency data (→ 92.6%),
  measured exactly. Clear net-positive.

---

## Pipeline (built)

- **Submodule:** `external/frequency-words` →
  `https://github.com/hermitdave/FrequencyWords.git`. Owner command to (re)add on a
  fresh clone: `git submodule add https://github.com/hermitdave/FrequencyWords.git external/frequency-words`.
  Note: the full repo is ~1.4 GB (all languages); a sparse/partial checkout of just
  `content/2018/en/en_full.txt` would trim it substantially if size matters.
- **Scripts:** `src/tools/apply_frequency_data.py` (replace-all enrichment, whose
  `enrich_all` is reused by `src/tools/basis.py` to enrich the editor's review-pool
  candidates too) and `src/tools/spelling_variants.py` (UK/US ruleset).
- **Integration:** the enrichment runs BEFORE the patch overlay, inside each
  producer of `$(READLEX_PATH)` (the editor's publish path and the offline
  `apply_patches.py`) — frequency is upstream processing, and a patched freq is
  the last word. The pass is **idempotent** (a tagged record's corpus freq is not
  re-stashed, byte-identical re-run) and deterministic.
- **Policy — replace-all-from-corpus:** EVERY record's `freq` is set to its
  OpenSubtitles count (word + UK/US variant max) so the whole dictionary is on ONE
  comparable scale. ReadLex counts are on a different scale and are NOT kept as
  `freq` — but a record that HAD a non-zero ReadLex freq keeps it in `freq_readlex`
  (don't-throw-away-data). Corpus-uncovered records drop to `freq 0`. Corpus-sourced
  freq is tagged `"freq_source": "opensubtitles-2018"`.
- **Editor uniformity:** `basis.enrich_pool_frequency` runs the SAME `enrich_all`
  pass at view-load over the whole pool (basis + authored records), so a
  review-pool candidate carries the exact freq the readlex record it becomes will
  ship with. If the corpus is absent (fresh clone, pre-`make setup`) the editor
  logs a skip and starts without freq; the publish paths still fail loud on a
  missing corpus.

## Follow-up (deferred — NOT done here)

- **Editor freq-range filter facets** (Step 3): the editor already has freq-desc
  sort; adding range-filter facets keyed on the enriched freq is a follow-up owned
  by the editor codebase, deliberately out of scope for this upstream data work.
