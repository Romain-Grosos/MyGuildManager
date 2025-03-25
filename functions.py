def get_user_message(ctx, translations, key, **kwargs):
    """
    Utilise la locale du contexte si elle est disponible, sinon "en-US"
    """
    locale = getattr(ctx, "locale", "en-US")

    keys = key.split(".")
    entry = translations
    for k in keys:
        entry = entry.get(k, {})

    message = entry.get(locale) or entry.get("en-US") or ""
    return message.format(**kwargs)