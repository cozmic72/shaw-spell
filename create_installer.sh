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
if [ -d "dictionaries/shavian-english/objects/Shavian-English.dictionary" ]; then
    cp -R "dictionaries/shavian-english/objects/Shavian-English.dictionary" "$STAGING_DIR/Dictionaries/"
fi
if [ -d "dictionaries/english-shavian/objects/English-Shavian.dictionary" ]; then
    cp -R "dictionaries/english-shavian/objects/English-Shavian.dictionary" "$STAGING_DIR/Dictionaries/"
fi
if [ -d "dictionaries/shavian-shavian/objects/Shavian-Shavian.dictionary" ]; then
    cp -R "dictionaries/shavian-shavian/objects/Shavian-Shavian.dictionary" "$STAGING_DIR/Dictionaries/"
fi

# Copy spell server
echo "Copying spell server..."
if [ -f "src/spellserver/build/ShavianSpellServer.service/Contents/MacOS/ShavianSpellServer" ]; then
    mkdir -p "$STAGING_DIR/Spell Server"
    cp -R "src/spellserver/build/ShavianSpellServer.service" "$STAGING_DIR/Spell Server/"
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
fi

echo ""
echo "========================================="
echo "Installation Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. DICTIONARIES"
echo "   - Open Dictionary.app"
echo "   - Preferences > enable 'Shavian-English', 'English-Shavian', 'Shavian-Shavian'"
echo ""
echo "2. SPELL CHECKING"
echo "   - System Settings > Keyboard > Text Input > Edit (next to 'Spelling')"
echo "   - Select 'British English (ShawDict)' or your preferred variant"
echo "   - Log out and log back in (or restart)"
echo ""
echo "3. TEST"
echo "   - Open Dictionary.app and search for '𐑖𐑱𐑝𐑾𐑯'"
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

• Three bilingual dictionaries (Shavian-English, English-Shavian, Shavian-Shavian)
  - 75,000+ word entries with IPA transcriptions
  - WordNet definitions with examples
  - Regional variant labels (RP, Gen-Am, Gen-Au)

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
