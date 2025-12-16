# Common build definitions and directory structure
# This file is included by the main Makefile and all build-rules/*.mk files

# Quiet build mode for troubleshooting parallel builds
# By default, shows all output
# Use QUIET=1 to suppress tool output and only see progress messages
# Usage: $(RUN) command args...
ifdef QUIET
RUN = @$(SRC_TOOLS)/run-quiet.sh
else
RUN =
endif

# Version from root
VERSION := $(shell cat current-version | tr -d '\n')
export VERSION

# Build directory structure
BUILD_ROOT := build

# Organized subdirectories
BUILD_DICTIONARIES := $(BUILD_ROOT)/dictionaries
BUILD_DICT_XML := $(BUILD_DICTIONARIES)/xml
BUILD_DICT_PLISTS := $(BUILD_DICTIONARIES)/plists
BUILD_DICT_BUNDLES := $(BUILD_DICTIONARIES)/bundles

BUILD_SPELLCHECK := $(BUILD_ROOT)/spellcheck
BUILD_HUNSPELL := $(BUILD_SPELLCHECK)/hunspell
BUILD_SERVER_OBJS := $(BUILD_SPELLCHECK)/server-objects
BUILD_SERVER_BUNDLE := $(BUILD_SPELLCHECK)/Shaw-Spell.service

BUILD_INSTALLER := $(BUILD_ROOT)/installer
BUILD_INSTALLER_OBJS := $(BUILD_INSTALLER)/objects
BUILD_INSTALLER_RES := $(BUILD_INSTALLER)/resources
BUILD_INSTALLER_APP := $(BUILD_INSTALLER)/Install Shaw-Spell.app

BUILD_UNINSTALLER := $(BUILD_ROOT)/uninstaller
BUILD_UNINSTALLER_OBJS := $(BUILD_UNINSTALLER)/objects
BUILD_UNINSTALLER_RES := $(BUILD_UNINSTALLER)/resources
BUILD_UNINSTALLER_APP := $(BUILD_UNINSTALLER)/Uninstall Shaw-Spell.app

BUILD_DMG := $(BUILD_ROOT)/dmg
BUILD_DMG_STAGING := $(BUILD_DMG)/staging
BUILD_DMG_FILE := $(BUILD_DMG)/Shaw-Spell-$(VERSION).dmg

BUILD_SITE := $(BUILD_ROOT)/site
BUILD_SITE_DATA := $(BUILD_ROOT)/site-data

BUILD_ICONS := $(BUILD_ROOT)/icons

# All build directories that need to be created
BUILD_DIRS := $(BUILD_DICT_XML) $(BUILD_DICT_PLISTS) $(BUILD_DICT_BUNDLES) \
              $(BUILD_HUNSPELL) $(BUILD_SERVER_OBJS) \
              $(BUILD_INSTALLER_OBJS) $(BUILD_INSTALLER_RES) \
              $(BUILD_UNINSTALLER_OBJS) $(BUILD_UNINSTALLER_RES) \
              $(BUILD_DMG) $(BUILD_SITE_DATA) $(BUILD_ICONS)

# Create all build directories
$(BUILD_DIRS):
	@mkdir -p $@

# Source directories
SRC_DICTIONARIES := src/dictionaries
SRC_SERVER := src/server
SRC_INSTALLER := src/installer
SRC_UNINSTALLER := src/uninstaller
SRC_SITE := src/site
SRC_TOOLS := src/tools
SRC_FONTS := src/fonts
SRC_IMAGES := src/images
SRC_TEST := src/test

# External dependencies
READLEX_PATH := external/readlex/readlex.json
WORDNET_CACHE := data/wordnet-comprehensive.json

# Common tools
SIGN_BUNDLE := $(SRC_TOOLS)/sign-bundle.sh
BUILD_DMG_TOOL := $(SRC_TOOLS)/build-dmg.sh
BUILD_DICT_BUNDLE := $(SRC_TOOLS)/build-dictionary-bundle.sh

# Font URL for web frontend (can be overridden for CDN hosting)
FONT_URL ?= /fonts
export FONT_URL

# Load site deployment configuration if it exists (for site-tarball)
-include .site-config

# Load signing configuration if it exists
-include .signing-config
