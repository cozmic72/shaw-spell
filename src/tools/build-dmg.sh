#!/bin/bash
# Build DMG for Shaw-Spell installer
# Usage: build-dmg.sh <version> <installer-app> <uninstaller-app> <volume-icon> <ds-store-template> <output-dmg>

set -e

VERSION="$1"
INSTALLER_APP="$2"
UNINSTALLER_APP="$3"
VOLUME_ICON="$4"
DS_STORE_TEMPLATE="$5"
OUTPUT_DMG="$6"

if [ -z "$VERSION" ] || [ -z "$INSTALLER_APP" ] || [ -z "$UNINSTALLER_APP" ] || [ -z "$VOLUME_ICON" ] || [ -z "$OUTPUT_DMG" ]; then
    echo "Usage: build-dmg.sh <version> <installer-app> <uninstaller-app> <volume-icon> <ds-store-template> <output-dmg>"
    exit 1
fi

VOLUME_NAME="Shaw-Spell-${VERSION}"
TEMP_DMG="${OUTPUT_DMG%.dmg}-temp.dmg"

# Remove any existing DMG files
rm -f "$TEMP_DMG" "$OUTPUT_DMG"

# Create empty DMG (500MB should be plenty for dictionaries)
echo "Creating empty DMG..."
hdiutil create \
    -volname "$VOLUME_NAME" \
    -size 500m \
    -fs HFS+ \
    -type UDIF \
    "$TEMP_DMG"

# Mount the DMG
echo "Mounting DMG..."
MOUNT_POINT="$(mktemp -d)"
trap "hdiutil detach '$MOUNT_POINT' 2>/dev/null || true; rm -rf '$MOUNT_POINT'" EXIT

hdiutil attach "$TEMP_DMG" \
    -mountpoint "$MOUNT_POINT" \
    -nobrowse \
    -noverify \
    -noautoopen

# Copy apps into the mounted DMG
echo "Copying installer and uninstaller into DMG..."
cp -R "$INSTALLER_APP" "$MOUNT_POINT/"
cp -R "$UNINSTALLER_APP" "$MOUNT_POINT/"

# Customize DMG appearance
if [ -f "$DS_STORE_TEMPLATE" ]; then
    echo "Copying .DS_Store template..."
    cp "$DS_STORE_TEMPLATE" "$MOUNT_POINT/.DS_Store"
fi

echo "Setting volume icon..."
cp "$VOLUME_ICON" "$MOUNT_POINT/.VolumeIcon.icns"
SetFile -a C "$MOUNT_POINT"

# Unmount
echo "Unmounting DMG..."
hdiutil detach "$MOUNT_POINT"

# Convert to compressed read-only DMG
echo "Converting to compressed DMG..."
hdiutil convert "$TEMP_DMG" -format UDZO -o "$OUTPUT_DMG"

# Clean up temp DMG
rm -f "$TEMP_DMG"

# Set custom icon on the DMG file itself
echo "Setting custom icon on DMG..."
BUILD_DIR="$(dirname "$OUTPUT_DMG")"
TEMP_ICON="$BUILD_DIR/.VolumeIcon.tmp.icns"
TEMP_RSRC="$BUILD_DIR/.VolumeIcon.rsrc"

cp "$VOLUME_ICON" "$TEMP_ICON"
sips -i "$TEMP_ICON" >/dev/null
DeRez -only icns "$TEMP_ICON" > "$TEMP_RSRC"
Rez -append "$TEMP_RSRC" -o "$OUTPUT_DMG"
SetFile -a C "$OUTPUT_DMG"
rm -f "$TEMP_ICON" "$TEMP_RSRC"

echo "✓ DMG created: $OUTPUT_DMG"
