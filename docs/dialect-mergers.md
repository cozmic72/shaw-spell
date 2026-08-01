# Dialect vowel mergers

The dialect model separates a record's **base accent** from the **within-accent
vowel mergers** its spelling reflects. Base accent stays in the scalar `var`
field (`RRP`/`RSSB`/`GenAm`/…); mergers move to an additive **`mergers`** list.

- **Empty/absent `mergers`** = the canonical (non-merged) form for its base accent.
- **`mergers: ["trap-bath"]`** = a spelling produced by the trap-bath merger:
  PALM `𐑭` → TRAP `𐑨` (BATH words spelt with the short TRAP vowel).
- **`mergers: ["cot-caught"]`** = a spelling produced by the cot-caught merger:
  THOUGHT `𐑷` → LOT `𐑪`.
- **`mergers: ["lot-palm"]`** = a spelling produced by the lot-palm (father-bother)
  merger: PALM `𐑭` → LOT `𐑪` (GenAm renders broad-A / foreign PALM words with the
  LOT vowel, so `father` and `bother` rhyme).

The field is additive: an existing consumer that ignores `mergers` sees the same
records it always did, with the **one intended exception** below (ReadLex's
`TrapBath` var). The vocabulary and swap detection live in
`src/tools/dialect_mergers.py`.

> **Status:** all three mergers are ACTIVE (`MERGER_ENABLED` in
> `dialect_mergers.py`) — see [decisions.md](decisions.md). The direction
> findings and counts below are the analysis record that settled it.

## Where classification happens

A merger flag is layered on **only** when a variant is an exact single-vowel swap
of the non-merged form. It is detected per-record from the Shavian at the
differing position — no invented data, only spellings that already exist.

- **Supplements** (`src/tools/classify_dialect_mergers.py`) — stage 4 of the
  in-memory supplement build (see [pipeline-architecture.md](pipeline-architecture.md);
  the later collapse stage folds identical-spelling dialect variants into one RRP
  record — `src/tools/collapse_identical_dialects.py`).
  A GenAm spelling that is an exact merger swap of a non-merged RSSB/RRP sibling
  for the same `(word, pos)` — an RSSB sibling in the pool, or a non-merged
  ReadLex/RRP attestation — is tagged; its base `var` stays `GenAm`. RSSB/RRP
  records, and GenAm forms differing in any other way, carry no merger — an
  RSSB↔GenAm difference IS the base-accent difference, captured by the label,
  not a merger.
- **ReadLex `TrapBath`** (`src/tools/basis.py`, `reinterpret_upstream`) — ReadLex
  is a read-only submodule, so its `var: "TrapBath"` records are reinterpreted at
  the point the pipeline consumes them (the basis loader and the applicator both
  go through `load_upstream`): base accent **RRP**, `mergers: ["trap-bath"]`. This
  is the one intended break from the old scalar-var shape; nothing on disk in the
  submodule is rewritten.

## Counts

Combined group view (ReadLex + both filtered supplements), grouped by
`(word.lower(), pos)`:

| Category | Groups |
|---|---:|
| Single spelling → base, no merger | 122,406 |
| RSSB/RRP + GenAm base pairs (2 spellings, no merger) | 15,403 |
| Complex / residue groups | 11,882 |

Merger-tagged **records** (the additive flag), per source:

| Merger | ReadLex | Supplement basis | Notes |
|---|---:|---:|---|
| trap-bath | 1,697 | 578 | ReadLex = the whole `TrapBath` var, reinterpreted |
| cot-caught | 0 | 715 | ReadLex has no cot-caught var; all from supplements |
| lot-palm | 0 | 534 | ReadLex has no lot-palm var; all from supplements |

The supplement figures above are the historical basis-stage tallies. Measured at
the `classified` stage on the current combined-deduped pool the tallies are
trap-bath **883**, cot-caught **1,212**, lot-palm **534** — the first two are
unchanged by adding lot-palm (merger precedence keeps prior tags stable).

ReadLex's 1,697 `TrapBath` records are exactly the trap-bath-tagged ReadLex set:
1,690 are a clean PALM→TRAP swap of an RRP sibling; the other 7 (the
`moustache`/`mustache` family and `masted`) change a second vowel or are
identical, so they are *not* clean swaps — they keep the reinterpreted flag
because the source labelled them `TrapBath`, but they are the known messy dozen,
not new signal.

## Cot-caught direction (confirmed)

The merged (GenAm) form flattens **THOUGHT `𐑷` → LOT `𐑪`**. Confirmed on real
data (forward GenAm-merges vastly outnumber the reverse: 762 vs 24 in the deduped
supplement set) and consistent with `ipa_to_shavian.py` ("GenAm merges LOT into
ɑ; ReadLex canonical form is LOT"). Samples (RSSB non-merged → GenAm merged):

| Word (pos) | RSSB (THOUGHT 𐑷) | GenAm (LOT 𐑪) |
|---|---|---|
| abroad [AV0] | 𐑩𐑚𐑮**𐑷**𐑛 | 𐑩𐑚𐑮**𐑪**𐑛 |
| applaud [VVI] | 𐑩𐑐𐑤**𐑷**𐑛 | 𐑩𐑐𐑤**𐑪**𐑛 |
| auction [NN1] | **𐑷**𐑒𐑖𐑩𐑯 | **𐑪**𐑒𐑖𐑩𐑯 |
| altered [AJ0] | **𐑷**𐑤𐑑𐑼𐑛 | **𐑪**𐑤𐑑𐑼𐑛 |
| astronaut [NN1] | 𐑨𐑕𐑑𐑮𐑩𐑯**𐑷**𐑑 | 𐑨𐑕𐑑𐑮𐑩𐑯**𐑪**𐑑 |
| aforethought [AJ0] | 𐑩𐑓𐑹𐑔**𐑷**𐑑 | 𐑩𐑓𐑹𐑔**𐑪**𐑑 |
| baltimore [NN1] | 𐑚**𐑷**𐑤𐑑𐑦𐑥𐑹 | 𐑚**𐑪**𐑤𐑑𐑦𐑥𐑹 |
| bengal [NN1] | 𐑚𐑧𐑙𐑜**𐑷**𐑤 | 𐑚𐑧𐑙𐑜**𐑪**𐑤 |

## Lot-palm direction (confirmed)

The merged (GenAm) form flattens **PALM `𐑭` → LOT `𐑪`** — the *opposite* endpoint
to trap-bath (which flattens PALM onto TRAP `𐑨`). Confirmed on real data: in the
deduped supplement pool the forward direction (non-merged `𐑭` → merged `𐑪`)
outnumbers the reverse **543 to 230**, and every clean case is a broad-A / foreign
PALM word GenAm renders with the LOT vowel. Same target convention as cot-caught
(ReadLex canonical is LOT `𐑪`). Samples (non-merged PALM `𐑭` → GenAm LOT `𐑪`):

| Word (pos) | non-merged (PALM 𐑭) | lot-palm (LOT 𐑪) |
|---|---|---|
| Aachen [NP0] | **𐑭**𐑒𐑩𐑯 | **𐑪**𐑒𐑩𐑯 |
| Abaza [NN1] | 𐑩𐑚**𐑭**𐑟𐑩 | 𐑩𐑚**𐑪**𐑟𐑩 |
| Accra [NP0] | 𐑩𐑒𐑮**𐑭** | 𐑩𐑒𐑮**𐑪** |
| Abba [NN1] | 𐑨𐑚**𐑭** | 𐑨𐑚**𐑪** |

### Ambiguity: distinct swaps, one multi-sibling tie-break

The three swaps are **distinct ordered vowel-pairs** — `𐑭→𐑨` (trap-bath),
`𐑷→𐑪` (cot-caught), `𐑭→𐑪` (lot-palm). `lot-palm` and `trap-bath` share the
distinguished vowel `𐑭` but flatten it to different targets, so a *single*
spelling-pair can still only match one merger: `merger_of` fixes both endpoints at
every differing position, and no two swaps share the same ordered pair. Verified
by brute force — **0** of 52,333 sibling comparisons matched more than one merger.

There is one real edge, at the *sibling-set* level (not the pair level): a word can
carry two non-merged siblings, and a merged `𐑪` form can be a cot-caught swap of a
`𐑷` sibling **and** a lot-palm swap of a `𐑭` sibling (e.g. `vase`: `𐑝𐑷𐑟` and
`𐑝𐑭𐑟` both attested, GenAm `𐑝𐑪𐑟`). `merger_for` resolves this by **merger
declaration precedence** (`MERGER_SWAPS` order: trap-bath, cot-caught, lot-palm),
not sibling sort order — so an added merger can only claim records that matched
*nothing* before, and the pre-existing trap-bath (883) and cot-caught (1,212)
counts are **unchanged** by adding lot-palm. Which sibling is truly the word's RP
vowel is a data question the flag does not settle (for `spa`/`qualm`/`vase` ReadLex
attests PALM, so lot-palm is right; for `gaunt`/`bengal` it attests THOUGHT, so
cot-caught is right) — every tagged record is a **review candidate**, so a stable,
documented precedence is the honest resolution rather than a correctness claim.

Adding lot-palm tags **534** supplement records (the 543 forward swaps minus the 9
that cot-caught keeps under precedence).

## Samples per category

### Single spelling → base, no merger
`'em [PNP]`, `'neath [PRP]`, `'tude [NN1]`, `abacus [NN1]`, `dictionary [NN1]` —
one spelling across all sources, so it covers every dialect with no flag.

### RSSB/GenAm base pair, no merger (base-accent difference only)
Two spellings whose difference is the base accent itself, not a known merger — no
flag on either; the `var` label already carries the distinction:

- `ability [NN1]` — RSSB 𐑩𐑚𐑦𐑤𐑦𐑑𐑦 vs GenAm …𐑤**𐑩**𐑑𐑦 (unstressed onset).
- `'twas [UNC]` — 𐑑𐑢**𐑪**𐑟 vs 𐑑𐑢**𐑳**𐑟 (LOT vs STRUT, not a merger pair).
- `accessary [AJ0]` — rhotic 𐑼 vs 𐑮 (consonantal, not a vowel merger).

### trap-bath tagged (PALM 𐑭 → TRAP 𐑨)
Base stays; the swap spelling gains `mergers: ["trap-bath"]`:

| Word (pos) | non-merged (PALM 𐑭) | trap-bath (TRAP 𐑨) |
|---|---|---|
| abaft [AV0] (ReadLex) | əˈb**Ɑ**ːft → 𐑩𐑚**𐑭**𐑓𐑑 | 𐑩𐑚**𐑨**𐑓𐑑 |
| basket [NN1] | 𐑚**𐑭**𐑕𐑒𐑦𐑑 | 𐑚**𐑨**𐑕𐑒𐑦𐑑 |
| aftermath [NN1] | **𐑭**𐑓𐑑𐑼𐑥**𐑭**𐑔 | **𐑨**𐑓𐑑𐑼𐑥**𐑨**𐑔 (both PALM positions swap) |
| bastard [AJ0] | 𐑚**𐑭**𐑕𐑑𐑼𐑛 | 𐑚**𐑨**𐑕𐑑𐑼𐑛 |
| contrast [VVI] | 𐑒𐑪𐑯𐑑𐑮**𐑭**𐑕𐑑 | 𐑒𐑪𐑯𐑑𐑮**𐑨**𐑕𐑑 |
| alexander [NN1] | 𐑨𐑤𐑦𐑜𐑟**𐑭**𐑯𐑛𐑼 | 𐑨𐑤𐑦𐑜𐑟**𐑨**𐑯𐑛𐑼 |

### cot-caught tagged (THOUGHT 𐑷 → LOT 𐑪)
See the direction table above; further examples: `altogether [AV0]`, `auction
[VVI]`, `aweless [AJ0]`, `caller [AJ0]`, `brother-in-law [NN1]`, `autotroph
[NN1]`.

### lot-palm tagged (PALM 𐑭 → LOT 𐑪)
See the lot-palm direction table above; further examples: `Aalborg [NP0]`,
`Aaronical [AJ0]`, `Abt system [NN1]`, `Alanic [AJ0]`, `Algonquin [NN1]`. Almost
all are proper nouns / foreign borrowings whose broad-A vowel GenAm renders as LOT.

### Unrecognized residue (left as-is, no flag)
11,882 complex groups do not reduce to a single known merger. Bucketed by shape:

| Count | Shape | Example |
|---:|---|---|
| 6,295 | 3+ co-existing spellings | `a cappella [AJ0]` |
| 3,687 | 1 vowel position, no known merger | `ability [NN1]` (schwa/TRAP onset) |
| 1,190 | length diff (insertion/deletion) | often hyphen/spacing, orthographic |
| 361 | 1 mixed (consonant) position | rhotic 𐑼/𐑮, yod |
| 182 | 2 vowel positions, no known merger | |
| … | long tail (3–6 differing positions) | |

The dominant residue is the **unstressed schwa↔TRAP onset** alternation
(`ability`, `abduct`) — real GenAm dialect signal the two current mergers do not
model, and the clearest candidate for the next flag. Length/hyphen diffs are
largely orthographic, not phonological. This residue is intentionally left
untouched rather than force-fit.

## Data-quality junk surfaced

Classification exposed a handful of shaws carrying **stray non-Shavian
characters** (they can never align to a merger swap and land in residue):

- **IPA leaking into Shavian** — `antibody`/`at all` 𐑨𐑯𐑑𐑦𐑚𐑷**ɾ**𐑦 (tap `ɾ`),
  `au revoir` 𐑷**ʁ** (uvular `ʁ`).
- **Invisible formatting artifacts** — `adhd`/`ai`/`bbc`/`bc` prefixed with word-
  joiner `⁠` + dotted-circle `⸰`; `bonhoeffer` with a combining mark
  `︀`; `attune` with a tie `͜`.
- **Stray Latin punctuation** — `beer` 𐑚𐑾**/ [**𐑦 (a `/[` fragment).

These are source-data defects (upstream generators / ReadLex), not a model
problem — worth a cleanup pass. This complements the prototype's earlier finds
(stray Latin `c` in `dogmatically`, IPA `ʏ` in `abune`).
