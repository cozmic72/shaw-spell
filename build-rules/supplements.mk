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

data/supplement-wordnet-reliable.json data/supplement-wordnet-speculative.json: $(SRC_TOOLS)/generate_wordnet_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WORDNET_CACHE)
	@echo "Generating WordNet supplement..."
	$(RUN) python3 $(SRC_TOOLS)/generate_wordnet_supplement.py

data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json: $(SRC_TOOLS)/generate_wiktionary_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WIKTIONARY_JSONL)
	@echo "Generating Wiktionary supplement (this takes a few minutes)..."
	$(RUN) python3 $(SRC_TOOLS)/generate_wiktionary_supplement.py

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

# Pass 1 — duplicate filtering. A candidate whose (word, shaw) an established
# entry (upstream ReadLex + sanctioned patches) already covers on both the var
# and pos axes is dropped. See src/tools/filter_supplement_duplicates.py.
data/supplement-wordnet-deduped.json data/supplement-wiktionary-deduped.json: $(SRC_TOOLS)/filter_supplement_duplicates.py data/supplement-wordnet-reliable.json data/supplement-wiktionary-rescued.json external/readlex/readlex.json data/patches/patches.jsonl
	@echo "Filtering duplicate supplement candidates..."
	$(RUN) python3 $(SRC_TOOLS)/filter_supplement_duplicates.py

# Pass 2 — dialect merger classification. Each candidate is annotated with a
# `mergers` list: a GenAm spelling that is an exact within-accent vowel-merger
# swap (trap-bath 𐑭->𐑨, cot-caught 𐑷->𐑪) of an RSSB sibling is tagged with that
# merger; the field is additive and absent when empty. The base accent `var` is
# unchanged. See src/tools/classify_dialect_mergers.py and docs/dialect-mergers.md.
data/supplement-wordnet-classified.json data/supplement-wiktionary-classified.json: $(SRC_TOOLS)/classify_dialect_mergers.py $(SRC_TOOLS)/dialect_mergers.py data/supplement-wordnet-deduped.json data/supplement-wiktionary-deduped.json
	@echo "Classifying dialect vowel mergers..."
	$(RUN) python3 $(SRC_TOOLS)/classify_dialect_mergers.py

# Pass 3 — identical-spelling dialect collapse. When 2+ specific dialects spell a
# (word, pos) the SAME way, that spelling is universal, so the identical-spelling
# variants collapse to a single RRP (all-dialects) record — the reviewer sees it
# once, not per dialect. Records disagreeing on the `mergers` flag stay separate
# (a real within-accent difference). See src/tools/collapse_identical_dialects.py.
data/supplement-wordnet-collapsed.json data/supplement-wiktionary-collapsed.json: $(SRC_TOOLS)/collapse_identical_dialects.py data/supplement-wordnet-classified.json data/supplement-wiktionary-classified.json data/patches/patches.jsonl
	@echo "Collapsing identical-spelling dialect variants..."
	$(RUN) python3 $(SRC_TOOLS)/collapse_identical_dialects.py

# Pass 4 — phrase pruning. A multi-word candidate whose pronunciation is just
# its component words glued together (classified `matches`) is dropped, so the
# review surface never sees sum-of-parts noise. The -filtered.json output is
# what the editorial basis reads (records pass through verbatim, so the merger
# annotation survives). See src/tools/filter_supplement_phrases.py.
data/supplement-wordnet-filtered.json data/supplement-wiktionary-filtered.json: $(SRC_TOOLS)/filter_supplement_phrases.py $(SRC_TOOLS)/detect_phrase_divergence.py $(SRC_TOOLS)/ipa_to_shavian.py data/supplement-wordnet-collapsed.json data/supplement-wiktionary-collapsed.json data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json external/readlex/readlex.json data/patches/patches.jsonl
	@echo "Pruning sum-of-parts phrase candidates..."
	$(RUN) python3 $(SRC_TOOLS)/filter_supplement_phrases.py

###########################################
# Merged readlex (combines original + supplements)
###########################################

SUPPLEMENT_DEPS := data/supplement-wordnet-filtered.json data/supplement-wiktionary-filtered.json

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
