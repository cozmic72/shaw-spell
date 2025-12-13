# Makefile for Shavian Spell Server
#
# Builds an NSSpellServer service that provides English spell-checking
# with support for both Latin and Shavian scripts.

# Configuration
SERVICE_NAME = ShavianSpellServer
BUNDLE_NAME = $(SERVICE_NAME).service
INSTALL_DIR = $(HOME)/Library/Services
CODESIGN_IDENTITY = Jonathan Ross

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
HUNSPELL_DYLIB_SRC = /opt/homebrew/opt/hunspell/lib/libhunspell-1.7.0.dylib
ifeq ($(wildcard $(HUNSPELL_INCLUDE)),)
    HUNSPELL_INCLUDE = /usr/local/include/hunspell
    HUNSPELL_LIB = /usr/local/lib
    HUNSPELL_DYLIB_SRC = /usr/local/opt/hunspell/lib/libhunspell-1.7.0.dylib
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
	@echo "Bundling Hunspell library..."
	@mkdir -p $(CONTENTS_DIR)/Frameworks
	@cp $(HUNSPELL_DYLIB_SRC) $(CONTENTS_DIR)/Frameworks/
	@chmod +w $(CONTENTS_DIR)/Frameworks/libhunspell-1.7.0.dylib
	@echo "Updating library paths..."
	@install_name_tool -change $(HUNSPELL_DYLIB_SRC) @executable_path/../Frameworks/libhunspell-1.7.0.dylib $(MACOS_DIR)/$(SERVICE_NAME)
	@install_name_tool -id @executable_path/../Frameworks/libhunspell-1.7.0.dylib $(CONTENTS_DIR)/Frameworks/libhunspell-1.7.0.dylib
	@echo "Code signing service bundle with '$(CODESIGN_IDENTITY)'..."
	@codesign --force --sign "$(CODESIGN_IDENTITY)" $(CONTENTS_DIR)/Frameworks/libhunspell-1.7.0.dylib
	@codesign --force --deep --sign "$(CODESIGN_IDENTITY)" $(BUNDLE_DIR)
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
	@echo "Installing LaunchAgent..."
	@mkdir -p $(HOME)/Library/LaunchAgents
	@mkdir -p $(HOME)/Library/Logs
	@sed "s|__HOME__|$(HOME)|g" io.joro.shaw-dict.spellserver.plist > $(HOME)/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist
	@echo "Loading LaunchAgent..."
	@launchctl unload $(HOME)/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist 2>/dev/null || true
	@launchctl load $(HOME)/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist
	@echo "Updating services..."
	@/System/Library/CoreServices/pbs -update
	@echo ""
	@echo "Installation complete!"
	@echo "The spell server is now running and will start automatically on login."
	@echo ""
	@echo "To use the spell server:"
	@echo "1. Restart any applications that use spell-checking"
	@echo "2. In System Settings > Keyboard > Text Input > Edit..."
	@echo "3. Look for 'ShawDict' spell checkers in the list"
	@echo ""
	@echo "Logs: $(HOME)/Library/Logs/ShavianSpellServer.log"

uninstall:
	@echo "Uninstalling from $(INSTALL_DIR)..."
	@echo "Stopping LaunchAgent..."
	@launchctl unload $(HOME)/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist 2>/dev/null || true
	@rm -f $(HOME)/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist
	@rm -f $(HOME)/Library/LaunchAgents/org.shavian.spellserver.plist
	@rm -rf $(INSTALL_DIR)/$(BUNDLE_NAME)
	@/System/Library/CoreServices/pbs -update
	@echo "Uninstallation complete!"
	@echo ""
	@echo "Note: You may want to remove the log file:"
	@echo "  rm $(HOME)/Library/Logs/ShavianSpellServer.log"

# Check for Hunspell
check-hunspell:
	@echo "Checking for Hunspell..."
	@if [ ! -d "$(HUNSPELL_INCLUDE)" ]; then \
		echo "ERROR: Hunspell headers not found at $(HUNSPELL_INCLUDE)"; \
		echo "Please install Hunspell: brew install hunspell"; \
		exit 1; \
	fi
	@echo "Hunspell found at $(HUNSPELL_INCLUDE)"
