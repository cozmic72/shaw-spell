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
A patch is `{anchor, op, changes, meta}` (op ∈ accept/drop/flag; `changes` = intrinsic
edits only). Owner's edit wins silently over the recomputed basis; the basis is never
mutated; deleting a patch is rollback. Derived provenance (source/confidence/freq) is
never stored in a patch. NB the earlier *full-record* shape in the design doc / editor
README is superseded — see [record-schema.md](record-schema.md) doc-drift note.
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

**Mergers are FROZEN — direction & one-vs-two unsettled** — FROZEN. **Important.**
`trap-bath` is clear-cut and ON. `cot-caught` and `lot-palm` are **DISABLED** (per-merger
enable flags, commit 44e289f) to buy analysis space. The owner's linguistic framing
(canonical=LOT, variant=PALM) is the OPPOSITE direction to the code's current `MERGER_SWAPS`,
and whether lot-palm/cot-caught is one bidirectional merger or two directional ones is
genuinely unresolved. Do NOT re-enable them, alter `MERGER_SWAPS`, or commit merger logic
until the owner completes a data analysis (an R&D task, not a code change).
→ per-merger flags in `dialect_mergers.py` / `classify_dialect_mergers.py`.

**The `variant` flag IS live** — SETTLED (the decidable half of the frozen model).
Anchor every decision to the **RRP canonical** spelling for `(word, pos)`:
(1) shaw == canonical → no flag; (2) shaw != canonical but no contrasting sibling
→ no flag (isolated sample, nothing to vary from); (3) shaw != canonical AND a
contrasting canonical sibling exists → this record is the variant → flag `variant`.
Canonical = ReadLex-attested base-RRP spelling, or the sole RRP pool specimen IF
high-confidence (rrp_tier A/B). Multiple competing / low-conf lone → no safe canonical → no flags.
→ [`src/tools/flag_variants.py`](../src/tools/flag_variants.py).

**Multi-accent harvest + fallback hierarchy** — PENDING (designed, not built).
Harvest standard national accents ReadLex is thin on (GenAus, Canada, South-African,
New-Zealand, Ireland-Republic) from Wiktionary `tags`, as their own vars. Records are
stored only at the most-specific level where the spelling DIVERGES from its parent in the
fallback hierarchy **Canada→GenAm→RRP; GenAus/NZ/SA/Ireland→RRP** (else it collapses to
the parent — same principle as the D2 identical-dialect collapse). Harvested accents flow
into `readlex.json` + editor but NOT the shipped US/UK dicts (yet). Northern-Ireland and
all sub-national tags are dropped.

**Wiktionary geo-tag filtering** — PENDING (the primary half of the harvest feature).
The wiktionary generator currently DEFAULTS off-target regional tags in as `var=UNC`
instead of dropping them → common-word pronunciation bloat. Fix: allowlist the KEEP accents
(RP/UK/British, GenAm/US, GenAus, Canada, SA, NZ, Ireland-Republic); DROP every other
geographic tag (Northumbria, Scotland, MLE, Southern-US, Indic, …).
→ [`src/tools/generate_wiktionary_supplement.py`](../src/tools/generate_wiktionary_supplement.py) (in flight — do not disturb).

**Wiktionary quality tags → the `info` field** — SETTLED (schema landed).
Rather than a lossy upfront drop, carry Wiktionary quality/register tags
(obsolete/dialectal/dated/rare/archaic…) through onto the record's `info` list, surfaced
as an editor filter/badge, so the owner judges them at review. A general-purpose catch-all
field for non-essential metadata (NOT the patch `note`).
→ `INFO_FIELD` in [`src/tools/basis.py`](../src/tools/basis.py) (commit 5e3ac8c).

**Untagged pronunciations kept as SSB** — SETTLED (part of harvest design).
The ~33% of Wiktionary sounds with no accent tag (mostly legit main pronunciations) are
kept as **SSB** (the honest "general/unconfirmed British" bucket), then the RRP reclassifier
may promote to RRP. Junk stays SSB/low-confidence for review.

**RSSB reaches output — fate undecided** — PENDING/open.
RSSB is our own var (SSB made rhotic); no downstream consumer (spell-check, site, installer)
handles it, and legacy builds normalised RSSB→RRP. The new applicator preserves it. Harmless
on this branch (not wired to production). Do NOT special-case it away without an owner decision.
→ [editorial-overlay-design.md](editorial-overlay-design.md) "Known open issues".

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

**shave-names path is feature-flagged OFF by default** — SETTLED.
The IPA-basis path is pure/deterministic. The `generate_rrp` shave/names path (no-IPA names)
is gated behind `SHAW_SPELL_ENABLE_SHAVE_NAMES` (default OFF) — present but dormant, an
owner-undecided lane. shave is non-deterministic on low-confidence spellings, which orphans
patches; the `-reliable`/`names`/`generated` targets are order-only Make targets (rebuilt only
when missing) so a checkout can't re-shave and orphan the owner's decisions.
→ [`src/tools/generate_rrp.py`](../src/tools/generate_rrp.py) `ENABLE_SHAVE_NAMES`,
[`src/tools/build_supplement.py`](../src/tools/build_supplement.py).

**Count-preservation asserted on the stages that promise it** — SETTLED.
Stages contracted as 1:1 (reclassify, generate) assert count preservation (fail-loud) so a
future edit can't silently build a wrong basis. Drop-stages are unguarded by design.
→ orchestrator in `build_supplement.py` (commit a257dbb).

---

## Definitions

**Every definition must have a Shavian transliteration** — SETTLED (invariant) / PENDING (build).
Coverage must be total (quality then improved by review). Closed by a **gap-fill-only** shave
pass (never re-transliterate existing keys → can't orphan definition-patches).
→ [`src/tools/transliterate_definitions_gap.py`](../src/tools/transliterate_definitions_gap.py),
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
