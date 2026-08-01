# Data files

Reference for the key files under `data/`. For how they flow together see
[pipeline-architecture.md](pipeline-architecture.md).

"Ships" = feeds the built US/UK dictionaries / spell-checker. "Tracked" = committed in
the `data` submodule.

Standing policy (see [decisions.md](decisions.md)): the committed artifact IS the
combined+filtered pool. Tracked = the pipeline's checkpoint outputs; the per-source
supplement files are gitignored intermediates, rebuilt when missing.

## Ship / build outputs

| File | What it is | Written by | Tracked | Ships |
|---|---|---|---|---|
| `readlex.json` | the shipping dictionary (final merged + frequency-stamped, ReadLex-shaped via `collapse_readlex`) | editor daemon (Commit publish); offline `apply_patches.py` | yes | yes |
| `definitions-shavian-{gb,us}.json` | machine Shavian transliterations of glosses, keyed `word\|synset-id` | `make complete-definitions` (fill-missing-only) | yes | yes (dict builds) |
| `definitions-latin-{gb,us}.json` | English glosses (source of truth), keyed `word\|synset-id` | `make complete-definitions` (fill-missing-only) | yes | source for translit |
| `definitions-wiktionary.json` | raw extracted Wiktionary definitions | `extract_wiktionary_definitions.py` | gitignored | source |

## Editorial store (SACRED)

| File | What it is | Written by | Tracked | Ships |
|---|---|---|---|---|
| `patches/patches.jsonl` | the owner's word-review decisions (accept/drop/flag). **Owner-only; pipeline never writes it** | owner (editor daemon) | yes | applied into readlex.json |
| `patches/definition-patches.jsonl` | owner's definition-transliteration corrections (separate store) | owner (editor daemon) | yes (once created) | applied into def caches |

See [decisions.md](decisions.md) "patches.jsonl is sacred".

## Supplement sources (candidate inputs — all gitignored, rebuilt when missing)

The labelled sources wired into the pool (`combine_supplements.py` `SOURCES`; upstream
ReadLex itself is the fifth, label `readlex`, read from `external/readlex/`). Each
label becomes the record's `source`.

| File | Label | What it is | Wired? |
|---|---|---|---|
| `supplement-wordnet-reliable.json` | `wordnet` | WordNet words WITH a pronunciation → IPA→Shavian | **yes** |
| `supplement-wiktionary-neardot.json` | `wiktionary` | Wiktionary words after rescue + NEAR syllable-dot fix | **yes** |
| `supplement-names-ipa.json` | `names` | curated proper names (shave + CMUdict voters) + CMUdict IPA-fill over `supplement-names.json` | **yes** |
| `supplement-generated-ipa.json` | `generated` | net-new no-IPA WordNet words, shave-spelled + neural-G2P IPA-fill over `supplement-generated.json` | **yes** |

Not wired (side outputs / future lanes, also gitignored): `supplement-wordnet-speculative.json`
(no usable pronunciation), `supplement-wiktionary-speculative.json` (`var=UNC`, a future
lane), `supplement-wiktionary-{reliable,rescued}.json` (pre-neardot intermediates),
`supplement-britfone.json` (**dropped** — see [decisions.md](decisions.md)).

## The committed checkpoint

- `supplement-combined-filtered.json` — the output of the whole supplement build
  (`build_supplement.py`) and the file the applicator + editor read (via `basis.py`
  `SUPPLEMENT_PATHS`). **Tracked** — this is the committed artifact; the build does
  not re-derive it unless asked.

## Models & corpus inputs

| File | What it is | Tracked |
|---|---|---|
| `rhoticity-model.pkl` | trained R-insertion classifier (99.7%) | yes |
| `ipa-normalizer-model.json` | ML IPA normaliser | yes |
| `g2p-model/`, `g2p-judge-model/` | neural G2P + judge (IPA-fill for `generated`) | yes |
| `bncfreq/1_1_all_fullalpha.txt` | BNC1994 LRW per-POS frequencies (freq POS split) | yes |
| `phrase-divergence.{json,tsv}` | phrase keeper/noise classification (`make phrase-divergence`) | gitignored |

## Legacy CSV editorial (superseded)

`editorial*.csv` and `readlex-reference.tsv` belong to the **pre-overlay** CSV review
workflow, now replaced by the patch-overlay system
([editorial-overlay-design.md](editorial-overlay-design.md)). They are untracked
(gitignored) and not the live path. `data/README.md` "Other Data Files" is partly
stale — prefer this doc.
