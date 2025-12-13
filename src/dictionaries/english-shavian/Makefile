#
# Makefile for English-Shavian Dictionary
#

###########################

DIALECT			?=	gb
DICT_NAME		=	English-Shavian-$(DIALECT)
DICT_SRC_PATH		=	../../../build/english-shavian-$(DIALECT).xml
CSS_PATH		=	EnglishShavian.css
PLIST_PATH		=	$(if $(filter us,$(DIALECT)),EnglishShavian-us.plist,EnglishShavian.plist)

DICT_BUILD_OPTS		=
# Suppress adding supplementary key.
# DICT_BUILD_OPTS		=	-s 0

###########################

DICT_BUILD_TOOL_DIR	=	"/Library/Developer/Dictionary Development Kit"
DICT_BUILD_TOOL_BIN	=	"$(DICT_BUILD_TOOL_DIR)/bin"

###########################

DICT_DEV_KIT_OBJ_DIR	=	../../../build/dictionaries/english-shavian-$(DIALECT)
export	DICT_DEV_KIT_OBJ_DIR

DESTINATION_FOLDER	=	~/Library/Dictionaries
RM			=	/bin/rm

###########################

all:
	"$(DICT_BUILD_TOOL_BIN)/build_dict.sh" $(DICT_BUILD_OPTS) $(DICT_NAME) $(DICT_SRC_PATH) $(CSS_PATH) $(PLIST_PATH)
	echo "Done building $(DICT_NAME)."

install:
	echo "Installing $(DICT_NAME) into $(DESTINATION_FOLDER)".
	mkdir -p $(DESTINATION_FOLDER)
	ditto --noextattr --norsrc $(DICT_DEV_KIT_OBJ_DIR)/$(DICT_NAME).dictionary  $(DESTINATION_FOLDER)/$(DICT_NAME).dictionary
	touch $(DESTINATION_FOLDER)
	echo "Done."
	echo "To test the new dictionary, try Dictionary.app."

clean:
	@echo "Dictionary objects are in build/dictionaries/ (cleaned by top-level Makefile)"
