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

# Stage the editor into build/editor (index.cgi is the representative target,
# mirroring site's $(BUILD_SITE)/index.cgi).
$(BUILD_EDITOR)/index.cgi: $(EDITOR_WEB_SRCS) \
                           $(EDITOR_DAEMON_SRCS) \
                           $(SRC_EDITOR)/deploy_editor.py \
                           $(SRC_FONTS)/BernieSansBetaVF.woff2 \
                           Makefile
	@echo "Staging editorial editor..."
	$(RUN) $(SRC_EDITOR)/deploy_editor.py --version $(VERSION)

.PHONY: editor editor-tarball clean-editor

editor: $(BUILD_EDITOR)/index.cgi
	@echo "Editorial editor staged successfully!"
	@echo "Location: $(BUILD_EDITOR)/"

editor-tarball:
	@echo "Staging editor v$(VERSION)..."
	@$(MAKE) editor
	@echo "Creating deployable editor tarball..."
	@cd build && tar czf shaw-spell-editor-$(VERSION).tar.gz editor/
	@echo "✓ Tarball created: build/shaw-spell-editor-$(VERSION).tar.gz"
	@echo ""
	@echo "The tarball ships CODE only. The daemon's read-only basis inputs and"
	@echo "the writable stores are synced separately by ops (see step 4)."
	@echo ""
	@echo "To deploy on Linux:"
	@echo "  1. Extract:  tar xzf shaw-spell-editor-$(VERSION).tar.gz"
	@echo ""
	@echo "  2. Web tier (Apache docroot /var/www/shaw-spell/editor):"
	@echo "       sudo cp editor/editor.cgi editor/index.cgi \\"
	@echo "               editor/editor.js editor/editor.css \\"
	@echo "               /var/www/shaw-spell/editor/"
	@echo "       sudo cp -r editor/fonts /var/www/shaw-spell/editor/"
	@echo "       # authstore.py goes ONE level ABOVE the docroot (the CGI imports"
	@echo "       # it via dirname(dirname(cgi))); it is NOT web-served:"
	@echo "       sudo cp editor/authstore.py /var/www/shaw-spell/"
	@echo "       # Apache MUST point the CGI at the shared auth DB (authstore's"
	@echo "       # __file__-relative default would resolve to /var/data/... here):"
	@echo "       #   <Directory /var/www/shaw-spell/editor>"
	@echo "       #     SetEnv SHAW_SPELL_AUTH_DB /opt/shaw-spell/data/auth/users.sqlite"
	@echo "       #   </Directory>"
	@echo "       # (+ExecCGI, .cgi handler, DirectoryIndex index.cgi are already set;"
	@echo "       #  HTTPS=on at Apache auto-enables the Secure session cookie.)"
	@echo ""
	@echo "  3. Daemon (/opt/shaw-spell — this is the daemon's PROJECT_ROOT):"
	@echo "       sudo mkdir -p /opt/shaw-spell"
	@echo "       sudo cp -r editor/editor-daemon/editor /opt/shaw-spell/"
	@echo "       sudo cp -r editor/editor-daemon/tools  /opt/shaw-spell/"
	@echo "       sudo cp editor/editor-daemon/shaw-spell-editord.service \\"
	@echo "               /etc/systemd/system/"
	@echo "       sudo systemctl daemon-reload"
	@echo "       sudo systemctl enable --now shaw-spell-editord"
	@echo ""
	@echo "  4. Sync the read-only basis inputs ops keeps (NOT in the tarball),"
	@echo "     preserving these paths under /opt/shaw-spell/:"
	@echo "       external/readlex/readlex.json"
	@echo "       data/supplement-combined-filtered.json"
	@echo "       data/definitions-shavian-gb.json"
	@echo "       data/definitions-shavian-us.json"
	@echo "       external/frequency-words/.../en_full.txt   (optional — freq sort)"
	@echo ""
	@echo "  5. Writable stores (www-data must own these; the tarball ships them"
	@echo "     empty under editor-daemon/data/):"
	@echo "       sudo mkdir -p /opt/shaw-spell/data/patches /opt/shaw-spell/data/auth"
	@echo "       sudo chown -R www-data:www-data /opt/shaw-spell/data"
	@echo "       # seed the first editor account (writes users.sqlite):"
	@echo "       sudo -u www-data SHAW_SPELL_AUTH_DB=/opt/shaw-spell/data/auth/users.sqlite \\"
	@echo "            python3 /opt/shaw-spell/editor/authstore.py --create-user HANDLE"
	@echo ""
	@echo "  The CGI reaches the daemon over /run/shaw-spell/editord.sock (created"
	@echo "  by the service). Commit-from-UI is disabled on a tarball deploy (no .git)."
	@echo ""
	@echo "  Version: $(VERSION)"

clean-editor:
	@echo "Cleaning editor artifacts..."
	@rm -rf $(BUILD_EDITOR)
	@echo "Editor clean complete"
