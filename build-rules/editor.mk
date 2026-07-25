# Build rules for the editorial editor
#
# Deploys the read-write editorial tool via install-editor: CODE is copied into
# /opt/shaw-spell/src and the mutable DATA is a live git clone the daemon's
# Commit button commits+pushes (see the install-editor comment below for the
# full model). The editor is PURE PYTHON + committed data — it needs no
# model/dictionary build, so this target pulls NO heavy deps (contrast
# build-rules/site.mk, whose site-data indexes depend on the built XML
# dictionaries).

.PHONY: install-editor

# --- install-editor: deploy the editor (copied code + a live data clone) ---
#
# MODEL (supersedes the tarball snapshot): only the DATA needs to be a git checkout
# on the server. So:
#   * CODE  (src/editor, src/tools) is COPIED into $(OPT_ROOT)/src — deploy-by-copy,
#     no git. Upgrades come from re-running this target with fresh files.
#   * ReadLex (external/readlex/readlex.json) is COPIED — a read-only basis, never
#     committed, so it needs no clone.
#   * DATA  ($(DATA_DIR)) is a STANDALONE `git clone` of $(DATA_REMOTE). This is
#     the ONLY git checkout on the server; the daemon's Commit button commits the
#     patch store here and pushes it upstream. It is SINGLE-OWNER = $(SERVICE_USER):
#     only the daemon reads/edits/commits/pushes it (the owner works via the editor
#     UI or from a separate laptop clone), so the clone AND all fetch/merge run AS
#     $(SERVICE_USER) — www-data owns its own object store start to finish, no
#     group-sharing. It lives under /var/lib (FHS: mutable state), NOT
#     $(OPT_ROOT)/data — that path belongs to the dictionary site's install-site.
#     The systemd unit points basis.py's DATA_ROOT at it via SHAW_SPELL_DATA_DIR;
#     PROJECT_ROOT stays $(OPT_ROOT) for the read-only external/ basis.
#
# Run from THIS repo (not from /opt):  sudo -v && make install-editor
# The build never runs as root; only the privileged commands (writing /var/www,
# /opt, /etc/systemd, chown, systemctl) escalate via sudo.
#
# Idempotent: safe to re-run to upgrade. PRESERVES mutable state — the auth DB under
# /var/lib, and the data clone's working tree + patch store (re-clone is SKIPPED if
# $(DATA_DIR) is already a clone; only a `git fetch` refreshes it, never a
# reset that would clobber uncommitted patches). Does NOT edit Apache config or seed
# users — prints those manual steps.
#
# Override any path on the command line, e.g.
#   make install-editor WWW_ROOT_EDITOR=/srv/www/shaw-spell/editor
WWW_ROOT_EDITOR ?= /var/www/shaw-spell/editor
OPT_ROOT ?= /opt/shaw-spell
VAR_LIB ?= /var/lib/shaw-spell
# The mutable data clone. MUST match the systemd unit's SHAW_SPELL_DATA_DIR.
DATA_DIR ?= $(VAR_LIB)/data
SERVICE_USER ?= www-data
# git author on the daemon's commits (the Commit button). Override if you like.
EDITOR_GIT_NAME ?= Shaw-Spell Editor
EDITOR_GIT_EMAIL ?= editor@joro.io
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
	         "$(SRC_SITE)/js/virtual-keyboard-modal.js" \
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
	echo "    data:     $(DATA_DIR)  (git clone of $(DATA_REMOTE) — daemon commits+pushes this)"; \
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
	echo "==> Data clone -> $(DATA_DIR) (from $(DATA_REMOTE), owned by $(SERVICE_USER))"; \
	if [ -e "$(DATA_DIR)/.git" ]; then \
	  echo "    already a clone — repairing ownership then rebasing onto origin/main (daemon's local patch-commits replayed on top, working tree + patches preserved, no reset)"; \
	  sudo chown -R "$(SERVICE_USER):$(SERVICE_USER)" "$(DATA_DIR)"; \
	  echo "    (a real rebase conflict here is a legitimate stop-and-fix — resolve it in $(DATA_DIR) then re-run)"; \
	  sudo -u "$(SERVICE_USER)" git -C "$(DATA_DIR)" -c protocol.file.allow=always pull --rebase origin main; \
	else \
	  [ -e "$(DATA_DIR)" ] && { \
	    echo "install-editor: $(DATA_DIR) exists but is not a git clone — refusing" >&2; \
	    echo "  to overwrite it. Move it aside and re-run." >&2; exit 1; }; \
	  sudo mkdir -p "$(VAR_LIB)"; \
	  sudo chown "$(SERVICE_USER):$(SERVICE_USER)" "$(VAR_LIB)"; \
	  sudo -u "$(SERVICE_USER)" git -c protocol.file.allow=always clone "$(DATA_REMOTE)" "$(DATA_DIR)"; \
	fi; \
	echo "==> Web tier -> $(WWW_ROOT_EDITOR)"; \
	sudo mkdir -p "$(WWW_ROOT_EDITOR)" "$(WWW_ROOT_EDITOR)/fonts"; \
	sudo install -m 755 "$$SITE/editor.cgi"   "$(WWW_ROOT_EDITOR)/editor.cgi"; \
	sudo install -m 755 "$$SITE/editor.cgi"   "$(WWW_ROOT_EDITOR)/index.cgi"; \
	sudo install -m 644 "$$SRC_EDITOR/authstore.py" "$(WWW_ROOT_EDITOR)/authstore.py"; \
	sudo install -m 644 "$$SITE/editor.js"    "$(WWW_ROOT_EDITOR)/editor.js"; \
	sudo install -m 644 "$$SITE/editor.css"   "$(WWW_ROOT_EDITOR)/editor.css"; \
	sudo install -m 644 "$(SRC_FONTS)"/*.woff2 "$(WWW_ROOT_EDITOR)/fonts/"; \
	sudo install -m 644 "$(SRC_SITE)/js/virtual-keyboard-modal.js" "$(WWW_ROOT_EDITOR)/virtual-keyboard-modal.js"; \
	$(call replace-dir-tree,$$SITE,$(WWW_ROOT_EDITOR),virtual-keyboard); \
	echo "==> systemd unit -> /etc/systemd/system/shaw-spell-editord.service"; \
	sudo install -m 644 "$$SRC_EDITOR/shaw-spell-editord.service" \
	                    /etc/systemd/system/shaw-spell-editord.service; \
	echo "==> Auth DB dir -> $(VAR_LIB)/auth (created + chowned; data preserved)"; \
	sudo mkdir -p "$(VAR_LIB)/auth"; \
	sudo chown -R "$(SERVICE_USER):$(SERVICE_USER)" "$(VAR_LIB)/auth"; \
	echo "==> Commit+push config -> data clone trusted + daemon git identity ($(SERVICE_USER))"; \
	sudo git config --system --add safe.directory "$(DATA_DIR)"; \
	sudo git config --system --add safe.directory "$(DATA_REMOTE)"; \
	sudo -u "$(SERVICE_USER)" git -C "$(DATA_DIR)" config user.name  "$(EDITOR_GIT_NAME)"; \
	sudo -u "$(SERVICE_USER)" git -C "$(DATA_DIR)" config user.email "$(EDITOR_GIT_EMAIL)"; \
	echo "==> systemd daemon-reload + (re)start"; \
	sudo systemctl daemon-reload; \
	sudo systemctl enable shaw-spell-editord; \
	sudo systemctl restart shaw-spell-editord; \
	echo; \
	echo "============================================================"; \
	echo "Installed:"; \
	echo "  web tier   -> $(WWW_ROOT_EDITOR) (editor.cgi, index.cgi, authstore.py, js/css/fonts, keyboard)"; \
	echo "  code       -> $(OPT_ROOT)/src/{editor,tools} (copied) + the systemd unit"; \
	echo "  readlex    -> $(OPT_ROOT)/external/readlex (copied, read-only basis)"; \
	echo "  data       -> $(DATA_DIR) (git clone of $(DATA_REMOTE); daemon commits+pushes)"; \
	echo "  patches    -> $(DATA_DIR)/patches/ (IN the clone → Commit button can commit+push)"; \
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
	echo "3. The BARE remote $(DATA_REMOTE) — the ONE thing this target won't"; \
	echo "   touch. UNLIKE the checkout (single-owner $(SERVICE_USER)), the bare repo is"; \
	echo "   pushed by BOTH the daemon ($(SERVICE_USER)) and YOU (from your laptop), so it"; \
	echo "   genuinely needs group-write + setgid + shared-repo. Give it that group"; \
	echo "   treatment once — never chown it to $(SERVICE_USER) (pick a group you both"; \
	echo "   belong to, e.g. GROUP=gitshaw, and add $(SERVICE_USER): sudo usermod -aG GROUP $(SERVICE_USER)):"; \
	echo "        sudo chgrp -R GROUP $(DATA_REMOTE)"; \
	echo "        sudo chmod -R g+rwX $(DATA_REMOTE) && sudo find $(DATA_REMOTE) -type d -exec chmod g+s {} +"; \
	echo "        sudo git -C $(DATA_REMOTE) config core.sharedRepository group"; \
	echo "   (the checkout's safe.directory and the daemon's git identity are set by"; \
	echo "   this target; verify origin with:  git -C $(DATA_DIR) remote -v)"; \
	echo "============================================================"; \
	echo "Done."
