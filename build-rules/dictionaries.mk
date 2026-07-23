# Dictionary building rules
# Generates dictionary XML files and builds Dictionary.app bundles

###########################################
# Cache generation
###########################################

# Comprehensive WordNet cache (auto-builds if missing, ~2 min)
$(WORDNET_CACHE): $(SRC_TOOLS)/build_wordnet_cache.py $(SRC_DICTIONARIES)/wordnet_dialect.py $(wildcard external/english-wordnet/src/yaml/*.yaml)
	@echo "Building comprehensive WordNet cache from YAML..."
	@echo "This is expensive preprocessing (~2 minutes)."
	@mkdir -p data
	$(RUN) $(SRC_TOOLS)/build_wordnet_cache.py
	@echo "✓ WordNet cache generated: $(WORDNET_CACHE)"
	@echo "  Note: This file is large and not committed to git."

# Transliteration caches (auto-build if missing, requires shave tool)
data/definitions-shavian-gb.json: $(SRC_DICTIONARIES)/build_definition_caches.py $(READLEX_PATH)
	@echo "Building Shavian definition cache (GB)..."
	@echo "This requires the shave tool."
	@mkdir -p data
	$(RUN) $(SRC_DICTIONARIES)/build_definition_caches.py --gb

data/definitions-shavian-us.json: $(SRC_DICTIONARIES)/build_definition_caches.py $(READLEX_PATH)
	@echo "Building Shavian definition cache (US)..."
	@echo "This requires the shave tool."
	@mkdir -p data
	$(RUN) $(SRC_DICTIONARIES)/build_definition_caches.py --us

###########################################
# Definition transliteration coverage gap
###########################################
# The base cache above only transliterates WordNet single-word synset senses. The
# gap-fill pass ADDS a Shavian transliteration for every remaining English gloss
# (the WordNet senses the base pass missed + the whole Wiktionary def corpus),
# NEVER re-transliterating an existing key (rewriting an entry would orphan the
# owner's definition-correction patches; gap-fill only). shave itself is
# deterministic — see project_shave_nondeterminism.md — the freeze protects the
# patch anchors, not against drift.
#
# A stamp file records completion: the gap tool rewrites the shavian-*.json files in
# place, so it cannot be its own Make output without a rebuild loop. The stamp depends
# on the base caches (ORDER-ONLY, via '|': the gap augments them but must never force
# a base re-shave) and on the gap tool + its gloss sources; touching any of those
# re-runs the gap-fill.
DEFINITIONS_GAP_STAMP := data/.definitions-gap.stamp

$(DEFINITIONS_GAP_STAMP): $(SRC_TOOLS)/transliterate_definitions_gap.py \
                          $(WORDNET_CACHE) \
                          data/definitions-wiktionary.json \
                          external/readlex/readlex.json \
                          | data/definitions-shavian-gb.json data/definitions-shavian-us.json
	@echo "Filling definition transliteration coverage gap (GB & US)..."
	@echo "This requires the shave tool."
	$(RUN) $(SRC_TOOLS)/transliterate_definitions_gap.py
	@touch $@

.PHONY: definitions-gap
definitions-gap: $(DEFINITIONS_GAP_STAMP)
	@echo "✓ Definition transliteration coverage gap filled"

# Latin definition files with dialect-specific spelling (auto-build if missing)
data/definitions-latin-gb.json data/definitions-latin-us.json: $(SRC_TOOLS)/generate_dialect_definitions.py $(WORDNET_CACHE) data/definitions-shavian-gb.json
	@echo "Building dialect-specific Latin definitions (GB & US)..."
	@mkdir -p data
	$(RUN) $(SRC_TOOLS)/generate_dialect_definitions.py

# Phony targets to explicitly regenerate caches
.PHONY: wordnet-cache transliterations
wordnet-cache:
	@echo "Rebuilding comprehensive WordNet cache..."
	@rm -f $(WORDNET_CACHE)
	@$(MAKE) $(WORDNET_CACHE)

.PHONY: transliterations-gb transliterations-us
transliterations-gb:
	@echo "Rebuilding Shavian GB transliteration cache..."
	@mkdir -p data
	$(RUN) $(SRC_DICTIONARIES)/build_definition_caches.py --gb --force
	@echo "✓ GB transliteration cache rebuilt"

transliterations-us:
	@echo "Rebuilding Shavian US transliteration cache..."
	@mkdir -p data
	$(RUN) $(SRC_DICTIONARIES)/build_definition_caches.py --us --force
	@echo "✓ US transliteration cache rebuilt"

transliterations: transliterations-gb transliterations-us
	@echo "Filling definition transliteration coverage gap after base rebuild..."
	$(RUN) $(SRC_TOOLS)/transliterate_definitions_gap.py
	@touch $(DEFINITIONS_GAP_STAMP)
	@echo "✓ All transliteration caches rebuilt (base + coverage gap)"

###########################################
# XML generation
###########################################

DICT_SCRIPT := $(SRC_DICTIONARIES)/generate_dictionaries.py

# GB dictionary XMLs
$(BUILD_DICT_XML)/shavian-english-gb.xml: $(READLEX_PATH) $(DICT_SCRIPT) $(WORDNET_CACHE) data/definitions-latin-gb.json | $(BUILD_DICT_XML)
	@echo "Generating Shavian-English XML (GB)..."
	$(RUN) $(DICT_SCRIPT) --gb --dict shavian-english

$(BUILD_DICT_XML)/english-shavian-gb.xml: $(READLEX_PATH) $(DICT_SCRIPT) $(WORDNET_CACHE) data/definitions-shavian-gb.json $(DEFINITIONS_GAP_STAMP) | $(BUILD_DICT_XML)
	@echo "Generating English-Shavian XML (GB)..."
	$(RUN) $(DICT_SCRIPT) --gb --dict english-shavian

$(BUILD_DICT_XML)/shavian-shavian-gb.xml: $(READLEX_PATH) $(DICT_SCRIPT) $(WORDNET_CACHE) data/definitions-shavian-gb.json $(DEFINITIONS_GAP_STAMP) | $(BUILD_DICT_XML)
	@echo "Generating Shavian-Shavian XML (GB)..."
	$(RUN) $(DICT_SCRIPT) --gb --dict shavian-shavian

# US dictionary XMLs
$(BUILD_DICT_XML)/shavian-english-us.xml: $(READLEX_PATH) $(DICT_SCRIPT) $(WORDNET_CACHE) data/definitions-latin-us.json | $(BUILD_DICT_XML)
	@echo "Generating Shavian-English XML (US)..."
	$(RUN) $(DICT_SCRIPT) --us --dict shavian-english

$(BUILD_DICT_XML)/english-shavian-us.xml: $(READLEX_PATH) $(DICT_SCRIPT) $(WORDNET_CACHE) data/definitions-shavian-us.json $(DEFINITIONS_GAP_STAMP) | $(BUILD_DICT_XML)
	@echo "Generating English-Shavian XML (US)..."
	$(RUN) $(DICT_SCRIPT) --us --dict english-shavian

$(BUILD_DICT_XML)/shavian-shavian-us.xml: $(READLEX_PATH) $(DICT_SCRIPT) $(WORDNET_CACHE) data/definitions-shavian-us.json $(DEFINITIONS_GAP_STAMP) | $(BUILD_DICT_XML)
	@echo "Generating Shavian-Shavian XML (US)..."
	$(RUN) $(DICT_SCRIPT) --us --dict shavian-shavian

###########################################
# Dictionary bundles
###########################################

# GB dictionary bundles
$(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-gb.dictionary: $(BUILD_DICT_XML)/shavian-english-gb.xml | $(BUILD_DICT_BUNDLES)
	@echo "Building Shavian-English dictionary (GB)..."
	$(RUN) $(BUILD_DICT_BUNDLE) shavian-english gb $(VERSION) $< $(BUILD_DICT_BUNDLES)

$(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-gb.dictionary: $(BUILD_DICT_XML)/english-shavian-gb.xml | $(BUILD_DICT_BUNDLES)
	@echo "Building English-Shavian dictionary (GB)..."
	$(RUN) $(BUILD_DICT_BUNDLE) english-shavian gb $(VERSION) $< $(BUILD_DICT_BUNDLES)

$(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-gb.dictionary: $(BUILD_DICT_XML)/shavian-shavian-gb.xml | $(BUILD_DICT_BUNDLES)
	@echo "Building Shavian-Shavian dictionary (GB)..."
	$(RUN) $(BUILD_DICT_BUNDLE) shavian-shavian gb $(VERSION) $< $(BUILD_DICT_BUNDLES)

# US dictionary bundles
$(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-us.dictionary: $(BUILD_DICT_XML)/shavian-english-us.xml | $(BUILD_DICT_BUNDLES)
	@echo "Building Shavian-English dictionary (US)..."
	$(RUN) $(BUILD_DICT_BUNDLE) shavian-english us $(VERSION) $< $(BUILD_DICT_BUNDLES)

$(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-us.dictionary: $(BUILD_DICT_XML)/english-shavian-us.xml | $(BUILD_DICT_BUNDLES)
	@echo "Building English-Shavian dictionary (US)..."
	$(RUN) $(BUILD_DICT_BUNDLE) english-shavian us $(VERSION) $< $(BUILD_DICT_BUNDLES)

$(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-us.dictionary: $(BUILD_DICT_XML)/shavian-shavian-us.xml | $(BUILD_DICT_BUNDLES)
	@echo "Building Shavian-Shavian dictionary (US)..."
	$(RUN) $(BUILD_DICT_BUNDLE) shavian-shavian us $(VERSION) $< $(BUILD_DICT_BUNDLES)

###########################################
# Convenience targets
###########################################

.PHONY: dictionaries
dictionaries: dictionaries-gb dictionaries-us
	@echo "All dictionaries (GB & US) built successfully!"

.PHONY: dictionaries-gb
dictionaries-gb: $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-gb.dictionary \
                 $(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-gb.dictionary \
                 $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-gb.dictionary
	@echo "All GB dictionaries built successfully!"

.PHONY: dictionaries-us
dictionaries-us: $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-us.dictionary \
                 $(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-us.dictionary \
                 $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-us.dictionary
	@echo "All US dictionaries built successfully!"

# Individual dictionary type targets
.PHONY: shavian-english shavian-english-gb shavian-english-us
shavian-english: shavian-english-gb shavian-english-us
	@echo "Shavian-English dictionaries (GB & US) built successfully!"

shavian-english-gb: $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-gb.dictionary
	@echo "Shavian-English dictionary (GB) built successfully!"

shavian-english-us: $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-us.dictionary
	@echo "Shavian-English dictionary (US) built successfully!"

.PHONY: english-shavian english-shavian-gb english-shavian-us
english-shavian: english-shavian-gb english-shavian-us
	@echo "English-Shavian dictionaries (GB & US) built successfully!"

english-shavian-gb: $(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-gb.dictionary
	@echo "English-Shavian dictionary (GB) built successfully!"

english-shavian-us: $(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-us.dictionary
	@echo "English-Shavian dictionary (US) built successfully!"

.PHONY: shavian-shavian shavian-shavian-gb shavian-shavian-us
shavian-shavian: shavian-shavian-gb shavian-shavian-us
	@echo "Shavian-Shavian dictionaries (GB & US) built successfully!"

shavian-shavian-gb: $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-gb.dictionary
	@echo "Shavian-Shavian dictionary (GB) built successfully!"

shavian-shavian-us: $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-us.dictionary
	@echo "Shavian-Shavian dictionary (US) built successfully!"
