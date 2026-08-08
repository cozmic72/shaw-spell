# Shaw-Spell and the Shavian Spelling Rules — the Project Layer

The global `shavian-spelling` skill (`~/.claude/skills/shavian-spelling/SKILL.md`) is the durable **linguistic** reference: the Guide's principles, the affix tables, the neutral-vowel rule, dialect conventions. This doc is the **project layer**: how Shaw-Spell *applies* — and deliberately *bends* — those rules, and the encodings and open issues that change as the project evolves. When this doc and a linked design doc disagree, the design doc wins.

## The two goals in practice

- **Goal 1 (primary):** conformal, canonical vocabulary expansion — new entries spelt as ReadLex itself would spell them, labelled **RRP** wherever the rules permit. The RP/SSB classifier is a *canonicalizer*: RSSB is the honest residue the rules block, not enrichment to preserve.
- **Goal 2 (secondary, deliberate):** modern-spoken variants added *alongside* canonical entries, consciously bending ReadLex's conservative (archaic-leaning, US/UK-compromise) choices. Every entry must be attributable to one goal or the other.

The classifier's 5-step "can this be RRP?" procedure lives in the skill (§1); this doc holds the project-side consequences below.

## Merger flags — the encoding

(Concept in the skill §7; full model in `docs/dialect-mergers.md` — that doc is authoritative. Summary of the encoding:)

- A record carries a **base accent** (`var`: RRP/RSSB/GenAm/…) plus an additive **`mergers`** list of within-accent vowel mergers its spelling reflects. Empty/absent `mergers` = the canonical, non-merged form for its base accent.
- **`trap-bath`**: PALM 𐑭 → TRAP 𐑨 (*basket* 𐑚𐑭𐑕𐑒𐑦𐑑 → 𐑚𐑨𐑕𐑒𐑦𐑑). ReadLex's own `TrapBath` var is **reinterpreted** as base `RRP` + `mergers: ["trap-bath"]`.
- **`cot-caught`**: THOUGHT 𐑷 → LOT 𐑪 (*auction* 𐑷𐑒𐑖𐑩𐑯 → 𐑪𐑒𐑖𐑩𐑯). Direction confirmed empirically; ReadLex canonical keeps THOUGHT.
- A flag is applied **only** for an exact single-vowel swap of an attested non-merged sibling — detected, never invented.
- An RSSB↔GenAm difference that isn't a known merger IS the base-accent difference — the `var` label carries it, no flag.
- The dominant unmodelled residue is the unstressed **schwa↔TRAP onset** alternation (*ability*, *abduct*) — real GenAm signal, candidate for a future flag.

## RSSB — status and open issue

- **RSSB** is Shaw-Spell's own var (SSB made rhotic to align with RRP); it is **not handled downstream** (spell-check daemon, site, installer). Legacy builds normalised RSSB→RRP for production.
- Its fate is an **open owner decision** — do not special-case it away, and preserve it in the editorial layer (see `docs/editorial-overlay-design.md`, Known open issues).
- The **RP/SSB phonotactic reclassification** programme will empirically mine which paired RP↔SSB differences are principled category shifts vs mere realisation drift (e.g. the shwi→shwa weak-vowel shift), yielding rules for a principled RSSB→RRP reclassify. Prefer its mined rules over ad-hoc judgement once available.

## Editorial overlay and record identity

- **Record identity** is the natural key **`(word, pos, shaw, var)`** — the Shavian spelling IS the payload; a different spelling is a different record; `var` is in the key (a spelling correction is dialect-specific). `ipa`/`freq` are provenance, **not** identity.
- **Editorial decisions live in a patch overlay** (`patches.jsonl`, git-authoritative) layered over an on-demand **basis** (upstream ReadLex + supplements). Current stance: a patch stores only the **changed fields (minimal diff)** over the live basis; the owner's edit wins silently. Derived/novelty relations are computed live, never baked into patches. The basis is never mutated; deleting a patch is rollback; apply **fails loud** on orphaned anchors. **`docs/editorial-overlay-design.md` is authoritative** — consult it rather than this summary when details matter.
- **`source`/`confidence` are basis-derived provenance**, not reviewer-editable; `status` (`supplemental` → `sanctioned` on accept) lives in the record.
- **ReadLex is gospel for what it covers** (e.g. plurals); supplements extend, they don't overrule, except through an explicit editorial patch.

## Data quality — fail fast

- Unmapped IPA characters (ĭ ʁ ɬ ɾ ʏ…), stray Latin letters, and invisible formatting must **never** leak into a Shavian spelling — detect and filter/flag; don't ship contaminated shaw. (Known upstream defect class; see `docs/dialect-mergers.md`, "Data-quality junk".)
- **Stress provenance** (skill §2): the neutral-vowel rule needs the source's IPA stress marks. A polysyllabic candidate with no stress information cannot be spelt — flag it; never guess a stress pattern.
- Merger classification tags only exact single-vowel swaps of attested siblings; the residue is left honest, never force-fit.

## Conversion tooling

- `src/tools/ipa_to_shavian.py` — rule-based IPA→Shavian converter (~99% on ReadLex self-test) plus `normalize_ipa()` for dialect normalisation.
- The `shave` CLI — a full morphological Roman→Shavian G2P (no IPA needed).
- The supplement pipeline scores confidence by rules/ML/shave consensus.
- Pipeline and encoding detail: the `readlex` skill (`.claude/skills/readlex/SKILL.md`).
