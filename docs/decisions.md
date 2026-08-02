# Decision log

Durable decisions, each with the one-line rationale and where it lives in the
code. **SETTLED** = decided and built; **FROZEN** = deliberately parked pending
owner analysis, do not touch; **PENDING** = designed, not built.

For the full pipeline see [pipeline-architecture.md](pipeline-architecture.md);
for the dialect model [dialect-mergers.md](dialect-mergers.md); for the schema
[record-schema.md](record-schema.md).

---

## Review & the patch store

**Never auto-accept** — SETTLED, standing hard rule.
Everything the pipeline produces (classifier, generator, name import, merger/variant
tagging) lands as an *unreviewed candidate*. Tools assist review; the owner accepts.
No auto-accept threshold, batch-accept, or auto-sanction tier — a near-perfect
confidence tier still only *prioritises* review. Lifts only if the owner explicitly says so.
→ enforced throughout; candidates carry `status` until an accept patch sanctions them.

**`patches.jsonl` is sacred — owner decisions, never machine-written** — SETTLED, absolute.
`data/patches/patches.jsonl` is the owner's alone. The pipeline only READS it (via
`apply_patches.py`); nothing in the build writes/edits/migrates/reverts it. Auto-re-anchor
in `apply_patches` is in-memory only. `repair_patches.py --write` exists for the OWNER to
run, never an agent against the live store.
→ [`src/tools/apply_patches.py`](../src/tools/apply_patches.py) reads; nothing writes.

**Patch = minimal diff over the live basis** — SETTLED (code).
A patch is `{anchor, op, changes, meta}` (op ∈ accept/edit/drop/flag; `changes` =
intrinsic edits only; `edit` = a dirty not-yet-reviewed edit that ships nothing).
Owner's edit wins silently over the recomputed basis; the basis is never mutated;
deleting a patch is rollback. Derived provenance (source/confidence) is never stored
in a patch.
→ [`src/tools/basis.py`](../src/tools/basis.py) `INTRINSIC_FIELDS`, `resolve_patch`.

**Definition corrections use a SEPARATE store** — SETTLED (design + code).
`data/patches/definition-patches.jsonl`, distinct from the word `patches.jsonl` — a
definition correction has a different natural key (`word|synset-id`) and lifecycle;
mixing would muddy the sacred word-decisions file.
→ [`src/editor/definition_patches.py`](../src/editor/definition_patches.py).

---

## Dialect / variant model

**RRP is the universal base; GenAm/TrapBath are exceptions only** — SETTLED.
An RRP-only entry covers ALL dialects (RRP = Rhotic Received Pronunciation, a UK/US
compromise). GenAm (~1,081) and TrapBath (1,697) entries exist only where the accent
genuinely differs. Absence of a GenAm entry is NOT a coverage gap.

**Base accent (`var`) + additive `mergers` list** — SETTLED.
A record's within-accent vowel mergers move out of `var` into an additive `mergers`
list (`trap-bath` / `cot-caught` / `lot-palm`); empty = canonical non-merged form.
ReadLex's `TrapBath` var is reinterpreted at consumption as base `RRP` + `mergers:[trap-bath]`
(the submodule is read-only, nothing rewritten on disk).
→ [`src/tools/dialect_mergers.py`](../src/tools/dialect_mergers.py), `basis.py` reinterpret;
[dialect-mergers.md](dialect-mergers.md).

**Mergers are FROZEN — direction & one-vs-two unsettled** — SUPERSEDED by "All three mergers
ENABLED" below (2026-08-01). Kept for history: `cot-caught` and `lot-palm` were disabled
(per-merger enable flags, commit 44e289f) pending a direction analysis. The owner's linguistic
framing (canonical=LOT, variant=PALM) had looked like the OPPOSITE direction to the code's
`MERGER_SWAPS`, and whether lot-palm/cot-caught was one bidirectional merger or two directional
ones was unresolved.
→ per-merger flags in `dialect_mergers.py` / `classify_dialect_mergers.py`.

**All three mergers ENABLED** — SETTLED (commit 15fe62f).
The owner ruled on direction (see [dialect-mergers.md](dialect-mergers.md)): the variety that
DISTINGUISHES the vowels is canonical, the collapsing one carries the flag. That is an editorial
call, not a measurement, and reversing one is a single tuple in `_MERGER_SWAPS_ALL` — expect it to
be revisited once real output has been reviewed. The attestation rule was separately narrowed to
RP/SSB-attested upstream siblings, removing the base-selection defect that motivated disabling
them. `trap-bath`, `cot-caught`, and `lot-palm` are all default-on in `MERGER_ENABLED`.
→ [`src/tools/dialect_mergers.py`](../src/tools/dialect_mergers.py) `MERGER_ENABLED`.

**The `variant` flag IS live** — SETTLED (the decidable half of the frozen model).
Anchor every decision to the **RRP canonical** spelling for `(word, pos)`:
(1) shaw == canonical → no flag; (2) shaw != canonical but no contrasting sibling
→ no flag (isolated sample, nothing to vary from); (3) shaw != canonical AND a
contrasting canonical sibling exists → this record is the variant → flag `variant`.
Canonical = ReadLex-attested base-RRP spelling, or the sole RRP pool specimen IF
high-confidence (rrp_tier A/B). Multiple competing / low-conf lone → no safe canonical → no flags.
→ [`src/tools/flag_variants.py`](../src/tools/flag_variants.py).

**Multi-accent harvest + fallback hierarchy** — SETTLED (built).
Standard national accents are harvested from Wiktionary `tags` as their own vars
(`GenAus`, `GenCan`, `SthAfr`, `NZ`, `IrEng`, alongside `RRP`/`GenAm`). A harvested
record is kept only where its spelling DIVERGES from its parent in the hierarchy
**GenCan→GenAm→RRP; GenAus/SthAfr/NZ/IrEng→RRP** (else it collapses to the parent —
the same principle as the D2 identical-dialect collapse). Harvested lanes reach the
editor; the export boundary decides what publishes (see "readlex.json stays
ReadLex-shaped" below).
→ `KEEP_ACCENTS` in [`src/tools/generate_wiktionary_supplement.py`](../src/tools/generate_wiktionary_supplement.py);
hierarchy in [`src/tools/collapse_identical_dialects.py`](../src/tools/collapse_identical_dialects.py).

**Wiktionary geo-tag filtering** — SETTLED (built, same allowlist).
The generator KEEPs the allowlisted accents above and DROPs every other geographic
tag (Northumbria, Scotland, MLE, Southern-US, …) instead of defaulting them in as
`var=UNC`.
→ `KEEP_ACCENTS` / drop set in [`src/tools/generate_wiktionary_supplement.py`](../src/tools/generate_wiktionary_supplement.py).

**Wiktionary quality tags → the `info` field** — SETTLED (schema landed).
Rather than a lossy upfront drop, carry Wiktionary quality/register tags
(obsolete/dialectal/dated/rare/archaic…) through onto the record's `info` list, surfaced
as an editor filter/badge, so the owner judges them at review. A general-purpose catch-all
field for non-essential metadata (NOT the patch `note`).
→ `INFO_FIELD` in [`src/tools/basis.py`](../src/tools/basis.py) (commit 5e3ac8c).

**Untagged pronunciations kept as RSSB** — SETTLED (built).
Wiktionary sounds with no accent tag (mostly legit main pronunciations) are kept as
**RSSB** (the "unconfirmed British" bucket, SSB made rhotic), merging with wordnet's
RSSB records at combine time; the RRP reclassifier may promote to RRP. Junk stays
RSSB/low-confidence for review.
→ `UNTAGGED_VAR` in [`src/tools/generate_wiktionary_supplement.py`](../src/tools/generate_wiktionary_supplement.py).

**readlex.json export shape — accent + `*Var` suffix + `mergers` list** — SETTLED
(supersedes the original ReadLex-shaped collapse, commit 6ad6c3d). The internal lane
model (harvest vars, `mergers`, `variant`, RSSB) is richer than upstream ReadLex's;
rather than impoverish the pool, `collapse_readlex()` runs in BOTH producers right
before serialization: a record carrying variation (any merger, or the `variant` flag)
publishes as accent+`Var` (`RRPVar`, `GenAmVar`, …— upstream's `RRPVar` convention
generalised) with `mergers` shipped as a sorted list; the `variant` boolean is consumed
by the suffix, never shipped. Upstream's `TrapBath` var is **deliberately not emitted**
(a breaking change the owner accepted): those records ship as `RRPVar` +
`mergers: ["trap-bath"]`. **RSSB collapses into RRP** (as legacy production always
did); regional lanes with no upstream counterpart (NZ/IrEng/SthAfr/GenCan) are held
back from publication, not lost; an unknown var fails loud. The editor keeps seeing
every record and every lane. Consumers recover the accent with
`dialect_display.split_var`; a `*Var` with no `mergers` is free variation.
→ [`src/tools/basis.py`](../src/tools/basis.py) `collapse_readlex`.

---

## Vocabulary admission

**Keep ReadLex phrase entries; admit defined phrases & hyphenated words** — SETTLED (policy).
A multi-word phrase or internal-hyphen word that carries an upstream DEFINITION is
dictionary-worthy → admit it (it carries meaning its components don't). The phrase-divergence
filter drops only NON-divergent, spelling-derivable phrases, never a defined one. Hyphenated
words are NOT systematically filtered.
→ [`src/tools/filter_supplement_phrases.py`](../src/tools/filter_supplement_phrases.py),
[phrase-divergence.md](phrase-divergence.md).

**RSSB/GenAm identical-spelling collapse (D2)** — SETTLED.
When dialect variants of a word produce the same Shavian spelling, they collapse to one
RRP record (the spelling is universal); `source` unions the origins.
→ [`src/tools/collapse_identical_dialects.py`](../src/tools/collapse_identical_dialects.py).

---

## Generation & determinism

**The committed artifact IS the combined+filtered pool** — SETTLED (policy).
`data/` commits the pipeline's *checkpoint outputs* — `supplement-combined-filtered.json`,
`definitions-{latin,shavian}-{gb,us}.json`, `readlex.json`, `patches/`, the trained
models — not the per-source intermediates (all `supplement-<source>*.json` are
gitignored, regenerated on demand). Build and editor are dumb readers of the checkpoint;
they never re-derive it. Source-specific processing belongs upstream in the generators.
→ [`data/.gitignore`](../data/.gitignore); [data-files.md](data-files.md).

**shave-names path is feature-flagged OFF by default** — SETTLED.
The IPA-basis path is pure/deterministic. The `generate_rrp` shave/names path (no-IPA names)
is gated behind `SHAW_SPELL_ENABLE_SHAVE_NAMES` (default OFF) — present but dormant, an
owner-undecided lane. shave is deterministic (a re-shave is idempotent — see
[`project_shave_nondeterminism`], verified run-to-run incl. `--confidence 0`) but EXPENSIVE, and
the `-reliable`/`names`/`generated` files are the anchor identity for the owner's patches; the
targets are order-only Make targets (rebuilt only when missing) so a stray checkout mtime-shuffle
can't trigger a wasteful re-shave — a deliberateness/cost guard, not an anti-drift one.
→ [`src/tools/generate_rrp.py`](../src/tools/generate_rrp.py) `ENABLE_SHAVE_NAMES`,
[`src/tools/build_supplement.py`](../src/tools/build_supplement.py).

**Count-preservation asserted on the stages that promise it** — SETTLED.
Stages contracted as 1:1 (reclassify, generate) assert count preservation (fail-loud) so a
future edit can't silently build a wrong basis. Drop-stages are unguarded by design.
→ orchestrator in `build_supplement.py` (commit a257dbb).

---

## Definitions

**Every definition must have a Shavian transliteration** — SETTLED (invariant + built).
Coverage must be total (quality then improved by review). Closed by a **fill-missing-only**
pass (never re-transliterate existing keys → can't orphan definition-patches): `make
complete-definitions` (manual — shave is expensive; run after a gloss source changes).
→ [`src/tools/complete_definition_corpus.py`](../src/tools/complete_definition_corpus.py),
[definitions-editor-design.md](definitions-editor-design.md).

**Definition coverage: ~50%, gap is a long tail not a systemic hole** — SETTLED (finding).
50% of the 79,126 dict headwords have an upstream English definition. The "~95k defined-but-missing"
scare was a bad analysis (keys carry `word|synset` sense-suffixes — strip + dedup before counting);
only ~567 words are genuine never-candidates (441 affixes, correctly excluded; ~126 real tail).
→ definition caches, [data-files.md](data-files.md).

**Definitions editor scope: transliteration only, Shavian side only** — SETTLED (owner, v1).
The editor works over `definitions-shavian-{gb,us}.json` only; the English gloss is read-only;
correct the Shavian transliteration → a `definition-patches.jsonl` patch. New source ingest:
Wikidata CC0 (names gap) only; kaikki examples dropped ("we want definitions not examples").
→ [definitions-editor-design.md](definitions-editor-design.md) §6a.
