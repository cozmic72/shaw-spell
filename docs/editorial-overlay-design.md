# Editorial Overlay System — Design

**Status:** design settled (2026-07-16); implementation phased, not yet built.

This replaces the spreadsheet/CSV editorial process with a **patch overlay** on top
of a live-computed dictionary, backed by a UI (eventually online). It supersedes the
`editorial*.csv` + `generate_merged_readlex.py` + `merge_editorial_edits.py` machinery.

## The core idea

Two clean inputs, nothing frozen in between:

1. **The basis** — the raw combination of *all* upstream sources (upstream ReadLex +
   wordnet + wiktionary supplements), computed **on-demand**. Every candidate,
   including provisional/supplemental ones, is already a record *in the basis*,
   flagged with its origin, source, status, and confidence. The basis is never
   persisted as an editorial artifact; it is "whatever the sources currently say"
   and may grow/change freely.

2. **The patches** — the *only* persisted editorial artifact. One patch per record a
   human has ruled on. Nothing else is stored. The ~85K unreviewed candidates have
   **zero persistence footprint** — they are simply the parts of the basis that no
   patch touches, so upstream churn touches them for free.

The old CSV world froze a *snapshot* mixing raw candidates and human decisions, which
rotted whenever upstream/supplements changed (hence `merge_editorial_edits.py`'s fuzzy
re-join, "lost verdicts", and audits). The new world never freezes the basis, so there
is nothing to re-join.

## The natural key (record identity)

Determined empirically against `data/readlex.json` (112,385 entries):

**`(word, pos, shaw, var)`** is the identity of a dictionary record.

- `word` (Latn), `pos` — identifying.
- `shaw` — the Shavian spelling *is* the dictionary's payload; a different spelling is
  a different record.
- `var` (dialect: RRP / GenAm / TrapBath / …) — **in the key.** Records identical but
  for `var` are distinct facts ("this spelling applies to this dialect"). This is why
  a spelling correction is dialect-specific: fixing the RRP spelling does not touch the
  GenAm entry; you patch each.
- `ipa`, `freq` — **NOT in the key.** They are derivation/provenance. Of the 64
  collisions on `(word,pos,shaw,var)`, 50 are exact duplicates and 14 differ *only* in
  `ipa`/`freq` (stress-mark re-notation of the same pronunciation → same Shavian).
  Putting `ipa` in the key would enshrine upstream notation noise as identity and
  orphan patches on trivial upstream re-notation. Zero collisions differ in anything
  semantically load-bearing.

Identity must stay **minimal** — every field in the key is a field whose upstream drift
can orphan a patch.

## The patch record

A patch is a **record rewrite**. One shape; behaviour falls out of `old`/`new`:

```jsonc
{
  "id": "p_01H…",                                   // ULID, stable, never reused
  "old": {"word","pos","shaw","var"} | null,        // identity of the basis record acted on
  "new": {                                          // full record, or null
    "word","pos","shaw","var",                      //   identity
    "ipa","freq",                                   //   payload
    "source","status","confidence","note"           //   provenance (speaks the record's language)
  } | null,
  "meta": {"author","ts","note"}
}
```

| `old` | `new` | key change | Meaning |
|-------|-------|------------|---------|
| identity | record | (usually none) | **update** a basis record (e.g. keep: status → sanctioned) |
| identity | record | key differs (`shaw`) | **rewrite** — remove old identity, insert new (respell) |
| identity | null | — | **remove** a basis record (drop / suppress) |
| null | record | — | **authorship** — a record no source attests (manual/invented) |

**`old` is present for every decision on an attested basis record** (keep / respell /
drop / pos-gap). **`old: null` is reserved for pure authorship** — confirmed empirically:
of 48 manual entries, 35 are genuinely invented (contractions like `this'll`, names like
`Joro`, coinages like `e-book`/`EPUB`) with no basis record, and the other 13 have the
word attested but no exact `(pos,shaw,var)` match.

### Two schemas, opposite needs

- **Identity key** — kept *minimal* for drift-resistance.
- **Record payload** (of `new`) — kept *rich*, because the UI's whole job is filtering
  and every filter axis must be a field on the record. A patch's `new` speaks the same
  language as the intermediate/basis record (carries `source`, `status`, `confidence`,
  `note`, etc.), snapshotted as accepted — so there is no impedance seam between what an
  editor sees and what they write. But that richness is *derived at view time* on the
  basis; only the patch's own fields are persisted.

## The apply/build process

`apply_patches.py` replaces `generate_merged_readlex.py` with identical output semantics
and the same Make target (`$(READLEX_PATH)`), so nothing downstream changes:

1. Compute the basis (upstream + supplements) on-demand.
2. For each patch: resolve `old` against the current basis by identity
   `(word,pos,shaw,var)`; remove it; insert `new` (if non-null).
3. **Fail loud** on an authoritative patch (`old` present, but no longer resolves —
   upstream changed the shaw) rather than silently dropping it; surface it to an
   "orphaned decisions" queue. This is the re-anchor/drift problem `merge_editorial_edits.py`
   solves today, now formalized into the apply step instead of an ad-hoc CSV re-join.
   `merge_editorial_edits.py` and `generate_editorial_csv.py` are retired from the
   editorial path.

Determinism: total apply order = `(old.word, pos, shaw, var, meta.ts, id)`. Same inputs
→ same `readlex.json`.

## Decisions locked (2026-07-16)

- Store model: **git JSONL = source of truth**; a SQLite cache appears only in the
  online phase as a derived coordination layer that flushes back to the JSONL (git stays
  authoritative). Small-team framing confirmed — no Postgres-of-record.
- Basis is **computed on-demand**, never persisted as an editorial artifact.
- Natural key `(word, pos, shaw, var)`; `ipa`/`freq`/`source`/`status` are payload, not
  identity.
- Patch = record rewrite via `old`/`new`; `old:null` = authorship, `new:null` = removal.
- Trust model (collaborator patches direct-to-prod vs. review gate): **deferred** to
  Phase 2 (moot for single-user Phase 0/1).

## Deferred / open

- Combined keep+override vs. separate ops: settled as **one shape** (the rewrite).
- `patches.jsonl` single file vs. per-layer split: settled as **single file**
  (provenance is a field, not a filename).
- Migration: salvage verdicted CSV rows into `patches.jsonl` (see `migrate` tooling).
  ~808 patches: 645 keep + 8 drop + 4 corrected + 103 pos-gap-keep + 48 manual.
  `editorial-drops.csv` (1,632 machine-dropped affixes/fragments) NOT salvaged —
  re-derivable.
- Phasing: 0) applicator rewrite (invisible, output byte-identical) → 1) local
  single-user editor → 2) multi-user via git → 3) live online + SQLite cache.

## Phase 1 — the editor UI (MVP)

North star: **an editable version of the dictionary with extra ways of searching** —
not a bespoke review tool. The "review queue" is just a filter plus a stepping mode.

**Backend** — a sibling **`editord`** daemon in `src/editor/`, built on the SAME pattern
as the production `src/site-daemon/suggestd.py`: `socketserver` Unix-socket daemon,
line-oriented `{op: ...}` JSON protocol, in-memory state, deploy/systemd idiom. It holds
the basis (upstream + supplements) plus `patches.jsonl` and serves editor ops
(`op: entries` → filtered basis annotated with patch-state; `op: patch` → append/update a
patch). A thin CGI/HTTP frontend fronts it. **`suggestd` and the read-only production
spell-check path are untouched** — the read-write editorial tool is its own process, no
new deps.

**The annotated view** (the one non-trivial piece): the UI browses the basis with each
record annotated by its **patch-state** — untouched / kept / dropped / respelled /
authored — computed by overlaying `patches.jsonl` on the basis. This shares the anchor
matching logic with `apply_patches.py` (var-independent `(word,pos,shaw)`); factor it so
both use one implementation rather than a parallel copy.

**Filters:** `confidence` (threshold/range), `source`, `status` (supplement / new /
pos-gap / manual), `pos`, `var`, `word`/`shaw` substring, and patch-state.

**Layout:** filter bar on top; left panel = scrollable list/table of matches; right =
detail editor for the focused entry with **editable Shavian, focused by default**.
Stepping = arrow keys through the list.

**Accept / reject (pure patch model):**
- Accept → patch `{old: anchor, new: edits}` promoting the entry; any Shavian edit folds
  into `new.shaw` (edit-then-accept = a respell).
- Reject → removal patch `{old: anchor, new: null}`.
- Keyboard shortcuts for accept / reject / next / prev.

**Deferred to a later Phase-1 iteration:** editing the transliterated **definitions**
(`definitions-*.json`) — the same editor, extended. Design the entry model so definitions
can be added as an editable field later without reshaping the patch store.
