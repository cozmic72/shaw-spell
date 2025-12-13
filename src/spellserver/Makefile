# Makefile for Shavian Spell Server
#
# Builds an NSSpellServer service that provides English spell-checking
# with support for both Latin and Shavian scripts.

# Configuration
SERVICE_NAME = ShavianSpellServer
BUNDLE_NAME = $(SERVICE_NAME).service
INSTALL_DIR = $(HOME)/Library/Services

# Source files
SOURCES = main.m ShavianSpellChecker.m
OBJECTS = $(SOURCES:.m=.o)

# Compiler and linker flags
CC = clang
CFLAGS = -Wall -Wextra -O2 -fobjc-arc
FRAMEWORKS = -framework Foundation -framework AppKit
LIBS = -lhunspell-1.7

# Hunspell paths (via Homebrew)
HUNSPELL_INCLUDE = /opt/homebrew/include/hunspell
HUNSPELL_LIB = /opt/homebrew/lib
ifeq ($(wildcard $(HUNSPELL_INCLUDE)),)
    HUNSPELL_INCLUDE = /usr/local/include/hunspell
    HUNSPELL_LIB = /usr/local/lib
endif

INCLUDES = -I$(HUNSPELL_INCLUDE)
LDFLAGS = -L$(HUNSPELL_LIB)

# Build directory structure
BUILD_DIR = build
BUNDLE_DIR = $(BUILD_DIR)/$(BUNDLE_NAME)
CONTENTS_DIR = $(BUNDLE_DIR)/Contents
MACOS_DIR = $(CONTENTS_DIR)/MacOS
RESOURCES_DIR = $(CONTENTS_DIR)/Resources

.PHONY: all clean install uninstall

all: $(BUILD_DIR)/$(SERVICE_NAME)
	@echo "Building service bundle..."
	@mkdir -p $(MACOS_DIR) $(RESOURCES_DIR)
	@cp $(BUILD_DIR)/$(SERVICE_NAME) $(MACOS_DIR)/
	@cp Info.plist $(CONTENTS_DIR)/
	@echo "Service bundle created at $(BUNDLE_DIR)"

$(BUILD_DIR)/$(SERVICE_NAME): $(OBJECTS) | $(BUILD_DIR)
	@echo "Linking $(SERVICE_NAME)..."
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJECTS) $(FRAMEWORKS) $(LIBS)

%.o: %.m
	@echo "Compiling $<..."
	$(CC) $(CFLAGS) $(INCLUDES) -c $< -o $@

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

clean:
	@echo "Cleaning build artifacts..."
	@rm -rf $(BUILD_DIR) $(OBJECTS)

install: all
	@echo "Installing to $(INSTALL_DIR)..."
	@mkdir -p $(INSTALL_DIR)
	@cp -R $(BUNDLE_DIR) $(INSTALL_DIR)/
	@echo "Updating services..."
	@/System/Library/CoreServices/pbs -update
	@echo ""
	@echo "Installation complete!"
	@echo "To use the spell server:"
	@echo "1. Restart any applications that use spell-checking"
	@echo "2. In System Settings > Keyboard > Text Input > Edit..."
	@echo "3. Look for 'ShawDict' spell checkers in the list"
	@echo ""
	@echo "Note: You may need to log out and log back in for the service to appear."

uninstall:
	@echo "Uninstalling from $(INSTALL_DIR)..."
	@rm -rf $(INSTALL_DIR)/$(BUNDLE_NAME)
	@/System/Library/CoreServices/pbs -update
	@echo "Uninstallation complete!"

# Check for Hunspell
check-hunspell:
	@echo "Checking for Hunspell..."
	@if [ ! -d "$(HUNSPELL_INCLUDE)" ]; then \
		echo "ERROR: Hunspell headers not found at $(HUNSPELL_INCLUDE)"; \
		echo "Please install Hunspell: brew install hunspell"; \
		exit 1; \
	fi
	@echo "Hunspell found at $(HUNSPELL_INCLUDE)"
