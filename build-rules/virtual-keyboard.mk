# Virtual keyboard assets — copied from the external/virtual-keyboard submodule
# into each web docroot so the daemons serve them at /virtual-keyboard/... The
# submodule is the source of truth; these dirs are generated and gitignored.
# Stamp files gate idempotent copies on submodule changes (mirrors shave).

VK_SRC := external/virtual-keyboard

VK_SITE_DEST   := $(SRC_SITE)/virtual-keyboard
VK_SITE_STAMP  := $(VK_SITE_DEST)/.stamp

VK_EDITOR_DEST  := $(SRC_EDITOR)/site/virtual-keyboard
VK_EDITOR_STAMP := $(VK_EDITOR_DEST)/.stamp

.PHONY: virtual-keyboard
virtual-keyboard: $(VK_SITE_STAMP) $(VK_EDITOR_STAMP)

# Both docroots stage identically: the stamp's own directory ($(@D)) is the
# dest, so one recipe serves both. Add another docroot by listing its stamp here.
$(VK_SITE_STAMP) $(VK_EDITOR_STAMP): $(VK_SRC)/virtual-keyboard.js
	@test -d $(VK_SRC) || { \
		echo "Error: $(VK_SRC) not found. Run 'git submodule update --init external/virtual-keyboard' first."; \
		exit 1; \
	}
	@mkdir -p $(@D)
	@# Glob, not `/.`: the source is a submodule ROOT, so copying dotfiles would
	@# publish its .git gitlink and .gitignore into the docroot.
	cp -R $(VK_SRC)/* $(@D)/
	@touch $@
	@echo "Virtual keyboard assets copied to $(@D)/"
