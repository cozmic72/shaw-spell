# Editorial Overlay System — Design

**Status:** design record (settled 2026-07-16; built). The live patch schema is
[record-schema.md](record-schema.md) (minimal-diff `{anchor, op, changes, meta}` —
this doc's original full-record patch model was superseded); the live editor is
`src/editor/` (see its README for the daemon protocol). What remains here is the
rationale that does not live anywhere else.

This replaced the spreadsheet/CSV editorial process (`editorial*.csv` +
`generate_merged_readlex.py` + `merge_editorial_edits.py`) with a **patch overlay**
on top of a live-computed dictionary.

## The core idea

Two clean inputs, nothing frozen in between:

1. **The basis** — the raw combination of *all* upstream sources (upstream ReadLex +
   supplements), computed **on-demand**. Every candidate is already a record *in the
   basis*, flagged with its origin, source, status, and confidence. The basis is never
   persisted as an editorial artifact; it is "whatever the sources currently say"
   and may grow/change freely.

2. **The patches** — the *only* persisted editorial artifact. One patch per record a
   human has ruled on. Nothing else is stored. The unreviewed candidates have
   **zero persistence footprint** — they are simply the parts of the basis that no
   patch touches, so upstream churn touches them for free.

The old CSV world froze a *snapshot* mixing raw candidates and human decisions, which
rotted whenever upstream/supplements changed (hence the fuzzy re-join, "lost
verdicts", and audits). The new world never freezes the basis, so there is nothing
to re-join.

Corollaries (all live in code today):
- **Reviewed** = a patch exists for the anchor; no stored flag.
- **Rollback** = delete the patch; the intact basis *is* the undo.
- The **anchor never changes when you edit** — an entry never moves or disappears
  as a consequence of being edited; only its displayed content changes.
- **Fail loud** on a patch whose anchor no longer resolves (upstream drifted out
  from under the decision) rather than silently dropping it.
- Deterministic: same inputs → same `readlex.json`.

## The natural key (record identity) — empirical derivation

Determined against `data/readlex.json` (112,385 entries at the time):

**`(word, pos, shaw, var, lemma)`** is the identity of a dictionary record.

- `word` (Latn), `pos` — identifying.
- `shaw` — the Shavian spelling *is* the dictionary's payload; a different spelling is
  a different record.
- `var` — **in the key.** Records identical but for `var` are distinct facts ("this
  spelling applies to this dialect"), so a spelling fix is dialect-specific.
- `lemma` — **in the key** (2026-08, structured `{Latn, pos, Shaw}` sub-object on the
  anchor, a nested tuple in the key). Two records can share all four other fields yet
  belong to different lemmas (`axes` VVZ is filed under both `ax` and `axe` upstream —
  36 dual-filed record pairs), and homograph slots (`ad` æd vs ˌeɪˈdiː) need the lemma
  to tell records apart. Absent lemma (`()` in the key) means "none stated".
  Migration: `src/tools/migrate_patch_lemmas.py`, run in one sitting with a pool
  regeneration.
- `ipa`, `freq` — **NOT in the key.** They are derivation/provenance. Of the 64
  collisions on `(word,pos,shaw,var)`, 50 were exact duplicates and 14 differed *only*
  in `ipa`/`freq` (stress-mark re-notation of the same pronunciation → same Shavian).
  Putting `ipa` in the key would enshrine upstream notation noise as identity and
  orphan patches on trivial upstream re-notation. Zero collisions differed in anything
  semantically load-bearing.

Identity must stay **minimal** — every field in the key is a field whose upstream drift
can orphan a patch. (The `orig_*` convention in record-schema.md is the later answer
to transforms that legitimately move a key field.)

## Store model

Git JSONL (`data/patches/patches.jsonl`) is the source of truth — single file,
provenance is a field, not a filename. A SQLite cache would appear only in a
multi-user online phase, as a derived coordination layer; git stays authoritative.

## History

- Migration (2026-07): verdicted CSV rows were salvaged into `patches.jsonl`
  (~808 patches); the 1,632 machine-dropped affix/fragment rows were re-derivable
  and not salvaged.
- Phasing as executed: 0) applicator rewrite (output byte-identical) → 1) local
  single-user editor (built, `src/editor/`) → 2+) multi-user/online (not built).
- The RSSB-reaches-output question this doc used to track is resolved — see the
  export-collapse decision in [decisions.md](decisions.md).
