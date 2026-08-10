# Build rules for the editorial editor
#
# Deploys the read-write editorial tool via install-editor: CODE is copied into
# /opt/shaw-spell/src and the mutable DATA is a live git clone the daemon's
# Commit button commits+pushes (see the install-editor comment below for the
# full model). The editor is PURE PYTHON + committed data — it needs no
# model/dictionary build, so this target pulls NO heavy deps. The site's
# indexes DO depend on the built XML dictionaries, which is why site.mk builds
# them on the build machine and install-site ships the prebuilt data.

.PHONY: install-editor

# --- install-editor: deploy the editor (copied code + a live data clone) ---
#
# MODEL (supersedes the tarball snapshot): only the DATA needs to be a git checkout
# on the server. So:
#   * CODE  (src/editor, src/tools) is COPIED into $(OPT_ROOT)/src — deploy-by-copy,
#     no git. Upgrades come from re-running this target with fresh files.
#   * ReadLex (external/readlex/readlex.json) is COPIED — a read-only basis, never
#     committed, so it needs no clone.
#   * The frequency corpus ($(FREQUENCY_CORPUS)) is COPIED the same way — the
#     daemon REFUSES TO PUBLISH without it at its runtime path under $(OPT_ROOT).
#     It is a prerequisite of this target, so a fresh checkout auto-runs
#     `make setup` to materialise it (rule in build-rules/supplements.mk).
#   * Everything else the daemon hard-requires ships INSIDE the data clone
#     ($(EDITOR_DATA_RUNTIME_FILES)), so it needs no copy — but the daemon dies
#     (startup) or refuses to publish (LRW list) without it, so this target
#     verifies each is reachable in $(DATA_DIR) after the clone/pull.
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
SYSTEMD_UNIT_DIR ?= /etc/systemd/system
# The mutable data clone. MUST match the systemd unit's SHAW_SPELL_DATA_DIR.
DATA_DIR ?= $(VAR_LIB)/data
SERVICE_USER ?= www-data
# git author on the daemon's commits (the Commit button). Override if you like.
EDITOR_GIT_NAME ?= Shaw-Spell Editor
EDITOR_GIT_EMAIL ?= editor@joro.io
AUTH_DB ?= $(VAR_LIB)/auth/users.sqlite
# The bare remote the DATA clone is cloned from and the daemon pushes to. It is
# local to the server (the daemon has no ssh keys for ssh://joro.io), reached over
# file:// (needs protocol.file.allow=always for CVE-2022-39253).
DATA_REMOTE ?= /var/git/shaw-spell-data.git
# The files the DAEMON hard-requires from the data clone, DATA-ROOT-relative.
# Startup dies without the basis pool (basis.py SUPPLEMENT_PATHS), the
# definitions caches (definitions.py) and the patch store (patchstore.py);
# publish refuses without the LRW list (lrw_frequencies.py). All are committed
# to the data repo — reachability in $(DATA_DIR) is verified after the
# clone/pull below.
EDITOR_DATA_RUNTIME_FILES = $(LRW_LIST) supplement-combined-filtered.json \
  definitions-latin-gb.json definitions-shavian-gb.json \
  definitions-shavian-us.json patches/patches.jsonl

# install-editor builds only the Shaw Keys assets (needed for the web tier)
# and the frequency corpus checkout (a publish-time runtime requirement — see the
# model above); it needs NO dictionary/basis build — the basis is the cloned data
# + copied readlex.
install-editor: $(SK_EDITOR_STAMP) $(FREQUENCY_CORPUS)
	@set -eu; \
	SRC_EDITOR="$(SRC_EDITOR)"; SITE="$(SRC_EDITOR)/site"; \
	echo "==> Installing Shaw-Spell editor (copied code + live data clone)"; \
	echo "    web:      $(WWW_ROOT_EDITOR)"; \
	echo "    code:     $(OPT_ROOT)/src  (copied)"; \
	echo "    readlex:  $(OPT_ROOT)/external/readlex  (copied, read-only basis)"; \
	echo "    corpus:   $(OPT_ROOT)/$(FREQUENCY_CORPUS)  (copied — publish needs it)"; \
	echo "    data:     $(DATA_DIR)  (git clone of $(DATA_REMOTE) — daemon commits+pushes this)"; \
	echo "    auth db:  $(VAR_LIB)/auth  (owner: $(SERVICE_USER))"; \
	echo; \
	if [ "$(SERVICE_USER)" = "$$(id -un)" ]; then \
	  OWN_SERVICE_USER=1; \
	  echo "    (SERVICE_USER $(SERVICE_USER) is the invoking user — chown and"; \
	  echo "     git config --system steps are no-ops and will be SKIPPED)"; \
	else \
	  OWN_SERVICE_USER=0; \
	fi; \
	echo "==> Daemon code -> $(OPT_ROOT)/src/{editor,tools} (copied)"; \
	$(SUDO) mkdir -p "$(OPT_ROOT)/src"; \
	$(SUDO) rm -rf "$(OPT_ROOT)/src/editor" "$(OPT_ROOT)/src/tools"; \
	$(SUDO) cp -R "$(SRC_EDITOR)" "$(OPT_ROOT)/src/editor"; \
	$(SUDO) cp -R "$(SRC_TOOLS)"  "$(OPT_ROOT)/src/tools"; \
	echo "==> ReadLex basis -> $(OPT_ROOT)/external/readlex (copied, read-only)"; \
	$(SUDO) mkdir -p "$(OPT_ROOT)/external/readlex"; \
	$(SUDO) install -m 644 "external/readlex/readlex.json" "$(OPT_ROOT)/external/readlex/readlex.json"; \
	echo "==> Frequency corpus -> $(OPT_ROOT)/$(FREQUENCY_CORPUS) (copied, read-only)"; \
	$(SUDO) mkdir -p "$(OPT_ROOT)/$(dir $(FREQUENCY_CORPUS))"; \
	$(SUDO) install -m 644 "$(FREQUENCY_CORPUS)" "$(OPT_ROOT)/$(FREQUENCY_CORPUS)"; \
	echo "==> Data clone -> $(DATA_DIR) (from $(DATA_REMOTE), owned by $(SERVICE_USER))"; \
	if [ -e "$(DATA_DIR)/.git" ]; then \
	  echo "    already a clone — repairing ownership then rebasing onto origin/main (daemon's local patch-commits replayed on top, working tree + patches preserved, no reset)"; \
	  if [ "$$OWN_SERVICE_USER" -eq 1 ]; then \
	    echo "    SKIP chown $(DATA_DIR): already owned by $(SERVICE_USER)"; \
	  else \
	    $(SUDO) chown -R "$(SERVICE_USER):$(SERVICE_USER)" "$(DATA_DIR)"; \
	  fi; \
	  echo "    (a real rebase conflict here is a legitimate stop-and-fix — resolve it in $(DATA_DIR) then re-run)"; \
	  $(RUN_AS) git -C "$(DATA_DIR)" -c protocol.file.allow=always pull --rebase origin main; \
	else \
	  [ -e "$(DATA_DIR)" ] && { \
	    echo "install-editor: $(DATA_DIR) exists but is not a git clone — refusing" >&2; \
	    echo "  to overwrite it. Move it aside and re-run." >&2; exit 1; }; \
	  $(SUDO) mkdir -p "$(VAR_LIB)"; \
	  if [ "$$OWN_SERVICE_USER" -eq 1 ]; then \
	    echo "    SKIP chown $(VAR_LIB): already owned by $(SERVICE_USER)"; \
	  else \
	    $(SUDO) chown "$(SERVICE_USER):$(SERVICE_USER)" "$(VAR_LIB)"; \
	  fi; \
	  $(RUN_AS) git -c protocol.file.allow=always clone "$(DATA_REMOTE)" "$(DATA_DIR)"; \
	fi; \
	for f in $(EDITOR_DATA_RUNTIME_FILES); do \
	  [ -e "$(DATA_DIR)/$$f" ] || { \
	    echo "install-editor: daemon runtime file missing from the data clone: $(DATA_DIR)/$$f" >&2; \
	    echo "  the daemon cannot run/publish without it — push the data commit providing it to $(DATA_REMOTE), then re-run" >&2; \
	    exit 1; }; \
	done; \
	echo "==> Web tier -> $(WWW_ROOT_EDITOR)"; \
	$(SUDO) mkdir -p "$(WWW_ROOT_EDITOR)" "$(WWW_ROOT_EDITOR)/fonts"; \
	$(SUDO) install -m 755 "$$SITE/editor.cgi"   "$(WWW_ROOT_EDITOR)/editor.cgi"; \
	$(SUDO) install -m 755 "$$SITE/editor.cgi"   "$(WWW_ROOT_EDITOR)/index.cgi"; \
	$(SUDO) install -m 644 "$$SRC_EDITOR/authstore.py" "$(WWW_ROOT_EDITOR)/authstore.py"; \
	$(SUDO) install -m 644 "$$SITE/editor.js"    "$(WWW_ROOT_EDITOR)/editor.js"; \
	$(SUDO) install -m 644 "$$SITE/editor.css"   "$(WWW_ROOT_EDITOR)/editor.css"; \
	$(SUDO) install -m 644 "$(SRC_FONTS)"/*.woff2 "$(WWW_ROOT_EDITOR)/fonts/"; \
	$(SUDO) install -m 644 "$(SRC_SITE)/js/shaw-keys-modal.js" "$(WWW_ROOT_EDITOR)/shaw-keys-modal.js"; \
	$(call replace-dir-tree,$$SITE,$(WWW_ROOT_EDITOR),shaw-keys,$(SUDO)); \
	echo "==> systemd unit -> $(SYSTEMD_UNIT_DIR)/shaw-spell-editord.service"; \
	$(SUDO) install -m 644 "$$SRC_EDITOR/shaw-spell-editord.service" \
	                       "$(SYSTEMD_UNIT_DIR)/shaw-spell-editord.service"; \
	if [ "$(SYSTEMD_UNIT_DIR)" != /etc/systemd/system ]; then \
	  echo "    (unit written to $(SYSTEMD_UNIT_DIR), not the system unit dir — systemd will not see it)"; \
	fi; \
	echo "==> Auth DB dir -> $(VAR_LIB)/auth (created + chowned; data preserved)"; \
	$(SUDO) mkdir -p "$(VAR_LIB)/auth"; \
	if [ "$$OWN_SERVICE_USER" -eq 1 ]; then \
	  echo "    SKIP chown $(VAR_LIB)/auth: already owned by $(SERVICE_USER)"; \
	else \
	  $(SUDO) chown -R "$(SERVICE_USER):$(SERVICE_USER)" "$(VAR_LIB)/auth"; \
	fi; \
	echo "==> Commit+push config -> data clone trusted + daemon git identity ($(SERVICE_USER))"; \
	if [ "$$OWN_SERVICE_USER" -eq 1 ]; then \
	  echo "    SKIP git config --system safe.directory: the clone is owned by the"; \
	  echo "    invoking user, so git raises no dubious-ownership error to suppress."; \
	else \
	  $(SUDO) git config --system --add safe.directory "$(DATA_DIR)"; \
	  $(SUDO) git config --system --add safe.directory "$(DATA_REMOTE)"; \
	fi; \
	$(RUN_AS) git -C "$(DATA_DIR)" config user.name  "$(EDITOR_GIT_NAME)"; \
	$(RUN_AS) git -C "$(DATA_DIR)" config user.email "$(EDITOR_GIT_EMAIL)"; \
	if [ "$(SYSTEMD_UNIT_DIR)" != /etc/systemd/system ]; then \
	  echo "==> SKIP systemctl: unit went to $(SYSTEMD_UNIT_DIR), not the system unit dir"; \
	elif [ "$(OPT_ROOT)" != /opt/shaw-spell ]; then \
	  echo "==> SKIP systemctl: OPT_ROOT is $(OPT_ROOT), but the unit hardcodes"; \
	  echo "    /opt/shaw-spell, so the system daemon would read the wrong tree"; \
	else \
	  echo "==> systemd daemon-reload + (re)start"; \
	  $(SUDO) systemctl daemon-reload; \
	  $(SUDO) systemctl enable shaw-spell-editord; \
	  $(SUDO) systemctl restart shaw-spell-editord; \
	fi; \
	echo; \
	echo "============================================================"; \
	echo "Installed:"; \
	echo "  web tier   -> $(WWW_ROOT_EDITOR) (editor.cgi, index.cgi, authstore.py, js/css/fonts, keyboard)"; \
	echo "  code       -> $(OPT_ROOT)/src/{editor,tools} (copied) + the systemd unit"; \
	echo "  readlex    -> $(OPT_ROOT)/external/readlex (copied, read-only basis)"; \
	echo "  corpus     -> $(OPT_ROOT)/$(FREQUENCY_CORPUS) (copied; publish-time frequency source)"; \
	echo "  data files -> daemon runtime files verified present in $(DATA_DIR)"; \
	echo "  data       -> $(DATA_DIR) (git clone of $(DATA_REMOTE); daemon commits+pushes)"; \
	echo "  patches    -> $(DATA_DIR)/patches/ (IN the clone → Commit button can commit+push)"; \
	echo "  auth db    -> $(VAR_LIB)/auth (owned by $(SERVICE_USER); existing data preserved)"; \
	echo; \
	if [ "$(SYSTEMD_UNIT_DIR)" = /etc/systemd/system ] && [ "$(OPT_ROOT)" = /opt/shaw-spell ]; then \
	  echo "The daemon is enabled and running."; \
	fi; \
	echo "Remaining MANUAL steps (this target cannot safely guess these):"; \
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
