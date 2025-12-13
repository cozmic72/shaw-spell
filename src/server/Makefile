# Makefile for Shavian Spell Server
#
# Builds an NSSpellServer service that provides English spell-checking
# with support for both Latin and Shavian scripts.

# Configuration
SERVICE_NAME = Shaw-Spell
BUNDLE_NAME = $(SERVICE_NAME).service
INSTALL_DIR = $(HOME)/Library/Services

# Code signing configuration
REPO_ROOT = ../..
ENTITLEMENTS = Shaw-Spell.entitlements
include $(REPO_ROOT)/src/signing.mk

# Source files
SWIFT_SOURCES = main.swift ShavianSpellChecker.swift
BRIDGE_HEADER = HunspellBridge.h

# Compiler and linker flags
SWIFTC = swiftc
SWIFT_FLAGS = -O -whole-module-optimization -warnings-as-errors -import-objc-header $(BRIDGE_HEADER)
FRAMEWORKS = -framework Foundation -framework AppKit
LIBS = -lhunspell-1.7

# Hunspell paths (via Homebrew)
HUNSPELL_INCLUDE = /opt/homebrew/include/hunspell
HUNSPELL_LIB = /opt/homebrew/lib
HUNSPELL_DYLIB_SRC = /opt/homebrew/opt/hunspell/lib/libhunspell-1.7.0.dylib
ifeq ($(wildcard $(HUNSPELL_INCLUDE)),)
    HUNSPELL_INCLUDE = /usr/local/include/hunspell
    HUNSPELL_LIB = /usr/local/lib
    HUNSPELL_DYLIB_SRC = /usr/local/opt/hunspell/lib/libhunspell-1.7.0.dylib
endif

INCLUDES = -I$(HUNSPELL_INCLUDE)
LDFLAGS = -L$(HUNSPELL_LIB)

# Build directory structure (use top-level build directory)
BUILD_DIR = ../../build
BUNDLE_DIR = $(BUILD_DIR)/$(BUNDLE_NAME)
CONTENTS_DIR = $(BUNDLE_DIR)/Contents
MACOS_DIR = $(CONTENTS_DIR)/MacOS
RESOURCES_DIR = $(CONTENTS_DIR)/Resources
OBJECTS_DIR = $(BUILD_DIR)/server-objects
TEST_DIR = $(BUILD_DIR)/test

# Test programs
TEST_SOURCES = test_direct.m test_spell.m test_textview.m
TEST_PROGRAMS = $(addprefix $(TEST_DIR)/,$(TEST_SOURCES:.m=))

.PHONY: clean install uninstall test

# Use marker file to avoid directory timestamp issues
BUNDLE_MARKER = $(BUILD_DIR)/.spellserver-built

all: $(BUNDLE_MARKER)

$(BUNDLE_MARKER): $(BUILD_DIR)/$(SERVICE_NAME) Info.plist
	@echo "Building service bundle..."
	@mkdir -p $(MACOS_DIR) $(RESOURCES_DIR)
	@cp $(BUILD_DIR)/$(SERVICE_NAME) $(MACOS_DIR)/
	@cp Info.plist $(CONTENTS_DIR)/
	@echo "Bundling Hunspell library..."
	@mkdir -p $(CONTENTS_DIR)/Frameworks
	@cp $(HUNSPELL_DYLIB_SRC) $(CONTENTS_DIR)/Frameworks/
	@chmod +w $(CONTENTS_DIR)/Frameworks/libhunspell-1.7.0.dylib
	@echo "Updating library paths..."
	@install_name_tool -change $(HUNSPELL_DYLIB_SRC) @executable_path/../Frameworks/libhunspell-1.7.0.dylib $(MACOS_DIR)/$(SERVICE_NAME)
	@install_name_tool -id @executable_path/../Frameworks/libhunspell-1.7.0.dylib $(CONTENTS_DIR)/Frameworks/libhunspell-1.7.0.dylib
	$(call SIGN_LIBRARY,$(CONTENTS_DIR)/Frameworks/libhunspell-1.7.0.dylib)
	$(call SIGN_LIBRARY,$(MACOS_DIR)/$(SERVICE_NAME))
	$(call SIGN_BUNDLE,$(BUNDLE_DIR),$(ENTITLEMENTS))
	@touch $(BUNDLE_MARKER)
	@echo "Service bundle created at $(BUNDLE_DIR)"

$(BUILD_DIR)/$(SERVICE_NAME): $(SWIFT_SOURCES) $(BRIDGE_HEADER) | $(BUILD_DIR)
	@echo "Compiling and linking $(SERVICE_NAME) with Swift..."
	$(SWIFTC) $(SWIFT_FLAGS) $(INCLUDES) $(LDFLAGS) $(FRAMEWORKS) $(LIBS) -o $@ $(SWIFT_SOURCES)

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

$(TEST_DIR):
	@mkdir -p $(TEST_DIR)

# Test targets
test: $(TEST_PROGRAMS)
	@echo "Test programs built in $(TEST_DIR)"

$(TEST_DIR)/test_direct: test_direct.m ShavianSpellChecker.m | $(TEST_DIR)
	@echo "Building test_direct..."
	$(CC) $(CFLAGS) $(INCLUDES) $(LDFLAGS) -o $@ $^ $(FRAMEWORKS) $(LIBS)

$(TEST_DIR)/test_spell: test_spell.m ShavianSpellChecker.m | $(TEST_DIR)
	@echo "Building test_spell..."
	$(CC) $(CFLAGS) $(INCLUDES) $(LDFLAGS) -o $@ $^ $(FRAMEWORKS) $(LIBS)

$(TEST_DIR)/test_textview: test_textview.m ShavianSpellChecker.m | $(TEST_DIR)
	@echo "Building test_textview..."
	$(CC) $(CFLAGS) $(INCLUDES) $(LDFLAGS) -o $@ $^ $(FRAMEWORKS) $(LIBS)

clean:
	@echo "Cleaning build artifacts..."
	@rm -rf $(BUNDLE_DIR) $(BUILD_DIR)/$(SERVICE_NAME) $(TEST_DIR) $(BUNDLE_MARKER)

install: all
	@echo "Installing to $(INSTALL_DIR)..."
	@mkdir -p $(INSTALL_DIR)
	@cp -R $(BUNDLE_DIR) $(INSTALL_DIR)/
	@echo "Installing LaunchAgent..."
	@mkdir -p $(HOME)/Library/LaunchAgents
	@mkdir -p $(HOME)/Library/Logs
	@sed "s|__HOME__|$(HOME)|g" io.joro.Shaw-Spell.plist > $(HOME)/Library/LaunchAgents/io.joro.Shaw-Spell.plist
	@echo "Loading LaunchAgent..."
	@launchctl unload $(HOME)/Library/LaunchAgents/io.joro.Shaw-Spell.plist 2>/dev/null || true
	@launchctl load $(HOME)/Library/LaunchAgents/io.joro.Shaw-Spell.plist
	@echo "Updating services..."
	@/System/Library/CoreServices/pbs -update
	@echo ""
	@echo "Installation complete!"
	@echo "The spell server is now running and will start automatically on login."
	@echo ""
	@echo "To use the spell server:"
	@echo "1. Restart any applications that use spell-checking"
	@echo "2. In System Settings > Keyboard > Text Input > Edit..."
	@echo "3. Look for 'Shaw-Spell' spell checkers in the list"
	@echo ""
	@echo "Logs: $(HOME)/Library/Logs/Shaw-Spell.log"

uninstall:
	@echo "Uninstalling from $(INSTALL_DIR)..."
	@echo "Stopping LaunchAgent..."
	@launchctl unload $(HOME)/Library/LaunchAgents/io.joro.Shaw-Spell.plist 2>/dev/null || true
	@rm -f $(HOME)/Library/LaunchAgents/io.joro.Shaw-Spell.plist
	@rm -rf $(INSTALL_DIR)/$(BUNDLE_NAME)
	@/System/Library/CoreServices/pbs -update
	@echo "Uninstallation complete!"
	@echo ""
	@echo "Note: You may want to remove the log file:"
	@echo "  rm $(HOME)/Library/Logs/Shaw-Spell.log"

# Check for Hunspell
check-hunspell:
	@echo "Checking for Hunspell..."
	@if [ ! -d "$(HUNSPELL_INCLUDE)" ]; then \
		echo "ERROR: Hunspell headers not found at $(HUNSPELL_INCLUDE)"; \
		echo "Please install Hunspell: brew install hunspell"; \
		exit 1; \
	fi
	@echo "Hunspell found at $(HUNSPELL_INCLUDE)"
