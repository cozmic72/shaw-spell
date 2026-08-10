# Shaw Keys assets — copied from the external/shaw-keys submodule into each web
# docroot so the daemons serve them at /shaw-keys/... The submodule is the
# source of truth; these dirs are generated and gitignored.
# Stamp files gate idempotent copies on submodule changes (mirrors shave).

SK_SRC := external/shaw-keys

SK_SITE_DEST   := $(SRC_SITE)/shaw-keys
SK_EDITOR_DEST  := $(SRC_EDITOR)/site/shaw-keys

# stage.sh bakes $(FONT_URL) into the staged CSS, so the value is part of what
# the stamp attests — not just the library source. Naming the stamp after the
# URL is what makes a switch rebuild: staging with /fonts and then installing
# with the production origin finds no stamp for that URL and restages, where a
# fixed name would look up to date and ship the local URL to production.
SK_FONT_URL_TAG = $(shell printf '%s' '$(FONT_URL)' | shasum | cut -c1-12)
SK_SITE_STAMP   = $(SK_SITE_DEST)/.stamp-$(SK_FONT_URL_TAG)
SK_EDITOR_STAMP = $(SK_EDITOR_DEST)/.stamp-$(SK_FONT_URL_TAG)

# The shared modal wrapper. The site serves it from its own tree at /js/, but the
# editor's docroot IS $(SRC_EDITOR)/site, served live rather than copied, and the
# page imports it from the docroot ROOT — so the editor needs it staged there.
# A symlink, not a copy: one source of truth, nothing that can drift.
SK_WRAPPER_SRC    := $(SRC_SITE)/js/shaw-keys-modal.js
SK_EDITOR_WRAPPER := $(SRC_EDITOR)/site/shaw-keys-modal.js

.PHONY: shaw-keys
shaw-keys: $(SK_SITE_STAMP) $(SK_EDITOR_STAMP) $(SK_EDITOR_WRAPPER)

# Both docroots stage identically: the stamp's own directory ($(@D)) is the
# dest, so one canned recipe serves both. Each docroot needs its OWN pattern
# rule — a multi-target pattern rule is a GROUPED rule, one invocation for all
# targets, so a shared rule would stage whichever docroot make happened to
# match and silently skip the other. Add a docroot by repeating the pair below.
define sk-stage-docroot
	@test -d $(SK_SRC) || { \
		echo "Error: $(SK_SRC) not found. Run 'git submodule update --init external/shaw-keys' first."; \
		exit 1; \
	}
	$(SK_SRC)/tools/stage.sh --font-url $(FONT_URL) $(@D)
	@rm -f $(@D)/.stamp $(@D)/.stamp-*
	@touch $@
endef

$(SK_SITE_DEST)/.stamp-%: $(SK_SRC)/shaw-keys.js
	$(sk-stage-docroot)

$(SK_EDITOR_DEST)/.stamp-%: $(SK_SRC)/shaw-keys.js
	$(sk-stage-docroot)

$(SK_EDITOR_WRAPPER): $(SK_WRAPPER_SRC)
	@ln -sfn $(abspath $<) $@
	@echo "Keyboard wrapper linked into $(@D)/"
