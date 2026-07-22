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

$(VK_SITE_STAMP): $(SHAW_TYPE_SRC)/virtual-keyboard.js
	@test -d $(SHAW_TYPE_SRC) || { \
		echo "Error: $(SHAW_TYPE_SRC) not found. Run 'git submodule update --init external/shaw-type' first."; \
		exit 1; \
	}
	@mkdir -p $(VK_SITE_DEST)
	cp -R $(SHAW_TYPE_SRC)/. $(VK_SITE_DEST)/
	@touch $(VK_SITE_STAMP)
	@echo "Virtual keyboard assets copied to $(VK_SITE_DEST)/"

$(VK_EDITOR_STAMP): $(SHAW_TYPE_SRC)/virtual-keyboard.js
	@test -d $(SHAW_TYPE_SRC) || { \
		echo "Error: $(SHAW_TYPE_SRC) not found. Run 'git submodule update --init external/shaw-type' first."; \
		exit 1; \
	}
	@mkdir -p $(VK_EDITOR_DEST)
	cp -R $(SHAW_TYPE_SRC)/. $(VK_EDITOR_DEST)/
	@touch $(VK_EDITOR_STAMP)
	@echo "Virtual keyboard assets copied to $(VK_EDITOR_DEST)/"
