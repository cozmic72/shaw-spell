#!/bin/bash
#
# Creates AppIcon.icns from the uninstaller SVG icon
#

set -e

SVG_SOURCE="src/resources/icon.svg"
BUILD_UNINSTALLER_DIR="../../build/uninstaller"
ICONSET_DIR="$BUILD_UNINSTALLER_DIR/AppIcon.iconset"
ICON_OUTPUT="$BUILD_UNINSTALLER_DIR/AppIcon.icns"

# Check for required tools
if ! command -v rsvg-convert &> /dev/null; then
    echo "Error: rsvg-convert not found."
    echo "Install with: brew install librsvg"
    exit 1
fi

echo "Creating uninstaller icon from $SVG_SOURCE..."

# Create build directory
mkdir -p "$BUILD_UNINSTALLER_DIR"

# Create iconset directory
rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

# Generate all required icon sizes from SVG
echo "Generating PNG files from SVG..."
rsvg-convert -w 16 -h 16 "$SVG_SOURCE" > "$ICONSET_DIR/icon_16x16.png"
rsvg-convert -w 32 -h 32 "$SVG_SOURCE" > "$ICONSET_DIR/icon_16x16@2x.png"
rsvg-convert -w 32 -h 32 "$SVG_SOURCE" > "$ICONSET_DIR/icon_32x32.png"
rsvg-convert -w 64 -h 64 "$SVG_SOURCE" > "$ICONSET_DIR/icon_32x32@2x.png"
rsvg-convert -w 128 -h 128 "$SVG_SOURCE" > "$ICONSET_DIR/icon_128x128.png"
rsvg-convert -w 256 -h 256 "$SVG_SOURCE" > "$ICONSET_DIR/icon_128x128@2x.png"
rsvg-convert -w 256 -h 256 "$SVG_SOURCE" > "$ICONSET_DIR/icon_256x256.png"
rsvg-convert -w 512 -h 512 "$SVG_SOURCE" > "$ICONSET_DIR/icon_256x256@2x.png"
rsvg-convert -w 512 -h 512 "$SVG_SOURCE" > "$ICONSET_DIR/icon_512x512.png"
rsvg-convert -w 1024 -h 1024 "$SVG_SOURCE" > "$ICONSET_DIR/icon_512x512@2x.png"

echo "Converting iconset to icns..."
iconutil -c icns "$ICONSET_DIR" -o "$ICON_OUTPUT"

echo "Cleaning up iconset directory..."
rm -rf "$ICONSET_DIR"

echo "Uninstaller icon created successfully: $ICON_OUTPUT"
