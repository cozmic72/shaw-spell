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
#   external/shaw-keys/*.css               InterAlia-VF.otf
# Ormin-Regular.otf is NOT here — icons.mk bakes it into images at build time.
# card.cgi's BernieSansBetaVF.ttf and InterAlia-Regular.otf are not here either:
# PIL reads those from the docroot's own fonts/ beside the CGI, which
# deploy_site.py stages, and they are never fetched over HTTP.
WEB_FONTS := BernieSansBetaVF.woff2 InterAlia-VF.otf

INSTALLED_FONTS := $(addprefix $(FONT_ROOT)/,$(WEB_FONTS))

# The origin is shared and arbitration is "latest source timestamp wins", so the
# destination must carry the SOURCE's mtime, not the install's. `install` alone
# stamps now, which makes an older font deployed later win. `touch -r` rather
# than `install -p`: BSD's -p implies compare-and-copy, GNU's does not.
# Preserved mtimes also make make's own check correct — an older source is then
# skipped as up to date instead of overwriting a newer origin.
$(FONT_ROOT)/%: $(SRC_FONTS)/%
	$(SUDO) mkdir -p $(@D)
	$(SUDO) install -m 644 $< $@
	$(SUDO) touch -r $< $@

.PHONY: install-fonts
install-fonts: $(INSTALLED_FONTS)
	@echo "Fonts at $(FONT_ROOT): $(WEB_FONTS)"
