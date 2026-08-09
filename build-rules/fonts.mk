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
# The origin is shared and arbitration is "latest source timestamp wins", so the
# destination must carry the SOURCE's mtime, not the install's. `install` alone
# stamps now, which makes an older font deployed later win. `touch -r` rather
# than `install -p`: BSD's -p implies compare-and-copy, GNU's does not.
# Preserved mtimes also make make's own check correct — an older source is then
# skipped as up to date instead of overwriting a newer origin.
$(FONT_ROOT)/%: $(SRC_FONTS)/% | fonts-preconditions
	$(SUDO) mkdir -p $(@D)
	$(SUDO) install -m 644 $< $@
	$(SUDO) touch -r $< $@

.PHONY: install-fonts
install-fonts: $(INSTALLED_FONTS)
	@echo "Fonts at $(FONT_ROOT): $(WEB_FONTS)"

# A face named by a stylesheet but absent from WEB_FONTS is the sitecommon.py
# defect again — an install list and a requirement list drifting apart, found in
# production. Grep the consumers for what they fetch and demand the lists agree.
#
# Only the stylesheets whose url() this origin answers. src/editor/site/editor.css
# is deliberately absent: it names fonts/ relative to its own docroot, gets no
# {{FONT_URL}} substitution, and editor.mk installs the faces beside it.
FONT_FACE_CONSUMERS := $(SRC_SITE)/css/style.css $(VK_SRC)/virtual-keyboard.css

FONT_EXTENSIONS := woff2|woff|otf|ttf|eot

# The font filename in every url() a consumer contains. A newline before each
# url() puts one per line: `.*url(` matches only the last on a line and hides
# every earlier face. Quotes are optional and either kind, as is the path.
#
# Matched by extension rather than by enclosing @font-face block because the
# faces are written url('{{FONT_URL}}/x.woff2') and the placeholder's own braces
# end any attempt to read as far as the block's closing brace. Extensions also
# keep out background images, which this origin does not serve.
#
# ERE, because BSD sed has no \| alternation and the server's GNU sed accepts
# both — a BRE here would pass silently on the owner's Mac. The s@@@ delimiter
# is not cosmetic: # ends a make line, which truncates the script to `sed -nE "s`
# and leaves a check that matches nothing while still exiting 0.
font-faces-requested = { tr '\n' ' ' < $(1); echo; } | sed 's/url(/\n&/g' \
	| sed -nE "s@^url\([\"']?([^\"')]*/)?([^\"'/)]*\.($(FONT_EXTENSIONS)))[\"']?\).*@\2@p"

.PHONY: fonts-preconditions
fonts-preconditions:
	@set -eu; \
	$(call require-files,$(addprefix $(SRC_FONTS)/,$(WEB_FONTS)) $(FONT_FACE_CONSUMERS),install-fonts); \
	$(call require-dest-dirs,$(FONT_ROOT),$(SUDO),install-fonts); \
	REQUESTED="$$( { $(foreach c,$(FONT_FACE_CONSUMERS),$(call font-faces-requested,$(c)); ) } | sort -u)"; \
	for f in $$REQUESTED; do \
	  case " $(WEB_FONTS) " in \
	    *" $$f "*) ;; \
	    *) echo "install-fonts: a stylesheet fetches $$f but WEB_FONTS does not list it," >&2; \
	       echo "  so the origin would 404 it. Add it to WEB_FONTS in build-rules/fonts.mk." >&2; \
	       exit 1;; \
	  esac; \
	done; \
	echo "    ok: font sources, $(FONT_ROOT), stylesheets request only listed faces"
