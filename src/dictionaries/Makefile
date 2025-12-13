#
# Unified Makefile for all Shaw-Spell dictionaries
#
# Builds any dictionary type (shavian-english, english-shavian, shavian-shavian)
# for any dialect (gb, us) using shared templates and CSS.
#

###########################
# Parameters
###########################

DICT_TYPE		?=	shavian-english
DIALECT			?=	gb

# Dictionary metadata based on type
ifeq ($(DICT_TYPE),shavian-english)
    DISPLAY_NAME	=	Shavian-English
    BUNDLE_ID_BASE	=	shavian-english
endif

ifeq ($(DICT_TYPE),english-shavian)
    DISPLAY_NAME	=	English-Shavian
    BUNDLE_ID_BASE	=	english-shavian
endif

ifeq ($(DICT_TYPE),shavian-shavian)
    DISPLAY_NAME	=	Shavian
    BUNDLE_ID_BASE	=	shavian-shavian
endif

# Paths and names
DICT_NAME		=	Shaw-Spell-$(DISPLAY_NAME)-$(DIALECT)
DICT_SRC_PATH		=	../../build/$(DICT_TYPE)-$(DIALECT).xml
CSS_PATH		=	dictionary.css
PLIST_PATH		=	../../build/dictionaries/$(DICT_TYPE)-$(DIALECT).plist
PLIST_TEMPLATE		=	dictionary.plist.template
DESCRIPTION_FILE	=	dictionary-description.html

# Bundle metadata
BUNDLE_ID		=	io.joro.shaw-spell.$(BUNDLE_ID_BASE)-$(DIALECT)
BUNDLE_NAME		=	$(DISPLAY_NAME) ($(shell echo $(DIALECT) | tr a-z A-Z))

# Build settings
DICT_BUILD_OPTS		=
DICT_BUILD_TOOL_DIR	=	"/Library/Developer/Dictionary Development Kit"
DICT_BUILD_TOOL_BIN	=	"$(DICT_BUILD_TOOL_DIR)/bin"

# Output paths
DICT_DEV_KIT_OBJ_DIR	=	../../build/dictionaries/$(DICT_TYPE)-$(DIALECT)
export DICT_DEV_KIT_OBJ_DIR

DICT_OUTPUT		=	$(DICT_DEV_KIT_OBJ_DIR)/$(DICT_NAME).dictionary
DESTINATION_FOLDER	=	~/Library/Dictionaries

###########################
# Targets
###########################

.PHONY: all install clean

all: $(DICT_OUTPUT)

# Generate plist from shared template
$(PLIST_PATH): $(PLIST_TEMPLATE) $(DESCRIPTION_FILE)
	@echo "Generating $@ from shared template..."
	@mkdir -p $(dir $@)
	@# First interpolate description with VERSION
	@./interpolate_template.py $(DESCRIPTION_FILE) $(DESCRIPTION_FILE).tmp VERSION="$(VERSION)"
	@# Then generate plist with interpolated description
	@./interpolate_template.py $(PLIST_TEMPLATE) $@ \
		BUNDLE_ID=$(BUNDLE_ID) \
		BUNDLE_NAME="$(BUNDLE_NAME)" \
		DESCRIPTION=$(DESCRIPTION_FILE).tmp
	@rm -f $(DESCRIPTION_FILE).tmp

# Build dictionary
$(DICT_OUTPUT): $(DICT_SRC_PATH) $(CSS_PATH) $(PLIST_PATH) $(DESCRIPTION_FILE)
	@echo "Building $(DICT_NAME) dictionary..."
	"$(DICT_BUILD_TOOL_BIN)/build_dict.sh" $(DICT_BUILD_OPTS) $(DICT_NAME) $(DICT_SRC_PATH) $(CSS_PATH) $(PLIST_PATH)
	@echo "Done building $(DICT_NAME)."

install: $(DICT_OUTPUT)
	@echo "Installing $(DICT_NAME) into $(DESTINATION_FOLDER)..."
	@mkdir -p $(DESTINATION_FOLDER)
	@ditto --noextattr --norsrc $(DICT_OUTPUT) $(DESTINATION_FOLDER)/$(DICT_NAME).dictionary
	@touch $(DESTINATION_FOLDER)
	@echo "Done. Test with Dictionary.app."

clean:
	@echo "Cleaning $(DICT_TYPE)-$(DIALECT) plist..."
	@rm -f $(PLIST_PATH)
