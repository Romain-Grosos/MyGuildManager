import json
import logging

try:
    with open("translations.json", "r", encoding="utf-8") as f:
        translations = json.load(f)
    logging.info("[TranslationsManager] 🔤 Translations loaded successfully.")
except Exception as e:
    logging.error(f"[TranslationsManager] ❌ Failed to load translations: {e}")
    translations = {}