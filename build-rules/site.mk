# Build rules for web frontend
#
# Builds the shaw-dict.com web dictionary application
# - Converts XML dictionaries to JSON indexes
# - Stages the static frontend (HTML, CSS, JS) into build/site
# - install-site copies the staged tree into place (web tier + suggestd daemon)

# Note: BUILD_SITE and BUILD_SITE_DATA are defined in common.mk

# Site data files (JSON indexes) - individual targets for parallel builds
$(BUILD_SITE_DATA)/english-shavian-gb-index.json $(BUILD_SITE_DATA)/english-shavian-gb-entries.json $(BUILD_SITE_DATA)/english-shavian-gb-summaries.json: $(BUILD_DICT_XML)/english-shavian-gb.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building English-Shavian (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py english-shavian-gb

$(BUILD_SITE_DATA)/english-shavian-us-index.json $(BUILD_SITE_DATA)/english-shavian-us-entries.json $(BUILD_SITE_DATA)/english-shavian-us-summaries.json: $(BUILD_DICT_XML)/english-shavian-us.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building English-Shavian (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py english-shavian-us

$(BUILD_SITE_DATA)/shavian-english-gb-index.json $(BUILD_SITE_DATA)/shavian-english-gb-entries.json $(BUILD_SITE_DATA)/shavian-english-gb-summaries.json: $(BUILD_DICT_XML)/shavian-english-gb.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-English (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-english-gb

$(BUILD_SITE_DATA)/shavian-english-us-index.json $(BUILD_SITE_DATA)/shavian-english-us-entries.json $(BUILD_SITE_DATA)/shavian-english-us-summaries.json: $(BUILD_DICT_XML)/shavian-english-us.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-English (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-english-us

$(BUILD_SITE_DATA)/shavian-shavian-gb-index.json $(BUILD_SITE_DATA)/shavian-shavian-gb-entries.json $(BUILD_SITE_DATA)/shavian-shavian-gb-summaries.json: $(BUILD_DICT_XML)/shavian-shavian-gb.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-Shavian (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-shavian-gb

$(BUILD_SITE_DATA)/shavian-shavian-us-index.json $(BUILD_SITE_DATA)/shavian-shavian-us-entries.json $(BUILD_SITE_DATA)/shavian-shavian-us-summaries.json: $(BUILD_DICT_XML)/shavian-shavian-us.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-Shavian (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-shavian-us

# Collect all site data files for convenience
SITE_DATA_FILES = $(BUILD_SITE_DATA)/english-shavian-gb-index.json \
                  $(BUILD_SITE_DATA)/english-shavian-gb-entries.json \
                  $(BUILD_SITE_DATA)/english-shavian-gb-summaries.json \
                  $(BUILD_SITE_DATA)/english-shavian-us-index.json \
                  $(BUILD_SITE_DATA)/english-shavian-us-entries.json \
                  $(BUILD_SITE_DATA)/english-shavian-us-summaries.json \
                  $(BUILD_SITE_DATA)/shavian-english-gb-index.json \
                  $(BUILD_SITE_DATA)/shavian-english-gb-entries.json \
                  $(BUILD_SITE_DATA)/shavian-english-gb-summaries.json \
                  $(BUILD_SITE_DATA)/shavian-english-us-index.json \
                  $(BUILD_SITE_DATA)/shavian-english-us-entries.json \
                  $(BUILD_SITE_DATA)/shavian-english-us-summaries.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-gb-index.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-gb-entries.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-gb-summaries.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-us-index.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-us-entries.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-us-summaries.json

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
                         $(HUNSPELL_FILES) \
                         Makefile \
                         $(wildcard $(SRC_FONTS)/*)
	@echo "Deploying web frontend..."
	$(RUN) $(SRC_SITE)/deploy_site.py --version $(VERSION) --font-url $(FONT_URL)

.PHONY: site install-site clean-site

# --- install-site: deploy the staged site from build/site into place ---
#
# Installs directly from the staged build tree (build/site, produced by
# `make site`): $HERE is that tree. Run as the normal user: `make install-site`.
# Only the privileged commands (writing /var/www, /opt, /etc/systemd, systemctl)
# escalate via sudo; the build itself never runs as root.
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

install-site: site
	@set -eu; \
	HERE="$(BUILD_SITE)"; \
	echo "==> Preflight: verifying staged site tree in $$HERE"; \
	for d in css js fonts templates virtual-keyboard site-daemon site-data hunspell; do \
	  [ -d "$$HERE/$$d" ] || { echo "install-site: expected dir missing from build: $$d (run 'make site')" >&2; exit 1; }; \
	done; \
	for f in index.cgi card.cgi .htaccess site-daemon/suggestd.py site-daemon/shaw-spell-suggestd.service; do \
	  [ -f "$$HERE/$$f" ] || { echo "install-site: expected file missing from build: $$f (run 'make site')" >&2; exit 1; }; \
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
	@echo "To test: src/tools/test_site.py 8000"

clean-site:
	@echo "Cleaning web frontend artifacts..."
	@rm -rf $(BUILD_SITE) $(BUILD_SITE_DATA)
	@echo "Site clean complete"
