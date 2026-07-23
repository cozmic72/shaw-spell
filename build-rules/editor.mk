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
                  $(SRC_EDITOR)/site/editor.css \
                  $(SRC_SITE)/js/virtual-keyboard-modal.js

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
                           $(VK_EDITOR_STAMP) \
                           $(EDITOR_DAEMON_SRCS) \
                           $(EDITOR_BASIS_SRCS) \
                           $(SRC_EDITOR)/deploy_editor.py \
                           $(SRC_EDITOR)/install.sh.template \
                           $(SRC_FONTS)/BernieSansBetaVF.woff2 \
                           Makefile
	@echo "Staging editorial editor..."
	$(RUN) $(SRC_EDITOR)/deploy_editor.py --version $(VERSION)

.PHONY: editor editor-tarball install-editor clean-editor

# --- install-editor: deploy the editor (copied code + a live data clone) ---
#
# MODEL (supersedes the tarball snapshot): only the DATA needs to be a git checkout
# on the server. So:
#   * CODE  (src/editor, src/tools) is COPIED into $(OPT_ROOT)/src — deploy-by-copy,
#     no git. Upgrades come from re-running this target with fresh files.
#   * ReadLex (external/readlex/readlex.json) is COPIED — a read-only basis, never
#     committed, so it needs no clone.
#   * DATA  ($(OPT_ROOT)/data) is a STANDALONE `git clone` of $(DATA_REMOTE). This is
#     the ONLY git checkout on the server; the daemon's Commit button commits the
#     patch store here and pushes it upstream. basis.py's PROJECT_ROOT is
#     $(OPT_ROOT), so a plain clone at $(OPT_ROOT)/data satisfies every basis path —
#     it need NOT be a submodule of anything.
#
# Run from THIS repo (not from /opt):  sudo -v && make install-editor
# The build never runs as root; only the privileged commands (writing /var/www,
# /opt, /etc/systemd, chown, systemctl) escalate via sudo.
#
# Idempotent: safe to re-run to upgrade. PRESERVES mutable state — the auth DB under
# /var/lib, and the data clone's working tree + patch store (re-clone is SKIPPED if
# $(OPT_ROOT)/data is already a clone; only a `git fetch` refreshes it, never a
# reset that would clobber uncommitted patches). Does NOT edit Apache config or seed
# users — prints those manual steps.
#
# Override any path on the command line, e.g.
#   make install-editor WWW_ROOT_EDITOR=/srv/www/shaw-spell/editor
WWW_ROOT_EDITOR ?= /var/www/shaw-spell/editor
OPT_ROOT ?= /opt/shaw-spell
VAR_LIB ?= /var/lib/shaw-spell
SERVICE_USER ?= www-data
AUTH_DB = $(VAR_LIB)/auth/users.sqlite
# The bare remote the DATA clone is cloned from and the daemon pushes to. It is
# local to the server (the daemon has no ssh keys for ssh://joro.io), reached over
# file:// (needs protocol.file.allow=always for CVE-2022-39253).
DATA_REMOTE ?= /var/git/shaw-spell-data.git

# install-editor builds only the virtual-keyboard assets (needed for the web tier);
# it needs NO dictionary/basis build — the basis is the cloned data + copied readlex.
install-editor: $(VK_EDITOR_STAMP)
	@set -eu; \
	SRC_EDITOR="$(SRC_EDITOR)"; SITE="$(SRC_EDITOR)/site"; \
	for f in "$$SITE/editor.cgi" "$$SITE/editor.js" "$$SITE/editor.css" \
	         "$$SRC_EDITOR/authstore.py" \
	         "$$SITE/virtual-keyboard-modal.js" \
	         "$$SITE/virtual-keyboard/virtual-keyboard.js" \
	         "$$SRC_EDITOR/shaw-spell-editord.service" \
	         "$(SRC_TOOLS)/basis.py" \
	         "external/readlex/readlex.json" \
	         "$(SRC_FONTS)/BernieSansBetaVF.woff2"; do \
	  [ -e "$$f" ] || { echo "install-editor: missing source file: $$f" >&2; exit 1; }; \
	done; \
	echo "==> Installing Shaw-Spell editor (copied code + live data clone)"; \
	echo "    web:      $(WWW_ROOT_EDITOR)"; \
	echo "    code:     $(OPT_ROOT)/src  (copied)"; \
	echo "    readlex:  $(OPT_ROOT)/external/readlex  (copied, read-only basis)"; \
	echo "    data:     $(OPT_ROOT)/data  (git clone of $(DATA_REMOTE) — daemon commits+pushes this)"; \
	echo "    auth db:  $(VAR_LIB)/auth  (owner: $(SERVICE_USER))"; \
	echo; \
	echo "==> Daemon code -> $(OPT_ROOT)/src/{editor,tools} (copied)"; \
	sudo mkdir -p "$(OPT_ROOT)/src"; \
	sudo rm -rf "$(OPT_ROOT)/src/editor" "$(OPT_ROOT)/src/tools"; \
	sudo cp -R "$(SRC_EDITOR)" "$(OPT_ROOT)/src/editor"; \
	sudo cp -R "$(SRC_TOOLS)"  "$(OPT_ROOT)/src/tools"; \
	echo "==> ReadLex basis -> $(OPT_ROOT)/external/readlex (copied, read-only)"; \
	sudo mkdir -p "$(OPT_ROOT)/external/readlex"; \
	sudo install -m 644 "external/readlex/readlex.json" "$(OPT_ROOT)/external/readlex/readlex.json"; \
	echo "==> Data clone -> $(OPT_ROOT)/data (from $(DATA_REMOTE))"; \
	if [ -e "$(OPT_ROOT)/data/.git" ]; then \
	  echo "    already a clone — fetching (working tree + patches preserved, no reset)"; \
	  sudo -u "$(SERVICE_USER)" git -C "$(OPT_ROOT)/data" \
	       -c protocol.file.allow=always fetch --prune origin; \
	else \
	  [ -e "$(OPT_ROOT)/data" ] && { \
	    echo "install-editor: $(OPT_ROOT)/data exists but is not a git clone — refusing" >&2; \
	    echo "  to overwrite it. Move it aside and re-run." >&2; exit 1; }; \
	  sudo mkdir -p "$(OPT_ROOT)"; \
	  sudo chown "$(SERVICE_USER):$(SERVICE_USER)" "$(OPT_ROOT)"; \
	  sudo -u "$(SERVICE_USER)" git -c protocol.file.allow=always \
	       clone "$(DATA_REMOTE)" "$(OPT_ROOT)/data"; \
	fi; \
	echo "==> Web tier -> $(WWW_ROOT_EDITOR)"; \
	sudo mkdir -p "$(WWW_ROOT_EDITOR)" "$(WWW_ROOT_EDITOR)/fonts"; \
	sudo install -m 755 "$$SITE/editor.cgi"   "$(WWW_ROOT_EDITOR)/editor.cgi"; \
	sudo install -m 755 "$$SITE/editor.cgi"   "$(WWW_ROOT_EDITOR)/index.cgi"; \
	sudo install -m 644 "$$SRC_EDITOR/authstore.py" "$(WWW_ROOT_EDITOR)/authstore.py"; \
	sudo install -m 644 "$$SITE/editor.js"    "$(WWW_ROOT_EDITOR)/editor.js"; \
	sudo install -m 644 "$$SITE/editor.css"   "$(WWW_ROOT_EDITOR)/editor.css"; \
	sudo install -m 644 "$(SRC_FONTS)"/*.woff2 "$(WWW_ROOT_EDITOR)/fonts/"; \
	sudo install -m 644 "$$SITE/virtual-keyboard-modal.js" "$(WWW_ROOT_EDITOR)/virtual-keyboard-modal.js"; \
	sudo rm -rf "$(WWW_ROOT_EDITOR)/virtual-keyboard"; \
	sudo cp -R "$$SITE/virtual-keyboard" "$(WWW_ROOT_EDITOR)/virtual-keyboard"; \
	echo "==> systemd unit -> /etc/systemd/system/shaw-spell-editord.service"; \
	sudo install -m 644 "$$SRC_EDITOR/shaw-spell-editord.service" \
	                    /etc/systemd/system/shaw-spell-editord.service; \
	echo "==> Auth DB dir -> $(VAR_LIB)/auth (created + chowned; data preserved)"; \
	sudo mkdir -p "$(VAR_LIB)/auth"; \
	sudo chown -R "$(SERVICE_USER):$(SERVICE_USER)" "$(VAR_LIB)/auth"; \
	echo "==> Commit+push perms -> chown data clone to $(SERVICE_USER)"; \
	sudo chown -R "$(SERVICE_USER):$(SERVICE_USER)" "$(OPT_ROOT)/data"; \
	echo "==> systemd daemon-reload + enable"; \
	sudo systemctl daemon-reload; \
	sudo systemctl enable --now shaw-spell-editord; \
	echo; \
	echo "============================================================"; \
	echo "Installed:"; \
	echo "  web tier   -> $(WWW_ROOT_EDITOR) (editor.cgi, index.cgi, authstore.py, js/css/fonts, keyboard)"; \
	echo "  code       -> $(OPT_ROOT)/src/{editor,tools} (copied) + the systemd unit"; \
	echo "  readlex    -> $(OPT_ROOT)/external/readlex (copied, read-only basis)"; \
	echo "  data       -> $(OPT_ROOT)/data (git clone of $(DATA_REMOTE); daemon commits+pushes)"; \
	echo "  patches    -> $(OPT_ROOT)/data/patches/ (IN the clone → Commit button can commit+push)"; \
	echo "  auth db    -> $(VAR_LIB)/auth (owned by $(SERVICE_USER); existing data preserved)"; \
	echo; \
	echo "The daemon is enabled and running. Remaining MANUAL steps (this target"; \
	echo "cannot safely guess these):"; \
	echo; \
	echo "1. Point the CGI at the auth DB via Apache (paste into the editor <Directory>):"; \
	echo "     <Directory $(WWW_ROOT_EDITOR)>"; \
	echo "       SetEnv SHAW_SPELL_AUTH_DB $(AUTH_DB)"; \
	echo "     </Directory>"; \
	echo "   Then:  sudo systemctl reload apache2   (or: apachectl graceful)"; \
	echo "   (+ExecCGI, .cgi handler, DirectoryIndex index.cgi, TLS are already configured.)"; \
	echo; \
	echo "2. Seed the first editor account (writes $(AUTH_DB)):"; \
	echo "     sudo -u $(SERVICE_USER) SHAW_SPELL_AUTH_DB=$(AUTH_DB) \\"; \
	echo "          python3 $(WWW_ROOT_EDITOR)/authstore.py --create-user HANDLE"; \
	echo; \
	echo "3. Commit+push identity + remote perms (the daemon runs as $(SERVICE_USER)):"; \
	echo "   a) git identity for $(SERVICE_USER) in the data clone:"; \
	echo "        sudo -u $(SERVICE_USER) git -C $(OPT_ROOT)/data config user.name  'Shaw-Spell Editor'"; \
	echo "        sudo -u $(SERVICE_USER) git -C $(OPT_ROOT)/data config user.email 'editor@joro.io'"; \
	echo "   b) let $(SERVICE_USER) push over file:// to the bare remote:"; \
	echo "        sudo -u $(SERVICE_USER) git -C $(OPT_ROOT)/data config protocol.file.allow always"; \
	echo "      and ensure $(DATA_REMOTE) is writable by $(SERVICE_USER):"; \
	echo "        sudo chown -R $(SERVICE_USER):$(SERVICE_USER) $(DATA_REMOTE)"; \
	echo "      (or add $(SERVICE_USER) to a shared group that owns it, group-writable +s)."; \
	echo "   c) confirm the clone's origin is the LOCAL bare remote (clone set it already):"; \
	echo "        sudo -u $(SERVICE_USER) git -C $(OPT_ROOT)/data remote -v"; \
	echo "============================================================"; \
	echo "Done."

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
