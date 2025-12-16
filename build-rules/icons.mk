# Icon generation rules
# Generates all icons from the Ormin font

# Icon file paths in new structure
ICON_INSTALLER := $(BUILD_ICONS)/installer-AppIcon.icns
ICON_UNINSTALLER := $(BUILD_ICONS)/uninstaller-AppIcon.icns
ICON_VOLUME := $(BUILD_ICONS)/VolumeIcon.icns
ICON_FAVICON := $(BUILD_ICONS)/favicon.png
ICON_APPLE_TOUCH := $(BUILD_ICONS)/apple-touch-icon-180x180.png

# All icons
ALL_ICONS := $(ICON_INSTALLER) $(ICON_UNINSTALLER) $(ICON_VOLUME) \
             $(ICON_FAVICON) $(ICON_APPLE_TOUCH)

# Icon dependencies
ICON_GENERATOR := $(SRC_TOOLS)/generate-icons.py
ICON_FONT := $(SRC_FONTS)/Ormin-Regular.otf

# Generate all icons together (script generates all icons at once)
# Pick the installer icon as the canonical target since it's always needed
$(ICON_INSTALLER): $(ICON_GENERATOR) $(ICON_FONT) | $(BUILD_ICONS)
	@echo "Generating all icons..."
	$(RUN) python3 $(ICON_GENERATOR)
	@echo "Icons generated successfully"

# Other icons are generated alongside the installer icon
$(ICON_UNINSTALLER) $(ICON_VOLUME) $(ICON_FAVICON) $(ICON_APPLE_TOUCH): $(ICON_INSTALLER)

# Convenience target
.PHONY: icons
icons: $(ALL_ICONS)
	@echo "All icons built in $(BUILD_ICONS)/"
