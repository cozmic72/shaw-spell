# Spellcheck rules - Hunspell dictionaries and spell server
# Generates Hunspell .dic/.aff files and builds the NSSpellServer service

###########################################
# Hunspell Dictionary Generation
###########################################

# Hunspell dictionary paths in organized structure
HUNSPELL_GB = $(BUILD_HUNSPELL)/io.joro.shaw-spell.shavian-gb.dic
HUNSPELL_US = $(BUILD_HUNSPELL)/io.joro.shaw-spell.shavian-us.dic
HUNSPELL_EN_GB = $(BUILD_HUNSPELL)/io.joro.shaw-spell.en_GB.dic
HUNSPELL_EN_US = $(BUILD_HUNSPELL)/io.joro.shaw-spell.en_US.dic

# All Hunspell files (including .aff counterparts)
HUNSPELL_FILES = $(HUNSPELL_GB) $(BUILD_HUNSPELL)/io.joro.shaw-spell.shavian-gb.aff \
                 $(HUNSPELL_US) $(BUILD_HUNSPELL)/io.joro.shaw-spell.shavian-us.aff \
                 $(HUNSPELL_EN_GB) $(BUILD_HUNSPELL)/io.joro.shaw-spell.en_GB.aff \
                 $(HUNSPELL_EN_US) $(BUILD_HUNSPELL)/io.joro.shaw-spell.en_US.aff

# Shavian Hunspell dictionaries (both GB and US generated together)
# Pick GB .dic as canonical target, others depend on it
$(HUNSPELL_GB): $(READLEX_PATH) $(SRC_SERVER)/generate_spellcheck.py | $(BUILD_HUNSPELL)
	@echo "Generating Shavian Hunspell dictionaries..."
	@# Script currently writes to build/ - need to update it to write to BUILD_HUNSPELL
	@# For now, generate to build/ and move
	$(RUN) $(SRC_SERVER)/generate_spellcheck.py
	@mv build/io.joro.shaw-spell.shavian-gb.dic build/io.joro.shaw-spell.shavian-gb.aff $(BUILD_HUNSPELL)/
	@mv build/io.joro.shaw-spell.shavian-us.dic build/io.joro.shaw-spell.shavian-us.aff $(BUILD_HUNSPELL)/
	@echo "✓ Shavian Hunspell dictionaries generated"

# Other files generated alongside GB .dic
$(BUILD_HUNSPELL)/io.joro.shaw-spell.shavian-gb.aff $(HUNSPELL_US) $(BUILD_HUNSPELL)/io.joro.shaw-spell.shavian-us.aff: $(HUNSPELL_GB)

# Latin Hunspell dictionaries (from WordNet)
# Each generates a .dic and .aff file - use .dic as canonical target
$(HUNSPELL_EN_GB): $(SRC_DICTIONARIES)/generate_hunspell.py $(WORDNET_CACHE) | $(BUILD_HUNSPELL)
	@echo "Generating English (GB) Hunspell dictionary from WordNet..."
	@# Script currently writes to build/ - need to update it
	$(RUN) $(SRC_DICTIONARIES)/generate_hunspell.py --dialect gb
	@mv build/io.joro.shaw-spell.en_GB.dic build/io.joro.shaw-spell.en_GB.aff $(BUILD_HUNSPELL)/
	@echo "✓ English (GB) Hunspell dictionary generated"

# .aff file generated alongside .dic
$(BUILD_HUNSPELL)/io.joro.shaw-spell.en_GB.aff: $(HUNSPELL_EN_GB)

$(HUNSPELL_EN_US): $(SRC_DICTIONARIES)/generate_hunspell.py $(WORDNET_CACHE) | $(BUILD_HUNSPELL)
	@echo "Generating English (US) Hunspell dictionary from WordNet..."
	$(RUN) $(SRC_DICTIONARIES)/generate_hunspell.py --dialect us
	@mv build/io.joro.shaw-spell.en_US.dic build/io.joro.shaw-spell.en_US.aff $(BUILD_HUNSPELL)/
	@echo "✓ English (US) Hunspell dictionary generated"

# .aff file generated alongside .dic
$(BUILD_HUNSPELL)/io.joro.shaw-spell.en_US.aff: $(HUNSPELL_EN_US)

###########################################
# Spell Server
###########################################

# Spell server bundle - the actual executable inside the service bundle
SPELLSERVER_BUNDLE = $(BUILD_ROOT)/Shaw-Spell.service/Contents/MacOS/Shaw-Spell

$(SPELLSERVER_BUNDLE): $(wildcard $(SRC_SERVER)/*.swift) $(wildcard $(SRC_SERVER)/*.h) \
                       $(SRC_SERVER)/Makefile $(SRC_SERVER)/Info.plist \
                       $(HUNSPELL_FILES)
	@echo "Building spell server..."
	@cd $(SRC_SERVER) && $(MAKE)

###########################################
# Convenience Targets
###########################################

.PHONY: spellcheck spellserver hunspell

spellcheck: $(HUNSPELL_FILES)
	@echo "All Hunspell dictionaries (Shavian & Latin) built successfully!"

hunspell: $(HUNSPELL_FILES)
	@echo "All Hunspell dictionaries built in $(BUILD_HUNSPELL)/"

spellserver: $(SPELLSERVER_BUNDLE)
	@echo "Spell server built successfully!"
	@echo "Location: build/Shaw-Spell.service/"
