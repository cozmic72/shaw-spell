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
$(BUILD_SITE)/index.cgi: $(SITE_DATA_FILES) $(shell find $(SRC_SITE) -type f 2>/dev/null) Makefile $(SRC_FONTS)/*.otf
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
	@echo "✓ Tarball created: build/shaw-spell-site-$(VERSION).tar.gz"
	@echo ""
	@echo "To deploy on Linux:"
	@echo "  1. Extract: tar xzf shaw-spell-site-$(VERSION).tar.gz"
	@echo "  2. Configure web server to serve site/ directory with CGI support"
	@echo "  3. Requires: Python 3 (standard library only)"
	@echo ""
	@echo "Configuration:"
	@echo "  Font URL: $(FONT_URL)"
	@echo "  Version:  $(VERSION)"

clean-site:
	@echo "Cleaning web frontend artifacts..."
	@rm -rf $(BUILD_SITE) $(BUILD_SITE_DATA)
	@echo "Site clean complete"
