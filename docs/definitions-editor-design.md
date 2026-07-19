# Definitions viewer + editor — design

Status: DRAFT for owner review. No code yet.
Author: orchestrator, 2026-07-19.

## 1. Purpose & invariant

The dictionary carries **definitions** for its words (English glosses from WordNet +
Wiktionary), and machine-produced **Shavian transliterations** of those glosses. The
transliterations are imperfect. This feature lets the owner **view** a word's definitions
and **correct bad transliterations**, through the same patch-overlay discipline the word
editor already uses.

**Invariant (owner, 2026-07-19):** *every definition has a Shavian transliteration* — not
only the ones with a sanctioned/high-confidence version. Coverage must be total; quality is
then improved by review. (Today: ~135k Latin-def words vs ~88k Shavian-def keys — a real
gap the invariant must close. #11 R&D is quantifying its shape.)

Two orthogonal jobs, don't conflate them:
- **Coverage** (pipeline): guarantee a transliteration exists for *every* definition.
- **Correction** (editor): let the owner fix a specific bad transliteration → a patch.

## 2. Data model (as it exists today)

- `data/definitions-latin-{gb,us}.json` — `word -> [ {definition, pos, examples, source} ]`.
  ~135,249 keys. The English glosses. `gb`/`us` are near-identical (dialect spelling of the
  *English*, e.g. "colour"), NOT different senses.
- `data/definitions-shavian-{gb,us}.json` — `"word|synset-id" -> { definition,
  transliterated_definition, pos, transliterated_pos, examples, transliterated_examples }`.
  ~87,703 keys. The machine transliterations.

Key observations that drive the design:
- **The sense is the unit.** A word has *multiple* definitions (senses), each its own POS and
  synset id. The Shavian file is already keyed per-sense (`word|synset-id`). Corrections must
  therefore anchor **per-sense**, not per-word.
- **gb/us split.** Two transliteration sets. A correction may apply to one dialect or both.
  Design must decide (see §6 open Q).
- **Fields that get transliterated:** `transliterated_definition`, `transliterated_pos`,
  `transliterated_examples[]`. All three are correction targets, though the *definition* is
  the primary one.

## 3. Relationship to the word overlay (reuse, don't reinvent)

The word editor already has the pattern we want, and we mirror it:

| Word overlay | Definitions overlay |
|---|---|
| natural key `(word,pos,shaw,var)` | sense key `(word, synset-id, dialect?)` |
| minimal-diff patch `{anchor, op, changes}` | same shape, different anchor |
| `patches.jsonl` store | **separate** `definition-patches.jsonl` store |
| daemon ops entries/entry/patch/flag/unpatch | analogous def-ops (or namespaced) |
| `recordEditor()` render | `definitionEditor()` render |
| owner's edit wins silently over live basis | same |

**A separate patch store** (`definition-patches.jsonl`), not the word store. Rationale: a
definition correction is a different natural key and a different lifecycle; mixing them would
muddy `patches.jsonl` (the sacred word-decisions file) and complicate commit/att­ribution.
Same *mechanism*, separate *ledger*.

## 4. The coverage mechanism (closing the invariant)

Two distinct coverage gaps, closed by different means:

- **English-definition gap** — words/senses with NO gloss at all. Closed primarily by
  **ingesting additional open-source definition datasets** (the main thrust of #11 R&D:
  Open English WordNet, GCIDE/Webster public-domain, Wikidata/Wikipedia short descriptions for
  proper nouns & names, Wordset, fuller Wiktionary extraction, etc.). Real human-written
  definitions beat machine-drafted ones; LLM-drafting is only the residual fallback for what no
  open source covers. Licence compatibility is a gating concern per source.
- **Transliteration gap** — English glosses that exist but lack a Shavian version (135k Latin vs
  88k Shavian). Closed by a transliteration pass (below).

A pipeline pass — call it `transliterate_definitions.py` — that guarantees total *transliteration*
coverage over whatever English defs we have (existing + newly ingested):

1. For every `(word, sense)` in the Latin defs lacking a Shavian transliteration, generate
   one with **shave** (the deterministic Roman→Shavian G2P we already use; `-b` British for
   gb, default/US settings for us — TBD per §6).
2. Mark provenance + confidence on each generated transliteration (source: `shave`, plus
   shave's confidence signal where available — same goldmine we use elsewhere).
3. Result: 100% coverage; low-confidence ones surface first in the editor as review
   candidates. Existing hand-or-better transliterations are preserved (shave only fills
   gaps + optionally re-scores, never overwrites a sanctioned correction).

This is the same philosophy as the word supplement: **generate broadly, let the editor be the
sieve.** #11 R&D is checking what breaks (multi-word glosses, punctuation, the POS words like
`𐑨𐑛𐑝𐑻𐑚`, per-sense keying) before we commit to shave-over-everything.

Caveat noted from memory: shave is non-deterministic on low-confidence re-spells, which orphaned
word patches before. For *definitions* the same risk exists → the coverage pass must be
**gap-fill only** (never re-run over already-transliterated senses), so it can't churn existing
keys and orphan definition-patches. Mirror the `annotate_definitions` discipline.

## 5. UX — the correction editor

Owner leans **modal**, open to **inline**. My recommendation: **do both, layered** — an inline
*affordance* that opens a *modal* for the actual editing. Reasoning below.

### 5a. Where definitions live in the current UI
The word detail panel already shows a `has_definition` badge (`definitionBadge`). Today it's a
boolean pill — you can see *that* a word has a definition, not *what it is*. The natural home for
"view + correct definitions" is **an expansion of that badge into a definitions section** of the
word being reviewed.

### 5b. Recommended flow (modal-primary, inline-triggered)

```
Word detail panel
 ├─ …existing word fields (shaw/var/pos/mergers…)…
 └─ Definitions  [3 senses ▾]        ← inline, collapsed summary under the word
      • (n)  a small domesticated carnivore …      𐑩 𐑕𐑥𐑹𐑤 …   ✎   ⚑
      • (v)  to move stealthily …                  𐑑𐑵 𐑥𐑵𐑝 …   ✎   ⚑
      • (n)  a whip with nine knotted cords …      … (no translit yet) ✎!  ← flagged: needs review
```

- **Inline, read-only summary** of each sense right in the word panel: English gloss + its
  Shavian transliteration, per sense. This satisfies "view definitions" with zero clicks and
  keeps the definition anchored to the word you're reviewing (the important context).
- The **✎ pencil per sense opens a MODAL** — the focused correction surface. Modal because a
  definition correction wants room (multi-line gloss, the transliteration, examples, a shave-vs-
  correction diff) and shouldn't cramp the word panel. This is exactly why the word editor uses a
  modal for clone/create.
- **⚑ flag per sense** — "this transliteration is wrong" without fixing it now (mirrors the word
  flag op). Feeds a "definitions needing review" filter.
- **Coverage gaps are visible inline** — a sense with no transliteration renders a `needs
  transliteration` state (✎!), so the invariant's tail is discoverable, not hidden.

### 5c. The modal itself
- English gloss (read-only — we're not editing the English here; that's a different, bigger job).
- The Shavian `transliterated_definition` — **editable** (the main target).
- `transliterated_pos`, `transliterated_examples[]` — editable, secondary.
- **shave suggestion vs current** shown as a diff (like the word editor surfaces upstream vs
  edited), so the owner sees what the machine did and what they're changing.
- Save → a minimal-diff definition-patch `{anchor: (word, synset, dialect?), op: "edit",
  changes: {transliterated_definition: "…"}}`. Owner's edit wins silently, forever.
- **Never auto-accept** (standing rule): a shave-drafted transliteration is an unreviewed
  candidate; it becomes sanctioned only by the owner's explicit save/accept. Loading candidates
  ≠ accepting them.

### 5d. Why not pure-inline editing in the word panel?
Inline editing of a multi-line Shavian gloss inside the already-dense word panel would crowd it and
fight the word-review flow. Inline *view* + modal *edit* keeps each surface doing one job. (If
after using it the owner wants true inline editing for quick one-glyph fixes, it's an additive
enhancement — the modal stays for the heavy cases.)

## 6. Open questions for the owner

1. **gb/us split.** Correct one dialect or both at once? Options: (a) edit each dialect
   separately (two patches); (b) one correction applies to both unless they diverge; (c) treat
   the transliteration as dialect-agnostic where the English gloss is identical and only split
   when it actually differs. My lean: (c) — most glosses transliterate identically across gb/us,
   so default to one correction covering both, split only on genuine divergence. Confirm?
2. **Separate `definition-patches.jsonl` store** (my recommendation) vs folding into the word
   store — OK?
3. **Coverage pass = shave gap-fill only** (never re-transliterate existing keys, to avoid
   orphaning definition-patches) — agree?
4. **Editing scope:** correct *transliterations only* (my assumption), or also edit/choose the
   *English definitions* themselves? The latter grows once we ingest multiple def sources (#11) —
   the owner may want to pick/prefer a source, or edit a gloss. I've scoped v1 to transliteration
   correction; source-selection/gloss-editing is a natural v2. Confirm the v1 boundary.
5. **Entry point:** is the definitions section part of the **word** detail panel (my design), or a
   separate top-level "definitions" mode/filter in the workbench? I recommend hanging it off the
   word (context matters), with a "definitions needing review" filter as the triage entry.
6. **Definition source provenance in the UI:** once #11 lands new sources (WordNet vs Wiktionary vs
   GCIDE vs Wikidata…), each sense should show WHICH source it came from (like the word records'
   `source` list), so the owner can judge trust + pick. Fold into the inline sense summary.

## 7. Build phasing (once design is agreed) — NOT started
- P0: coverage pass (`transliterate_definitions.py`, shave gap-fill) → invariant holds.
- P1: daemon def-ops (view senses for a word; def-patch/flag/unpatch) + `definition-patches.jsonl`.
- P2: inline definitions section in the word panel (read-only view + gap visibility).
- P3: the correction modal (edit transliteration, shave-diff, save→patch).
- P4: "definitions needing review" filter + flag triage.
- Each phase reviewed; nothing auto-accepts; patches.jsonl untouched throughout.
