# Makefile for Shaw-Spell Installer
#
# Builds a native macOS installer application for Shaw-Spell

# Configuration
APP_NAME = Install Shaw-Spell
BUNDLE_NAME = Install Shaw-Spell.app
EXECUTABLE_NAME = ShawSpellInstaller
BUNDLE_IDENTIFIER = io.joro.shaw-spell.installer
CODESIGN_IDENTITY = Jonathan Ross

# Source files
SWIFT_SOURCES = src/main.swift src/AppDelegate.swift

# Compiler and linker flags
SWIFTC = swiftc
SWIFT_FLAGS = -O -warnings-as-errors
FRAMEWORKS = -framework Cocoa -framework WebKit

# Build directory - use top-level build/
BUILD_DIR = ../../build
BUNDLE_DIR = $(BUILD_DIR)/$(BUNDLE_NAME)
CONTENTS_DIR = $(BUNDLE_DIR)/Contents
MACOS_DIR = $(CONTENTS_DIR)/MacOS
RESOURCES_DIR = $(CONTENTS_DIR)/Resources

# Icon (generated in build dir)
ICON_FILE = $(BUILD_DIR)/installer/AppIcon.icns

.PHONY: clean install icon

# Use marker file to avoid directory timestamp issues
BUNDLE_MARKER = $(BUILD_DIR)/.installer-built

all: $(BUNDLE_MARKER)

$(BUNDLE_MARKER): $(BUILD_DIR)/$(EXECUTABLE_NAME) $(ICON_FILE) src/Info.plist resources/*
	@echo "Building application bundle..."
	@mkdir -p "$(MACOS_DIR)" "$(RESOURCES_DIR)"
	@cp "$(BUILD_DIR)/$(EXECUTABLE_NAME)" "$(MACOS_DIR)/"
	@cp src/Info.plist "$(CONTENTS_DIR)/"
	@echo "Copying resources..."
	@cp "$(ICON_FILE)" "$(RESOURCES_DIR)/"
	@cp resources/* "$(RESOURCES_DIR)/" 2>/dev/null || true
	@echo "Bundling dictionaries and components for installation..."
	@mkdir -p "$(RESOURCES_DIR)/dictionaries"
	@mkdir -p "$(RESOURCES_DIR)/hunspell"
	@cp -R "$(BUILD_DIR)/dictionaries/shavian-english-gb/Shaw-Spell-Shavian-English-gb.dictionary" "$(RESOURCES_DIR)/dictionaries/" 2>/dev/null || true
	@cp -R "$(BUILD_DIR)/dictionaries/english-shavian-gb/Shaw-Spell-English-Shavian-gb.dictionary" "$(RESOURCES_DIR)/dictionaries/" 2>/dev/null || true
	@cp -R "$(BUILD_DIR)/dictionaries/shavian-shavian-gb/Shaw-Spell-Shavian-gb.dictionary" "$(RESOURCES_DIR)/dictionaries/" 2>/dev/null || true
	@cp -R "$(BUILD_DIR)/dictionaries/shavian-english-us/Shaw-Spell-Shavian-English-us.dictionary" "$(RESOURCES_DIR)/dictionaries/" 2>/dev/null || true
	@cp -R "$(BUILD_DIR)/dictionaries/english-shavian-us/Shaw-Spell-English-Shavian-us.dictionary" "$(RESOURCES_DIR)/dictionaries/" 2>/dev/null || true
	@cp -R "$(BUILD_DIR)/dictionaries/shavian-shavian-us/Shaw-Spell-Shavian-us.dictionary" "$(RESOURCES_DIR)/dictionaries/" 2>/dev/null || true
	@cp "$(BUILD_DIR)/io.joro.shaw-spell.shavian-gb.dic" "$(BUILD_DIR)/io.joro.shaw-spell.shavian-gb.aff" "$(RESOURCES_DIR)/hunspell/" 2>/dev/null || true
	@cp "$(BUILD_DIR)/io.joro.shaw-spell.shavian-us.dic" "$(BUILD_DIR)/io.joro.shaw-spell.shavian-us.aff" "$(RESOURCES_DIR)/hunspell/" 2>/dev/null || true
	@cp "$(BUILD_DIR)/io.joro.shaw-spell.en_GB.dic" "$(BUILD_DIR)/io.joro.shaw-spell.en_GB.aff" "$(RESOURCES_DIR)/hunspell/" 2>/dev/null || true
	@cp "$(BUILD_DIR)/io.joro.shaw-spell.en_US.dic" "$(BUILD_DIR)/io.joro.shaw-spell.en_US.aff" "$(RESOURCES_DIR)/hunspell/" 2>/dev/null || true
	@cp -R "$(BUILD_DIR)/Shaw-Spell.service" "$(RESOURCES_DIR)/" 2>/dev/null || true
	@cp "../../src/server/io.joro.Shaw-Spell.plist" "$(RESOURCES_DIR)/" 2>/dev/null || true
	@echo "Code signing application..."
	@codesign --force --deep --sign "$(CODESIGN_IDENTITY)" "$(BUNDLE_DIR)" 2>/dev/null || echo "Warning: Code signing failed (not critical for testing)"
	@touch $(BUNDLE_MARKER)
	@echo ""
	@echo "Installer app created at: $(BUNDLE_DIR)"
	@echo "You can run it with: open \"$(BUNDLE_DIR)\""

$(BUILD_DIR)/$(EXECUTABLE_NAME): $(SWIFT_SOURCES) | $(BUILD_DIR)
	@echo "Compiling and linking $(EXECUTABLE_NAME)..."
	$(SWIFTC) $(SWIFT_FLAGS) $(FRAMEWORKS) -o $@ $(SWIFT_SOURCES)

$(BUILD_DIR):
	@mkdir -p "$(BUILD_DIR)"

$(ICON_FILE): src/resources/icon.svg create-icon.sh
	@echo "Creating app icon..."
	@./create-icon.sh

icon: $(ICON_FILE)

clean:
	@echo "Cleaning installer artifacts..."
	@rm -rf "$(BUNDLE_DIR)" "$(BUILD_DIR)/installer" "$(BUILD_DIR)/$(EXECUTABLE_NAME)" "$(BUNDLE_MARKER)"
	@echo "Clean complete"

install:
	@echo "The installer app is meant to be distributed, not installed itself."
	@echo "To use it, run: open \"$(BUNDLE_DIR)\""
