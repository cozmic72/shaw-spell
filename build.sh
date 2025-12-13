#!/bin/bash
#
# Build script for Shavian language tools (dictionaries and spell-check)
#

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
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

show_help() {
    echo -e "${BOLD}Shavian Language Tools Build Script${NC}\n"
    echo -e "${BOLD}USAGE:${NC}"
    echo -e "    ./build.sh [OPTIONS] [DICTIONARIES...] [COMMAND]\n"
    echo -e "${BOLD}DICTIONARIES (build specific dictionaries):${NC}"
    echo -e "    shavian-english         Shavian → English dictionary"
    echo -e "    english-shavian         English → Shavian dictionary"
    echo -e "    shavian-shavian         Shavian → Shavian dictionary\n"
    echo -e "    ${BLUE}Default:${NC} All three dictionaries if none specified\n"
    echo -e "${BOLD}COMMANDS:${NC}"
    echo -e "    install                 Build and install to ~/Library/Dictionaries"
    echo -e "                            (Must restart Dictionary.app after install)\n"
    echo -e "    spellcheck              Generate Hunspell spell-check files"
    echo -e "    spellcheck install      Generate and install to ~/Library/Spelling\n"
    echo -e "    clean                   Remove build artifacts (*.xml, objects/)"
    echo -e "    clean-cache             Remove definition caches"
    echo -e "    clean-all               Remove all build artifacts and caches\n"
    echo -e "    -h, --help             Show this help message\n"
    echo -e "${BOLD}OPTIONS:${NC}"
    echo -e "    --rebuild-cache        Force rebuild of Shavian definition cache"
    echo -e "    --gb                   Build British English (GB) variant (default)"
    echo -e "    --us                   Build American English (US) variant\n"
    echo -e "${BOLD}EXAMPLES:${NC}"
    echo -e "    # Build all dictionaries (GB variant, default)"
    echo -e "    ./build.sh\n"
    echo -e "    # Build US variant"
    echo -e "    ./build.sh --us\n"
    echo -e "    # Build and install GB variant"
    echo -e "    ./build.sh --gb install\n"
    echo -e "    # Build and install only Shavian-English"
    echo -e "    ./build.sh shavian-english install\n"
    echo -e "    # Build specific dictionaries"
    echo -e "    ./build.sh english-shavian shavian-shavian\n"
    echo -e "    # Force rebuild cache, then build all"
    echo -e "    ./build.sh --rebuild-cache\n"
    echo -e "    # Generate spell-check files"
    echo -e "    ./build.sh spellcheck\n"
    echo -e "    # Install spell-check files"
    echo -e "    ./build.sh spellcheck install\n"
    echo -e "    # Clean everything"
    echo -e "    ./build.sh clean-all\n"
    echo -e "${BOLD}BUILD PROCESS:${NC}"
    echo -e "    Dictionaries:"
    echo -e "      1. Check/build Shavian definition cache (src/build_definition_caches.py)"
    echo -e "      2. Generate dictionary XML files (src/generate_dictionaries.py)"
    echo -e "      3. Build .dictionary bundles (Apple's build_dict.sh)"
    echo -e "      4. Optionally install to ~/Library/Dictionaries\n"
    echo -e "    Spell-check:"
    echo -e "      1. Generate Hunspell files from readlex (src/generate_spellcheck.py)"
    echo -e "      2. Optionally install to ~/Library/Spelling\n"
    echo -e "${BOLD}DATA SOURCES:${NC}"
    echo -e "    - readlex.json:     Shavian word list with pronunciations"
    echo -e "    - WordNet:          English definitions (Open English WordNet 2024)\n"
    echo -e "${BOLD}MORE INFO:${NC}"
    echo -e "    See README.txt for detailed documentation"
}

# Show help and exit
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Handle spellcheck command
if [ "$1" = "spellcheck" ]; then
    echo_step "Generating Hunspell spell-check files..."
    ./src/generate_spellcheck.py
    echo_success "Spell-check files generated"

    # Install if requested
    if [ "$2" = "install" ]; then
        echo_step "Installing to ~/Library/Spelling..."
        mkdir -p ~/Library/Spelling
        cp build/shaw.dic ~/Library/Spelling/
        cp build/shaw.aff ~/Library/Spelling/
        echo_success "Installation complete!"
        echo ""
        echo "Shavian spell-check installed to ~/Library/Spelling"
        echo "Restart applications to use the new dictionary"
    fi
    exit 0
fi

# Clean build artifacts
if [ "$1" = "clean" ]; then
    echo_step "Cleaning build artifacts..."
    rm -rf build/*.xml
    rm -rf build/shaw.dic
    rm -rf build/shaw.aff
    rm -rf dictionaries/*/objects
    echo_success "Clean complete"
    exit 0
fi

# Clean definition caches
if [ "$1" = "clean-cache" ]; then
    echo_step "Cleaning definition caches..."
    rm -f data/definitions-shavian-gb.json
    rm -f data/definitions-shavian-us.json
    rm -f data/definitions-shavian.json  # Old format
    rm -f data/transliterations.json  # Old cache format
    echo_success "Cache clean complete"
    echo "Run ./build.sh to rebuild caches"
    exit 0
fi

# Clean all
if [ "$1" = "clean-all" ]; then
    echo_step "Cleaning all build artifacts and caches..."
    rm -rf build/*.xml
    rm -rf build/shaw.dic
    rm -rf build/shaw.aff
    rm -rf dictionaries/*/objects
    rm -f data/definitions-shavian-gb.json
    rm -f data/definitions-shavian-us.json
    rm -f data/definitions-shavian.json
    rm -f data/transliterations.json
    echo_success "Complete clean finished"
    exit 0
fi

# Parse arguments
DICTIONARIES=()
INSTALL_FLAG=""
REBUILD_CACHE=""
DIALECT="gb"  # Default to GB

for arg in "$@"; do
    case "$arg" in
        install)
            INSTALL_FLAG="install"
            ;;
        --rebuild-cache)
            REBUILD_CACHE="--force"
            ;;
        --gb)
            DIALECT="gb"
            ;;
        --us)
            DIALECT="us"
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
    CACHE_FILE="data/definitions-shavian-${DIALECT}.json"
    if [ ! -f "$CACHE_FILE" ] || [ -n "$REBUILD_CACHE" ]; then
        echo_step "Building Shavian definition cache ($(echo $DIALECT | tr '[:lower:]' '[:upper:]'))..."
        ./src/build_definition_caches.py --${DIALECT} $REBUILD_CACHE
        echo_success "Cache build complete"
        echo ""
    fi
fi

# Step 1: Generate XML files
echo_step "Generating dictionary XML files ($(echo $DIALECT | tr '[:lower:]' '[:upper:]'))..."
./src/generate_dictionaries.py --${DIALECT} $DICT_ARGS
echo_success "XML generation complete"

# Step 2: Build each specified dictionary
for dict in "${DICTIONARIES[@]}"; do
    echo_step "Building $dict dictionary ($(echo $DIALECT | tr '[:lower:]' '[:upper:]'))..."
    cd "dictionaries/$dict"
    make clean > /dev/null 2>&1 || true
    make DIALECT=${DIALECT}
    echo_success "$dict dictionary built"
    cd "$SCRIPT_DIR"
done

# Step 3: Install if requested
if [ -n "$INSTALL_FLAG" ]; then
    echo_step "Installing dictionaries to ~/Library/Dictionaries ($(echo $DIALECT | tr '[:lower:]' '[:upper:]'))..."

    for dict in "${DICTIONARIES[@]}"; do
        cd "dictionaries/$dict"
        make DIALECT=${DIALECT} install
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
        echo "${DICTIONARIES[0]} dictionary ($(echo $DIALECT | tr '[:lower:]' '[:upper:]')) built successfully!"
    else
        echo "All ${#DICTIONARIES[@]} dictionaries ($(echo $DIALECT | tr '[:lower:]' '[:upper:]')) built successfully!"
    fi
    echo "To install, run: ./build.sh --${DIALECT} ${DICTIONARIES[@]} install"
fi
