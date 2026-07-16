# Supplement generation rules
# Generates supplementary dictionary data from WordNet and Wiktionary

###########################################
# Source data paths
###########################################

WIKTIONARY_JSONL := external/wiktionary/kaikki.org-dictionary-English.jsonl
WORDNET_YAML := external/english-wordnet/src/yaml

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
# Merged readlex (combines original + supplements)
###########################################

SUPPLEMENT_DEPS := data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json

# Merged readlex is now produced by applying the editorial patch store
# (data/patches/patches.jsonl) to upstream + supplements. The legacy
# generate_merged_readlex.py is retained on disk for reference but no longer
# on the build path.
$(READLEX_PATH): $(SRC_TOOLS)/apply_patches.py external/readlex/readlex.json $(SUPPLEMENT_DEPS) data/patches/patches.jsonl
	@echo "Applying editorial patches to produce merged readlex..."
	$(RUN) python3 $(SRC_TOOLS)/apply_patches.py

###########################################
# Editorial review
###########################################

.PHONY: editorial
editorial: $(SUPPLEMENT_DEPS)
	@echo "Updating editorial CSV files..."
	$(RUN) python3 $(SRC_TOOLS)/generate_editorial_csv.py

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
