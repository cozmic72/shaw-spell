#!/bin/bash
# Code sign a bundle or library with proper hardened runtime flags
# Usage: sign-bundle.sh [bundle|library] <path> [entitlements_file]

set -e  # Exit on error

TYPE="$1"
TARGET="$2"
ENTITLEMENTS="$3"

if [ -z "$TYPE" ] || [ -z "$TARGET" ]; then
    echo "Usage: sign-bundle.sh [bundle|library] <path> [entitlements_file]"
    exit 1
fi

# Load signing configuration if available
# Look for .signing-config in the repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ -f "$REPO_ROOT/.signing-config" ]; then
    source "$REPO_ROOT/.signing-config"
fi

# Check if we have a signing identity configured
if [ -z "$CODESIGN_IDENTITY" ]; then
    echo "Skipping code signing (no identity configured in .signing-config)"
    exit 0
fi

echo "Code signing $TYPE with: $CODESIGN_IDENTITY"

case "$TYPE" in
    bundle)
        if [ -n "$ENTITLEMENTS" ] && [ -f "$ENTITLEMENTS" ]; then
            codesign --force --options runtime --timestamp --sign "$CODESIGN_IDENTITY" --entitlements "$ENTITLEMENTS" "$TARGET"
        else
            codesign --force --options runtime --timestamp --sign "$CODESIGN_IDENTITY" "$TARGET"
        fi
        ;;
    library)
        codesign --force --options runtime --timestamp --sign "$CODESIGN_IDENTITY" "$TARGET"
        ;;
    *)
        echo "Error: TYPE must be 'bundle' or 'library'"
        exit 1
        ;;
esac

echo "Code signing complete: $TARGET"
