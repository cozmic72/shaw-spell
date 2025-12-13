# Makefile for Shaw Spell Installer
#
# Builds a native macOS installer application for Shaw Spell

# Configuration
APP_NAME = Install Shaw Spell
BUNDLE_NAME = Install Shaw Spell.app
EXECUTABLE_NAME = ShawSpellInstaller
BUNDLE_IDENTIFIER = io.joro.shaw-spell.installer
CODESIGN_IDENTITY = Jonathan Ross

# Source files
SOURCES = src/main.m src/InstallerAppDelegate.m
OBJECTS = $(SOURCES:.m=.o)

# Compiler and linker flags
CC = clang
CFLAGS = -Wall -Wextra -O2 -fobjc-arc
FRAMEWORKS = -framework Cocoa
LDFLAGS =

# Build directory - use top-level build/
BUILD_DIR = ../../build
BUNDLE_DIR = $(BUILD_DIR)/$(BUNDLE_NAME)
CONTENTS_DIR = $(BUNDLE_DIR)/Contents
MACOS_DIR = $(CONTENTS_DIR)/MacOS
RESOURCES_DIR = $(CONTENTS_DIR)/Resources

# Icon (generated in build dir)
ICON_FILE = $(BUILD_DIR)/installer/AppIcon.icns

.PHONY: all clean install icon

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
	@echo "Installer app created at: $(BUNDLE_DIR)"
	@echo "You can run it with: open \"$(BUNDLE_DIR)\""

$(BUILD_DIR)/$(EXECUTABLE_NAME): $(OBJECTS) | $(BUILD_DIR)
	@echo "Linking $(EXECUTABLE_NAME)..."
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJECTS) $(FRAMEWORKS)

%.o: %.m
	@echo "Compiling $<..."
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR):
	@mkdir -p "$(BUILD_DIR)"

$(ICON_FILE): src/resources/icon.svg create-icon.sh
	@echo "Creating app icon..."
	@./create-icon.sh

icon: $(ICON_FILE)

clean:
	@echo "Cleaning installer artifacts..."
	@rm -rf "$(BUNDLE_DIR)" src/*.o "$(BUILD_DIR)/installer"
	@echo "Clean complete"

install:
	@echo "The installer app is meant to be distributed, not installed itself."
	@echo "To use it, run: open \"$(BUNDLE_DIR)\""
