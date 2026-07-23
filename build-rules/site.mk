# Build rules for web frontend
#
# Builds the shaw-dict.com web dictionary application
# - Converts XML dictionaries to JSON indexes
# - Deploys static frontend (HTML, CSS, JS)
# - Generates deployable tarballs for Linux/web servers

# Note: BUILD_SITE and BUILD_SITE_DATA are defined in common.mk

# Site data files (JSON indexes) - individual targets for parallel builds
$(BUILD_SITE_DATA)/english-shavian-gb-index.json $(BUILD_SITE_DATA)/english-shavian-gb-entries.json: $(BUILD_DICT_XML)/english-shavian-gb.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building English-Shavian (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py english-shavian-gb

$(BUILD_SITE_DATA)/english-shavian-us-index.json $(BUILD_SITE_DATA)/english-shavian-us-entries.json: $(BUILD_DICT_XML)/english-shavian-us.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building English-Shavian (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py english-shavian-us

$(BUILD_SITE_DATA)/shavian-english-gb-index.json $(BUILD_SITE_DATA)/shavian-english-gb-entries.json: $(BUILD_DICT_XML)/shavian-english-gb.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-English (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-english-gb

$(BUILD_SITE_DATA)/shavian-english-us-index.json $(BUILD_SITE_DATA)/shavian-english-us-entries.json: $(BUILD_DICT_XML)/shavian-english-us.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-English (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-english-us

$(BUILD_SITE_DATA)/shavian-shavian-gb-index.json $(BUILD_SITE_DATA)/shavian-shavian-gb-entries.json: $(BUILD_DICT_XML)/shavian-shavian-gb.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-Shavian (GB) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-shavian-gb

$(BUILD_SITE_DATA)/shavian-shavian-us-index.json $(BUILD_SITE_DATA)/shavian-shavian-us-entries.json: $(BUILD_DICT_XML)/shavian-shavian-us.xml $(SRC_SITE)/build_site_index.py | $(BUILD_SITE_DATA)
	@echo "Building Shavian-Shavian (US) web indexes..."
	$(RUN) $(SRC_SITE)/build_site_index.py shavian-shavian-us

# Collect all site data files for convenience
SITE_DATA_FILES = $(BUILD_SITE_DATA)/english-shavian-gb-index.json \
                  $(BUILD_SITE_DATA)/english-shavian-gb-entries.json \
                  $(BUILD_SITE_DATA)/english-shavian-us-index.json \
                  $(BUILD_SITE_DATA)/english-shavian-us-entries.json \
                  $(BUILD_SITE_DATA)/shavian-english-gb-index.json \
                  $(BUILD_SITE_DATA)/shavian-english-gb-entries.json \
                  $(BUILD_SITE_DATA)/shavian-english-us-index.json \
                  $(BUILD_SITE_DATA)/shavian-english-us-entries.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-gb-index.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-gb-entries.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-us-index.json \
                  $(BUILD_SITE_DATA)/shavian-shavian-us-entries.json

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
                         $(SRC_SITE_DAEMON)/install.sh.template \
                         $(HUNSPELL_FILES) \
                         Makefile \
                         $(wildcard $(SRC_FONTS)/*)
	@echo "Deploying web frontend..."
	$(RUN) $(SRC_SITE)/deploy_site.py --version $(VERSION) --font-url $(FONT_URL)

.PHONY: site site-tarball clean-site

site: $(BUILD_SITE)/index.cgi
	@echo "Web dictionary frontend built successfully!"
	@echo "Location: $(BUILD_SITE)/"
	@echo "To test: src/tools/test_site.py 8000"

site-tarball:
	@if [ ! -f .site-config ]; then \
		echo "Error: .site-config file not found"; \
		echo ""; \
		echo "Create .site-config from the example:"; \
		echo "  cp .site-config.example .site-config"; \
		echo "  # Edit .site-config with your production FONT_URL"; \
		echo ""; \
		exit 1; \
	fi
	@echo "Building site with FONT_URL=$(FONT_URL)..."
	@$(MAKE) site
	@echo "Creating deployable site tarball..."
	@cd build && tar czf shaw-spell-site-$(VERSION).tar.gz site/
	@echo "✓ Tarball: build/shaw-spell-site-$(VERSION).tar.gz (v$(VERSION))"
	@echo "  Deploy: extract, then  sudo ./install.sh  (./install.sh --help for details)."
	@echo "  It installs the frontend + suggestd daemon and prints any remaining"
	@echo "  manual steps (hunspell prereq, Apache CGI check)."

clean-site:
	@echo "Cleaning web frontend artifacts..."
	@rm -rf $(BUILD_SITE) $(BUILD_SITE_DATA)
	@echo "Site clean complete"
