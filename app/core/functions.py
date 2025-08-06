import logging
import re

# #################################################################################### #
#                            Translation System Utilities
# #################################################################################### #
def sanitize_kwargs(**kwargs):
    """
    Sanitize kwargs for safe string formatting in translations.
    
    Args:
        **kwargs: Keyword arguments to sanitize
        
    Returns:
        Dictionary of sanitized key-value pairs safe for string formatting
    """
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
    """
    Safely navigate nested dictionary structure with depth protection.
    
    Args:
        data: Dictionary to navigate
        keys: List of keys to traverse
        max_depth: Maximum traversal depth for security (default: 5)
        
    Returns:
        Retrieved value or None if not found or error occurred
    """
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

# #################################################################################### #
#                            Locale Management System
# #################################################################################### #
async def get_effective_locale(bot, guild_id: int, user_id: int) -> str:
    """
    Get effective locale for a user with hierarchical fallback system.
    
    Priority order:
    1. guild_members.language (user preference in guild context)
    2. user_setup.locale (global user preference)
    3. guild_settings.guild_lang (guild default)
    4. "en-US" (system fallback)
    
    Args:
        bot: Discord bot instance with cache system
        guild_id: Guild ID
        user_id: User ID
        
    Returns:
        Effective locale string (e.g., "en-US", "fr", "es-ES")
    """
    try:
        await bot.cache_loader.ensure_guild_settings_loaded()
        await bot.cache_loader.ensure_user_setup_loaded()

        guild_member_data = await bot.cache.get_guild_member_data(guild_id, user_id)
        if guild_member_data and guild_member_data.get('language'):
            member_language = guild_member_data.get('language')
            supported_locales = bot.translations.get('global', {}).get('supported_locales', [])
            
            if member_language == 'en' and 'en-US' in supported_locales:
                return 'en-US'
            elif member_language in supported_locales:
                return member_language
            else:
                return member_language

        user_setup_data = await bot.cache.get_user_setup_data(guild_id, user_id)
        if user_setup_data and user_setup_data.get('locale'):
            return user_setup_data.get('locale')

        guild_lang = await bot.cache.get_guild_data(guild_id, 'guild_lang')
        if guild_lang:
            return guild_lang

        return "en-US"
        
    except Exception as e:
        logging.error(f"[LocaleManager] Error getting effective locale for guild {guild_id}, user {user_id}: {e}")
        return "en-US"

# #################################################################################### #
#                            Main Translation Function
# #################################################################################### #
async def get_user_message(ctx, translations, key, **kwargs):
    """
    Get localized message from translations with safe formatting and fallbacks.
    
    Args:
        ctx: Discord context object with locale information
        translations: Translation dictionary
        key: Translation key in dot notation (e.g., 'commands.help.title')
        **kwargs: Variables for string formatting
        
    Returns:
        Formatted localized message string, empty string if error
    """
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

    if ctx and hasattr(ctx, 'bot') and hasattr(ctx, 'guild') and hasattr(ctx, 'author'):
        try:
            locale = await get_effective_locale(ctx.bot, ctx.guild.id, ctx.author.id)
        except Exception as e:
            logging.warning(f"[Translation] Failed to get effective locale, using ctx.locale: {e}")
            locale = getattr(ctx, "locale", "en-US")
    else:
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

async def get_guild_message(bot, guild_id: int, translations, key, **kwargs) -> str:
    """
    Get localized message for guild-wide announcements using guild language.
    
    Args:
        bot: Discord bot instance with cache system
        guild_id: Guild ID to get language preference for
        translations: Translation dictionary
        key: Translation key in dot notation
        **kwargs: Variables for string formatting
        
    Returns:
        Formatted localized message string using guild language
    """
    try:
        await bot.cache_loader.ensure_guild_settings_loaded()

        guild_lang = await bot.cache.get_guild_data(guild_id, 'guild_lang') or "en-US"

        keys = key.split(".")
        entry = get_nested_value(translations, keys)
        
        if entry is None or not isinstance(entry, dict):
            logging.warning(f"[Translation] Guild message key not found: {key}")
            return ""

        message = entry.get(guild_lang) or entry.get("en-US") or ""
        
        if not message:
            return ""

        try:
            safe_kwargs = sanitize_kwargs(**kwargs)
            return message.format(**safe_kwargs)
        except Exception as e:
            logging.error(f"[Translation] Guild message formatting error for key '{key}': {e}")
            return message
            
    except Exception as e:
        logging.error(f"[Translation] Error getting guild message for guild {guild_id}, key '{key}': {e}")
        return ""
