# shaw-spell

**Read [`docs/README.md`](docs/README.md) and then [`docs/decisions.md`](docs/decisions.md) before
touching anything.** They are the authority on what this project is, how the pipeline and editor
are shaped, and which decisions are already settled. This file deliberately does not summarise
them — a second summary is what let the merger claim in `docs/README.md` drift out of step with
`docs/decisions.md`, and where the two disagree, `docs/decisions.md` wins.

Two rules bind before you have read anything:

- **Never auto-accept.** Everything the pipeline produces is an unreviewed candidate. The owner
  accepts; tools only assist and prioritise. No threshold, batch or confidence tier lifts this.
- **`data/patches/patches.jsonl` is the owner's alone.** The pipeline READS it. Nothing you write
  edits, migrates or reverts it — `repair_patches.py --write` is for the owner to run, never an
  agent against the live store.

Both are recorded with their rationale in [`docs/decisions.md`](docs/decisions.md).
