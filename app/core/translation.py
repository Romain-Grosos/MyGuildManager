import json
import logging
import os
import sys

from ..config import TRANSLATION_FILE, MAX_TRANSLATION_FILE_SIZE

# #################################################################################### #
#                            Translation System Loader
# #################################################################################### #
translations = {}

def load_translations():
    """
    Load and validate translation file with comprehensive error handling.

    Loads the JSON translation file, validates its structure and content,
    and populates the global translations dictionary. Exits the program
    if any critical errors occur during loading.

    Raises:
        SystemExit: If translation file is missing, invalid, or cannot be loaded
    """
    global translations
    
    if not os.path.exists(TRANSLATION_FILE):
        logging.error(f"[TranslationsManager] Translations file '{TRANSLATION_FILE}' not found.")
        logging.error("[TranslationsManager] Critical error: Cannot continue without translations.")
        sys.exit(1)
    
    try:
        file_size = os.path.getsize(TRANSLATION_FILE)
        if file_size > MAX_TRANSLATION_FILE_SIZE:
            logging.error(f"[TranslationsManager] Translation file too large: {file_size} bytes (max: {MAX_TRANSLATION_FILE_SIZE})")
            sys.exit(1)
        
        if file_size == 0:
            logging.error(f"[TranslationsManager] Translation file is empty: {TRANSLATION_FILE}")
            sys.exit(1)
            
        with open(TRANSLATION_FILE, "r", encoding="utf-8") as f:
            translations = json.load(f)
            
        if not isinstance(translations, dict):
            logging.error("[TranslationsManager] Translation file must contain a JSON object")
            sys.exit(1)
            
        if not translations:
            logging.error("[TranslationsManager] Translation file contains no translations")
            sys.exit(1)
            
        logging.info(f"[TranslationsManager] Translations loaded successfully ({len(translations)} entries).")
        
    except json.JSONDecodeError as e:
        logging.error(f"[TranslationsManager] Failed to decode translations JSON: {e}")
        sys.exit(1)
    except PermissionError:
        logging.error(f"[TranslationsManager] Permission denied reading translations file: {TRANSLATION_FILE}")
        sys.exit(1)
    except OSError as e:
        logging.error(f"[TranslationsManager] OS error reading translations file: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"[TranslationsManager] Unexpected error loading translations: {e}")
        sys.exit(1)

load_translations()

