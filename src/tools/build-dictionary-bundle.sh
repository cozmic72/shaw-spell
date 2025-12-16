#!/bin/bash
# Build a Dictionary.app dictionary bundle
# Usage: build-dictionary-bundle.sh <dict_type> <dialect> <version> <xml_source> <output_dir>

set -e  # Exit on error

DICT_TYPE="$1"      # shavian-english, english-shavian, shavian-shavian
DIALECT="$2"        # gb, us
VERSION="$3"
XML_SOURCE="$4"
OUTPUT_DIR="$5"

if [ -z "$DICT_TYPE" ] || [ -z "$DIALECT" ] || [ -z "$VERSION" ] || [ -z "$XML_SOURCE" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "Usage: build-dictionary-bundle.sh <dict_type> <dialect> <version> <xml_source> <output_dir>"
    exit 1
fi

# Dictionary metadata based on type
case "$DICT_TYPE" in
    shavian-english)
        DISPLAY_NAME="Shavian-English"
        BUNDLE_ID_BASE="shavian-english"
        ;;
    english-shavian)
        DISPLAY_NAME="English-Shavian"
        BUNDLE_ID_BASE="english-shavian"
        ;;
    shavian-shavian)
        DISPLAY_NAME="Shavian"
        BUNDLE_ID_BASE="shavian-shavian"
        ;;
    *)
        echo "Error: Unknown dict_type '$DICT_TYPE'"
        exit 1
        ;;
esac

DICT_NAME="Shaw-Spell-$DISPLAY_NAME-$DIALECT"
BUNDLE_ID="io.joro.shaw-spell.$BUNDLE_ID_BASE-$DIALECT"
BUNDLE_NAME="$DISPLAY_NAME ($(echo $DIALECT | tr a-z A-Z))"

# Paths
SCRIPT_DIR=$(dirname "$0")
DICT_SRC_DIR="$SCRIPT_DIR/../dictionaries"
CSS_PATH="$DICT_SRC_DIR/dictionary.css"
PLIST_TEMPLATE="$DICT_SRC_DIR/dictionary.plist.template"
DESCRIPTION_FILE="$DICT_SRC_DIR/dictionary-description.html"

# Build settings
DICT_BUILD_TOOL_DIR="/Library/Developer/Dictionary Development Kit"
DICT_BUILD_TOOL_BIN="$DICT_BUILD_TOOL_DIR/bin"

# Create temporary directory for build
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

PLIST_PATH="$TEMP_DIR/dictionary.plist"
DESCRIPTION_TMP="$TEMP_DIR/dictionary-description.html"

# Generate plist from template
echo "Generating plist for $DICT_NAME..."
mkdir -p "$(dirname "$PLIST_PATH")"

# First interpolate description with VERSION
"$DICT_SRC_DIR/interpolate_template.py" "$DESCRIPTION_FILE" "$DESCRIPTION_TMP" VERSION="$VERSION"

# Then generate plist with interpolated description
"$DICT_SRC_DIR/interpolate_template.py" "$PLIST_TEMPLATE" "$PLIST_PATH" \
    BUNDLE_ID="$BUNDLE_ID" \
    BUNDLE_NAME="$BUNDLE_NAME" \
    DESCRIPTION="$DESCRIPTION_TMP"

# Set environment variable for Apple's build tool
export DICT_DEV_KIT_OBJ_DIR="$TEMP_DIR/dict_build"
mkdir -p "$DICT_DEV_KIT_OBJ_DIR"

# Build dictionary
echo "Building $DICT_NAME dictionary..."
"$DICT_BUILD_TOOL_BIN/build_dict.sh" "$DICT_NAME" "$XML_SOURCE" "$CSS_PATH" "$PLIST_PATH"

# Move the completed bundle to final location atomically
FINAL_BUNDLE="$OUTPUT_DIR/$DICT_NAME.dictionary"
mkdir -p "$OUTPUT_DIR"

# Remove any existing bundle
rm -rf "$FINAL_BUNDLE"

# Move from temp location to final location
mv "$DICT_DEV_KIT_OBJ_DIR/$DICT_NAME.dictionary" "$FINAL_BUNDLE"

# Touch the bundle to update its timestamp
touch "$FINAL_BUNDLE"

echo "Dictionary bundle created: $FINAL_BUNDLE"
