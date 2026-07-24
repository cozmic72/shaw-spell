# Virtual keyboard assets — copied from the external/shaw-type submodule into
# each web docroot so the daemons serve them at /virtual-keyboard/... The
# submodule is the source of truth; these dirs are generated and gitignored.
# Stamp files gate idempotent copies on submodule changes (mirrors shave).

SHAW_TYPE_SRC := external/shaw-type/src/virtual-keyboard

VK_SITE_DEST   := $(SRC_SITE)/virtual-keyboard
VK_SITE_STAMP  := $(VK_SITE_DEST)/.stamp

VK_EDITOR_DEST  := $(SRC_EDITOR)/site/virtual-keyboard
VK_EDITOR_STAMP := $(VK_EDITOR_DEST)/.stamp

.PHONY: virtual-keyboard
virtual-keyboard: $(VK_SITE_STAMP) $(VK_EDITOR_STAMP)

# Both docroots stage identically: the stamp's own directory ($(@D)) is the
# dest, so one recipe serves both. Add another docroot by listing its stamp here.
$(VK_SITE_STAMP) $(VK_EDITOR_STAMP): $(SHAW_TYPE_SRC)/virtual-keyboard.js
	@test -d $(SHAW_TYPE_SRC) || { \
		echo "Error: $(SHAW_TYPE_SRC) not found. Run 'git submodule update --init external/shaw-type' first."; \
		exit 1; \
	}
	@mkdir -p $(@D)
	cp -R $(SHAW_TYPE_SRC)/. $(@D)/
	@touch $@
	@echo "Virtual keyboard assets copied to $(@D)/"
