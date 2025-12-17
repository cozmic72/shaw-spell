# Makefile for Shaw-Spell Installer
#
# Builds a native macOS installer application for Shaw-Spell

# Configuration
APP_NAME = Install Shaw-Spell
BUNDLE_NAME = Install Shaw-Spell.app
EXECUTABLE_NAME = ShawSpellInstaller
BUNDLE_IDENTIFIER = io.joro.shaw-spell.installer

# Code signing configuration
REPO_ROOT = ../..
ENTITLEMENTS = Installer.entitlements
include $(REPO_ROOT)/src/signing.mk

# Source files
SWIFT_SOURCES = src/main.swift src/AppDelegate.swift

# Compiler and linker flags
SWIFTC = swiftc
SWIFT_FLAGS = -O -warnings-as-errors
SWIFT_FLAGS_ARM64 = $(SWIFT_FLAGS) -target arm64-apple-macos13.0
SWIFT_FLAGS_X86_64 = $(SWIFT_FLAGS) -target x86_64-apple-macos13.0
FRAMEWORKS = -framework Cocoa -framework WebKit

# Build directory - use top-level build/
BUILD_DIR = ../../build
BUNDLE_DIR = $(BUILD_DIR)/$(BUNDLE_NAME)
CONTENTS_DIR = $(BUNDLE_DIR)/Contents
MACOS_DIR = $(CONTENTS_DIR)/MacOS
RESOURCES_DIR = $(CONTENTS_DIR)/Resources

# Icon (generated in centralized build/icons/ dir)
ICON_FILE = $(BUILD_DIR)/icons/installer-AppIcon.icns

# Actual artifacts this installer depends on
DICT_BUNDLES = $(BUILD_DIR)/dictionaries/bundles/Shaw-Spell-Shavian-English-gb.dictionary \
               $(BUILD_DIR)/dictionaries/bundles/Shaw-Spell-English-Shavian-gb.dictionary \
               $(BUILD_DIR)/dictionaries/bundles/Shaw-Spell-Shavian-gb.dictionary \
               $(BUILD_DIR)/dictionaries/bundles/Shaw-Spell-Shavian-English-us.dictionary \
               $(BUILD_DIR)/dictionaries/bundles/Shaw-Spell-English-Shavian-us.dictionary \
               $(BUILD_DIR)/dictionaries/bundles/Shaw-Spell-Shavian-us.dictionary

HUNSPELL_DIR = $(BUILD_DIR)/spellcheck/hunspell

HUNSPELL_FILES = $(HUNSPELL_DIR)/io.joro.shaw-spell.shavian-gb.dic \
                 $(HUNSPELL_DIR)/io.joro.shaw-spell.shavian-gb.aff \
                 $(HUNSPELL_DIR)/io.joro.shaw-spell.shavian-us.dic \
                 $(HUNSPELL_DIR)/io.joro.shaw-spell.shavian-us.aff \
                 $(HUNSPELL_DIR)/io.joro.shaw-spell.en_GB.dic \
                 $(HUNSPELL_DIR)/io.joro.shaw-spell.en_GB.aff \
                 $(HUNSPELL_DIR)/io.joro.shaw-spell.en_US.dic \
                 $(HUNSPELL_DIR)/io.joro.shaw-spell.en_US.aff

SPELLSERVER_BUNDLE = $(BUILD_DIR)/Shaw-Spell.service/Contents/MacOS/Shaw-Spell

.PHONY: clean install

# Target is the actual executable inside the bundle
all: $(MACOS_DIR)/$(EXECUTABLE_NAME)

# Build the complete installer app bundle atomically
$(MACOS_DIR)/$(EXECUTABLE_NAME): $(BUILD_DIR)/$(EXECUTABLE_NAME) $(ICON_FILE) \
                                  $(DICT_BUNDLES) $(HUNSPELL_FILES) $(SPELLSERVER_BUNDLE) \
                                  src/Info.plist resources/*.html
	@echo "Building installer app bundle..."
	@TEMP=$$(mktemp -d) && \
	TEMP_BUNDLE="$$TEMP/$(BUNDLE_NAME)" && \
	TEMP_CONTENTS="$$TEMP_BUNDLE/Contents" && \
	TEMP_MACOS="$$TEMP_CONTENTS/MacOS" && \
	TEMP_RESOURCES="$$TEMP_CONTENTS/Resources" && \
	mkdir -p "$$TEMP_MACOS" "$$TEMP_RESOURCES" && \
	echo "  Copying executable..." && \
	cp "$(BUILD_DIR)/$(EXECUTABLE_NAME)" "$$TEMP_MACOS/" && \
	echo "  Copying Info.plist..." && \
	cp src/Info.plist "$$TEMP_CONTENTS/" && \
	echo "  Copying icon..." && \
	cp "$(ICON_FILE)" "$$TEMP_RESOURCES/AppIcon.icns" && \
	echo "  Interpolating HTML resources..." && \
	for html in resources/*.html; do \
		../../src/dictionaries/interpolate_template.py "$$html" "$$TEMP_RESOURCES/$$(basename $$html)" VERSION="$(VERSION)"; \
	done && \
	echo "  Bundling dictionaries..." && \
	mkdir -p "$$TEMP_RESOURCES/dictionaries" && \
	cp -R $(DICT_BUNDLES) "$$TEMP_RESOURCES/dictionaries/" && \
	echo "  Bundling Hunspell files..." && \
	mkdir -p "$$TEMP_RESOURCES/hunspell" && \
	cp $(HUNSPELL_FILES) "$$TEMP_RESOURCES/hunspell/" && \
	echo "  Bundling spell server..." && \
	cp -R "$(BUILD_DIR)/Shaw-Spell.service" "$$TEMP_RESOURCES/" && \
	cp "../../src/server/io.joro.Shaw-Spell.plist" "$$TEMP_RESOURCES/" && \
	echo "  Code signing..." && \
	$(REPO_ROOT)/src/tools/sign-bundle.sh bundle "$$TEMP_BUNDLE" $(ENTITLEMENTS) && \
	echo "  Moving to final location..." && \
	rm -rf "$(BUNDLE_DIR)" && \
	mv "$$TEMP_BUNDLE" "$(BUILD_DIR)/" && \
	rm -rf "$$TEMP" && \
	touch "$(MACOS_DIR)/$(EXECUTABLE_NAME)" && \
	echo "✓ Installer app created at: $(BUNDLE_DIR)"

$(BUILD_DIR)/$(EXECUTABLE_NAME): $(SWIFT_SOURCES) | $(BUILD_DIR)
	@echo "Compiling $(EXECUTABLE_NAME) for arm64..."
	$(SWIFTC) $(SWIFT_FLAGS_ARM64) $(FRAMEWORKS) -o $(BUILD_DIR)/$(EXECUTABLE_NAME)-arm64 $(SWIFT_SOURCES)
	@echo "Compiling $(EXECUTABLE_NAME) for x86_64..."
	$(SWIFTC) $(SWIFT_FLAGS_X86_64) $(FRAMEWORKS) -o $(BUILD_DIR)/$(EXECUTABLE_NAME)-x86_64 $(SWIFT_SOURCES)
	@echo "Creating universal binary..."
	lipo -create $(BUILD_DIR)/$(EXECUTABLE_NAME)-arm64 $(BUILD_DIR)/$(EXECUTABLE_NAME)-x86_64 -output $@
	@rm -f $(BUILD_DIR)/$(EXECUTABLE_NAME)-arm64 $(BUILD_DIR)/$(EXECUTABLE_NAME)-x86_64

$(BUILD_DIR):
	@mkdir -p "$(BUILD_DIR)"

clean:
	@echo "Cleaning installer artifacts..."
	@rm -rf "$(BUNDLE_DIR)" "$(BUILD_DIR)/$(EXECUTABLE_NAME)"
	@echo "Clean complete"

install:
	@echo "The installer app is meant to be distributed, not installed itself."
	@echo "To use it, run: open \"$(BUNDLE_DIR)\""
