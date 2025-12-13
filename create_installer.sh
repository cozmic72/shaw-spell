#!/bin/bash
# Create Shaw Dict installer DMG

set -e

PRODUCT_NAME="Shaw Dict"
VERSION=$(cat current-version 2>/dev/null || echo "1.0.0")
DMG_NAME="ShawDict-${VERSION}.dmg"
VOLUME_NAME="Shaw Dict ${VERSION}"
STAGING_DIR="build/dmg_staging"
BUILD_DIR="build"

echo "Creating Shaw Dict installer DMG v${VERSION}..."

# Clean and create staging directory
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
mkdir -p "$BUILD_DIR"

# Copy dictionaries
echo "Copying dictionaries..."
mkdir -p "$STAGING_DIR/Dictionaries"
# Shavian-English (both GB and US)
if [ -d "dictionaries/shavian-english/objects-gb/Shavian-English-gb.dictionary" ]; then
    cp -R "dictionaries/shavian-english/objects-gb/Shavian-English-gb.dictionary" "$STAGING_DIR/Dictionaries/"
fi
if [ -d "dictionaries/shavian-english/objects-us/Shavian-English-us.dictionary" ]; then
    cp -R "dictionaries/shavian-english/objects-us/Shavian-English-us.dictionary" "$STAGING_DIR/Dictionaries/"
fi
# English-Shavian (both GB and US)
if [ -d "dictionaries/english-shavian/objects-gb/English-Shavian-gb.dictionary" ]; then
    cp -R "dictionaries/english-shavian/objects-gb/English-Shavian-gb.dictionary" "$STAGING_DIR/Dictionaries/"
fi
if [ -d "dictionaries/english-shavian/objects-us/English-Shavian-us.dictionary" ]; then
    cp -R "dictionaries/english-shavian/objects-us/English-Shavian-us.dictionary" "$STAGING_DIR/Dictionaries/"
fi
# Shavian (both GB and US)
if [ -d "dictionaries/shavian-shavian/objects-gb/Shavian-gb.dictionary" ]; then
    cp -R "dictionaries/shavian-shavian/objects-gb/Shavian-gb.dictionary" "$STAGING_DIR/Dictionaries/"
fi
if [ -d "dictionaries/shavian-shavian/objects-us/Shavian-us.dictionary" ]; then
    cp -R "dictionaries/shavian-shavian/objects-us/Shavian-us.dictionary" "$STAGING_DIR/Dictionaries/"
fi

# Copy spell server
echo "Copying spell server..."
if [ -f "src/spellserver/build/ShavianSpellServer.service/Contents/MacOS/ShavianSpellServer" ]; then
    mkdir -p "$STAGING_DIR/Spell Server"
    cp -R "src/spellserver/build/ShavianSpellServer.service" "$STAGING_DIR/Spell Server/"
    cp "src/spellserver/io.joro.shaw-dict.spellserver.plist" "$STAGING_DIR/Spell Server/"
fi

# Copy Hunspell dictionaries
echo "Copying Hunspell dictionaries..."
mkdir -p "$STAGING_DIR/Hunspell"
if [ -f "$HOME/Library/Spelling/shaw.dic" ]; then
    cp "$HOME/Library/Spelling/shaw.dic" "$STAGING_DIR/Hunspell/"
    cp "$HOME/Library/Spelling/shaw.aff" "$STAGING_DIR/Hunspell/"
fi
if [ -f "$HOME/Library/Spelling/en_GB.dic" ]; then
    cp "$HOME/Library/Spelling/en_GB.dic" "$STAGING_DIR/Hunspell/"
    cp "$HOME/Library/Spelling/en_GB.aff" "$STAGING_DIR/Hunspell/"
fi

# Create installer script
echo "Creating installer script..."
cat > "$STAGING_DIR/Install.command" << 'INSTALLER_SCRIPT'
#!/bin/bash
# Shaw Dict Installer

set -e

echo "========================================="
echo "Shaw Dict Installer"
echo "========================================="
echo ""

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Install dictionaries
echo "Installing dictionaries to ~/Library/Dictionaries..."
mkdir -p "$HOME/Library/Dictionaries"
if [ -d "$SCRIPT_DIR/Dictionaries" ]; then
    cp -R "$SCRIPT_DIR/Dictionaries/"*.dictionary "$HOME/Library/Dictionaries/" 2>/dev/null || true
    echo "  ✓ Dictionaries installed"
fi

# Install Hunspell dictionaries
echo "Installing Hunspell dictionaries to ~/Library/Spelling..."
mkdir -p "$HOME/Library/Spelling"
if [ -d "$SCRIPT_DIR/Hunspell" ]; then
    cp "$SCRIPT_DIR/Hunspell/"*.{dic,aff} "$HOME/Library/Spelling/" 2>/dev/null || true
    echo "  ✓ Hunspell dictionaries installed"
fi

# Install spell server
echo "Installing spell server to ~/Library/Services..."
mkdir -p "$HOME/Library/Services"
if [ -d "$SCRIPT_DIR/Spell Server/ShavianSpellServer.service" ]; then
    cp -R "$SCRIPT_DIR/Spell Server/ShavianSpellServer.service" "$HOME/Library/Services/"
    /System/Library/CoreServices/pbs -update 2>/dev/null || true
    echo "  ✓ Spell server installed"

    # Install LaunchAgent
    if [ -f "$SCRIPT_DIR/Spell Server/io.joro.shaw-dict.spellserver.plist" ]; then
        echo "Installing LaunchAgent..."
        mkdir -p "$HOME/Library/LaunchAgents"
        mkdir -p "$HOME/Library/Logs"
        sed "s|__HOME__|$HOME|g" "$SCRIPT_DIR/Spell Server/io.joro.shaw-dict.spellserver.plist" > "$HOME/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist"
        launchctl unload "$HOME/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist" 2>/dev/null || true
        launchctl load "$HOME/Library/LaunchAgents/io.joro.shaw-dict.spellserver.plist"
        echo "  ✓ LaunchAgent installed and started"
    fi
fi

echo ""
echo "========================================="
echo "Installation Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. DICTIONARIES"
echo "   - Restart Dictionary.app (or run: killall Dictionary)"
echo "   - Dictionary > Preferences > enable dictionaries:"
echo "     • Shavian-English (GB) and/or Shavian-English (US)"
echo "     • English-Shavian (GB) and/or English-Shavian (US)"
echo "     • Shavian (GB) and/or Shavian (US)"
echo ""
echo "2. SPELL CHECKING"
echo "   - The spell server is now running automatically"
echo "   - System Settings > Keyboard > Text Input > Edit (next to 'Spelling')"
echo "   - Select 'ShawDict' in the spelling options"
echo "   - Restart any apps to use the new spell checker"
echo ""
echo "3. TEST"
echo "   - Open Dictionary.app and search for '𐑖𐑱𐑝𐑾𐑯' or 'hello'"
echo "   - Open Pages/Notes and type Shavian text to test spell checking"
echo ""
echo "Press any key to exit..."
read -n 1
INSTALLER_SCRIPT

chmod +x "$STAGING_DIR/Install.command"

# Create README
cat > "$STAGING_DIR/README.txt" << 'README'
SHAW DICT

A comprehensive Shavian alphabet dictionary suite for macOS.

CONTENTS:

• Six bilingual dictionaries:
  - Shavian-English (GB): Look up English words from Shavian (British)
  - Shavian-English (US): Look up English words from Shavian (American)
  - English-Shavian (GB): British English to Shavian with definitions
  - English-Shavian (US): American English to Shavian with definitions
  - Shavian (GB): British pronunciation Shavian definitions
  - Shavian (US): American pronunciation Shavian definitions

  Features:
  - 75,000+ word entries with IPA transcriptions
  - Open English WordNet 2024 definitions
  - Regional variants (RP, Gen-Am, Gen-Au)

• Spell-checking service
  - Native NSSpellServer integration
  - Dual-script support (Shavian + Latin)
  - Works with Pages, Notes, TextEdit, etc.

INSTALLATION:

Double-click "Install.command" and follow the on-screen instructions.

REQUIREMENTS:

• macOS 10.10 or later
• ~100MB disk space

MORE INFO:

https://github.com/yourusername/shaw-dict

LICENSE:

See LICENSE file in the repository.

Copyright © 2025. All rights reserved.
README

# Create symbolic link for easier access
ln -sf "Install.command" "$STAGING_DIR/Double-click to Install.command"

# Create DMG
echo "Creating DMG..."
rm -f "$BUILD_DIR/$DMG_NAME"

hdiutil create -volname "$VOLUME_NAME" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    "$BUILD_DIR/$DMG_NAME"

echo ""
echo "========================================="
echo "DMG created: $BUILD_DIR/$DMG_NAME"
echo "========================================="
echo ""
echo "Size: $(du -h "$BUILD_DIR/$DMG_NAME" | cut -f1)"
echo ""
