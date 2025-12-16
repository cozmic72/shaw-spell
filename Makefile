# Makefile for Shaw-Spell
# Provides incremental builds for dictionaries and spell checker

.PHONY: all clean install uninstall help spellcheck spellserver transliterations shavian-english english-shavian shavian-shavian notarize staple wordnet-cache site site-tarball clean-site test
.PHONY: shavian-english-gb shavian-english-us english-shavian-gb english-shavian-us shavian-shavian-gb shavian-shavian-us
.DEFAULT_GOAL := help

# Include modular build system
include build-rules/common.mk
include build-rules/icons.mk
include build-rules/dictionaries.mk
include build-rules/spellcheck.mk
include build-rules/site.mk

# Notarization configuration
# Set these in .signing-config or pass on the command line
# See .signing-config.example for the format
APPLE_ID ?=
TEAM_ID ?=
NOTARY_PASSWORD ?=

# (Dictionary configuration moved to build-rules/dictionaries.mk)

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
	@echo "  site                Build web dictionary frontend"
	@echo "  site-tarball        Build deployable tarball for Linux/web servers"
	@echo ""
	@echo "Cache regeneration (explicit only, commits to git):"
	@echo "  wordnet-cache       Rebuild comprehensive WordNet cache (~2 min)"
	@echo "  transliterations    Rebuild Shavian caches (requires shave tool)"
	@echo ""
	@echo "Cleanup targets:"
	@echo "  clean               Remove build/ artifacts (preserves data/ caches)"
	@echo "  uninstall           Remove installed components"

# Cache generation, XML generation, and dictionary building now in build-rules/dictionaries.mk

# Legacy dictionary paths for backward compatibility
DICT_SHAVIAN_ENGLISH_GB = $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-gb.dictionary
DICT_ENGLISH_SHAVIAN_GB = $(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-gb.dictionary
DICT_SHAVIAN_SHAVIAN_GB = $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-gb.dictionary
DICT_SHAVIAN_ENGLISH_US = $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-English-us.dictionary
DICT_ENGLISH_SHAVIAN_US = $(BUILD_DICT_BUNDLES)/Shaw-Spell-English-Shavian-us.dictionary
DICT_SHAVIAN_SHAVIAN_US = $(BUILD_DICT_BUNDLES)/Shaw-Spell-Shavian-us.dictionary

# Spellcheck and spell server rules now in build-rules/spellcheck.mk

# Actual build artifacts (not marker files)
INSTALLER_APP = build/Install Shaw-Spell.app/Contents/MacOS/ShawSpellInstaller
UNINSTALLER_APP = build/Uninstall Shaw-Spell.app/Contents/MacOS/ShawSpellUninstaller
DMG_FILE = build/Shaw-Spell-$(VERSION).dmg

# Icon files - now use centralized build/icons/ directory (see build-rules/icons.mk)
INSTALLER_ICON = $(ICON_INSTALLER)
UNINSTALLER_ICON = $(ICON_UNINSTALLER)
DMG_ICON = $(ICON_VOLUME)
SITE_ICONS = $(ICON_FAVICON) $(ICON_APPLE_TOUCH)

$(INSTALLER_APP): $(DICT_SHAVIAN_ENGLISH_GB) $(DICT_ENGLISH_SHAVIAN_GB) $(DICT_SHAVIAN_SHAVIAN_GB) \
                  $(DICT_SHAVIAN_ENGLISH_US) $(DICT_ENGLISH_SHAVIAN_US) $(DICT_SHAVIAN_SHAVIAN_US) \
                  $(HUNSPELL_GB) $(HUNSPELL_US) $(HUNSPELL_EN_GB) $(HUNSPELL_EN_US) \
                  $(SPELLSERVER_BUNDLE) $(INSTALLER_ICON) \
                  src/installer/src/*.swift src/installer/src/Info.plist src/installer/resources/*.html
	@cd src/installer && $(MAKE)

$(UNINSTALLER_APP): $(UNINSTALLER_ICON) src/uninstaller/src/*.swift src/uninstaller/src/Info.plist src/uninstaller/Makefile
	@cd src/uninstaller && $(MAKE)

.PHONY: installer uninstaller-app
installer: $(INSTALLER_APP)
	@echo "Installer app built successfully at: build/Install Shaw-Spell.app"

uninstaller-app: $(UNINSTALLER_APP)
	@echo "Uninstaller app built successfully at: build/Uninstall Shaw-Spell.app"

$(DMG_FILE): $(INSTALLER_APP) $(UNINSTALLER_APP) $(DMG_ICON) src/installer/dmg-template/DS_Store_template
	@echo "Creating installer DMG..."
	$(RUN) src/tools/build-dmg.sh \
		"$(VERSION)" \
		"build/Install Shaw-Spell.app" \
		"build/Uninstall Shaw-Spell.app" \
		"$(DMG_ICON)" \
		"src/installer/dmg-template/DS_Store_template" \
		"$(DMG_FILE)"

.PHONY: dmg
dmg: $(DMG_FILE)

# Notarize the DMG with Apple
notarize:
	@if [ ! -f "$(DMG_FILE)" ]; then \
		echo "Error: DMG file not found: $(DMG_FILE)"; \
		echo "Run 'make dmg' first to build the DMG."; \
		exit 1; \
	fi
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
	$(RUN) xcrun notarytool submit "$(DMG_FILE)" \
		--apple-id "$(APPLE_ID)" \
		--team-id "$(TEAM_ID)" \
		--password "$(NOTARY_PASSWORD)" \
		--wait
	@echo ""
	@echo "Notarization successful! Stapling ticket to DMG..."
	$(RUN) xcrun stapler staple "$(DMG_FILE)"
	@echo ""
	@echo "DMG is now notarized and stapled - ready for distribution!"
	@echo "File: $(DMG_FILE)"

# Staple the notarization ticket to the DMG
staple:
	@if [ ! -f "$(DMG_FILE)" ]; then \
		echo "Error: DMG file not found: $(DMG_FILE)"; \
		echo "Run 'make dmg' first to build the DMG."; \
		exit 1; \
	fi
	@echo "Stapling notarization ticket to DMG..."
	$(RUN) xcrun stapler staple "$(DMG_FILE)"
	@echo ""
	@echo "DMG is now stapled and ready for distribution!"
	@echo "File: $(DMG_FILE)"

###########################################
# High-level targets
###########################################

all: $(DMG_FILE) site
	@echo "All components built successfully!"
	@echo "DMG installer ready at: $(DMG_FILE)"
	@echo "Web frontend ready at: build/site/"

# Dictionary convenience targets moved to build-rules/dictionaries.mk

# Web frontend rules now in build-rules/site.mk

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
	@rm -rf build/
	@cd src/installer && $(MAKE) clean 2>/dev/null || true
	@cd src/uninstaller && $(MAKE) clean 2>/dev/null || true
	@echo "Clean complete"
	@echo "Note: Pre-built caches in data/ are preserved."
	@echo "      To regenerate caches, run: make wordnet-cache or make transliterations"

# clean-site target now in build-rules/site.mk

###########################################
# Testing
###########################################

test: $(BUILD_DICT_XML)/shavian-english-gb.xml
	@echo "Running dictionary tests..."
	$(RUN) python3 src/test/test_dictionaries.py $(BUILD_DICT_XML)/shavian-english-gb.xml
