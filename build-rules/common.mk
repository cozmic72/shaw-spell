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

# Idempotent replace of one or more asset subdirs during a privileged deploy.
# Both install-editor and install-site hand-rolled the same "sudo rm -rf the old
# copy, then sudo cp -R the new one" idiom to stage web/opt asset trees — it is
# the single most-duplicated deploy step. This canned recipe factors it (DRY),
# in the same $(@D)-style parametrised-recipe spirit as virtual-keyboard.mk.
#
# It is designed to $(call) INTO a single-shell `@set -eu; \ ...` recipe: every
# body line is backslash-continued, so the whole loop collapses to one recipe
# line and splices between the caller's own `; \`-joined statements (put a `; \`
# after the $(call)). Call as:
#   $(call replace-dir-tree,SRC_BASE,DEST_BASE,dir1 dir2 ...)
# where each `dirN` is copied from SRC_BASE/dirN to DEST_BASE/dirN. Pass a shell
# variable (e.g. $$HERE) for either base to defer it to run time; pass a make
# path to expand it now.
define replace-dir-tree
	for d in $(3); do \
	  sudo rm -rf "$(2)/$$d"; \
	  sudo cp -R "$(1)/$$d" "$(2)/$$d"; \
	done
endef

# The external Roman->Shavian transliterator (github.com/Shavian-info/shave),
# invoked as a bare binary by seven call sites. Four of them CATCH
# FileNotFoundError and carry on with an empty result, so a missing shave does
# not stop the build — it silently produces a pool with every shave
# consultation dropped. That is why require-shave exists and why it is a
# prerequisite of every target whose recipe can reach a shave call site: the
# only reliable moment to detect the absence is before the build starts.
SHAVE ?= shave

.PHONY: require-shave
require-shave:
	@command -v $(SHAVE) >/dev/null 2>&1 || { \
	  echo "$(SHAVE): not found on \$$PATH." >&2; \
	  echo "  The supplement generators transliterate Roman to Shavian by" >&2; \
	  echo "  shelling out to it, and most of them treat its absence as an" >&2; \
	  echo "  empty result — the build would SUCCEED and produce an" >&2; \
	  echo "  under-transliterated pool." >&2; \
	  echo "  Build and install it from https://github.com/Shavian-info/shave," >&2; \
	  echo "  or set SHAVE=/path/to/shave. See README.md, 'The bootstrap cycle'." >&2; \
	  exit 1; }

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

BUILD_ICONS := $(BUILD_ROOT)/icons

# All build directories that need to be created
BUILD_DIRS := $(BUILD_DICT_XML) $(BUILD_DICT_PLISTS) $(BUILD_DICT_BUNDLES) \
              $(BUILD_HUNSPELL) $(BUILD_SERVER_OBJS) \
              $(BUILD_INSTALLER_OBJS) $(BUILD_INSTALLER_RES) \
              $(BUILD_UNINSTALLER_OBJS) $(BUILD_UNINSTALLER_RES) \
              $(BUILD_DMG) $(BUILD_ICONS)

# Create all build directories
$(BUILD_DIRS):
	@mkdir -p $@

# Source directories
SRC_DICTIONARIES := src/dictionaries
SRC_SERVER := src/server
SRC_INSTALLER := src/installer
SRC_UNINSTALLER := src/uninstaller
SRC_SITE := src/site
SRC_SITE_DAEMON := src/site-daemon
SRC_EDITOR := src/editor
SRC_TOOLS := src/tools
SRC_FONTS := src/fonts
SRC_IMAGES := src/images
SRC_TEST := src/test

# External dependencies
READLEX_PATH := data/readlex.json
WORDNET_CACHE := data/wordnet-comprehensive.json

# The editor daemon's RUNTIME frequency inputs — the publish step (the Commit
# button) refuses to run without them, so any target that needs them at build
# time or deploys the daemon must police them. The corpus is repo-relative
# (lean-checkout submodule; `make setup` materialises it — rule in
# supplements.mk). The LRW list is DATA-ROOT-relative: it ships INSIDE the data
# clone, so it resolves under data/ here and under DATA_DIR on a deployed box.
FREQUENCY_CORPUS := external/frequency-words/content/2018/en/en_full.txt
LRW_LIST := bncfreq/1_1_all_fullalpha.txt

# Common tools
SIGN_BUNDLE := $(SRC_TOOLS)/sign-bundle.sh
BUILD_DMG_TOOL := $(SRC_TOOLS)/build-dmg.sh
BUILD_DICT_BUNDLE := $(SRC_TOOLS)/build-dictionary-bundle.sh

# Baked into the pages' @font-face at build time. The local default is what
# makes a fresh checkout serve its own fonts; production supplies the shared
# origin on the deploy invocation:
#   make install-site FONT_URL=https://joro.io/fonts
FONT_URL ?= /fonts
export FONT_URL

# Load signing configuration if it exists
-include .signing-config
