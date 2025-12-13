# Makefile for Shaw-Spell Uninstaller
#
# Builds a native macOS uninstaller application for Shaw-Spell

# Configuration
APP_NAME = Uninstall Shaw-Spell
BUNDLE_NAME = Uninstall Shaw-Spell.app
EXECUTABLE_NAME = ShawSpellUninstaller
BUNDLE_IDENTIFIER = io.joro.shaw-spell.uninstaller

# Code signing configuration
REPO_ROOT = ../..
ENTITLEMENTS = Uninstaller.entitlements
include $(REPO_ROOT)/src/signing.mk

# Source files
SWIFT_SOURCES = src/main.swift src/AppDelegate.swift

# Compiler and linker flags
SWIFTC = swiftc
SWIFT_FLAGS = -O -warnings-as-errors
FRAMEWORKS = -framework Cocoa

# Build directory - use top-level build/
BUILD_DIR = ../../build
BUNDLE_DIR = $(BUILD_DIR)/$(BUNDLE_NAME)
CONTENTS_DIR = $(BUNDLE_DIR)/Contents
MACOS_DIR = $(CONTENTS_DIR)/MacOS
RESOURCES_DIR = $(CONTENTS_DIR)/Resources

# Icon (uninstaller-specific)
ICON_FILE = $(BUILD_DIR)/uninstaller/AppIcon.icns

.PHONY: clean icon

# Use marker file to avoid directory timestamp issues
BUNDLE_MARKER = $(BUILD_DIR)/.uninstaller-built

all: $(BUNDLE_MARKER)

$(BUNDLE_MARKER): $(BUILD_DIR)/$(EXECUTABLE_NAME) $(ICON_FILE) src/Info.plist
	@echo "Building application bundle..."
	@mkdir -p "$(MACOS_DIR)" "$(RESOURCES_DIR)"
	@cp "$(BUILD_DIR)/$(EXECUTABLE_NAME)" "$(MACOS_DIR)/"
	@cp src/Info.plist "$(CONTENTS_DIR)/"
	@echo "Copying icon..."
	@cp "$(ICON_FILE)" "$(RESOURCES_DIR)/"
	$(call SIGN_BUNDLE,$(BUNDLE_DIR),$(ENTITLEMENTS))
	@touch $(BUNDLE_MARKER)
	@echo ""
	@echo "Uninstaller app created at: $(BUNDLE_DIR)"
	@echo "You can run it with: open \"$(BUNDLE_DIR)\""

$(BUILD_DIR)/$(EXECUTABLE_NAME): $(SWIFT_SOURCES) | $(BUILD_DIR)
	@echo "Compiling and linking $(EXECUTABLE_NAME)..."
	$(SWIFTC) $(SWIFT_FLAGS) $(FRAMEWORKS) -o $@ $(SWIFT_SOURCES)

$(BUILD_DIR):
	@mkdir -p "$(BUILD_DIR)"

$(ICON_FILE): src/resources/icon.svg create-icon.sh
	@echo "Creating uninstaller icon..."
	@./create-icon.sh

icon: $(ICON_FILE)

clean:
	@echo "Cleaning uninstaller artifacts..."
	@rm -rf "$(BUNDLE_DIR)" "$(BUILD_DIR)/$(EXECUTABLE_NAME)" "$(BUNDLE_MARKER)"
	@echo "Clean complete"
