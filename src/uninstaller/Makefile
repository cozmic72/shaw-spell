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
SWIFT_FLAGS = -O -warnings-as-errors -target arm64-apple-macos13.0
FRAMEWORKS = -framework Cocoa

# Build directory - use top-level build/
BUILD_DIR = ../../build
BUNDLE_DIR = $(BUILD_DIR)/$(BUNDLE_NAME)
CONTENTS_DIR = $(BUNDLE_DIR)/Contents
MACOS_DIR = $(CONTENTS_DIR)/MacOS
RESOURCES_DIR = $(CONTENTS_DIR)/Resources

# Icon (generated in centralized build/icons/ dir)
ICON_FILE = $(BUILD_DIR)/icons/uninstaller-AppIcon.icns

.PHONY: clean

# Target is the actual executable inside the bundle
all: $(MACOS_DIR)/$(EXECUTABLE_NAME)

# Build the complete uninstaller app bundle atomically
$(MACOS_DIR)/$(EXECUTABLE_NAME): $(BUILD_DIR)/$(EXECUTABLE_NAME) $(ICON_FILE) src/Info.plist
	@echo "Building uninstaller app bundle..."
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
	echo "  Code signing..." && \
	$(REPO_ROOT)/src/tools/sign-bundle.sh bundle "$$TEMP_BUNDLE" $(ENTITLEMENTS) && \
	echo "  Moving to final location..." && \
	rm -rf "$(BUNDLE_DIR)" && \
	mv "$$TEMP_BUNDLE" "$(BUILD_DIR)/" && \
	rm -rf "$$TEMP" && \
	touch "$(MACOS_DIR)/$(EXECUTABLE_NAME)" && \
	echo "✓ Uninstaller app created at: $(BUNDLE_DIR)"

$(BUILD_DIR)/$(EXECUTABLE_NAME): $(SWIFT_SOURCES) | $(BUILD_DIR)
	@echo "Compiling $(EXECUTABLE_NAME)..."
	$(SWIFTC) $(SWIFT_FLAGS) $(FRAMEWORKS) -o $@ $(SWIFT_SOURCES)

$(BUILD_DIR):
	@mkdir -p "$(BUILD_DIR)"

clean:
	@echo "Cleaning uninstaller artifacts..."
	@rm -rf "$(BUNDLE_DIR)" "$(BUILD_DIR)/$(EXECUTABLE_NAME)"
	@echo "Clean complete"
