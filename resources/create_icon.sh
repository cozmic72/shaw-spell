#!/bin/bash
# Create macOS icon from SVG

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SVG_FILE="$SCRIPT_DIR/icon.svg"
ICONSET_DIR="$SCRIPT_DIR/AppIcon.iconset"

# Check for required tools
if ! command -v rsvg-convert &> /dev/null; then
    echo "Error: rsvg-convert not found. Install with: brew install librsvg"
    exit 1
fi

# Create iconset directory
rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

echo "Generating PNG files from SVG..."

# Generate all required icon sizes
rsvg-convert -w 16 -h 16 "$SVG_FILE" > "$ICONSET_DIR/icon_16x16.png"
rsvg-convert -w 32 -h 32 "$SVG_FILE" > "$ICONSET_DIR/icon_16x16@2x.png"
rsvg-convert -w 32 -h 32 "$SVG_FILE" > "$ICONSET_DIR/icon_32x32.png"
rsvg-convert -w 64 -h 64 "$SVG_FILE" > "$ICONSET_DIR/icon_32x32@2x.png"
rsvg-convert -w 128 -h 128 "$SVG_FILE" > "$ICONSET_DIR/icon_128x128.png"
rsvg-convert -w 256 -h 256 "$SVG_FILE" > "$ICONSET_DIR/icon_128x128@2x.png"
rsvg-convert -w 256 -h 256 "$SVG_FILE" > "$ICONSET_DIR/icon_256x256.png"
rsvg-convert -w 512 -h 512 "$SVG_FILE" > "$ICONSET_DIR/icon_256x256@2x.png"
rsvg-convert -w 512 -h 512 "$SVG_FILE" > "$ICONSET_DIR/icon_512x512.png"
rsvg-convert -w 1024 -h 1024 "$SVG_FILE" > "$ICONSET_DIR/icon_512x512@2x.png"

echo "Creating .icns file..."
iconutil -c icns "$ICONSET_DIR" -o "$SCRIPT_DIR/ShawDict.icns"

echo "Icon created: $SCRIPT_DIR/ShawDict.icns"

# Cleanup
rm -rf "$ICONSET_DIR"
