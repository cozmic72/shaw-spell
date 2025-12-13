# Shared code signing configuration and logic
# Include this in Makefiles that need to sign bundles

# Load signing configuration if it exists
-include $(REPO_ROOT)/.signing-config

# Signing identity (optional - set in .signing-config or leave empty to skip signing)
CODESIGN_IDENTITY ?=

# Sign a bundle with proper hardened runtime flags
# Usage: $(call SIGN_BUNDLE,bundle_path,entitlements_file)
# Example: $(call SIGN_BUNDLE,$(BUNDLE_DIR),$(ENTITLEMENTS))
define SIGN_BUNDLE
	@if [ -n "$(CODESIGN_IDENTITY)" ]; then \
		echo "Code signing bundle with: $(CODESIGN_IDENTITY)"; \
		IDENTITY='$(CODESIGN_IDENTITY)'; \
		if [ -n "$(2)" ]; then \
			codesign --force --options runtime --timestamp --sign "$$IDENTITY" --entitlements "$(2)" "$(1)"; \
		else \
			codesign --force --options runtime --timestamp --sign "$$IDENTITY" "$(1)"; \
		fi \
	else \
		echo "Skipping code signing (no identity configured in .signing-config)"; \
	fi
endef

# Sign a library/framework (no entitlements needed, but same runtime flags)
# Usage: $(call SIGN_LIBRARY,library_path)
define SIGN_LIBRARY
	@if [ -n "$(CODESIGN_IDENTITY)" ]; then \
		IDENTITY='$(CODESIGN_IDENTITY)'; \
		codesign --force --options runtime --timestamp --sign "$$IDENTITY" "$(1)"; \
	fi
endef
