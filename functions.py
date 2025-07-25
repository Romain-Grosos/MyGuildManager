import logging
import re

def sanitize_kwargs(**kwargs):
    safe_kwargs = {}
    for k, v in kwargs.items():
        if isinstance(k, str) and re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', k):
            if isinstance(v, (str, int, float, bool)):
                safe_kwargs[k] = str(v)[:200]
            else:
                safe_kwargs[k] = str(type(v).__name__)
        else:
            logging.warning(f"[Translation] Unsafe kwarg key filtered: {repr(k)}")
    return safe_kwargs

def get_nested_value(data, keys, max_depth=5):
    if len(keys) > max_depth:
        logging.warning(f"[Translation] Key depth exceeds limit: {'.'.join(keys)}")
        return None
    
    entry = data
    for i, k in enumerate(keys):
        if not isinstance(entry, dict):
            logging.error(f"[Translation] Unexpected structure at key level {i}: {'.'.join(keys[:i+1])}")
            return None
        
        entry = entry.get(k)
        if entry is None:
            logging.warning(f"[Translation] Key not found: {'.'.join(keys[:i+1])}")
            return None
    
    return entry

def get_user_message(ctx, translations, key, **kwargs):
    if not translations or not isinstance(translations, dict):
        logging.error("[Translation] Invalid translations dictionary")
        return ""
    
    if not key or not isinstance(key, str):
        logging.error("[Translation] Invalid key parameter")
        return ""
    
    key = key.strip()
    if len(key) > 100:
        logging.warning(f"[Translation] Key too long, truncating: {key[:50]}...")
        key = key[:100]

    if not re.match(r'^[a-zA-Z0-9_.]+$', key):
        logging.error(f"[Translation] Invalid key format: {repr(key)}")
        return ""
    
    locale = getattr(ctx, "locale", "en-US") if ctx else "en-US"

    keys = key.split(".")
    entry = get_nested_value(translations, keys)
    
    if entry is None:
        return ""
    
    if not isinstance(entry, dict):
        logging.error(f"[Translation] Final value for key '{key}' is not a dictionary.")
        return ""
    
    message = entry.get(locale) or entry.get("en-US") or ""
    
    if not message:
        logging.warning(f"[Translation] No message found for key '{key}' and locale '{locale}'")
        return ""

    if not isinstance(message, str):
        logging.error(f"[Translation] Message for key '{key}' is not a string: {type(message).__name__}")
        return ""

    try:
        safe_kwargs = sanitize_kwargs(**kwargs)
        formatted_message = message.format(**safe_kwargs)
    except KeyError as e:
        logging.error(f"[Translation] Missing placeholder {e} for key '{key}'")
        formatted_message = message
    except ValueError as e:
        logging.error(f"[Translation] Format string error for key '{key}': {e}")
        formatted_message = message
    except Exception as e:
        logging.error(f"[Translation] Unexpected formatting error for key '{key}': {e}")
        formatted_message = message

    return formatted_message