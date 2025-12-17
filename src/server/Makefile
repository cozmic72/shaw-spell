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
SWIFT_FLAGS_ARM64 = $(SWIFT_FLAGS) -target arm64-apple-macos13.0
SWIFT_FLAGS_X86_64 = $(SWIFT_FLAGS) -target x86_64-apple-macos13.0
FRAMEWORKS = -framework Foundation -framework AppKit
LIBS = -lhunspell-1.7

# Hunspell paths (via Homebrew)
# ARM64 paths (Apple Silicon)
HUNSPELL_INCLUDE_ARM64 = /opt/homebrew/include/hunspell
HUNSPELL_LIB_ARM64 = /opt/homebrew/lib
HUNSPELL_DYLIB_ARM64 = /opt/homebrew/opt/hunspell/lib/libhunspell-1.7.0.dylib

# x86_64 paths (Intel)
HUNSPELL_INCLUDE_X86_64 = /usr/local/include/hunspell
HUNSPELL_LIB_X86_64 = /usr/local/lib
HUNSPELL_DYLIB_X86_64 = /usr/local/opt/hunspell/lib/libhunspell-1.7.0.dylib

# Auto-detect current architecture for single-arch builds
HUNSPELL_INCLUDE = /opt/homebrew/include/hunspell
HUNSPELL_LIB = /opt/homebrew/lib
HUNSPELL_DYLIB_SRC = /opt/homebrew/opt/hunspell/lib/libhunspell-1.7.0.dylib
ifeq ($(wildcard $(HUNSPELL_INCLUDE)),)
    HUNSPELL_INCLUDE = /usr/local/include/hunspell
    HUNSPELL_LIB = /usr/local/lib
    HUNSPELL_DYLIB_SRC = /usr/local/opt/hunspell/lib/libhunspell-1.7.0.dylib
endif

INCLUDES_ARM64 = -I$(HUNSPELL_INCLUDE_ARM64)
INCLUDES_X86_64 = -I$(HUNSPELL_INCLUDE_X86_64)
LDFLAGS_ARM64 = -L$(HUNSPELL_LIB_ARM64)
LDFLAGS_X86_64 = -L$(HUNSPELL_LIB_X86_64)
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

# Target is the actual executable inside the bundle
all: $(MACOS_DIR)/$(SERVICE_NAME)

# Build the complete spell server bundle atomically
$(MACOS_DIR)/$(SERVICE_NAME): $(BUILD_DIR)/$(SERVICE_NAME) Info.plist
	@echo "Building spell server service bundle..."
	@TEMP=$$(mktemp -d) && \
	TEMP_BUNDLE="$$TEMP/$(BUNDLE_NAME)" && \
	TEMP_CONTENTS="$$TEMP_BUNDLE/Contents" && \
	TEMP_MACOS="$$TEMP_CONTENTS/MacOS" && \
	TEMP_RESOURCES="$$TEMP_CONTENTS/Resources" && \
	TEMP_FRAMEWORKS="$$TEMP_CONTENTS/Frameworks" && \
	mkdir -p "$$TEMP_MACOS" "$$TEMP_RESOURCES" "$$TEMP_FRAMEWORKS" && \
	echo "  Copying executable..." && \
	cp "$(BUILD_DIR)/$(SERVICE_NAME)" "$$TEMP_MACOS/" && \
	echo "  Copying Info.plist..." && \
	cp Info.plist "$$TEMP_CONTENTS/" && \
	echo "  Creating universal Hunspell library..." && \
	lipo -create "$(HUNSPELL_DYLIB_ARM64)" "$(HUNSPELL_DYLIB_X86_64)" -output "$$TEMP_FRAMEWORKS/libhunspell-1.7.0.dylib" && \
	chmod +w "$$TEMP_FRAMEWORKS/libhunspell-1.7.0.dylib" && \
	echo "  Updating library paths..." && \
	install_name_tool -change "$(HUNSPELL_DYLIB_ARM64)" @executable_path/../Frameworks/libhunspell-1.7.0.dylib "$$TEMP_MACOS/$(SERVICE_NAME)" && \
	install_name_tool -change "$(HUNSPELL_DYLIB_X86_64)" @executable_path/../Frameworks/libhunspell-1.7.0.dylib "$$TEMP_MACOS/$(SERVICE_NAME)" && \
	install_name_tool -id @executable_path/../Frameworks/libhunspell-1.7.0.dylib "$$TEMP_FRAMEWORKS/libhunspell-1.7.0.dylib" && \
	echo "  Code signing..." && \
	$(REPO_ROOT)/src/tools/sign-bundle.sh library "$$TEMP_FRAMEWORKS/libhunspell-1.7.0.dylib" && \
	$(REPO_ROOT)/src/tools/sign-bundle.sh library "$$TEMP_MACOS/$(SERVICE_NAME)" && \
	$(REPO_ROOT)/src/tools/sign-bundle.sh bundle "$$TEMP_BUNDLE" $(ENTITLEMENTS) && \
	echo "  Moving to final location..." && \
	rm -rf "$(BUNDLE_DIR)" && \
	mv "$$TEMP_BUNDLE" "$(BUILD_DIR)/" && \
	rm -rf "$$TEMP" && \
	touch "$(MACOS_DIR)/$(SERVICE_NAME)" && \
	echo "✓ Spell server service bundle created at $(BUNDLE_DIR)"

$(BUILD_DIR)/$(SERVICE_NAME): $(SWIFT_SOURCES) $(BRIDGE_HEADER) $(HUNSPELL_DYLIB_ARM64) $(HUNSPELL_DYLIB_X86_64) | $(BUILD_DIR)
	@echo "Compiling $(SERVICE_NAME) for arm64..."
	$(SWIFTC) $(SWIFT_FLAGS_ARM64) $(INCLUDES_ARM64) $(LDFLAGS_ARM64) $(FRAMEWORKS) $(LIBS) -o $(BUILD_DIR)/$(SERVICE_NAME)-arm64 $(SWIFT_SOURCES)
	@echo "Compiling $(SERVICE_NAME) for x86_64..."
	$(SWIFTC) $(SWIFT_FLAGS_X86_64) $(INCLUDES_X86_64) $(LDFLAGS_X86_64) $(FRAMEWORKS) $(LIBS) -o $(BUILD_DIR)/$(SERVICE_NAME)-x86_64 $(SWIFT_SOURCES)
	@echo "Creating universal binary..."
	lipo -create $(BUILD_DIR)/$(SERVICE_NAME)-arm64 $(BUILD_DIR)/$(SERVICE_NAME)-x86_64 -output $@
	@rm -f $(BUILD_DIR)/$(SERVICE_NAME)-arm64 $(BUILD_DIR)/$(SERVICE_NAME)-x86_64

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
	@rm -rf $(BUNDLE_DIR) $(BUILD_DIR)/$(SERVICE_NAME) $(TEST_DIR)

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
