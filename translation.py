import json
import logging
import os

translations = {}

translations_file = "translation.json"

if not os.path.exists(translations_file):
    logging.error(f"[TranslationsManager] ❌ Translations file '{translations_file}' not found.")
else:
    try:
        with open(translations_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
        logging.info("[TranslationsManager] 🔤 Translations loaded successfully.")
    except json.JSONDecodeError as e:
        logging.error(f"[TranslationsManager] ❌ Failed to decode translations JSON: {e}")
    except Exception as e:
        logging.error(f"[TranslationsManager] ❌ Failed to load translations: {e}")
