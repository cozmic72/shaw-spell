# Installing the web faces into the shared font origin.
#
# $(FONT_URL) only ever POINTED at an origin; nothing populated it. joro.io/fonts
# serves InterAlia-VF.otf and 404s the rest, so a correct URL still renders the
# page in a fallback face with no error anywhere. This installs what the pages
# ask for.
#
# FONT_ROOT is SHARED — other repos in the family serve their own faces from the
# same directory — so this never removes anything it did not put there.
FONT_ROOT ?= /var/www/fonts

# The faces the BROWSER fetches from $(FONT_URL), which is what this origin is
# for. Hand-listed against the two @font-face consumers rather than globbed
# $(SRC_FONTS): a glob would publish the five static InterAlia cuts and the
# BernieSans .ttf, none of which any stylesheet names, and the .ttf especially
# is a 155K download nobody would ever fetch.
#
# The consumers, and what each contributes:
#   src/site/css/style.css                 BernieSansBetaVF.woff2
#   external/virtual-keyboard/*.css        InterAlia-VF.otf
# Ormin-Regular.otf is NOT here — icons.mk bakes it into images at build time.
# card.cgi's BernieSansBetaVF.ttf and InterAlia-Regular.otf are not here either:
# PIL reads those from the docroot's own fonts/ beside the CGI, which
# deploy_site.py stages, and they are never fetched over HTTP.
#
# Adding an @font-face means adding its file here. The check below is what makes
# that hard to forget.
WEB_FONTS := BernieSansBetaVF.woff2 InterAlia-VF.otf

INSTALLED_FONTS := $(addprefix $(FONT_ROOT)/,$(WEB_FONTS))

# Order-only, so the checks run before the first copy rather than after the last
# one. A precondition hung on install-fonts itself would fire with the origin
# already rewritten, which is no precondition at all.
$(FONT_ROOT)/%: $(SRC_FONTS)/% | fonts-preconditions
	$(SUDO) mkdir -p $(@D)
	$(SUDO) install -m 644 $< $@

.PHONY: install-fonts
install-fonts: $(INSTALLED_FONTS)
	@echo "Fonts at $(FONT_ROOT): $(WEB_FONTS)"

# A face named by a stylesheet but absent from WEB_FONTS is the sitecommon.py
# defect again — an install list and a requirement list drifting apart, found in
# production. Grep the consumers for what they fetch and demand the lists agree.
FONT_FACE_CONSUMERS := $(SRC_SITE)/css/style.css $(VK_SRC)/virtual-keyboard.css

.PHONY: fonts-preconditions
fonts-preconditions:
	@set -eu; \
	$(call require-files,$(addprefix $(SRC_FONTS)/,$(WEB_FONTS)) $(FONT_FACE_CONSUMERS),install-fonts); \
	$(call require-dest-dirs,$(FONT_ROOT),$(SUDO),install-fonts); \
	REQUESTED="$$(sed -n "s/.*url('[^']*\/\([^'\/]*\)').*/\1/p" $(FONT_FACE_CONSUMERS) | sort -u)"; \
	for f in $$REQUESTED; do \
	  case " $(WEB_FONTS) " in \
	    *" $$f "*) ;; \
	    *) echo "install-fonts: a stylesheet fetches $$f but WEB_FONTS does not list it," >&2; \
	       echo "  so the origin would 404 it. Add it to WEB_FONTS in build-rules/fonts.mk." >&2; \
	       exit 1;; \
	  esac; \
	done; \
	echo "    ok: font sources, $(FONT_ROOT), stylesheets request only listed faces"
