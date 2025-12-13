# Makefile for Shaw Spell Uninstaller
#
# Builds a native macOS uninstaller application for Shaw Spell

# Configuration
APP_NAME = Uninstall Shaw Spell
BUNDLE_NAME = Uninstall Shaw Spell.app
EXECUTABLE_NAME = ShawSpellUninstaller
BUNDLE_IDENTIFIER = io.joro.shaw-spell.uninstaller
CODESIGN_IDENTITY = Jonathan Ross

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

# Icon (shared with installer)
ICON_FILE = $(BUILD_DIR)/installer/AppIcon.icns

.PHONY: all clean icon

all: $(BUILD_DIR)/$(EXECUTABLE_NAME) $(ICON_FILE)
	@echo "Building application bundle..."
	@mkdir -p "$(MACOS_DIR)" "$(RESOURCES_DIR)"
	@cp "$(BUILD_DIR)/$(EXECUTABLE_NAME)" "$(MACOS_DIR)/"
	@cp src/Info.plist "$(CONTENTS_DIR)/"
	@echo "Copying icon..."
	@cp "$(ICON_FILE)" "$(RESOURCES_DIR)/"
	@echo "Code signing application..."
	@codesign --force --deep --sign "$(CODESIGN_IDENTITY)" "$(BUNDLE_DIR)" 2>/dev/null || echo "Warning: Code signing failed (not critical for testing)"
	@echo ""
	@echo "Uninstaller app created at: $(BUNDLE_DIR)"
	@echo "You can run it with: open \"$(BUNDLE_DIR)\""

$(BUILD_DIR)/$(EXECUTABLE_NAME): $(SWIFT_SOURCES) | $(BUILD_DIR)
	@echo "Compiling and linking $(EXECUTABLE_NAME)..."
	$(SWIFTC) $(SWIFT_FLAGS) $(FRAMEWORKS) -o $@ $(SWIFT_SOURCES)

$(BUILD_DIR):
	@mkdir -p "$(BUILD_DIR)"

# Icon is built by installer
$(ICON_FILE):
	@echo "Building icon (from installer)..."
	@cd ../installer && $(MAKE) icon

icon: $(ICON_FILE)

clean:
	@echo "Cleaning uninstaller artifacts..."
	@rm -rf "$(BUNDLE_DIR)" "$(BUILD_DIR)/$(EXECUTABLE_NAME)"
	@echo "Clean complete"
