# Supplement generation rules
# Generates supplementary dictionary data from WordNet and Wiktionary

###########################################
# Source data paths
###########################################

WIKTIONARY_JSONL := external/wiktionary/kaikki.org-dictionary-English.jsonl
WORDNET_YAML := external/english-wordnet/src/yaml
READLEX_JSON := external/readlex/readlex.json

###########################################
# Supplement generation (from source data)
###########################################

# The -reliable.json files are COMMITTED artifacts and the anchor identity for
# every editorial patch. Their generators consult the external `shave` tool,
# which is NON-DETERMINISTIC (low-confidence Shavian drifts between runs), so
# regeneration is a DELIBERATE act — never an automatic mtime-triggered one.
# A `git checkout` shuffles mtimes, which could otherwise make a generator or
# source dump look "newer" and silently rebuild -reliable.json, drifting the
# Shavian and ORPHANING the owner's patches. Hence ALL prerequisites are
# order-only (after `|`): make rebuilds -reliable.json only when it is MISSING
# (e.g. a fresh clone), not when a prereq is merely newer. To re-baseline on
# purpose, use the `regenerate-supplements` target below.
data/supplement-wordnet-reliable.json data/supplement-wordnet-speculative.json: | $(SRC_TOOLS)/generate_wordnet_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WORDNET_CACHE)
	@echo "Generating WordNet supplement..."
	$(RUN) python3 $(SRC_TOOLS)/generate_wordnet_supplement.py

data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json: | $(SRC_TOOLS)/generate_wiktionary_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WIKTIONARY_JSONL)
	@echo "Generating Wiktionary supplement (this takes a few minutes)..."
	$(RUN) python3 $(SRC_TOOLS)/generate_wiktionary_supplement.py

# Deliberately regenerate the reliable supplements (re-runs the non-deterministic
# shave tool — expect Shavian drift; only run when you intend to re-baseline).
.PHONY: regenerate-supplements
regenerate-supplements:
	rm -f data/supplement-wordnet-reliable.json data/supplement-wordnet-speculative.json \
	      data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json
	@$(MAKE) data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json

###########################################
# Confidence re-scoring (fast, uses shave)
###########################################

.PHONY: rescore rescore-full
rescore: data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring supplement confidence..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py

rescore-full: data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring supplement confidence (full shave consultation)..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py --full-shave

###########################################
# Supplement candidate pruning (chained passes)
###########################################

# Pass 0 — proper-noun homograph rescue (wiktionary only). Many kaikki `name`
# entries have no IPA and were dropped by the generator; each is rescued by
# copying a same-spelling ReadLex homograph's IPA and tagged `copied-homograph`
# for review. Additive: the reliable set plus the rescued NP0 records. Pass 1
# reads this for wiktionary. See src/tools/rescue_proper_nouns.py.
data/supplement-wiktionary-rescued.json: $(SRC_TOOLS)/rescue_proper_nouns.py $(SRC_TOOLS)/ipa_to_shavian.py data/supplement-wiktionary-reliable.json $(WIKTIONARY_JSONL) $(READLEX_JSON)
	@echo "Rescuing IPA-less proper nouns via ReadLex homographs..."
	$(RUN) python3 $(SRC_TOOLS)/rescue_proper_nouns.py

# Pass 0.5 — NEAR syllable-dot correction (wiktionary only). The generator lost
# Wiktionary's syllable dot, so happier /ˈhæp.i.ə/ collapsed to NEAR (𐑣𐑨𐑐𐑽) not
# the two-syllable 𐑣𐑨𐑐𐑦𐑼. Each dot-collapsed NEAR record is re-derived from the
# dotted kaikki sound through the now-fixed converter, capped to needs-review
# confidence and tagged `near-dot-fixed` for the owner to adjudicate (ReadLex is
# editorially inconsistent here). Genuine NEAR (here/weird) and patch-anchored
# records are left untouched. See src/tools/fix_near_syllable_dots.py.
data/supplement-wiktionary-neardot.json: $(SRC_TOOLS)/fix_near_syllable_dots.py $(SRC_TOOLS)/ipa_to_shavian.py data/supplement-wiktionary-rescued.json $(WIKTIONARY_JSONL) data/patches/patches.jsonl
	@echo "Correcting NEAR syllable-dot collapses..."
	$(RUN) python3 $(SRC_TOOLS)/fix_near_syllable_dots.py

# Combine — unify the per-source candidate pools into ONE before any pruning, so
# every downstream filter runs on the union. Merges on the full anchor (word,
# pos, shaw, var); records gain a `source` list (union of attesting origins).
# This is what lets the identical-dialect collapse see a cross-source spelling
# collision. See src/tools/combine_supplements.py. (No patches prereq: combining
# is content-neutral — it neither drops nor edits, only unions.)
data/supplement-combined-raw.json: $(SRC_TOOLS)/combine_supplements.py data/supplement-wordnet-reliable.json data/supplement-wiktionary-neardot.json data/supplement-names.json
	@echo "Combining per-source supplement pools..."
	$(RUN) python3 $(SRC_TOOLS)/combine_supplements.py

# Definition annotation — join a `has_definition` provenance boolean onto each
# combined record: does the upstream source(s) that produced it carry a definition
# (wordnet synset gloss / wiktionary sense gloss)? A SEPARATE pass reading the SAME
# source files as the generators (never re-running them — shave is non-deterministic
# and would orphan patches). has_definition is the LOGICAL OR over the record's
# source list; it rides verbatim through the rest of the chain into the basis. See
# src/tools/annotate_definitions.py. (No patches prereq: annotation only adds a
# field, it neither drops nor reshapes.)
data/supplement-combined-defs.json: $(SRC_TOOLS)/annotate_definitions.py $(SRC_TOOLS)/generate_wordnet_supplement.py $(SRC_TOOLS)/generate_wiktionary_supplement.py data/supplement-combined-raw.json $(WORDNET_YAML) $(WIKTIONARY_JSONL)
	@echo "Annotating supplement candidates with upstream-definition provenance..."
	$(RUN) python3 $(SRC_TOOLS)/annotate_definitions.py

# Pass 1 — duplicate filtering. A candidate whose (word, shaw) an established
# entry (upstream ReadLex + sanctioned patches) already covers on both the var
# and pos axes is dropped. See src/tools/filter_supplement_duplicates.py.
data/supplement-combined-deduped.json: $(SRC_TOOLS)/filter_supplement_duplicates.py data/supplement-combined-defs.json external/readlex/readlex.json data/patches/patches.jsonl
	@echo "Filtering duplicate supplement candidates..."
	$(RUN) python3 $(SRC_TOOLS)/filter_supplement_duplicates.py

# Pass 2 — dialect merger classification. Each candidate is annotated with a
# `mergers` list: a GenAm spelling that is an exact within-accent vowel-merger
# swap (trap-bath 𐑭->𐑨, cot-caught 𐑷->𐑪) of an RSSB sibling is tagged with that
# merger; the field is additive and absent when empty. The base accent `var` is
# unchanged. On the combined pool a sibling may come from either source. See
# src/tools/classify_dialect_mergers.py and docs/dialect-mergers.md. (No patches
# prereq: classification only annotates, it neither drops nor reshapes.)
data/supplement-combined-classified.json: $(SRC_TOOLS)/classify_dialect_mergers.py $(SRC_TOOLS)/dialect_mergers.py data/supplement-combined-deduped.json
	@echo "Classifying dialect vowel mergers..."
	$(RUN) python3 $(SRC_TOOLS)/classify_dialect_mergers.py

# Pass 3 — identical-spelling dialect collapse. When 2+ dialects spell a
# (word, pos) the SAME way, that spelling is not a real dialect difference, so
# every record is relabelled onto the highest-precedence var (RRP > RSSB > GenAm)
# and merged — source lists union — so the reviewer sees it once with full
# provenance. Records disagreeing on the `mergers` flag stay separate (a real
# within-accent difference). See src/tools/collapse_identical_dialects.py. (No
# patches prereq: collapsing is a pure dialect-hierarchy rewrite; an orphaned
# anchor fails loud downstream by design.)
data/supplement-combined-collapsed.json: $(SRC_TOOLS)/collapse_identical_dialects.py data/supplement-combined-classified.json
	@echo "Collapsing identical-spelling dialect variants..."
	$(RUN) python3 $(SRC_TOOLS)/collapse_identical_dialects.py

# Pass 3.5 — contamination pruning. ipa_to_shavian passes an unmapped IPA symbol
# (a foreign/dialectal phoneme) through verbatim, so a candidate's Shaw can carry
# a Latin letter, IPA symbol or diacritic — garbage Shavian. Any such candidate
# is dropped so the review surface never sees it. Upstream ReadLex is untouched
# (its ring-point/word-joiner acronym markers are intentional conventions). See
# src/tools/filter_supplement_contamination.py.
data/supplement-combined-decontaminated.json: $(SRC_TOOLS)/filter_supplement_contamination.py $(SRC_TOOLS)/ipa_to_shavian.py data/supplement-combined-collapsed.json data/patches/patches.jsonl
	@echo "Pruning contaminated (non-Shavian) supplement candidates..."
	$(RUN) python3 $(SRC_TOOLS)/filter_supplement_contamination.py

# Pass 4 — phrase pruning. A multi-word candidate whose pronunciation is just
# its component words glued together (classified `matches`) is dropped, so the
# review surface never sees sum-of-parts noise. The -filtered.json output is
# what the editorial basis reads (records pass through verbatim, so the merger
# annotation and source list survive). The phrase classifier's citation index is
# still built from the per-source -reliable dumps. See
# src/tools/filter_supplement_phrases.py.
data/supplement-combined-filtered.json: $(SRC_TOOLS)/filter_supplement_phrases.py $(SRC_TOOLS)/detect_phrase_divergence.py $(SRC_TOOLS)/ipa_to_shavian.py data/supplement-combined-decontaminated.json data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json external/readlex/readlex.json data/patches/patches.jsonl
	@echo "Pruning sum-of-parts phrase candidates..."
	$(RUN) python3 $(SRC_TOOLS)/filter_supplement_phrases.py

###########################################
# Merged readlex (combines original + supplements)
###########################################

SUPPLEMENT_DEPS := data/supplement-combined-filtered.json

# readlex.json is produced by a two-stage SEQUENTIAL pipeline so the frequency
# enrichment can never be silently reverted by a rebuild:
#   1. apply_patches.py: patch store + supplements -> readlex-merged.json (intermediate)
#   2. apply_frequency_data.py: readlex-merged.json + corpus -> readlex.json (final)
# The final readlex.json — the thing every downstream target consumes — is only
# "done" after frequency runs, so any rebuild reruns both stages in order.
# (legacy generate_merged_readlex.py is retained on disk but off the build path.)
READLEX_MERGED := data/readlex-merged.json
FREQUENCY_CORPUS := external/frequency-words/content/2018/en/en_full.txt

$(READLEX_MERGED): $(SRC_TOOLS)/apply_patches.py $(SRC_TOOLS)/basis.py $(SRC_TOOLS)/dialect_mergers.py external/readlex/readlex.json $(SUPPLEMENT_DEPS) data/patches/patches.jsonl
	@echo "Applying editorial patches to produce merged readlex..."
	$(RUN) python3 $(SRC_TOOLS)/apply_patches.py --out $(READLEX_MERGED)

$(READLEX_PATH): $(READLEX_MERGED) $(SRC_TOOLS)/apply_frequency_data.py $(SRC_TOOLS)/basis.py $(SRC_TOOLS)/dialect_mergers.py $(SRC_TOOLS)/spelling_variants.py $(FREQUENCY_CORPUS)
	@echo "Filling missing frequency data from subtitle corpus..."
	$(RUN) python3 $(SRC_TOOLS)/apply_frequency_data.py --in $(READLEX_MERGED) --out $(READLEX_PATH)

# Convenience alias — the frequency step is now part of the readlex build itself.
.PHONY: frequency
frequency: $(READLEX_PATH)

# frequency-words is a ~1.4 GB all-languages submodule; setup checks it out lean
# (sparse-checkout, only content/2018/en) so a fresh clone stays ~30 MB.
$(FREQUENCY_CORPUS):
	@$(MAKE) setup

# One-time submodule setup for a fresh clone. Re-runnable and safe on an
# already-populated tree.
.PHONY: setup
setup:
	@src/tools/setup-submodules.sh

###########################################
# Editorial review
###########################################

.PHONY: editorial
editorial: $(SUPPLEMENT_DEPS)
	@echo "Updating editorial CSV files..."
	$(RUN) python3 $(SRC_TOOLS)/generate_editorial_csv.py

###########################################
# Phrase divergence detection (flags multi-word phrases whose pronunciation
# genuinely differs from their component words glued together — keepers — vs
# those that are just concatenation noise. See docs/phrase-divergence.md.)
###########################################

data/phrase-divergence.tsv data/phrase-divergence.json: $(SRC_TOOLS)/detect_phrase_divergence.py $(SRC_TOOLS)/ipa_to_shavian.py data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json external/readlex/readlex.json
	@echo "Detecting phrase divergence..."
	$(RUN) python3 $(SRC_TOOLS)/detect_phrase_divergence.py

.PHONY: phrase-divergence
phrase-divergence: data/phrase-divergence.tsv

###########################################
# Wiktionary definitions
###########################################

data/definitions-wiktionary.json: $(SRC_TOOLS)/extract_wiktionary_definitions.py $(READLEX_PATH) $(WIKTIONARY_JSONL)
	@echo "Extracting Wiktionary definitions..."
	$(RUN) python3 $(SRC_TOOLS)/extract_wiktionary_definitions.py

###########################################
# Review files (for human inspection)
###########################################

.PHONY: review-files
review-files: $(SUPPLEMENT_DEPS) $(READLEX_PATH)
	@echo "Generating review TSVs..."
	$(RUN) python3 $(SRC_TOOLS)/generate_review_files.py

###########################################
# Convenience targets
###########################################

.PHONY: supplements supplements-from-source
supplements: $(READLEX_PATH)
	@echo "✓ All supplements and merged readlex up to date"

supplements-from-source: data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring with full shave..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py --full-shave
	@echo "Applying editorial patches into readlex..."
	$(RUN) python3 $(SRC_TOOLS)/apply_patches.py
	@echo "Generating review files..."
	$(RUN) python3 $(SRC_TOOLS)/generate_review_files.py
	@echo "✓ All supplements rebuilt from source"
