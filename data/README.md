# Data Directory

For the full, current reference on every file under `data/` and how they flow
together, see the canonical docs:

- [`docs/data-files.md`](../docs/data-files.md) — every key file, who writes it, whether it ships.
- [`docs/pipeline-architecture.md`](../docs/pipeline-architecture.md) — how the sources become the shipping dictionary.
- [`docs/editorial-overlay-design.md`](../docs/editorial-overlay-design.md) — the patch-overlay editorial system.
- [`docs/record-schema.md`](../docs/record-schema.md) / [`docs/dialect-mergers.md`](../docs/dialect-mergers.md) — record fields and the dialect model.

## Editorial review (patch overlay)

Editorial review is a **patch overlay**, not a CSV workflow. Reviewers work in the
editor (`src/editor/`), which presents the **basis** — upstream ReadLex plus the
wordnet/wiktionary/names/generated supplements, computed on demand — and records
each decision as a patch in **`data/patches/patches.jsonl`**, the only persisted
editorial artifact (owner-only; the pipeline never writes it).

A patch is `{anchor, op, changes, meta}`:

- `anchor` — the reviewed record's immutable natural key `{word, pos, shaw, var}` (`null` = authorship).
- `op` — `accept` (sanction), `edit` (bare not-yet-reviewed edit), `drop` (remove), or `flag` (production no-op).
- `changes` — the minimal intrinsic edits laid over the basis record (empty = accept as-is).
- `meta` — `{author, origin, ts, note?}`.

The shipping `data/readlex.json` is produced by applying the patch store over the
basis: `apply_patches.py` (basis + patches → `readlex-merged.json`) followed by
`apply_frequency_data.py` (→ `readlex.json`).

> The older CSV editorial flow (`editorial.csv` with `verdict`/`*_override`
> columns, merged by `generate_merged_readlex.py`) is **superseded** by this
> overlay. Any remaining CSV files under `data/` are migration history, not the
> build path.

## Other data files

The `supplement-*.json` files are the candidate inputs (see `docs/data-files.md`
for the full list). The editorial basis reads a single combined, filtered pool,
`supplement-combined-filtered.json` (written by the `build_supplement.py`
orchestrator); `definitions-*.json` are the transliterated definition caches for
the dictionary builds.
