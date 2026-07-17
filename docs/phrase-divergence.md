# Phrase divergence detection

`src/tools/detect_phrase_divergence.py` flags which multi-word phrases in the
Wiktionary supplement deserve their own dictionary entry.

A phrase is a **keeper** only when its pronunciation is NOT simply its component
words glued together. "a priori" is a keeper — the "a" is /eɪ/ (FACE) or the
Latin /ɑː/, not the reduced article schwa. "outer space", "false friend", and
"hot dog" are just their words concatenated, so they are noise.

## How the signal is computed

The comparison happens in **Shavian**, not raw IPA. The project's
`ipa_to_shavian` converter already normalizes away exactly the noise that makes
a naive IPA comparison useless — it strips stress marks and syllable
separators, drops length marks, and folds dialect-notation variants (`oʊ`/`əʊ`,
`ɛ`/`e`) onto one segmental representation. `classify_shaw_difference` then
knows the weak-vowel alternations that are acceptable across a word boundary
(kit/schwa, trap/schwa, foot/schwa) — the reductions a phrase undergoes when its
parts run together. The detector reuses that phonology rather than inventing a
parallel IPA comparator.

Per phrase:

1. Split `Latn` on whitespace into component words.
2. Cite each component's canonical IPA. **ReadLex is consulted first** (the
   sanctioned dictionary); the supplements only fill words ReadLex lacks. Within
   a source: prefer the phrase's own dialect, else RRP (which is universal),
   highest `freq` wins.
3. Convert each citation to Shavian and concatenate: the **expected** phrase.
4. Convert the phrase's own `ipa` to Shavian: the **actual** phrase.
5. Compare (`classify_shaw_difference`, plus a local TRAP-BATH tolerance):
   - `matches` — same as sum-of-parts → droppable noise
   - `divergent` — differs beyond tolerance → KEEPER
   - `unknown` — a component could not be resolved (never guessed)

The heuristic leans toward `divergent`/`unknown` when uncertain: wrongly hiding
a keeper is worse than wrongly showing a droppable.

## Outputs

- `data/phrase-divergence.tsv` — inspection report: `phrase, pos, var,
  phrase_ipa, expected_ipa, phrase_shaw, expected_shaw, classification`.
- `data/phrase-divergence.json` — the classification keyed by anchor
  (`word\tpos\tshaw\tvar`, matching `basis.py`), for downstream consumers.

Build with `make phrase-divergence`.

## Known limitations

This is a heuristic. It is deliberately biased against false `matches`.

- **Foreign / Latin phrases resolve to `unknown`.** Their component words
  ("priori", "novo", "ipso") are not in the dictionaries, so — correctly — no
  citation is invented. "a priori" itself lands in `unknown`, not `divergent`,
  for this reason. These are surfaced, not hidden.
- **Word-sign notation inflates `divergent`.** ReadLex cites function words with
  word signs (`F` for "for", `Ð` for "the", `V` for "of", `N` for "and"), which
  map to a single Shavian letter, whereas a phrase often spells them out
  (`fɔːR`, `ðə`). "account for", "change the game" read as divergent on this
  alone. Safe direction, but noisy.
- **Length-mark drift inflates `divergent`.** Supplement phrase transcriptions
  sometimes drop a length mark the citation keeps (`ru` vs `ruː` → 𐑿 vs 𐑘𐑫;
  `ɡrin` vs `ɡriːn`), producing a segmental difference that is really just
  transcription granularity.
- **Garbled source transcriptions** (e.g. "wise man" as `wʌɪzman`) read as
  divergent. That is a supplement data-quality issue, not this tool's.
- **TRAP-BATH is tolerated locally.** A component cited in its BATH-long form
  (`Ɑː` → 𐑭) against a phrase using the TRAP-short form (`æ` → 𐑨) is the same
  word in a different accent, not divergence, so the 𐑨/𐑭 pair is folded into
  `matches` here (only here — it stays a real error elsewhere in the pipeline).
- **Multi-word component sub-phrases are not resolved.** Only single-word
  citations are indexed; a phrase whose "component" is itself idiomatic will not
  find a citation and falls to `unknown`.

The `matches` class is trustworthy (few false negatives — genuine keepers rarely
land here). The `divergent` class is noisier and is best read as "worth a look",
not "definitely a keeper".
