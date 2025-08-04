"""
Discord bot cogs (extensions) for various guild management features.
"""

# List of all available cogs for easy loading
AVAILABLE_COGS = [
    "absence",
    "autorole", 
    "contract",
    "core",
    "dynamic_voice",
    "epic_items_scraper",
    "guild_attendance",
    "guild_events",
    "guild_init",
    "guild_members",
    "guild_ptb",
    "llm",
    "loot_wishlist",
    "notification",
    "profile_setup"
]

def get_cog_path(cog_name: str) -> str:
    """Get the import path for a cog."""
    return f"app.cogs.{cog_name}"
