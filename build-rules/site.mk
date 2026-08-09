# Build rules for web frontend
#
# Builds the shaw-dict.com web dictionary application.
#
# BUILD MACHINE (`make site`): builds the XML dictionaries, derives the JSON
# indexes and hunspell dictionaries into the DATA repo (data/site-data,
# data/hunspell — committed artifacts, byte-deterministic), and stages the
# frontend into build/site. Commit + push the data repo to publish.
#
# SERVER (`make install-site`): stages from src/ + the data checkout and
# installs (web tier + suggestd daemon). It NEVER runs the dictionary/index
# generators — the server is far too slow for them (and lacks shyphenate, so
# its output would silently differ). Missing prebuilt data is a loud failure,
# never a fallback build.

# Note: BUILD_SITE is defined in common.mk
SITE_DATA_DIR := data/site-data
DATA_HUNSPELL_DIR := data/hunspell

$(SITE_DATA_DIR) $(DATA_HUNSPELL_DIR):
	@mkdir -p $@

# Site data files (JSON indexes) - individual targets for parallel builds
$(SITE_DATA_DIR)/english-shavian-gb-index.json $(SITE_DATA_DIR)/english-shavian-gb-entries.json $(SITE_DATA_DIR)/english-shavian-gb-summaries.json: $(BUILD_DICT_XML)/english-shavian-gb.xml $(SRC_SITE)/build_site_index.py | $(SITE_DATA_DIR)
	@echo "Building English-Shavian (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py english-shavian-gb

$(SITE_DATA_DIR)/english-shavian-us-index.json $(SITE_DATA_DIR)/english-shavian-us-entries.json $(SITE_DATA_DIR)/english-shavian-us-summaries.json: $(BUILD_DICT_XML)/english-shavian-us.xml $(SRC_SITE)/build_site_index.py | $(SITE_DATA_DIR)
	@echo "Building English-Shavian (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py english-shavian-us

$(SITE_DATA_DIR)/shavian-english-gb-index.json $(SITE_DATA_DIR)/shavian-english-gb-entries.json $(SITE_DATA_DIR)/shavian-english-gb-summaries.json: $(BUILD_DICT_XML)/shavian-english-gb.xml $(SRC_SITE)/build_site_index.py | $(SITE_DATA_DIR)
	@echo "Building Shavian-English (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-english-gb

$(SITE_DATA_DIR)/shavian-english-us-index.json $(SITE_DATA_DIR)/shavian-english-us-entries.json $(SITE_DATA_DIR)/shavian-english-us-summaries.json: $(BUILD_DICT_XML)/shavian-english-us.xml $(SRC_SITE)/build_site_index.py | $(SITE_DATA_DIR)
	@echo "Building Shavian-English (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-english-us

$(SITE_DATA_DIR)/shavian-shavian-gb-index.json $(SITE_DATA_DIR)/shavian-shavian-gb-entries.json $(SITE_DATA_DIR)/shavian-shavian-gb-summaries.json: $(BUILD_DICT_XML)/shavian-shavian-gb.xml $(SRC_SITE)/build_site_index.py | $(SITE_DATA_DIR)
	@echo "Building Shavian-Shavian (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-shavian-gb

$(SITE_DATA_DIR)/shavian-shavian-us-index.json $(SITE_DATA_DIR)/shavian-shavian-us-entries.json $(SITE_DATA_DIR)/shavian-shavian-us-summaries.json: $(BUILD_DICT_XML)/shavian-shavian-us.xml $(SRC_SITE)/build_site_index.py | $(SITE_DATA_DIR)
	@echo "Building Shavian-Shavian (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-shavian-us

# Collect all site data files for convenience
SITE_DATA_FILES = $(SITE_DATA_DIR)/english-shavian-gb-index.json \
                  $(SITE_DATA_DIR)/english-shavian-gb-entries.json \
                  $(SITE_DATA_DIR)/english-shavian-gb-summaries.json \
                  $(SITE_DATA_DIR)/english-shavian-us-index.json \
                  $(SITE_DATA_DIR)/english-shavian-us-entries.json \
                  $(SITE_DATA_DIR)/english-shavian-us-summaries.json \
                  $(SITE_DATA_DIR)/shavian-english-gb-index.json \
                  $(SITE_DATA_DIR)/shavian-english-gb-entries.json \
                  $(SITE_DATA_DIR)/shavian-english-gb-summaries.json \
                  $(SITE_DATA_DIR)/shavian-english-us-index.json \
                  $(SITE_DATA_DIR)/shavian-english-us-entries.json \
                  $(SITE_DATA_DIR)/shavian-english-us-summaries.json \
                  $(SITE_DATA_DIR)/shavian-shavian-gb-index.json \
                  $(SITE_DATA_DIR)/shavian-shavian-gb-entries.json \
                  $(SITE_DATA_DIR)/shavian-shavian-gb-summaries.json \
                  $(SITE_DATA_DIR)/shavian-shavian-us-index.json \
                  $(SITE_DATA_DIR)/shavian-shavian-us-entries.json \
                  $(SITE_DATA_DIR)/shavian-shavian-us-summaries.json

# The suggest daemon's hunspell dictionaries are derived data too (built from
# readlex/wordnet by spellcheck.mk), so they ship the same way as site-data:
# published into the data repo on the build machine, read from the data
# checkout on the server.
DATA_HUNSPELL_FILES = $(patsubst $(BUILD_HUNSPELL)/%,$(DATA_HUNSPELL_DIR)/%,$(HUNSPELL_FILES))

$(DATA_HUNSPELL_DIR)/%: $(BUILD_HUNSPELL)/% | $(DATA_HUNSPELL_DIR)
	install -m 644 $< $@

# Deploy site files to build/site (using index.cgi as representative target)
# Depends on:
#   - built site data indexes (JSON)
#   - everything under src/site (HTML, CSS, JS, CGI)
#   - everything under src/site-daemon (suggestd.py, systemd unit)
#   - font source files (any format)
#   - hunspell dictionaries (bundled for the daemon)
$(BUILD_SITE)/index.cgi: $(SITE_DATA_FILES) \
                         $(VK_SITE_STAMP) \
                         $(shell find $(SRC_SITE) -type f 2>/dev/null) \
                         $(shell find $(SRC_SITE_DAEMON) -type f 2>/dev/null) \
                         $(DATA_HUNSPELL_FILES) \
                         Makefile \
                         $(wildcard $(SRC_FONTS)/*)
	@echo "Deploying web frontend..."
	$(RUN) $(SRC_SITE)/deploy_site.py --version $(VERSION) --font-url $(FONT_URL)

.PHONY: site install-site clean-site

# --- install-site: stage from prebuilt data, then install into place ---
#
# Runs ON THE SERVER, in this repo's checkout. Deliberately NOT dependent on
# `site`: that graph reaches back through the index/XML generators, and the
# server must never run those (see the header above). Instead the recipe
# verifies the prebuilt artifacts are in the data checkout, stages build/site
# from src/ + data/ (cheap copies + $VERSION$ substitution), and installs the
# staged tree. Run as the normal user: `make install-site`.
# Only the privileged commands (writing /var/www, /opt, /etc/systemd, systemctl)
# escalate via sudo; the staging itself never runs as root.
#
# This server ALSO hosts the editor (make install-editor). The two share
# /opt/shaw-spell and the /var/www/shaw-spell docroot, so every removal here is
# SCOPED to the site's own subdirs — NEVER rm -rf the whole docroot or /opt.
# Idempotent: safe to re-run to upgrade.
#
# Override any path on the command line, e.g.
#   make install-site WWW_ROOT_SITE=/srv/www/shaw-spell
WWW_ROOT_SITE ?= /var/www/shaw-spell
# OPT_ROOT / SERVICE_USER default in editor.mk (shared); redeclare defensively
# in case site.mk is used without editor.mk.
OPT_ROOT ?= /opt/shaw-spell
SERVICE_USER ?= www-data

install-site: $(VK_SITE_STAMP)
	@set -eu; \
	[ "$(FONT_URL)" != "/fonts" ] || { \
	  echo "install-site: FONT_URL is still the local default — staging bakes it into" >&2; \
	  echo "  the pages, and /fonts is wrong for production. Supply it here:" >&2; \
	  echo "      make install-site FONT_URL=https://joro.io/fonts" >&2; \
	  exit 1; }; \
	echo "==> Advancing the data submodule to the pinned commit"; \
	git submodule update --init --recursive data; \
	for f in $(SITE_DATA_FILES) $(DATA_HUNSPELL_FILES); do \
	  [ -f "$$f" ] || { \
	    echo "install-site: prebuilt dictionary data missing after submodule update: $$f" >&2; \
	    echo "  This machine NEVER builds dictionaries — it is far too slow for the" >&2; \
	    echo "  generators, and without shyphenate its output would differ. Build on" >&2; \
	    echo "  the Mac: 'make site', commit data/site-data + data/hunspell in the" >&2; \
	    echo "  data repo, push, then re-run here." >&2; \
	    exit 1; }; \
	done; \
	echo "==> Staging site from src/ + prebuilt data/ -> $(BUILD_SITE)"; \
	$(SRC_SITE)/deploy_site.py --version $(VERSION) --font-url $(FONT_URL); \
	HERE="$(BUILD_SITE)"; \
	echo "==> Preflight: verifying staged site tree in $$HERE"; \
	for d in css js fonts templates virtual-keyboard site-daemon site-data hunspell; do \
	  [ -d "$$HERE/$$d" ] || { echo "install-site: expected dir missing from staged tree: $$d" >&2; exit 1; }; \
	done; \
	for f in index.cgi card.cgi sitecommon.py .htaccess site-daemon/suggestd.py site-daemon/shaw-spell-suggestd.service; do \
	  [ -f "$$HERE/$$f" ] || { echo "install-site: expected file missing from staged tree: $$f" >&2; exit 1; }; \
	done; \
	echo "==> Installing Shaw-Spell site"; \
	echo "    web:      $(WWW_ROOT_SITE)"; \
	echo "    daemon:   $(OPT_ROOT)/{site-daemon,site-data,hunspell}"; \
	echo; \
	echo "==> Web tier -> $(WWW_ROOT_SITE)"; \
	sudo mkdir -p "$(WWW_ROOT_SITE)"; \
	sudo install -m 755 "$$HERE/index.cgi" "$(WWW_ROOT_SITE)/index.cgi"; \
	sudo install -m 755 "$$HERE/card.cgi" "$(WWW_ROOT_SITE)/card.cgi"; \
	sudo install -m 644 "$$HERE/.htaccess" "$(WWW_ROOT_SITE)/.htaccess"; \
	[ -f "$$HERE/.version" ] && sudo install -m 644 "$$HERE/.version" "$(WWW_ROOT_SITE)/.version" || true; \
	$(call replace-dir-tree,$$HERE,$(WWW_ROOT_SITE),css js fonts templates virtual-keyboard); \
	echo "==> Daemon + data -> $(OPT_ROOT)"; \
	sudo mkdir -p "$(OPT_ROOT)"; \
	$(call replace-dir-tree,$$HERE,$(OPT_ROOT),site-daemon site-data hunspell); \
	sudo install -m 644 "$$HERE/site-daemon/shaw-spell-suggestd.service" \
	                    /etc/systemd/system/shaw-spell-suggestd.service; \
	if ! python3 -c "import PIL" 2>/dev/null; then \
	  echo "==> Installing python3-pil (card.cgi renders the social-preview images)"; \
	  sudo apt-get install -y python3-pil; \
	  python3 -c "import PIL" || { \
	    echo "install-site: python3-pil installed but 'import PIL' still fails" >&2; exit 1; }; \
	fi; \
	HUNSPELL_OK=1; \
	if ! python3 -c "import hunspell" 2>/dev/null; then \
	  HUNSPELL_OK=0; \
	  echo; \
	  echo "!! WARNING: python3 cannot 'import hunspell' — the daemon WILL fail to start." >&2; \
	  echo "!! Install the prerequisite, then re-run (or just restart the unit):" >&2; \
	  echo "!!     sudo apt install libhunspell-dev" >&2; \
	  echo "!!     sudo pip3 install hunspell" >&2; \
	  echo; \
	fi; \
	echo "==> systemd daemon-reload + enable"; \
	sudo systemctl daemon-reload; \
	if [ "$$HUNSPELL_OK" -eq 1 ]; then \
	  sudo systemctl enable shaw-spell-suggestd; \
	  sudo systemctl restart shaw-spell-suggestd; \
	else \
	  sudo systemctl enable shaw-spell-suggestd; \
	  echo "   (enabled but NOT started — install hunspell then: sudo systemctl start shaw-spell-suggestd)"; \
	fi; \
	echo; \
	echo "============================================================"; \
	echo "Installed:"; \
	echo "  web tier   -> $(WWW_ROOT_SITE) (index.cgi, card.cgi, css/, js/, fonts/, templates/, virtual-keyboard/)"; \
	echo "  daemon     -> $(OPT_ROOT)/site-daemon + /etc/systemd/system/shaw-spell-suggestd.service"; \
	echo "  data       -> $(OPT_ROOT)/{site-data,hunspell}"; \
	echo "  (the editor's $(WWW_ROOT_SITE)/editor and $(OPT_ROOT)/{src,external,data} are untouched)"; \
	echo; \
	echo "The CGI talks to the daemon over /run/shaw-spell/suggestd.sock. If the daemon"; \
	echo "is down, the site returns errors (no silent fallback)."; \
	echo; \
	echo "Remaining MANUAL steps (this target cannot safely do these):"; \
	echo; \
	echo "1. Apache must serve $(WWW_ROOT_SITE) with CGI enabled (ExecCGI, .cgi handler,"; \
	echo "   DirectoryIndex index.cgi). The owner's Apache already does this, so this is"; \
	echo "   typically a NO-OP — verify with:  curl -sI https://<host>/ | head -1"; \
	if [ "$$HUNSPELL_OK" -eq 0 ]; then \
	  echo "2. Install the hunspell python binding (see the WARNING above), then:"; \
	  echo "     sudo systemctl start shaw-spell-suggestd"; \
	fi; \
	echo "============================================================"; \
	echo "Done."

site: $(BUILD_SITE)/index.cgi
	@echo "Web dictionary frontend built successfully!"
	@echo "Location: $(BUILD_SITE)/"
	@echo ""
	@echo "Serve it with:  src/tools/test_site.py <port>"
	@echo ""
	@echo "That script is the ONLY way to serve this site locally. It is not"
	@echo "merely a convenience: index.cgi sits at the docroot ROOT, and stock"
	@echo "http.server executes CGI only under /cgi-bin/ — even with --cgi. So"
	@echo "'python3 -m http.server --cgi' serves index.cgi as a FILE and every"
	@echo "request 404s or returns the unexecuted template. test_site.py"
	@echo "subclasses CGIHTTPRequestHandler to fix exactly that, and starts the"
	@echo "suggestd daemon the CGI needs."

# data/site-data + data/hunspell are committed artifacts, not build output —
# clean never touches them.
clean-site:
	@echo "Cleaning web frontend artifacts..."
	@rm -rf $(BUILD_SITE)
	@echo "Site clean complete"
