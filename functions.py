import logging

def get_user_message(ctx, translations, key, **kwargs):
    locale = getattr(ctx, "locale", "en-US")

    keys = key.split(".")
    entry = translations
    for k in keys:
        if isinstance(entry, dict):
            entry = entry.get(k)
            if entry is None:
                logging.warning(f"[Translation] Key not found in translations for '{key}'.")
                return ""
        else:
            logging.error(f"[Translation] Unexpected structure for key '{key}'.")
            return ""

    if not isinstance(entry, dict):
        logging.error(f"[Translation] Final value for key '{key}' is not a dictionary.")
        return ""

    message = entry.get(locale) or entry.get("en-US") or ""

    try:
        formatted_message = message.format(**kwargs)
    except KeyError as e:
        logging.error(f"[Translation] Missing placeholder {e} for key '{key}' in message '{message}'.")
        formatted_message = message
    except Exception as e:
        logging.error(f"[Translation] Formatting error for key '{key}': {e}")
        formatted_message = message

    return formatted_message