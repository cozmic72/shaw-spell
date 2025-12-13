#!/bin/bash
#
# Build script for Shavian dictionaries
#
# Usage:
#   ./build.sh                        - Generate XML and build all dictionaries
#   ./build.sh shavian-english        - Build only Shavian-English dictionary
#   ./build.sh english-shavian shavian-shavian - Build specific dictionaries
#   ./build.sh install                - Build all and install to ~/Library/Dictionaries
#   ./build.sh shavian-english install - Build one and install
#   ./build.sh --rebuild-cache        - Rebuild Shavian definition cache first
#   ./build.sh clean                  - Clean build artifacts
#   ./build.sh clean-cache            - Clean definition caches
#
# Build process:
#   1. Check/build Shavian definition cache (src/build_definition_caches.py)
#   2. Generate dictionary XML files (src/generate_dictionaries.py)
#   3. Build .dictionary bundles (Apple's build_dict.sh)
#   4. Optionally install to ~/Library/Dictionaries
#

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo_step() {
    echo -e "${BLUE}==>${NC} $1"
}

echo_success() {
    echo -e "${GREEN}✓${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}Warning:${NC} $1"
}

# Clean build artifacts
if [ "$1" = "clean" ]; then
    echo_step "Cleaning build artifacts..."
    rm -rf build/*.xml
    rm -rf dictionaries/*/objects
    echo_success "Clean complete"
    exit 0
fi

# Clean definition caches
if [ "$1" = "clean-cache" ]; then
    echo_step "Cleaning definition caches..."
    rm -f data/definitions-shavian.json
    rm -f data/transliterations.json  # Old cache format
    echo_success "Cache clean complete"
    echo "Run ./build.sh to rebuild caches"
    exit 0
fi

# Parse arguments
DICTIONARIES=()
INSTALL_FLAG=""
REBUILD_CACHE=""

for arg in "$@"; do
    case "$arg" in
        install)
            INSTALL_FLAG="install"
            ;;
        --rebuild-cache)
            REBUILD_CACHE="--force"
            ;;
        shavian-english|english-shavian|shavian-shavian)
            DICTIONARIES+=("$arg")
            ;;
    esac
done

# Default to all dictionaries if none specified
if [ ${#DICTIONARIES[@]} -eq 0 ]; then
    DICTIONARIES=("shavian-english" "english-shavian" "shavian-shavian")
fi

# Build list of dictionaries to generate
DICT_ARGS=""
for dict in "${DICTIONARIES[@]}"; do
    DICT_ARGS="$DICT_ARGS --dict $dict"
done

# Step 0: Check/build Shavian definition cache (if needed)
NEEDS_CACHE=false
for dict in "${DICTIONARIES[@]}"; do
    if [[ "$dict" = "english-shavian" || "$dict" = "shavian-shavian" ]]; then
        NEEDS_CACHE=true
        break
    fi
done

if [ "$NEEDS_CACHE" = true ]; then
    if [ ! -f "data/definitions-shavian.json" ] || [ -n "$REBUILD_CACHE" ]; then
        echo_step "Building Shavian definition cache..."
        ./src/build_definition_caches.py $REBUILD_CACHE
        echo_success "Cache build complete"
        echo ""
    fi
fi

# Step 1: Generate XML files
echo_step "Generating dictionary XML files..."
./src/generate_dictionaries.py $DICT_ARGS
echo_success "XML generation complete"

# Step 2: Build each specified dictionary
for dict in "${DICTIONARIES[@]}"; do
    echo_step "Building $dict dictionary..."
    cd "dictionaries/$dict"
    make clean > /dev/null 2>&1 || true
    make
    echo_success "$dict dictionary built"
    cd "$SCRIPT_DIR"
done

# Step 3: Install if requested
if [ -n "$INSTALL_FLAG" ]; then
    echo_step "Installing dictionaries to ~/Library/Dictionaries..."

    for dict in "${DICTIONARIES[@]}"; do
        cd "dictionaries/$dict"
        make install
        cd "$SCRIPT_DIR"
    done

    echo_success "Installation complete!"
    echo ""
    echo "Installed dictionaries to ~/Library/Dictionaries:"
    for dict in "${DICTIONARIES[@]}"; do
        echo "  - $dict"
    done
    echo ""
    echo "Please restart Dictionary.app to use them."
else
    echo ""
    if [ ${#DICTIONARIES[@]} -eq 1 ]; then
        echo "${DICTIONARIES[0]} dictionary built successfully!"
    else
        echo "All ${#DICTIONARIES[@]} dictionaries built successfully!"
    fi
    echo "To install, run: ./build.sh ${DICTIONARIES[@]} install"
fi
