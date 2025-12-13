#!/bin/bash
#
# Build script for Shavian dictionaries
#
# Usage:
#   ./build.sh              - Generate XML and build dictionaries
#   ./build.sh install      - Build and install to ~/Library/Dictionaries
#   ./build.sh clean        - Clean build artifacts
#

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_step() {
    echo -e "${BLUE}==>${NC} $1"
}

echo_success() {
    echo -e "${GREEN}✓${NC} $1"
}

# Clean build artifacts
if [ "$1" = "clean" ]; then
    echo_step "Cleaning build artifacts..."
    rm -rf build/*.xml
    rm -rf dictionaries/*/objects
    echo_success "Clean complete"
    exit 0
fi

# Step 1: Generate XML files
echo_step "Generating dictionary XML files..."
./src/generate_dictionaries.py
echo_success "XML generation complete"

# Step 2: Build Shavian-English dictionary
echo_step "Building Shavian-English dictionary..."
cd dictionaries/shavian-english
make clean > /dev/null 2>&1 || true
make
echo_success "Shavian-English dictionary built"
cd "$SCRIPT_DIR"

# Step 3: Build English-Shavian dictionary
echo_step "Building English-Shavian dictionary..."
cd dictionaries/english-shavian
make clean > /dev/null 2>&1 || true
make
echo_success "English-Shavian dictionary built"
cd "$SCRIPT_DIR"

# Step 4: Install if requested
if [ "$1" = "install" ]; then
    echo_step "Installing dictionaries to ~/Library/Dictionaries..."

    cd dictionaries/shavian-english
    make install
    cd "$SCRIPT_DIR"

    cd dictionaries/english-shavian
    make install
    cd "$SCRIPT_DIR"

    echo_success "Installation complete!"
    echo ""
    echo "The dictionaries have been installed to ~/Library/Dictionaries"
    echo "Please restart Dictionary.app to use them."
else
    echo ""
    echo "Dictionaries built successfully!"
    echo "To install, run: ./build.sh install"
fi
