# shaw-spell — documentation index

shaw-spell **extends and modernises the ReadLex** (Kingsley Read Lexicon), the
IPA→Shavian pronunciation dictionary: it expands the vocabulary (canonicalising new
words to RRP where the rules permit) and adds modern-spoken variants alongside the
canonical entries.

**Start here, then read [decisions.md](decisions.md).** New agents: read this file
and decisions.md before touching anything.

## The shape of the system

- **Pipeline** — raw lexical sources → `data/readlex.json`. One in-memory orchestrator
  builds the supplement basis, the frequency pass stamps corpus frequencies, then the
  applicator overlays the editorial patches (the last word). → [pipeline-architecture.md](pipeline-architecture.md).
  Code: [`src/tools/`](../src/tools/) (`build_supplement.py`, `apply_patches.py`, `basis.py`, …).
- **Editor** — a read-write review tool (`editord` daemon + web UI) over the **basis**
  (upstream + supplements, computed on demand) annotated with the **patch overlay**. The
  patch store is the only persisted editorial artifact; the owner accepts, nothing
  auto-accepts. → [editorial-overlay-design.md](editorial-overlay-design.md).
  Code: [`src/editor/`](../src/editor/).
- **Record & patch schema** — the fields a record carries, and the patch shape. →
  [record-schema.md](record-schema.md).
- **Data files** — what each file under `data/` is, who writes it, whether it ships. →
  [data-files.md](data-files.md).

## Key standing rules

Every durable decision, with its status and rationale, is in
[decisions.md](decisions.md) — read it there. It is the only authority; this index
deliberately keeps no summary, because a second copy of the log drifts out of step
with it (a summary here recorded the mergers as frozen for a week after the owner
enabled all three).

## Docs

| Doc | What's in it |
|---|---|
| [decisions.md](decisions.md) | **Decision log** — every durable decision, rationale, where it lives (SETTLED / FROZEN / PENDING) |
| [record-schema.md](record-schema.md) | Record fields (intrinsic / provenance / orig_*) + the patch shape |
| [data-files.md](data-files.md) | Reference table of `data/` files: what, who writes, tracked, ships |
| [pipeline-architecture.md](pipeline-architecture.md) | The supplement build → merge → frequency pipeline; stages, determinism, invariants |
| [editorial-overlay-design.md](editorial-overlay-design.md) | The patch-overlay editorial system: why the basis is computed on demand and patches are the only persisted artifact, plus the natural-key derivation — all live. Its original full-record patch model is **superseded** by record-schema.md |
| [dialect-mergers.md](dialect-mergers.md) | The base-accent + additive-mergers dialect model; merger directions, counts, residue |
| [shaw-spell-spelling.md](shaw-spell-spelling.md) | Project layer over the Shavian spelling rules — how shaw-spell applies/bends them; the two goals |
| [phrase-divergence.md](phrase-divergence.md) | Which multi-word phrases earn their own entry (pronunciation ≠ sum of parts) |
| [definitions-editor-design.md](definitions-editor-design.md) | Definitions viewer + corrector design (transliteration-only, separate patch store) |
| [frequency-feasibility.md](frequency-feasibility.md) | Frequency-data enrichment from a subtitle corpus (built) |

## Deeper linguistic reference

The Shavian spelling rules themselves (the Guide, affix tables, dialect conventions)
live in the `shavian-spelling` and `readlex` Claude skills. This repo's
[shaw-spell-spelling.md](shaw-spell-spelling.md) is the project layer that applies them.
