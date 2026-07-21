# Build rules for the editorial editor
#
# Stages the read-write editorial tool into build/editor/ and tarballs it.
# The editor is PURE PYTHON + committed data — it needs no model/dictionary
# build, so these targets pull NO heavy deps (contrast build-rules/site.mk,
# whose site-data indexes depend on the built XML dictionaries).
#
# Note: BUILD_EDITOR is defined in common.mk.

# The daemon's Python closure editord actually imports (editor + tools modules),
# plus the web tier and the systemd unit. These are the ONLY inputs deploy_editor
# stages, so they are the only prerequisites — no dictionary or supplement target.
EDITOR_DAEMON_SRCS = $(SRC_EDITOR)/editord.py \
                     $(SRC_EDITOR)/overlay.py \
                     $(SRC_EDITOR)/patchstore.py \
                     $(SRC_EDITOR)/definitions.py \
                     $(SRC_EDITOR)/definition_patches.py \
                     $(SRC_EDITOR)/authstore.py \
                     $(SRC_EDITOR)/shaw-spell-editord.service \
                     $(SRC_TOOLS)/basis.py \
                     $(SRC_TOOLS)/dialect_mergers.py \
                     $(SRC_TOOLS)/apply_frequency_data.py \
                     $(SRC_TOOLS)/spelling_variants.py

EDITOR_WEB_SRCS = $(SRC_EDITOR)/site/editor.cgi \
                  $(SRC_EDITOR)/site/editor.js \
                  $(SRC_EDITOR)/site/editor.css

# The ~317MB read-only basis the tarball ships (the payload — the server
# rebuilds nothing). Restage when any of these change. The freq corpus is
# optional (deploy_editor skips-with-notice if absent), so it's not a prereq.
EDITOR_BASIS_SRCS = external/readlex/readlex.json \
                    data/supplement-combined-filtered.json \
                    data/definitions-shavian-gb.json \
                    data/definitions-shavian-us.json

# Stage the editor into build/editor (index.cgi is the representative target,
# mirroring site's $(BUILD_SITE)/index.cgi).
$(BUILD_EDITOR)/index.cgi: $(EDITOR_WEB_SRCS) \
                           $(EDITOR_DAEMON_SRCS) \
                           $(EDITOR_BASIS_SRCS) \
                           $(SRC_EDITOR)/deploy_editor.py \
                           $(SRC_EDITOR)/install.sh.template \
                           $(SRC_FONTS)/BernieSansBetaVF.woff2 \
                           Makefile
	@echo "Staging editorial editor..."
	$(RUN) $(SRC_EDITOR)/deploy_editor.py --version $(VERSION)

.PHONY: editor editor-tarball clean-editor

editor: $(BUILD_EDITOR)/index.cgi
	@echo "Editorial editor staged successfully!"
	@echo "Location: $(BUILD_EDITOR)/"

editor-tarball:
	@$(MAKE) editor
	@cd build && tar czf shaw-spell-editor-$(VERSION).tar.gz editor/
	@echo "✓ Tarball: build/shaw-spell-editor-$(VERSION).tar.gz (v$(VERSION))"
	@echo "  Deploy: extract, then  sudo ./install.sh  (./install.sh --help for details)."
	@echo "  It prints the remaining manual steps (basis rsync, Apache SetEnv, seed user)."

clean-editor:
	@echo "Cleaning editor artifacts..."
	@rm -rf $(BUILD_EDITOR)
	@echo "Editor clean complete"
