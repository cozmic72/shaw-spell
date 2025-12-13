# Makefile for Shaw Dict
# Provides incremental builds for dictionaries

.PHONY: all clean clean-cache clean-all install help
.DEFAULT_GOAL := help

# Configuration
DIALECT ?= gb
READLEX_PATH = ../shavian-info/readlex/readlex.json
WORDNET_PATH = build/wordnet-definitions.json

# Source files
CACHE_SCRIPT = src/build_definition_caches.py
DICT_SCRIPT = src/generate_dictionaries.py

# Generated files
CACHE_FILE = data/definitions-shavian-$(DIALECT).json
XML_SHAVIAN_ENGLISH = build/shavian-english-$(DIALECT).xml
XML_ENGLISH_SHAVIAN = build/english-shavian-$(DIALECT).xml
XML_SHAVIAN_SHAVIAN = build/shavian-shavian-$(DIALECT).xml

# Dictionary bundles
DICT_SHAVIAN_ENGLISH = dictionaries/shavian-english/objects-$(DIALECT)/Shavian-English-$(DIALECT).dictionary
DICT_ENGLISH_SHAVIAN = dictionaries/english-shavian/objects-$(DIALECT)/English-Shavian-$(DIALECT).dictionary
DICT_SHAVIAN_SHAVIAN = dictionaries/shavian-shavian/objects-$(DIALECT)/Shavian-$(DIALECT).dictionary

# Determine which dictionaries need the cache
CACHE_DEPS = $(READLEX_PATH) $(WORDNET_PATH) $(CACHE_SCRIPT)

###########################################
# Help
###########################################

help:
	@echo "Shaw Dict Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all                 Build all dictionaries (incremental)"
	@echo "  shavian-english     Build Shavian-English dictionary"
	@echo "  english-shavian     Build English-Shavian dictionary"
	@echo "  shavian-shavian     Build Shavian-Shavian dictionary"
	@echo "  install             Install all built dictionaries"
	@echo "  clean               Remove build artifacts"
	@echo "  clean-cache         Remove definition caches"
	@echo "  clean-all           Remove all build artifacts and caches"
	@echo ""
	@echo "Options:"
	@echo "  DIALECT=gb          Build British English variant (default)"
	@echo "  DIALECT=us          Build American English variant"
	@echo ""
	@echo "Examples:"
	@echo "  make                Build all dictionaries (GB)"
	@echo "  make DIALECT=us     Build all dictionaries (US)"
	@echo "  make install        Build and install (GB)"
	@echo "  make DIALECT=us install  Build and install (US)"

###########################################
# Cache generation
###########################################

$(CACHE_FILE): $(CACHE_DEPS)
	@echo "Building Shavian definition cache ($(DIALECT))..."
	@mkdir -p data
	$(CACHE_SCRIPT) --$(DIALECT)

###########################################
# XML generation
###########################################

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

###########################################
# Dictionary building
###########################################

$(DICT_SHAVIAN_ENGLISH): $(XML_SHAVIAN_ENGLISH) dictionaries/shavian-english/ShavianEnglish.css dictionaries/shavian-english/ShavianEnglish.plist
	@echo "Building Shavian-English dictionary ($(DIALECT))..."
	@cd dictionaries/shavian-english && $(MAKE) DIALECT=$(DIALECT)

$(DICT_ENGLISH_SHAVIAN): $(XML_ENGLISH_SHAVIAN) dictionaries/english-shavian/EnglishShavian.css
	@echo "Building English-Shavian dictionary ($(DIALECT))..."
	@cd dictionaries/english-shavian && $(MAKE) DIALECT=$(DIALECT)

$(DICT_SHAVIAN_SHAVIAN): $(XML_SHAVIAN_SHAVIAN) dictionaries/shavian-shavian/ShavianShavian.css
	@echo "Building Shavian-Shavian dictionary ($(DIALECT))..."
	@cd dictionaries/shavian-shavian && $(MAKE) DIALECT=$(DIALECT)

###########################################
# High-level targets
###########################################

all: $(DICT_SHAVIAN_ENGLISH) $(DICT_ENGLISH_SHAVIAN) $(DICT_SHAVIAN_SHAVIAN)
	@echo "All dictionaries ($(DIALECT)) built successfully!"

shavian-english: $(DICT_SHAVIAN_ENGLISH)
	@echo "Shavian-English dictionary ($(DIALECT)) built successfully!"

english-shavian: $(DICT_ENGLISH_SHAVIAN)
	@echo "English-Shavian dictionary ($(DIALECT)) built successfully!"

shavian-shavian: $(DICT_SHAVIAN_SHAVIAN)
	@echo "Shavian-Shavian dictionary ($(DIALECT)) built successfully!"

install: all
	@echo "Installing dictionaries ($(DIALECT)) to ~/Library/Dictionaries..."
	@cd dictionaries/shavian-english && $(MAKE) DIALECT=$(DIALECT) install
	@cd dictionaries/english-shavian && $(MAKE) DIALECT=$(DIALECT) install
	@cd dictionaries/shavian-shavian && $(MAKE) DIALECT=$(DIALECT) install
	@echo "Installation complete! Please restart Dictionary.app."

###########################################
# Cleaning
###########################################

clean:
	@echo "Cleaning build artifacts..."
	@rm -rf build/*.xml
	@rm -rf dictionaries/*/objects
	@echo "Clean complete"

clean-cache:
	@echo "Cleaning definition caches..."
	@rm -f data/definitions-shavian-gb.json
	@rm -f data/definitions-shavian-us.json
	@rm -f data/definitions-shavian.json
	@echo "Cache clean complete"

clean-all: clean clean-cache
	@echo "Complete clean finished"
