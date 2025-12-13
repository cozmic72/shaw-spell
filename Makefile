# Makefile for Shaw Spell
# Provides incremental builds for dictionaries and spell checker

.PHONY: all clean clean-cache clean-all install help spellcheck spellserver installer dmg transliterations shavian-english english-shavian shavian-shavian
.DEFAULT_GOAL := help

# Configuration
DIALECT ?= gb
READLEX_PATH = external/readlex/readlex.json
WORDNET_XML = build/english-wordnet-2024.xml
WORDNET_PATH = build/wordnet-definitions.json

# Source files
CACHE_SCRIPT = src/dictionaries/build_definition_caches.py
DICT_SCRIPT = src/dictionaries/generate_dictionaries.py

# Generated files
CACHE_FILE = data/definitions-shavian-$(DIALECT).json
XML_SHAVIAN_ENGLISH = build/shavian-english-$(DIALECT).xml
XML_ENGLISH_SHAVIAN = build/english-shavian-$(DIALECT).xml
XML_SHAVIAN_SHAVIAN = build/shavian-shavian-$(DIALECT).xml

# Dictionary bundles (current dialect)
DICT_SHAVIAN_ENGLISH = build/dictionaries/Shavian-English-$(DIALECT).dictionary
DICT_ENGLISH_SHAVIAN = build/dictionaries/English-Shavian-$(DIALECT).dictionary
DICT_SHAVIAN_SHAVIAN = build/dictionaries/Shavian-$(DIALECT).dictionary

# Dictionary bundles (both dialects for installer)
DICT_SHAVIAN_ENGLISH_GB = build/dictionaries/Shavian-English-gb.dictionary
DICT_ENGLISH_SHAVIAN_GB = build/dictionaries/English-Shavian-gb.dictionary
DICT_SHAVIAN_SHAVIAN_GB = build/dictionaries/Shavian-gb.dictionary
DICT_SHAVIAN_ENGLISH_US = build/dictionaries/Shavian-English-us.dictionary
DICT_ENGLISH_SHAVIAN_US = build/dictionaries/English-Shavian-us.dictionary
DICT_SHAVIAN_SHAVIAN_US = build/dictionaries/Shavian-us.dictionary

# Dictionary source directories
DICT_SHAVIAN_ENGLISH_DIR = src/dictionaries/shavian-english
DICT_ENGLISH_SHAVIAN_DIR = src/dictionaries/english-shavian
DICT_SHAVIAN_SHAVIAN_DIR = src/dictionaries/shavian-shavian

# Determine which dictionaries need the cache
CACHE_DEPS = $(READLEX_PATH) $(WORDNET_PATH) $(CACHE_SCRIPT)

###########################################
# Help
###########################################

help:
	@echo "Shaw Spell Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all                 Build dictionaries and spell checker"
	@echo "  transliterations    Build Shavian transliteration caches (GB & US)"
	@echo "  shavian-english     Build Shavian-English dictionary"
	@echo "  english-shavian     Build English-Shavian dictionary"
	@echo "  shavian-shavian     Build Shavian-Shavian dictionary"
	@echo "  spellcheck          Build Hunspell dictionaries (GB & US)"
	@echo "  spellserver         Build NSSpellServer service"
	@echo "  installer           Build graphical installer app"
	@echo "  dmg                 Create installer DMG for distribution"
	@echo "  install             Install all components"
	@echo "  clean               Remove build artifacts"
	@echo "  clean-cache         Remove definition caches"
	@echo "  clean-all           Remove all build artifacts and caches"
	@echo ""
	@echo "Options:"
	@echo "  DIALECT=gb          Build British English variant (default)"
	@echo "  DIALECT=us          Build American English variant"
	@echo ""
	@echo "Examples:"
	@echo "  make                         Build all components (GB)"
	@echo "  make DIALECT=us all          Build all components (US)"
	@echo "  make transliterations        Build transliteration caches"
	@echo "  make install                 Build and install everything"
	@echo "  make spellcheck              Build Hunspell dictionaries only"

###########################################
# WordNet XML generation and parsing
###########################################

# Generate WordNet XML from YAML sources in submodule
$(WORDNET_XML): external/english-wordnet/src/yaml/*.yaml
	@echo "Generating WordNet XML from YAML sources..."
	@mkdir -p build
	@python3 -c "import yaml" || (echo "Error: PyYAML not installed. Install with: pip3 install -r requirements.txt" && exit 1)
	@cd external/english-wordnet && python3 scripts/from_yaml.py
	@mv external/english-wordnet/wn.xml $(WORDNET_XML)
	@echo "WordNet XML generated: $(WORDNET_XML)"

# Parse WordNet XML to JSON format for dictionary generation
$(WORDNET_PATH): $(WORDNET_XML) src/dictionaries/parse_wordnet.py
	@echo "Parsing WordNet definitions..."
	@mkdir -p build
	src/dictionaries/parse_wordnet.py

###########################################
# Cache generation
###########################################

# Current dialect rule
$(CACHE_FILE): $(CACHE_DEPS)
	@echo "Building Shavian definition cache ($(DIALECT))..."
	@mkdir -p data
	$(CACHE_SCRIPT) --$(DIALECT)

# Explicit rules for both dialects
data/definitions-shavian-gb.json: $(CACHE_DEPS)
	@echo "Building Shavian definition cache (GB)..."
	@mkdir -p data
	$(CACHE_SCRIPT) --gb

data/definitions-shavian-us.json: $(CACHE_DEPS)
	@echo "Building Shavian definition cache (US)..."
	@mkdir -p data
	$(CACHE_SCRIPT) --us

###########################################
# XML generation
###########################################

# Current dialect rules
$(XML_SHAVIAN_ENGLISH): $(READLEX_PATH) $(WORDNET_PATH) $(DICT_SCRIPT)
	@echo "Generating Shavian-English XML ($(DIALECT))..."
	@mkdir -p build
	$(DICT_SCRIPT) --$(DIALECT) --dict shavian-english

$(XML_ENGLISH_SHAVIAN): $(CACHE_FILE) $(READLEX_PATH) $(DICT_SCRIPT)
	@echo "Generating English-Shavian XML ($(DIALECT))..."
	@mkdir -p build
	$(DICT_SCRIPT) --$(DIALECT) --dict english-shavian

$(XML_SHAVIAN_SHAVIAN): $(CACHE_FILE) $(READLEX_PATH) $(DICT_SCRIPT)
	@echo "Generating Shavian-Shavian XML ($(DIALECT))..."
	@mkdir -p build
	$(DICT_SCRIPT) --$(DIALECT) --dict shavian-shavian

# Explicit rules for GB XML files
build/shavian-english-gb.xml: $(READLEX_PATH) $(WORDNET_PATH) $(DICT_SCRIPT)
	@echo "Generating Shavian-English XML (GB)..."
	@mkdir -p build
	$(DICT_SCRIPT) --gb --dict shavian-english

build/english-shavian-gb.xml: data/definitions-shavian-gb.json $(READLEX_PATH) $(DICT_SCRIPT)
	@echo "Generating English-Shavian XML (GB)..."
	@mkdir -p build
	$(DICT_SCRIPT) --gb --dict english-shavian

build/shavian-shavian-gb.xml: data/definitions-shavian-gb.json $(READLEX_PATH) $(DICT_SCRIPT)
	@echo "Generating Shavian-Shavian XML (GB)..."
	@mkdir -p build
	$(DICT_SCRIPT) --gb --dict shavian-shavian

# Explicit rules for US XML files
build/shavian-english-us.xml: $(READLEX_PATH) $(WORDNET_PATH) $(DICT_SCRIPT)
	@echo "Generating Shavian-English XML (US)..."
	@mkdir -p build
	$(DICT_SCRIPT) --us --dict shavian-english

build/english-shavian-us.xml: data/definitions-shavian-us.json $(READLEX_PATH) $(DICT_SCRIPT)
	@echo "Generating English-Shavian XML (US)..."
	@mkdir -p build
	$(DICT_SCRIPT) --us --dict english-shavian

build/shavian-shavian-us.xml: data/definitions-shavian-us.json $(READLEX_PATH) $(DICT_SCRIPT)
	@echo "Generating Shavian-Shavian XML (US)..."
	@mkdir -p build
	$(DICT_SCRIPT) --us --dict shavian-shavian

###########################################
# Dictionary building
###########################################

# Current dialect rules
$(DICT_SHAVIAN_ENGLISH): $(XML_SHAVIAN_ENGLISH) $(DICT_SHAVIAN_ENGLISH_DIR)/ShavianEnglish.css $(DICT_SHAVIAN_ENGLISH_DIR)/ShavianEnglish.plist
	@echo "Building Shavian-English dictionary ($(DIALECT))..."
	@cd $(DICT_SHAVIAN_ENGLISH_DIR) && $(MAKE) DIALECT=$(DIALECT)

$(DICT_ENGLISH_SHAVIAN): $(XML_ENGLISH_SHAVIAN) $(DICT_ENGLISH_SHAVIAN_DIR)/EnglishShavian.css
	@echo "Building English-Shavian dictionary ($(DIALECT))..."
	@cd $(DICT_ENGLISH_SHAVIAN_DIR) && $(MAKE) DIALECT=$(DIALECT)

$(DICT_SHAVIAN_SHAVIAN): $(XML_SHAVIAN_SHAVIAN) $(DICT_SHAVIAN_SHAVIAN_DIR)/ShavianShavian.css
	@echo "Building Shavian-Shavian dictionary ($(DIALECT))..."
	@cd $(DICT_SHAVIAN_SHAVIAN_DIR) && $(MAKE) DIALECT=$(DIALECT)

# Explicit rules for GB dictionaries
$(DICT_SHAVIAN_ENGLISH_GB): build/shavian-english-gb.xml $(DICT_SHAVIAN_ENGLISH_DIR)/ShavianEnglish.css $(DICT_SHAVIAN_ENGLISH_DIR)/ShavianEnglish.plist
	@echo "Building Shavian-English dictionary (GB)..."
	@cd $(DICT_SHAVIAN_ENGLISH_DIR) && $(MAKE) DIALECT=gb

$(DICT_ENGLISH_SHAVIAN_GB): build/english-shavian-gb.xml $(DICT_ENGLISH_SHAVIAN_DIR)/EnglishShavian.css
	@echo "Building English-Shavian dictionary (GB)..."
	@cd $(DICT_ENGLISH_SHAVIAN_DIR) && $(MAKE) DIALECT=gb

$(DICT_SHAVIAN_SHAVIAN_GB): build/shavian-shavian-gb.xml $(DICT_SHAVIAN_SHAVIAN_DIR)/ShavianShavian.css
	@echo "Building Shavian-Shavian dictionary (GB)..."
	@cd $(DICT_SHAVIAN_SHAVIAN_DIR) && $(MAKE) DIALECT=gb

# Explicit rules for US dictionaries
$(DICT_SHAVIAN_ENGLISH_US): build/shavian-english-us.xml $(DICT_SHAVIAN_ENGLISH_DIR)/ShavianEnglish.css $(DICT_SHAVIAN_ENGLISH_DIR)/ShavianEnglish.plist
	@echo "Building Shavian-English dictionary (US)..."
	@cd $(DICT_SHAVIAN_ENGLISH_DIR) && $(MAKE) DIALECT=us

$(DICT_ENGLISH_SHAVIAN_US): build/english-shavian-us.xml $(DICT_ENGLISH_SHAVIAN_DIR)/EnglishShavian.css
	@echo "Building English-Shavian dictionary (US)..."
	@cd $(DICT_ENGLISH_SHAVIAN_DIR) && $(MAKE) DIALECT=us

$(DICT_SHAVIAN_SHAVIAN_US): build/shavian-shavian-us.xml $(DICT_SHAVIAN_SHAVIAN_DIR)/ShavianShavian.css
	@echo "Building Shavian-Shavian dictionary (US)..."
	@cd $(DICT_SHAVIAN_SHAVIAN_DIR) && $(MAKE) DIALECT=us

###########################################
# Spell checker building
###########################################

HUNSPELL_GB = build/shaw-gb.dic
HUNSPELL_US = build/shaw-us.dic
SPELLSERVER_BUNDLE = build/ShavianSpellServer.service

$(HUNSPELL_GB) $(HUNSPELL_US): $(READLEX_PATH) src/spellserver/generate_spellcheck.py
	@echo "Building Hunspell dictionaries..."
	@mkdir -p build
	src/spellserver/generate_spellcheck.py

$(SPELLSERVER_BUNDLE): src/spellserver/*.m src/spellserver/*.h src/spellserver/Makefile
	@echo "Building spell server..."
	@cd src/spellserver && $(MAKE)

spellcheck: $(HUNSPELL_GB) $(HUNSPELL_US)
	@echo "Hunspell dictionaries built successfully!"

spellserver: $(SPELLSERVER_BUNDLE)
	@echo "Spell server built successfully!"

installer: $(DICT_SHAVIAN_ENGLISH_GB) $(DICT_ENGLISH_SHAVIAN_GB) $(DICT_SHAVIAN_SHAVIAN_GB) \
           $(DICT_SHAVIAN_ENGLISH_US) $(DICT_ENGLISH_SHAVIAN_US) $(DICT_SHAVIAN_SHAVIAN_US) \
           spellcheck spellserver
	@echo "Building installer app..."
	@cd src/installer && $(MAKE)
	@echo "Installer app built successfully at: build/Install Shaw Spell.app"

dmg: installer
	@echo "Creating installer DMG..."
	@rm -rf build/dmg_staging
	@mkdir -p build/dmg_staging
	@cp -R "build/Install Shaw Spell.app" build/dmg_staging/
	@rm -f build/ShawSpellInstaller.dmg
	@hdiutil create -volname "Shaw Spell Installer" -srcfolder build/dmg_staging -ov -format UDZO build/ShawSpellInstaller.dmg
	@rm -rf build/dmg_staging
	@echo "DMG created at: build/ShawSpellInstaller.dmg"

###########################################
# High-level targets
###########################################

all: $(DICT_SHAVIAN_ENGLISH) $(DICT_ENGLISH_SHAVIAN) $(DICT_SHAVIAN_SHAVIAN) spellcheck spellserver
	@echo "All components ($(DIALECT)) built successfully!"

transliterations: data/definitions-shavian-gb.json data/definitions-shavian-us.json
	@echo "Transliterated definition caches built successfully!"
	@echo "  GB: data/definitions-shavian-gb.json"
	@echo "  US: data/definitions-shavian-us.json"

shavian-english: $(DICT_SHAVIAN_ENGLISH)
	@echo "Shavian-English dictionary ($(DIALECT)) built successfully!"

english-shavian: $(DICT_ENGLISH_SHAVIAN)
	@echo "English-Shavian dictionary ($(DIALECT)) built successfully!"

shavian-shavian: $(DICT_SHAVIAN_SHAVIAN)
	@echo "Shavian-Shavian dictionary ($(DIALECT)) built successfully!"

install: all
	@echo "Installing dictionaries ($(DIALECT)) to ~/Library/Dictionaries..."
	@cd $(DICT_SHAVIAN_ENGLISH_DIR) && $(MAKE) DIALECT=$(DIALECT) install
	@cd $(DICT_ENGLISH_SHAVIAN_DIR) && $(MAKE) DIALECT=$(DIALECT) install
	@cd $(DICT_SHAVIAN_SHAVIAN_DIR) && $(MAKE) DIALECT=$(DIALECT) install
	@echo "Installing Hunspell dictionaries to ~/Library/Spelling..."
	@mkdir -p ~/Library/Spelling
	@cp build/shaw-gb.* ~/Library/Spelling/ 2>/dev/null || true
	@cp build/shaw-us.* ~/Library/Spelling/ 2>/dev/null || true
	@echo "Installing spell server..."
	@cd src/spellserver && $(MAKE) install
	@echo ""
	@echo "Installation complete!"
	@echo "  - Dictionary.app: Please restart Dictionary.app"
	@echo "  - Spell Server: Running via LaunchAgent"

###########################################
# Cleaning
###########################################

clean:
	@echo "Cleaning build artifacts..."
	@rm -rf build/
	@cd src/installer && $(MAKE) clean 2>/dev/null || true
	@echo "Clean complete"

clean-cache:
	@echo "Cleaning definition caches..."
	@rm -f data/definitions-shavian-gb.json
	@rm -f data/definitions-shavian-us.json
	@rm -f data/definitions-shavian.json
	@rm -f build/wordnet-definitions.json
	@echo "Cache clean complete"

clean-all: clean clean-cache
	@echo "Complete clean finished"
