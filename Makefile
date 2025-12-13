# Makefile for Shaw-Spell
# Provides incremental builds for dictionaries and spell checker

.PHONY: all clean clean-cache clean-all install uninstall help spellcheck spellserver transliterations shavian-english english-shavian shavian-shavian notarize staple wordnet-cache
.PHONY: shavian-english-gb shavian-english-us english-shavian-gb english-shavian-us shavian-shavian-gb shavian-shavian-us
.DEFAULT_GOAL := help

# Configuration
VERSION = 1.0-beta
export VERSION

READLEX_PATH = external/readlex/readlex.json
WORDNET_XML = build/english-wordnet-2024.xml
WORDNET_PATH = build/wordnet-definitions.json
WORDNET_CACHE = data/wordnet-comprehensive.json

# Load signing configuration if it exists
-include .signing-config

# Notarization configuration
# Set these in .signing-config or pass on the command line
# See .signing-config.example for the format
APPLE_ID ?=
TEAM_ID ?=
NOTARY_PASSWORD ?=

# Source files
CACHE_SCRIPT = src/dictionaries/build_definition_caches.py
DICT_SCRIPT = src/dictionaries/generate_dictionaries.py

# Dictionary bundles
DICT_SHAVIAN_ENGLISH_GB = build/dictionaries/Shaw-Spell-Shavian-English-gb.dictionary
DICT_ENGLISH_SHAVIAN_GB = build/dictionaries/Shaw-Spell-English-Shavian-gb.dictionary
DICT_SHAVIAN_SHAVIAN_GB = build/dictionaries/Shaw-Spell-Shavian-gb.dictionary
DICT_SHAVIAN_ENGLISH_US = build/dictionaries/Shaw-Spell-Shavian-English-us.dictionary
DICT_ENGLISH_SHAVIAN_US = build/dictionaries/Shaw-Spell-English-Shavian-us.dictionary
DICT_SHAVIAN_SHAVIAN_US = build/dictionaries/Shaw-Spell-Shavian-us.dictionary

# Dictionary source directories
DICT_DIR = src/dictionaries

# Determine which dictionaries need the cache
CACHE_DEPS = $(READLEX_PATH) $(WORDNET_PATH) $(CACHE_SCRIPT)

###########################################
# Help
###########################################

help:
	@echo "Shaw-Spell Build System"
	@echo ""
	@echo "Common targets:"
	@echo "  make                Build complete installer DMG"
	@echo "  make install        Build and install to ~/Library"
	@echo "  make notarize       Notarize DMG for distribution"
	@echo "  make clean          Remove build artifacts"
	@echo ""
	@echo "Build targets:"
	@echo "  installer           Build installer app only"
	@echo "  uninstaller-app     Build uninstaller app only"
	@echo "  dmg                 Build DMG (without notarization)"
	@echo "  spellcheck          Build all Hunspell dictionaries"
	@echo "  wordnet-cache       Build comprehensive WordNet cache (expensive)"
	@echo ""
	@echo "Cleanup targets:"
	@echo "  clean               Remove build artifacts"
	@echo "  clean-cache         Remove definition caches"
	@echo "  clean-all           Remove all build artifacts and caches"
	@echo "  uninstall           Remove installed components"

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

# Explicit rules for both dialects (no pattern rule to avoid conflicts)
data/definitions-shavian-gb.json: $(CACHE_DEPS)
	@echo "Building Shavian definition cache (GB)..."
	@mkdir -p data
	$(CACHE_SCRIPT) --gb

data/definitions-shavian-us.json: $(CACHE_DEPS)
	@echo "Building Shavian definition cache (US)..."
	@mkdir -p data
	$(CACHE_SCRIPT) --us

# Comprehensive WordNet cache (expensive preprocessing, separate from 'all')
$(WORDNET_CACHE): $(WORDNET_XML) src/tools/build_wordnet_cache.py src/dictionaries/wordnet_dialect.py
	@echo "Building comprehensive WordNet cache..."
	@echo "This is expensive preprocessing (~2 minutes)."
	@mkdir -p data
	src/tools/build_wordnet_cache.py

# Target to explicitly build the WordNet cache (not part of 'all')
wordnet-cache: $(WORDNET_CACHE)
	@echo "WordNet comprehensive cache built successfully!"

###########################################
# XML generation
###########################################

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

# Explicit rules for GB dictionaries
$(DICT_SHAVIAN_ENGLISH_GB): build/shavian-english-gb.xml
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-english DIALECT=gb

$(DICT_ENGLISH_SHAVIAN_GB): build/english-shavian-gb.xml
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=english-shavian DIALECT=gb

$(DICT_SHAVIAN_SHAVIAN_GB): build/shavian-shavian-gb.xml
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-shavian DIALECT=gb

# Explicit rules for US dictionaries
$(DICT_SHAVIAN_ENGLISH_US): build/shavian-english-us.xml
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-english DIALECT=us

$(DICT_ENGLISH_SHAVIAN_US): build/english-shavian-us.xml
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=english-shavian DIALECT=us

$(DICT_SHAVIAN_SHAVIAN_US): build/shavian-shavian-us.xml
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-shavian DIALECT=us

###########################################
# Spell checker building
###########################################

HUNSPELL_GB = build/io.joro.shaw-spell.shavian-gb.dic
HUNSPELL_US = build/io.joro.shaw-spell.shavian-us.dic
HUNSPELL_EN_GB = build/io.joro.shaw-spell.en_GB.dic
HUNSPELL_EN_US = build/io.joro.shaw-spell.en_US.dic
SPELLSERVER_BUNDLE = build/Shaw-Spell.service
SPELLSERVER_MARKER = build/.spellserver-built
INSTALLER_MARKER = build/.installer-built
UNINSTALLER_MARKER = build/.uninstaller-built
DMG_FILE = build/Shaw-Spell-$(VERSION).dmg

# Shavian Hunspell dictionaries
$(HUNSPELL_GB) $(HUNSPELL_US): $(READLEX_PATH) src/server/generate_spellcheck.py
	@echo "Building Shavian Hunspell dictionaries..."
	@mkdir -p build
	src/server/generate_spellcheck.py

# Latin Hunspell dictionaries (generated from WordNet)
$(HUNSPELL_EN_GB): $(WORDNET_CACHE) src/dictionaries/generate_hunspell.py
	@echo "Generating English (GB) Hunspell dictionary from WordNet..."
	@mkdir -p build
	src/dictionaries/generate_hunspell.py --dialect gb

$(HUNSPELL_EN_US): $(WORDNET_CACHE) src/dictionaries/generate_hunspell.py
	@echo "Generating English (US) Hunspell dictionary from WordNet..."
	@mkdir -p build
	src/dictionaries/generate_hunspell.py --dialect us

$(SPELLSERVER_MARKER): src/server/*.swift src/server/*.h src/server/Makefile src/server/Info.plist
	@echo "Building spell server..."
	@cd src/server && $(MAKE)

spellcheck: $(HUNSPELL_GB) $(HUNSPELL_US) $(HUNSPELL_EN_GB) $(HUNSPELL_EN_US)
	@echo "All Hunspell dictionaries (Shavian & Latin) built successfully!"

spellserver: $(SPELLSERVER_MARKER)
	@echo "Spell server built successfully!"

$(INSTALLER_MARKER): $(DICT_SHAVIAN_ENGLISH_GB) $(DICT_ENGLISH_SHAVIAN_GB) $(DICT_SHAVIAN_SHAVIAN_GB) \
                     $(DICT_SHAVIAN_ENGLISH_US) $(DICT_ENGLISH_SHAVIAN_US) $(DICT_SHAVIAN_SHAVIAN_US) \
                     $(HUNSPELL_GB) $(HUNSPELL_US) $(HUNSPELL_EN_GB) $(HUNSPELL_EN_US) \
                     $(SPELLSERVER_MARKER) \
                     src/installer/src/*.swift src/installer/src/Info.plist src/installer/resources/*.html
	@echo "Building installer app..."
	@cd src/installer && $(MAKE)

$(UNINSTALLER_MARKER): src/uninstaller/src/*.swift src/uninstaller/src/Info.plist src/uninstaller/Makefile
	@echo "Building uninstaller app..."
	@cd src/uninstaller && $(MAKE)

$(DMG_FILE): $(INSTALLER_MARKER) $(UNINSTALLER_MARKER) src/installer/dmg-template/DS_Store_template
	@echo "Creating installer DMG..."
	@rm -rf build/dmg_staging
	@mkdir -p build/dmg_staging
	@cp -R "build/Install Shaw-Spell.app" build/dmg_staging/
	@cp -R "build/Uninstall Shaw-Spell.app" build/dmg_staging/
	@rm -f build/Shaw-Spell-temp.dmg $(DMG_FILE)
	@echo "Creating temporary read-write DMG..."
	@hdiutil create -volname "Shaw-Spell $(VERSION)" -srcfolder build/dmg_staging -ov -format UDRW build/Shaw-Spell-temp.dmg
	@echo "Mounting temporary DMG..."
	@mkdir -p build/dmg_mount
	@hdiutil attach build/Shaw-Spell-temp.dmg -mountpoint build/dmg_mount -nobrowse
	@if [ -f src/installer/dmg-template/DS_Store_template ]; then \
		echo "Copying layout template..."; \
		cp src/installer/dmg-template/DS_Store_template "build/dmg_mount/.DS_Store"; \
	fi
	@echo "Unmounting temporary DMG..."
	@hdiutil detach build/dmg_mount
	@rmdir build/dmg_mount
	@echo "Converting to compressed read-only DMG..."
	@hdiutil convert build/Shaw-Spell-temp.dmg -format UDZO -o $(DMG_FILE)
	@rm build/Shaw-Spell-temp.dmg
	@echo "DMG created at: $(DMG_FILE)"
	@echo "Staging directory preserved at: build/dmg_staging/"

# Convenience targets
installer: $(INSTALLER_MARKER)
	@echo "Installer app built successfully at: build/Install Shaw-Spell.app"

uninstaller-app: $(UNINSTALLER_MARKER)
	@echo "Uninstaller app built successfully at: build/Uninstall Shaw-Spell.app"

dmg: $(DMG_FILE)

# Notarize the DMG with Apple
notarize: $(DMG_FILE)
	@if [ -z "$(APPLE_ID)" ] || [ -z "$(NOTARY_PASSWORD)" ] || [ -z "$(TEAM_ID)" ]; then \
		echo "Error: APPLE_ID, TEAM_ID, and NOTARY_PASSWORD must be set"; \
		echo ""; \
		echo "Option 1: Create .signing-config file (recommended)"; \
		echo "  cp .signing-config.example .signing-config"; \
		echo "  # Edit .signing-config with your credentials"; \
		echo ""; \
		echo "Option 2: Pass on command line"; \
		echo "  make notarize APPLE_ID=your@email.com TEAM_ID=XXXX NOTARY_PASSWORD=xxxx-xxxx-xxxx-xxxx"; \
		echo ""; \
		echo "See NOTARIZATION.md for detailed instructions."; \
		exit 1; \
	fi
	@echo "Submitting DMG to Apple for notarization..."
	@echo "This may take 1-15 minutes..."
	xcrun notarytool submit "$(DMG_FILE)" \
		--apple-id "$(APPLE_ID)" \
		--team-id "$(TEAM_ID)" \
		--password "$(NOTARY_PASSWORD)" \
		--wait
	@echo ""
	@echo "Notarization successful! Stapling ticket to DMG..."
	xcrun stapler staple "$(DMG_FILE)"
	@echo ""
	@echo "DMG is now notarized and stapled - ready for distribution!"
	@echo "File: $(DMG_FILE)"

# Staple the notarization ticket to the DMG
staple: $(DMG_FILE)
	@echo "Stapling notarization ticket to DMG..."
	xcrun stapler staple "$(DMG_FILE)"
	@echo ""
	@echo "DMG is now notarized and ready for distribution!"
	@echo "File: $(DMG_FILE)"

###########################################
# High-level targets
###########################################

all: $(DMG_FILE)
	@echo "All components built successfully!"
	@echo "DMG installer ready at: $(DMG_FILE)"

transliterations: data/definitions-shavian-gb.json data/definitions-shavian-us.json
	@echo "Transliterated definition caches built successfully!"
	@echo "  GB: data/definitions-shavian-gb.json"
	@echo "  US: data/definitions-shavian-us.json"

# Convenience targets (build both dialects)
shavian-english: $(DICT_SHAVIAN_ENGLISH_GB) $(DICT_SHAVIAN_ENGLISH_US)
	@echo "Shavian-English dictionaries (GB & US) built successfully!"

english-shavian: $(DICT_ENGLISH_SHAVIAN_GB) $(DICT_ENGLISH_SHAVIAN_US)
	@echo "English-Shavian dictionaries (GB & US) built successfully!"

shavian-shavian: $(DICT_SHAVIAN_SHAVIAN_GB) $(DICT_SHAVIAN_SHAVIAN_US)
	@echo "Shavian-Shavian dictionaries (GB & US) built successfully!"

# Explicit dialect targets
shavian-english-gb: $(DICT_SHAVIAN_ENGLISH_GB)
	@echo "Shavian-English dictionary (GB) built successfully!"

shavian-english-us: $(DICT_SHAVIAN_ENGLISH_US)
	@echo "Shavian-English dictionary (US) built successfully!"

english-shavian-gb: $(DICT_ENGLISH_SHAVIAN_GB)
	@echo "English-Shavian dictionary (GB) built successfully!"

english-shavian-us: $(DICT_ENGLISH_SHAVIAN_US)
	@echo "English-Shavian dictionary (US) built successfully!"

shavian-shavian-gb: $(DICT_SHAVIAN_SHAVIAN_GB)
	@echo "Shavian-Shavian dictionary (GB) built successfully!"

shavian-shavian-us: $(DICT_SHAVIAN_SHAVIAN_US)
	@echo "Shavian-Shavian dictionary (US) built successfully!"

install: all
	@echo "Installing dictionaries (GB & US) to ~/Library/Dictionaries..."
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-english DIALECT=gb install
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=english-shavian DIALECT=gb install
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-shavian DIALECT=gb install
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-english DIALECT=us install
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=english-shavian DIALECT=us install
	@cd $(DICT_DIR) && $(MAKE) DICT_TYPE=shavian-shavian DIALECT=us install
	@echo "Installing Hunspell dictionaries to ~/Library/Spelling..."
	@mkdir -p ~/Library/Spelling
	@cp build/io.joro.shaw-spell.shavian-gb.* ~/Library/Spelling/ 2>/dev/null || true
	@cp build/io.joro.shaw-spell.shavian-us.* ~/Library/Spelling/ 2>/dev/null || true
	@cp build/io.joro.shaw-spell.en_GB.* ~/Library/Spelling/ 2>/dev/null || true
	@cp build/io.joro.shaw-spell.en_US.* ~/Library/Spelling/ 2>/dev/null || true
	@echo "Installing spell server..."
	@cd src/server && $(MAKE) install
	@echo ""
	@echo "Installation complete!"
	@echo "  - Dictionary.app: Please restart Dictionary.app"
	@echo "  - Spell Server: Running via LaunchAgent"

uninstall:
	@./uninstall.sh

###########################################
# Cleaning
###########################################

clean:
	@echo "Cleaning build artifacts..."
	@# Preserve expensive-to-generate files
	@if [ -f "$(WORDNET_XML)" ]; then \
		cp "$(WORDNET_XML)" /tmp/wordnet-xml-backup.xml; \
	fi
	@rm -rf build/
	@if [ -f /tmp/wordnet-xml-backup.xml ]; then \
		mkdir -p build && mv /tmp/wordnet-xml-backup.xml "$(WORDNET_XML)"; \
	fi
	@cd src/installer && $(MAKE) clean 2>/dev/null || true
	@cd src/uninstaller && $(MAKE) clean 2>/dev/null || true
	@echo "Clean complete"

clean-cache:
	@echo "Cleaning definition caches and expensive generated files..."
	@rm -f data/definitions-shavian-gb.json
	@rm -f data/definitions-shavian-us.json
	@rm -f data/definitions-shavian.json
	@rm -f build/wordnet-definitions.json
	@rm -f "$(WORDNET_XML)"
	@rm -f "$(WORDNET_CACHE)"
	@echo "Cache clean complete"

clean-all: clean clean-cache
	@echo "Complete clean finished"
