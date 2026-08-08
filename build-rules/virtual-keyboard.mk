# Virtual keyboard assets — copied from the external/virtual-keyboard submodule
# into each web docroot so the daemons serve them at /virtual-keyboard/... The
# submodule is the source of truth; these dirs are generated and gitignored.
# Stamp files gate idempotent copies on submodule changes (mirrors shave).

VK_SRC := external/virtual-keyboard

VK_SITE_DEST   := $(SRC_SITE)/virtual-keyboard
VK_SITE_STAMP  := $(VK_SITE_DEST)/.stamp

VK_EDITOR_DEST  := $(SRC_EDITOR)/site/virtual-keyboard
VK_EDITOR_STAMP := $(VK_EDITOR_DEST)/.stamp

# The shared modal wrapper. The site serves it from its own tree at /js/, but the
# editor's docroot IS $(SRC_EDITOR)/site, served live rather than copied, and the
# page imports it from the docroot ROOT — so the editor needs it staged there.
# A symlink, not a copy: one source of truth, nothing that can drift.
VK_WRAPPER_SRC    := $(SRC_SITE)/js/virtual-keyboard-modal.js
VK_EDITOR_WRAPPER := $(SRC_EDITOR)/site/virtual-keyboard-modal.js

.PHONY: virtual-keyboard
virtual-keyboard: $(VK_SITE_STAMP) $(VK_EDITOR_STAMP) $(VK_EDITOR_WRAPPER)

# Both docroots stage identically: the stamp's own directory ($(@D)) is the
# dest, so one recipe serves both. Add another docroot by listing its stamp here.
$(VK_SITE_STAMP) $(VK_EDITOR_STAMP): $(VK_SRC)/virtual-keyboard.js
	@test -d $(VK_SRC) || { \
		echo "Error: $(VK_SRC) not found. Run 'git submodule update --init external/virtual-keyboard' first."; \
		exit 1; \
	}
	$(VK_SRC)/tools/stage.sh --font-url $(FONT_URL) $(@D)
	@touch $@

$(VK_EDITOR_WRAPPER): $(VK_WRAPPER_SRC)
	@ln -sfn $(abspath $<) $@
	@echo "Keyboard wrapper linked into $(@D)/"
