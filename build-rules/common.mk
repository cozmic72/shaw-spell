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

# Idempotent replace of one or more asset subdirs during a deploy.
# Both install-editor and install-site hand-rolled the same "rm -rf the old
# copy, then cp -R the new one" idiom to stage web/opt asset trees — it is
# the single most-duplicated deploy step. This canned recipe factors it (DRY),
# in the same $(@D)-style parametrised-recipe spirit as shaw-keys.mk.
#
# It is designed to $(call) INTO a single-shell `@set -eu; \ ...` recipe: every
# body line is backslash-continued, so the whole loop collapses to one recipe
# line and splices between the caller's own `; \`-joined statements (put a `; \`
# after the $(call)). Call as:
#   $(call replace-dir-tree,SRC_BASE,DEST_BASE,dir1 dir2 ...[,PRIVILEGE])
# where each `dirN` is copied from SRC_BASE/dirN to DEST_BASE/dirN. Pass a shell
# variable (e.g. $$HERE) for either base to defer it to run time; pass a make
# path to expand it now. PRIVILEGE prefixes each command: `sudo` when installing
# to a system path, empty (omitted) for a destination the build user owns.
define replace-dir-tree
	for d in $(3); do \
	  $(4) rm -rf "$(2)/$$d"; \
	  $(4) cp -R "$(1)/$$d" "$(2)/$$d"; \
	done
endef

# Privilege escalation, behind variables so a deploy to a destination the
# invoking user owns can run unprivileged: `make install-site SUDO= RUN_AS= ...`.
# RUN_AS is separate because an empty SUDO would leave a bare `-u $(SERVICE_USER)`
# on the line rather than dropping the escalation.
SUDO ?= sudo
RUN_AS ?= sudo -u $(SERVICE_USER)

# $(call require-submodule-not-ahead,PATH,CONTEXT)
# Not a precondition — a refusal to destroy work. `git submodule update` checks
# the pin out unconditionally, so any commit the checkout has that the pin
# cannot reach is discarded without a word. Those commits are the owner's, and
# losing them is not a cost this target gets to accept. It belongs immediately
# before the update it guards, not in a survey phase.
#
# The question is "what would be lost", i.e. `pin..head` — NOT "is the pin an
# ancestor". A diverged checkout loses commits too, and an ancestor test calls
# that case safe.
#
# $(call)ed into a single-shell `@set -eu; \ ...` recipe, like replace-dir-tree
# above: every body line is backslash-continued, so the call collapses to one
# recipe line. Put a `; \` after the $(call).
define require-submodule-not-ahead
	pin="$$(git rev-parse "HEAD:$(1)")"; \
	head="$$(git -C "$(1)" rev-parse HEAD)"; \
	lost="$$(git -C "$(1)" --no-pager log --no-color --oneline "$$pin..$$head")"; \
	if [ -n "$$lost" ]; then \
	  echo "$(2): the $(1) submodule holds commits the pinned commit cannot reach." >&2; \
	  echo "  pinned:   $$pin" >&2; \
	  echo "  checkout: $$head" >&2; \
	  echo "  Updating it would discard these commits:" >&2; \
	  printf '%s\n' "$$lost" | sed 's/^/    /' >&2; \
	  echo "  Push them, then advance the pin:" >&2; \
	  echo "    git -C $(1) push && git add $(1) && git commit -m 'Advance $(1) pin'" >&2; \
	  exit 1; \
	fi
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

# Overridable so a deploy aimed at a temp docroot stages somewhere private
# rather than clobbering the working site the dev server is serving.
BUILD_SITE ?= $(BUILD_ROOT)/site

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

# Per-machine, untracked, never committed. See the .example files for the keys.
-include .signing-config
-include .site-config

# .site-config's font URL is for deploys only; every other build serves its own
# fonts from /fonts. `:=` captures the value now, before the pin below discards
# it — `?=` would defer the reference and read back /fonts.
ifeq ($(origin FONT_URL),file)
ifeq ($(origin DEPLOY_FONT_URL),undefined)
DEPLOY_FONT_URL := $(FONT_URL)
endif
endif

# `-include` has already run, so `?=` would let .site-config's value through as
# the local default. Only the command line outranks it.
ifneq ($(origin FONT_URL),command line)
FONT_URL := /fonts
endif

# Staging runs as a prerequisite of install-site and bakes the URL in, so a
# recipe guard fires too late. Validate at parse time.
ifneq ($(filter install-site,$(MAKECMDGOALS)),)
ifeq ($(origin FONT_URL),command line)
DEPLOY_FONT_URL := $(FONT_URL)
endif
ifeq ($(strip $(DEPLOY_FONT_URL)),)
$(error install-site: no deploy font URL. Set FONT_URL in .site-config, or pass \
FONT_URL=<url> on this command line. See .site-config.example)
endif
ifeq ($(DEPLOY_FONT_URL),/fonts)
$(error install-site: the deploy font URL is /fonts, the local default. Staging \
bakes it into the pages and the server has no /fonts to serve. Set the shared \
origin in .site-config — see .site-config.example)
endif
FONT_URL := $(DEPLOY_FONT_URL)
endif
