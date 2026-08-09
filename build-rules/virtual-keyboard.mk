# Virtual keyboard assets — copied from the external/virtual-keyboard submodule
# into each web docroot so the daemons serve them at /virtual-keyboard/... The
# submodule is the source of truth; these dirs are generated and gitignored.
# Stamp files gate idempotent copies on submodule changes (mirrors shave).

VK_SRC := external/virtual-keyboard

VK_SITE_DEST   := $(SRC_SITE)/virtual-keyboard
VK_EDITOR_DEST  := $(SRC_EDITOR)/site/virtual-keyboard

# stage.sh bakes $(FONT_URL) into the staged CSS, so the value is part of what
# the stamp attests — not just the library source. Naming the stamp after the
# URL is what makes a switch rebuild: staging with /fonts and then installing
# with the production origin finds no stamp for that URL and restages, where a
# fixed name would look up to date and ship the local URL to production.
VK_FONT_URL_TAG = $(shell printf '%s' '$(FONT_URL)' | shasum | cut -c1-12)
VK_SITE_STAMP   = $(VK_SITE_DEST)/.stamp-$(VK_FONT_URL_TAG)
VK_EDITOR_STAMP = $(VK_EDITOR_DEST)/.stamp-$(VK_FONT_URL_TAG)

# The shared modal wrapper. The site serves it from its own tree at /js/, but the
# editor's docroot IS $(SRC_EDITOR)/site, served live rather than copied, and the
# page imports it from the docroot ROOT — so the editor needs it staged there.
# A symlink, not a copy: one source of truth, nothing that can drift.
VK_WRAPPER_SRC    := $(SRC_SITE)/js/virtual-keyboard-modal.js
VK_EDITOR_WRAPPER := $(SRC_EDITOR)/site/virtual-keyboard-modal.js

.PHONY: virtual-keyboard
virtual-keyboard: $(VK_SITE_STAMP) $(VK_EDITOR_STAMP) $(VK_EDITOR_WRAPPER)

# Both docroots stage identically: the stamp's own directory ($(@D)) is the
# dest, so one canned recipe serves both. Each docroot needs its OWN pattern
# rule — a multi-target pattern rule is a GROUPED rule, one invocation for all
# targets, so a shared rule would stage whichever docroot make happened to
# match and silently skip the other. Add a docroot by repeating the pair below.
define vk-stage-docroot
	@test -d $(VK_SRC) || { \
		echo "Error: $(VK_SRC) not found. Run 'git submodule update --init external/virtual-keyboard' first."; \
		exit 1; \
	}
	$(VK_SRC)/tools/stage.sh --font-url $(FONT_URL) $(@D)
	@rm -f $(@D)/.stamp $(@D)/.stamp-*
	@touch $@
endef

$(VK_SITE_DEST)/.stamp-%: $(VK_SRC)/virtual-keyboard.js
	$(vk-stage-docroot)

$(VK_EDITOR_DEST)/.stamp-%: $(VK_SRC)/virtual-keyboard.js
	$(vk-stage-docroot)

$(VK_EDITOR_WRAPPER): $(VK_WRAPPER_SRC)
	@ln -sfn $(abspath $<) $@
	@echo "Keyboard wrapper linked into $(@D)/"
