# Record & patch schema

The fields a dictionary record carries, and the shape of an editorial patch.
Authoritative source in code: [`src/tools/basis.py`](../src/tools/basis.py)
(constants `INTRINSIC_FIELDS`, `PROVENANCE_FIELDS`, `ORIG_FIELDS`, `INFO_FIELD`).
This doc summarises them; when in doubt read basis.py.

## Record identity — the natural key

**`(word.lower(), pos, shaw, var)`** is the identity of a record. A patch's
`anchor` is exactly this key. Each dialect `var` is reviewed independently — a
spelling fix to the RRP record does not touch the GenAm record.

`ipa` and `freq` are **not** in the key (they are provenance/derivation; putting
them in identity would orphan patches on trivial upstream re-notation). See
[editorial-overlay-design.md](editorial-overlay-design.md) for the derivation.

## Intrinsic fields (human-editable — the only keys a patch `changes` may carry)

`INTRINSIC_FIELDS`:

| field | meaning |
|---|---|
| `word` | Latin (Latn) spelling; the headword |
| `shaw` | Shavian spelling — the dictionary's payload |
| `pos` | part of speech (C5 tagset: NN1, VVI, AJ0, NP0, UNC, …) |
| `ipa` | source IPA pronunciation |
| `var` | base accent (RRP / RSSB / GenAm / …) — see [dialect-mergers.md](dialect-mergers.md) |
| `mergers` | additive list of within-accent vowel mergers the spelling reflects (`trap-bath` / `cot-caught` / `lot-palm`); empty = canonical non-merged form |
| `variant` | additive boolean — this spelling diverges from the RRP canonical (a non-canonical variant); see [decisions.md](decisions.md) |

## Provenance fields (derived, read-only, never patch-editable)

`PROVENANCE_FIELDS` + `INFO_FIELD`. Carried end-to-end so the editor can surface,
filter, and sort the review pool; recomputed by the pipeline, never stored in a patch.

| field | written by | meaning |
|---|---|---|
| `source` | combine/prune chain | origin list that attested the anchor (`wordnet`, `wiktionary`, `readlex`, `names`, `generated`, or a set) |
| `confidence` | scorers | pipeline confidence |
| `status` | applicator | `sanctioned` on accept; else the supplemental candidate state. In the record because downstream reads it |
| `ipa_source` | generators | which source the IPA came from |
| `has_definition` | `annotate_definitions` | boolean — any attesting source carries a definition |
| `info` | wiktionary generator | catch-all list of non-essential metadata strings (first use: Wiktionary quality tags — obsolete/dialectal/dated…). Additive list like `mergers` |
| `rrp_outcome` `rrp_tier` `rrp_review` | `reclassify_rrp.py` | RRP reclassifier triage: outcome (PASS/PASS_RESPELL/STAY/REVIEW/SKIP_MERGER), tier (A..F), low-confidence review flag |
| `generated_shaw` `generated_tier` `generated_method` `generated_from` `generated_flags` | `generate_rrp.py` | RRP generator's *propose-alongside* provenance: a minted RRP spelling proposed BESIDE the record's own `shaw` (never overwriting), its tier, method, lineage, gated site |
| `merger_gate` | collapse (D3) | records a flag-strip: which flag was removed and why the canonical counterpart was not high-confidence |

`freq` is stamped wholesale by the frequency pass (`apply_frequency_data.py`),
so it is never carried in a patch either.

## orig_* — original-value provenance (derived)

`ORIG_FIELDS` = `{var: orig_var, shaw: orig_shaw, ipa: orig_ipa}`. When a pipeline
transform CHANGES a key field (e.g. the collapse rewrites `var`, a classifier
respells `shaw`), it records the pre-transform value under `orig_*`. This lets the
applicator **auto-re-anchor** a patch that was written against the old key — the
transformed record still carries the identity its patch resolves to.

- Additive: present only when that field was actually changed; absent = unchanged.
- SET-ONCE: the FIRST pre-image wins (the value the owner reviewed); later
  transforms never overwrite it.
- Not in `INTRINSIC_FIELDS` — a patch's `changes` may not carry it.

## The patch record (live model — code, not the design doc)

A patch in [`data/patches/patches.jsonl`](data-files.md) is a **minimal diff** over
the live basis:

```jsonc
{ "anchor": {word,pos,shaw,var} | null, "op": "...", "changes": {...}, "meta": {...} }
```

| field | meaning |
|---|---|
| `anchor` | natural key of the ONE basis record reviewed; `null` = authorship (a brand-new record no source attests) |
| `op` | `accept` (sanction the anchored record + lay `changes` over it), `drop` (emit nothing), `flag` (looked-at, no verdict — production no-op) |
| `changes` | the INTRINSIC edits (subset of `INTRINSIC_FIELDS`) an accept layers over the basis record. For an authorship patch, this is the WHOLE record |
| `meta` | `{author, ts, note}` — patch metadata; `note` is NEVER emitted to the dictionary |

`resolve_patch` (in basis.py) layers the patch over the *live* basis, so a decision
follows upstream drift instead of freezing a stale copy. Deleting a patch is rollback.

> **Doc drift, 2026-07-20:** [editorial-overlay-design.md](editorial-overlay-design.md)
> §"The patch record" and [`src/editor/README.md`](../src/editor/README.md) describe an
> earlier **full-record** `{anchor, record|null, meta}` shape. The shipped code
> (`basis.py`, `apply_patches.py`, `editord.py`) uses the **minimal-diff**
> `{anchor, op, changes, meta}` shape above. Trust the code / this doc.
