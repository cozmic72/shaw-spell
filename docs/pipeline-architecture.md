# Supplement pipeline architecture

How the dictionary is built, as of the in-memory-orchestrator refactor (commit 712724d).
This is the map; the code is the territory (`src/tools/build_supplement.py`).

## The shape

The pipeline turns raw lexical sources into `data/readlex.json` (the shipping dictionary) in
two halves:

1. **Supplement build** — one in-memory orchestrator, `src/tools/build_supplement.py`, that loads
   the sources once, composes every transform stage in memory, and writes
   `data/supplement-combined-filtered.json` once.
2. **Merge + frequency** — published by the EDITOR, not `make`: on Commit the editor daemon
   derives `data/readlex.json` in-process (`apply_patches` over the live basis, then
   `apply_frequency_data`'s corpus pass) and commits it alongside `data/patches/patches.jsonl`,
   so the published artifact is never out of sync with the patches that produced it. `make`
   just depends on the committed file.

```
sources ─► build_supplement.py ─► supplement-combined-filtered.json
                                        │
              apply_patches ◄───────────┘  (+ data/patches/patches.jsonl, the editorial decisions)
                     │
                     ▼
          apply_frequency_data ─► readlex.json   (both run in-process by the editor on Commit)
```

## Sources (the inputs)

Declared in `combine_supplements.py`'s `SOURCES` list; each carries a label that becomes the
record's `source`, so provenance survives to the editor:

| label | file | what it is |
|---|---|---|
| `wordnet` | `supplement-wordnet-reliable.json` | WordNet words WITH a pronunciation → IPA→Shavian |
| `wiktionary` | `supplement-wiktionary-neardot.json` | Wiktionary words (post rescue + NEAR-dot fix) |
| `names` | `supplement-names.json` | ~10K curated proper names (shave + CMUdict voters) |
| `generated` | `supplement-generated.json` | ~19K net-new no-IPA WordNet words, shave-generated |

Adding a source = one line in `SOURCES` **and** a prerequisite in `build-rules/supplements.mk`
(both, or `make` won't rebuild on change — see `docs`/memory on build-integration). `names` and
`generated` are curated inputs (tracked in git); the `combined-*` intermediates are gitignored.

Words WITHOUT a usable pronunciation are split off by the generators into `-speculative` buckets;
`generated` rescues the WordNet no-IPA slice via shave. The `wiktionary-speculative` bucket (has
IPA but `var=UNC`, a dialect-labelling issue) is NOT yet wired — a future lane.

## The stages (in-memory, in order)

`build_supplement()` yields each stage's result (for optional `--dump` debugging), but the
orchestrator composes them directly in memory — no intermediate files on the production path.
Each stage is a pure `records -> records` function; the per-stage `main()` CLIs still exist for
single-stage debugging.

| # | stage | module | count | what it does |
|---|---|---|---|---|
| 1 | combine | `combine_supplements` | grows | union the sources into one pool; unify `source` lists |
| 2 | annotate defs | `annotate_definitions` | = | set `has_definition` from the source glosses |
| 3 | dedup | `filter_supplement_duplicates` | drops | drop candidates already in ReadLex / duplicated |
| 4 | classify mergers | `classify_dialect_mergers` | = | tag trap-bath / cot-caught / lot-palm mergers |
| 5 | reclassify RRP | `reclassify_rrp` | **=** | relabel RRP-passable candidates' var → RRP |
| 6 | generate RRP | `generate_rrp` | **=** | mint RRP for IPA-only gaps (propose-alongside); flag-gate |
| 7 | collapse | `collapse_identical_dialects` | drops | merge identical-spelling dialects (D2) |
| 8 | flag variants | `flag_variants` | = | set the `variant` flag on disfavoured/regional spellings |
| 9 | decontaminate | `filter_supplement_contamination` | drops | drop IPA-contaminated Shavian |
| 10 | phrases | `filter_supplement_phrases` | drops | drop non-divergent multi-word candidates |
| 11 | score confidence | `score_confidence_blend` | = | overwrite `confidence` with the blended voter score (0–100) |

Stages marked **=** are count-preserving by contract; the orchestrator asserts this (fail-loud) so
a future edit that silently drops/dupes records can't build a wrong basis (commit a257dbb). The
`drops` stages legitimately change counts and are unguarded.

Order matters: **reclassify runs AFTER classify_mergers and skips merger-flagged records** — a
merged form (cot-caught 𐑪) passes as RRP in isolation, so reclassifying before the merger stage
would erase the merger relationship. The `mergers` flag is the "spelt-differently-known-merger"
signal that only exists post-stage-4.

## Determinism & the shave flag

The IPA-basis path is pure and deterministic. `generate_rrp`'s shave/names path (for no-IPA names)
is gated behind `ENABLE_SHAVE_NAMES` (default **OFF**; env `SHAW_SPELL_ENABLE_SHAVE_NAMES`) — the
code is present but dormant, an owner-undecided lane. With the flag off, the generator is
IPA-basis-only and the whole pipeline is byte-deterministic run-to-run. (shave itself IS
deterministic — a re-shave is idempotent, verified run-to-run incl. `--confidence 0` — but
EXPENSIVE, and the `-reliable`/`names`/`generated` files are the anchor identity for the
owner's patches, so they are built as order-only Make targets — rebuilt only when missing.
That guard is a deliberateness/cost measure, not anti-drift.)

## Invariants

- **`data/patches/patches.jsonl` is the owner's editorial decisions** — read-only to the pipeline;
  only `apply_patches` reads it, nothing in the build writes it.
- **Never auto-accept**: every generated/reclassified record lands as an *unreviewed candidate*.
- **Fail-fast**: no silent fallbacks; count-preservation asserted on the stages that promise it.
- **`make -j`-safe**: the whole supplement build is one Make recipe (the orchestrator), so parallel
  make can't race or reorder the stages — the ordering lives in Python, honestly.
