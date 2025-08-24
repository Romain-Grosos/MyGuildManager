"""
Profile Setup Cog - Manages member profile creation and role assignment workflow.
"""

import asyncio
import hashlib
import re
from datetime import datetime
from typing import Dict, Tuple, Any, Optional, List

import discord
import pytz
from discord.ext import commands
from discord.utils import escape_markdown, escape_mentions

from app.core.logger import ComponentLogger
from app.core.translation import translations as global_translations
from app.core.reliability import discord_resilient
from app.db import DBQueryError

MAX_PLAYTIME_LEN = 64
SUPPORTED_LOCALES = global_translations.get("global", {}).get(
    "supported_locales", ["en-US", "fr", "es-ES", "de", "it"]
)
LANGUAGE_NAMES = global_translations.get("global", {}).get("language_names", {})
WELCOME_MP = global_translations.get("welcome_mp", {})
PROFILE_SETUP_DATA = global_translations.get("profile_setup", {})

_logger = ComponentLogger("profile_setup")
_tz_france = pytz.timezone("Europe/Paris")
_slug_re = re.compile(r"[^a-z0-9-]+")

def _safe_txt(s: Any, limit: int = 64) -> str:
    """
    Sanitize user text to prevent markdown/mention exploits and enforce length limits.
    
    Args:
        s: User input (any type) to sanitize - will be converted to string
        limit: Maximum character limit (default: 64)
        
    Returns:
        Sanitized and length-limited text
    """
    s = str(s or "")[:limit]
    return escape_mentions(escape_markdown(s))

def _slugify(base: str, prefix: str = "") -> str:
    """
    Convert text to safe Discord channel name slug.
    
    Args:
        base: Base text to slugify
        prefix: Optional prefix to add
        
    Returns:
        Safe channel name slug (max 90 chars)
    """
    base = (base or "").lower().strip()
    base = base.replace(" ", "-")
    base = _slug_re.sub("-", base)
    base = re.sub(r"-{2,}", "-", base).strip("-")
    name = f"{prefix}{base}" if prefix else base
    return name[:90]

def tr(root: dict, path: List[str], locale: str, default: str = "") -> str:
    """
    Safely navigate deep dictionary paths for translation lookups.
    
    Prevents KeyErrors when accessing nested translation dictionaries.
    Falls back to en-US if locale not found, then to default.
    
    Args:
        root: Root dictionary to navigate
        path: List of keys representing the path to navigate
        locale: Target locale code (e.g. "fr", "es-ES")
        default: Default value if path/locale not found
        
    Returns:
        Translated string or default value
    """
    node = root
    for k in path:
        node = node.get(k, {})
    if isinstance(node, dict):
        return node.get(locale, node.get("en-US", default))
    return str(node) if node is not None else default


class ProfileSetup(commands.Cog):
    """Cog for managing member profile creation and role assignment workflow."""

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the ProfileSetup cog.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_locks: Dict[str, asyncio.Lock] = {}
        self._guild_cache: Dict[str, Tuple[Any, float]] = {}
        self._guild_cache_ttl = 300

    async def load_session(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        """
        Load or create a user session for profile setup.

        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID

        Returns:
            Dictionary containing user session data
        
        Raises:
            ValueError: If guild_id or user_id are invalid
        """
        if not isinstance(guild_id, int) or guild_id <= 0:
            raise ValueError(f"Invalid guild_id: {guild_id}")
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError(f"Invalid user_id: {user_id}")
            
        key = f"{guild_id}_{user_id}"
        if key not in self.sessions:
            self.sessions[key] = {}
        if key not in self.session_locks:
            self.session_locks[key] = asyncio.Lock()

        if len(self.sessions) > 1000:
            self._cleanup_old_sessions()
            
        return self.sessions[key]
    
    def _cleanup_old_sessions(self) -> None:
        """Clean up old sessions to prevent memory leaks."""
        if len(self.sessions) <= 500:
            return

        sessions_to_keep = 500
        keys_to_remove = list(self.sessions.keys())[:-sessions_to_keep]
        
        for key in keys_to_remove:
            self.sessions.pop(key, None)
            self.session_locks.pop(key, None)
            
        _logger.debug(
            "old_sessions_cleaned_up",
            removed_count=len(keys_to_remove),
            remaining_count=len(self.sessions)
        )
    
    async def _get_cached_guild_data(self, guild_id: int, data_type: str) -> Any:
        """
        Get guild data with local caching to reduce database hits.
        
        Args:
            guild_id: Discord guild ID
            data_type: Type of data to retrieve
            
        Returns:
            Cached data or fresh data from bot cache
        """
        import time
        
        cache_key = f"{guild_id}_{data_type}"
        current_time = time.monotonic()

        if cache_key in self._guild_cache:
            data, timestamp = self._guild_cache[cache_key]
            if current_time - timestamp < self._guild_cache_ttl:
                return data

        try:
            data = await self.bot.cache.get_guild_data(guild_id, data_type)
            self._guild_cache[cache_key] = (data, current_time)

            if len(self._guild_cache) > 100:
                self._cleanup_guild_cache()
                
            return data
        except Exception as e:
            _logger.error(
                "error_getting_cached_guild_data",
                guild_id=guild_id,
                data_type=data_type,
                error_type=type(e).__name__,
                error_msg=str(e)[:200]
            )
            return None
    
    def _cleanup_guild_cache(self) -> None:
        """Clean up expired guild cache entries."""
        import time
        current_time = time.monotonic()
        
        expired_keys = [
            key for key, (_, timestamp) in self._guild_cache.items()
            if current_time - timestamp > self._guild_cache_ttl
        ]
        
        for key in expired_keys:
            self._guild_cache.pop(key, None)
            
        if expired_keys:
            _logger.debug(
                "guild_cache_cleanup",
                expired_count=len(expired_keys),
                remaining_count=len(self._guild_cache)
            )

    async def get_guild_lang(self, guild_id: int) -> str:
        """
        Get guild language from cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            Guild language code (default: en-US)
        """
        if not isinstance(guild_id, int) or guild_id <= 0:
            _logger.warning("invalid_guild_id_for_lang", guild_id=guild_id)
            return "en-US"
            
        try:
            guild_lang = await self._get_cached_guild_data(guild_id, "guild_lang")
            return guild_lang or "en-US"
        except Exception as e:
            _logger.error(
                "error_getting_guild_lang",
                guild_id=guild_id,
                error_type=type(e).__name__,
                error_msg=str(e)[:200]
            )
            return "en-US"

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild settings from cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary containing guild settings
        """
        if not isinstance(guild_id, int) or guild_id <= 0:
            _logger.warning("invalid_guild_id_for_settings", guild_id=guild_id)
            return {}
            
        try:
            settings = await self._get_cached_guild_data(guild_id, "guild_settings")
            return settings or {}
        except Exception as e:
            _logger.error(
                "error_getting_guild_settings",
                guild_id=guild_id,
                error_type=type(e).__name__,
                error_msg=str(e)[:200]
            )
            return {}

    async def get_guild_roles(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild roles from cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary containing guild role IDs
        """
        if not isinstance(guild_id, int) or guild_id <= 0:
            _logger.warning("invalid_guild_id_for_roles", guild_id=guild_id)
            return {}
            
        try:
            roles = await self._get_cached_guild_data(guild_id, "roles")
            return roles or {}
        except Exception as e:
            _logger.error(
                "error_getting_guild_roles",
                guild_id=guild_id,
                error_type=type(e).__name__,
                error_msg=str(e)[:200]
            )
            return {}

    async def get_guild_channels(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild channels from cache.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary containing guild channel IDs
        """
        if not isinstance(guild_id, int) or guild_id <= 0:
            _logger.warning("invalid_guild_id_for_channels", guild_id=guild_id)
            return {}
            
        try:
            channels = await self._get_cached_guild_data(guild_id, "channels")
            return channels or {}
        except Exception as e:
            _logger.error(
                "error_getting_guild_channels",
                guild_id=guild_id,
                error_type=type(e).__name__,
                error_msg=str(e)[:200]
            )
            return {}

    async def _post(self, channel: discord.abc.GuildChannel, *, name: str, embed: discord.Embed, 
                   content: Optional[str] = None, view: Optional[discord.ui.View] = None, 
                   allowed_mentions: Optional[discord.AllowedMentions] = None):
        """
        Post to channel with automatic handling of ForumChannels vs regular channels.
        
        Args:
            channel: Discord channel to post to
            name: Thread name for forum channels
            embed: Embed to post
            content: Optional text content
            view: Optional Discord view
            allowed_mentions: Optional allowed mentions (defaults to none)
            
        Returns:
            Message or Thread object, or None if unsupported channel type
        """
        am = allowed_mentions or discord.AllowedMentions.none()
        kwargs = {"embed": embed, "allowed_mentions": am}
        if content:
            kwargs["content"] = content
        if view:
            kwargs["view"] = view
            
        if isinstance(channel, discord.ForumChannel):
            kwargs["name"] = name
            if "embed" in kwargs: kwargs["embeds"] = [kwargs.pop("embed")]
            return await channel.create_thread(**kwargs)
        elif isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await channel.send(**kwargs)
        else:
            _logger.error("unsupported_channel_type_for_post", channel_id=channel.id, typ=type(channel).__name__)
            return None

    async def get_welcome_message_for_user(
        self, guild_id: int, user_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get welcome message for a specific user from cache.

        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID

        Returns:
            Dictionary with welcome message info or None if not found
        """
        return await self.bot.cache.get_user_data(guild_id, user_id, "welcome_message")

    async def get_pending_validations(self) -> Dict[str, Dict[str, Any]]:
        """
        Get pending validations from cache.

        Returns:
            Dictionary containing pending diplomat validations
        """
        validations = await self.bot.cache.get("temporary", "pending_validations")
        return validations or {}

    def _sanitize_llm_input(self, text: str) -> str:
        """Sanitize text input for LLM queries to prevent prompt injection attacks.

        Args:
            text: Raw text input from user

        Returns:
            str: Sanitized text safe for LLM prompts
        """
        if not isinstance(text, str):
            return ""

        dangerous_patterns = [
            r"```.*?```",
            r"`[^`]*`",
            r"\n\s*[Rr]esponse:",
            r"\n\s*[Ii]nstruct(ion)?s?:",
            r"\n\s*[Tt]ask:",
            r"\n\s*[Ss]ystem:",
            r"\n\s*[Aa]ssistant:",
            r"\n\s*[Uu]ser:",
            r"<\|.*?\|>",
            r"\[INST\].*?\[/INST\]",
            r"###.*?###",
        ]

        sanitized = text
        for pattern in dangerous_patterns:
            sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE | re.DOTALL)

        sanitized = re.sub(r"\n+", " ", sanitized)
        sanitized = re.sub(r"\s+", " ", sanitized)

        sanitized = re.sub(r'[<>"\'`\\]', "", sanitized)

        max_length = 100
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length].strip()
            _logger.debug(
                "llm_input_truncated",
                max_length=max_length,
                original_length=len(text)
            )

        sanitized = sanitized.strip()
        if not sanitized:
            _logger.warning("llm_input_empty_after_sanitization", original_text=text[:50])
            return "Unknown"

        return sanitized

    def _validate_llm_response(
        self, response: str, original_input: str, valid_options: list
    ) -> str:
        """Validate LLM response to prevent malicious or unexpected outputs.

        Args:
            response: Raw response from LLM
            original_input: The original user input
            valid_options: List of valid response options

        Returns:
            str: Validated response or original input if validation fails
        """
        if not isinstance(response, str):
            _logger.warning("llm_response_invalid_type", response_type=type(response).__name__)
            return original_input

        cleaned_response = response.strip().strip('"').strip("'")

        if len(cleaned_response) > 200:
            _logger.warning(
                "llm_response_too_long",
                response_length=len(cleaned_response),
                max_allowed=200
            )
            return original_input

        dangerous_patterns = [
            r"```.*?```",
            r"<script",
            r"javascript:",
            r"data:",
            r"<.*?>",
            r"\n\s*[Ii]nstruct",
            r"\n\s*[Ss]ystem",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, cleaned_response, re.IGNORECASE | re.DOTALL):
                _logger.warning(
                    "llm_response_contains_dangerous_pattern",
                    pattern=pattern[:50],
                    response_preview=cleaned_response[:100]
                )
                return original_input

        if cleaned_response == original_input:
            return cleaned_response

        if cleaned_response in valid_options:
            return cleaned_response

        cleaned_lower = cleaned_response.lower()
        for option in valid_options:
            if option.lower() == cleaned_lower:
                return option

        _logger.warning(
            "llm_response_not_in_valid_options",
            response=cleaned_response,
            valid_options_count=len(valid_options),
            using_original=original_input
        )
        return original_input

    async def _load_pending_validations(self) -> None:
        """
        Load pending diplomat validations into cache.

        Retrieves all pending diplomat validations from database and stores
        them in cache for restoration after bot restart.
        """
        _logger.debug("loading_pending_validations_from_db")
        query = """
            SELECT guild_id, member_id, guild_name, channel_id, message_id, created_at 
            FROM pending_diplomat_validations 
            WHERE status = 'pending'
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            pending_validations = {}
            for row in rows:
                guild_id, member_id, guild_name, channel_id, message_id, created_at = (
                    row
                )
                key = f"{guild_id}_{member_id}_{guild_name}"
                pending_validations[key] = {
                    "guild_id": guild_id,
                    "member_id": member_id,
                    "guild_name": guild_name,
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "created_at": created_at,
                }
            await self.bot.cache.set(
                "temporary", pending_validations, "pending_validations"
            )
            _logger.debug(
                "pending_validations_loaded",
                entries_count=len(pending_validations)
            )
        except Exception as e:
            _logger.error(
                "error_loading_pending_validations",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )

    async def restore_pending_validation_views(self) -> None:
        """
        Restore pending validation views after bot restart.

        Re-attaches Discord UI views to pending validation messages
        so buttons remain functional after bot restarts.
        """
        _logger.debug("restoring_pending_validation_views")

        await asyncio.sleep(2)

        await self._load_pending_validations()

        pending_validations = await self.get_pending_validations()
        for key, validation_data in pending_validations.items():
            try:
                guild_id = validation_data["guild_id"]
                member_id = validation_data["member_id"]
                guild_name = validation_data["guild_name"]
                channel_id = validation_data["channel_id"]
                message_id = validation_data["message_id"]

                guild = self.bot.get_guild(guild_id)
                if not guild:
                    _logger.warning(
                        "guild_not_found_for_pending_validation",
                        guild_id=guild_id
                    )
                    await self._expire_pending(guild_id, member_id, guild_name)
                    continue

                member = guild.get_member(member_id)
                if not member:
                    _logger.warning(
                        "member_not_found_for_pending_validation",
                        member_id=member_id,
                        guild_id=guild_id
                    )
                    await self._expire_pending(guild_id, member_id, guild_name)
                    continue

                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if not channel:
                    _logger.warning(
                        "channel_not_found_for_pending_validation",
                        channel_id=channel_id,
                        guild_id=guild_id
                    )
                    await self._expire_pending(guild_id, member_id, guild_name)
                    continue

                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    _logger.warning(
                        "message_not_found_removing_from_pending",
                        message_id=message_id,
                        channel_id=channel_id
                    )
                    await self._expire_pending(guild_id, member_id, guild_name)
                    continue

                guild_lang = await self.get_guild_lang(guild_id)
                view = self.DiplomatValidationView(
                    member, channel, guild_lang, guild_name, self.bot
                )
                view.original_message = message

                self.bot.add_view(view, message_id=message_id)

                _logger.info(
                    "validation_view_restored",
                    member_name=member.display_name,
                    member_id=member.id,
                    guild_name=guild_name,
                    guild_id=guild_id
                )

            except Exception as e:
                _logger.error(
                    "error_restoring_validation_view",
                    validation_key=key,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )

    async def save_pending_validation(
        self,
        guild_id: int,
        member_id: int,
        guild_name: str,
        channel_id: int,
        message_id: int,
    ) -> None:
        """
        Save pending validation to database and cache.

        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID requiring validation
            guild_name: Name of the guild being validated for
            channel_id: Discord channel ID where validation message is
            message_id: Discord message ID of the validation message
        """
        query = """
            INSERT INTO pending_diplomat_validations 
            (guild_id, member_id, guild_name, channel_id, message_id, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
        """
        try:
            await self.bot.run_db_query(
                query,
                (guild_id, member_id, guild_name, channel_id, message_id),
                commit=True,
            )

            key = f"{guild_id}_{member_id}_{guild_name}"
            pending_validations = await self.get_pending_validations()
            pending_validations[key] = {
                "guild_id": guild_id,
                "member_id": member_id,
                "guild_name": guild_name,
                "channel_id": channel_id,
                "message_id": message_id,
                "created_at": "now",
            }
            await self.bot.cache.set(
                "temporary", pending_validations, "pending_validations"
            )
            _logger.debug(
                "pending_validation_saved",
                member_id=member_id,
                guild_name=guild_name,
                guild_id=guild_id,
                message_id=message_id
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "duplicate entry" in error_msg or "1062" in error_msg:
                _logger.warning(
                    "pending_validation_already_exists",
                    member_id=member_id,
                    guild_name=guild_name,
                    guild_id=guild_id
                )
            elif "foreign key constraint" in error_msg or "1452" in error_msg:
                _logger.error(
                    "foreign_key_constraint_failed_pending_validation",
                    member_id=member_id,
                    guild_id=guild_id,
                    error_msg=str(e)[:200]
                )
            else:
                _logger.error(
                    "error_saving_pending_validation",
                    member_id=member_id,
                    guild_id=guild_id,
                    guild_name=guild_name,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200]
                )
            raise

    async def remove_pending_validation(
        self, guild_id: int, member_id: int, guild_name: str
    ) -> None:
        """
        Remove pending validation from database and cache.

        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID to remove validation for
            guild_name: Name of the guild validation was for
        """
        query = """
            UPDATE pending_diplomat_validations 
            SET status = 'completed', completed_at = NOW()
            WHERE guild_id = %s AND member_id = %s AND guild_name = %s AND status = 'pending'
        """
        try:
            await self.bot.run_db_query(
                query, (guild_id, member_id, guild_name), commit=True
            )

            await self._remove_pending_from_cache(guild_id, member_id, guild_name)

            _logger.debug(
                "pending_validation_removed",
                member_id=member_id,
                guild_name=guild_name,
                guild_id=guild_id
            )
        except Exception as e:
            _logger.error(
                "error_removing_pending_validation",
                member_id=member_id,
                guild_id=guild_id,
                guild_name=guild_name,
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )
    
    async def _remove_pending_from_cache(self, guild_id: int, member_id: int, guild_name: str):
        """
        Remove pending validation from cache only, without updating database status.
        
        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID
            guild_name: Name of the guild being validated
        """
        key = f"{guild_id}_{member_id}_{guild_name}"
        pending_validations = await self.get_pending_validations()
        if key in pending_validations:
            del pending_validations[key]
            await self.bot.cache.set(
                "temporary", pending_validations, "pending_validations"
            )
            _logger.debug(
                "pending_validation_removed_from_cache",
                member_id=member_id,
                guild_name=guild_name,
                guild_id=guild_id
            )
    
    async def _expire_pending(self, guild_id: int, member_id: int, guild_name: str):
        """
        Mark a pending validation as expired in database and remove from cache.
        
        Used when restoring validations that reference non-existent guilds/members/channels.
        
        Args:
            guild_id: Discord guild ID
            member_id: Discord member ID  
            guild_name: Name of the guild being validated
        """
        try:
            query = """UPDATE pending_diplomat_validations
                       SET status='expired', completed_at=NOW()
                       WHERE guild_id=%s AND member_id=%s AND guild_name=%s AND status='pending'"""
            await self.bot.run_db_query(query, (guild_id, member_id, guild_name), commit=True)
            await self._remove_pending_from_cache(guild_id, member_id, guild_name)
            _logger.info(
                "pending_validation_expired",
                guild_id=guild_id,
                member_id=member_id,
                guild_name=guild_name
            )
        except Exception as e:
            _logger.error(
                "expire_pending_failed", 
                guild_id=guild_id, 
                member_id=member_id,
                guild_name=guild_name,
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )

    async def validate_guild_name_with_llm(
        self, guild_name: str, category_channel
    ) -> str:
        """
        Validate guild name with LLM to detect similar existing guilds.

        Args:
            guild_name: Guild name to validate
            category_channel: Discord category channel containing diplomat channels

        Returns:
            Validated guild name (may be corrected if similar guild found)
        """
        try:
            existing_guild_names = []
            for channel in category_channel.channels:
                if isinstance(channel, discord.TextChannel) and channel.name.startswith(
                    "diplomat-"
                ):
                    channel_guild_name = (
                        channel.name.replace("diplomat-", "").replace("-", " ").title()
                    )
                    existing_guild_names.append(channel_guild_name)

            if not existing_guild_names:
                return guild_name

            if len(existing_guild_names) > 50:
                _logger.warning(
                    "too_many_existing_guild_names_truncating",
                    guild_id=category_channel.guild.id,
                    original_count=len(existing_guild_names),
                    truncated_to=50
                )
                existing_guild_names = existing_guild_names[:50]

            llm_cog = self.bot.get_cog("LLMInteraction")
            if not llm_cog:
                _logger.warning(
                    "llm_cog_not_found_for_guild_validation",
                    guild_id=category_channel.guild.id
                )
                return guild_name

            if not hasattr(llm_cog, "safe_ai_query"):
                _logger.warning(
                    "llm_cog_missing_safe_ai_query_method",
                    guild_id=category_channel.guild.id
                )
                return guild_name

            sanitized_guild_name = self._sanitize_llm_input(guild_name)
            sanitized_existing_names = [
                self._sanitize_llm_input(name) for name in existing_guild_names
            ]

            if len(sanitized_existing_names) > 20:
                sanitized_existing_names = sanitized_existing_names[:20]
                _logger.warning(
                    "existing_guild_names_truncated_for_llm",
                    guild_id=category_channel.guild.id,
                    original_count=len([self._sanitize_llm_input(name) for name in existing_guild_names]),
                    truncated_to=20
                )

            prompt = f"""Task: Compare guild names for similarity detection.\n
            Input guild name: "{sanitized_guild_name}"\n
            Existing guild names: {', '.join(f'"{name}"' for name in sanitized_existing_names)}\n
            Instructions:\n
            1. If the input guild name is very similar to any existing guild name (typos, abbreviations), return the most similar existing guild name.\n
            2. If the input guild name is clearly different and unique, return the input guild name unchanged.\n
            3. Return only the guild name, no additional text or explanations.\n
            Examples:\n
            - Input "Guild War" vs existing "Guild Wars" -> return "Guild Wars"\n
            - Input "MGM" vs existing "MGM Guild" -> return "MGM Guild"\n
            - Input "DarK Knight" vs existing "Dark Knights" -> return "Dark Knights"\n
            Response:"""

            try:
                response = await asyncio.wait_for(
                    llm_cog.safe_ai_query(prompt),
                    timeout=30.0
                )
                if not response:
                    _logger.warning(
                        "llm_empty_response_using_original",
                        original_guild_name=guild_name,
                        guild_id=category_channel.guild.id
                    )
                    return guild_name

                validated_name = self._validate_llm_response(
                    response, guild_name, existing_guild_names
                )

                if validated_name in existing_guild_names:
                    _logger.info(
                        "llm_detected_similar_guild",
                        original_guild_name=guild_name,
                        validated_guild_name=validated_name,
                        guild_id=category_channel.guild.id
                    )
                    return validated_name
                elif validated_name == guild_name:
                    return guild_name
                else:
                    _logger.warning(
                        "llm_unexpected_result_using_original",
                        unexpected_result=validated_name,
                        original_guild_name=guild_name,
                        guild_id=category_channel.guild.id
                    )
                    return guild_name

            except asyncio.TimeoutError:
                _logger.warning(
                    "llm_validation_timeout_using_original",
                    guild_name=guild_name,
                    guild_id=category_channel.guild.id,
                    timeout_seconds=30.0
                )
                return guild_name
            except Exception as e:
                _logger.error(
                    "error_calling_llm_for_guild_validation",
                    guild_name=guild_name,
                    guild_id=category_channel.guild.id,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )
                return guild_name

        except Exception as e:
            _logger.error(
                "error_in_validate_guild_name_with_llm",
                guild_name=guild_name,
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )
            return guild_name

    @commands.Cog.listener()
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def on_ready(self):
        """Initialize profile setup data on bot ready."""

        async def safe_restore_pending_validation_views():
            try:
                await self.restore_pending_validation_views()
            except Exception as e:
                _logger.error(
                    "error_restoring_pending_validation_views",
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )

        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        asyncio.create_task(safe_restore_pending_validation_views())
        _logger.debug("waiting_for_initial_cache_load")

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def finalize_profile(self, guild_id: int, user_id: int) -> None:
        """
        Finalize user profile setup and assign roles.

        Args:
            guild_id: Discord guild ID
            user_id: Discord user ID to finalize profile for
        """
        _logger.debug(
            "finalize_profile_started",
            user_id=user_id,
            guild_id=guild_id
        )
        
        guild_lang_task = self.get_guild_lang(guild_id)
        guild_roles_task = self.get_guild_roles(guild_id)
        guild_channels_task = self.get_guild_channels(guild_id)
        session_task = self.load_session(guild_id, user_id)

        guild_lang, roles_config, channels_data, session = await asyncio.gather(
            guild_lang_task,
            guild_roles_task,
            guild_channels_task,
            session_task,
            return_exceptions=True
        )

        if isinstance(guild_lang, Exception):
            _logger.error("error_fetching_guild_lang", guild_id=guild_id, exc_info=guild_lang)
            guild_lang = "en-US"
        if isinstance(roles_config, Exception):
            _logger.error("error_fetching_roles_config", guild_id=guild_id, exc_info=roles_config)
            roles_config = {}
        if isinstance(channels_data, Exception):
            _logger.error("error_fetching_channels_data", guild_id=guild_id, exc_info=channels_data)
            channels_data = {}
        if isinstance(session, Exception):
            _logger.error("error_loading_session", guild_id=guild_id, user_id=user_id, exc_info=session)
            return

        if not isinstance(session, dict):
            _logger.error("session_not_dict", guild_id=guild_id, user_id=user_id, session_type=type(session).__name__)
            return

        _logger.debug(
            "session_loaded_in_finalize",
            user_id=user_id,
            guild_id=guild_id,
            session_keys=list(session.keys()),
            session_motif=session.get("motif")
        )

        def _values_from_session(s: Dict[str, Any]) -> Tuple[Any, ...]:
            """Internal method: Values from session."""
            return (
                guild_id,
                user_id,
                s.get("nickname"),
                s.get("locale"),
                s.get("motif"),
                s.get("friend_pseudo"),
                s.get("weapons"),
                s.get("guild_name"),
                s.get("guild_acronym"),
                s.get("gs"),
                s.get("playtime"),
                s.get("game_mode"),
                s.get("nickname"),
                s.get("locale"),
                s.get("motif"),
                s.get("friend_pseudo"),
                s.get("weapons"),
                s.get("guild_name"),
                s.get("guild_acronym"),
                s.get("gs"),
                s.get("playtime"),
                s.get("game_mode"),
            )

        query = """
            INSERT INTO user_setup
                (guild_id, user_id, nickname, locale, motif, friend_pseudo, weapons, guild_name, guild_acronym, gs, playtime, game_mode)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                nickname = %s, locale = %s, motif = %s, friend_pseudo = %s, weapons = %s, guild_name = %s, guild_acronym = %s, gs = %s, playtime = %s, game_mode = %s
        """

        try:
            await self.bot.run_db_query(
                query, _values_from_session(session), commit=True
            )
        except DBQueryError as exc:
            if "Data too long" in str(exc) and "playtime" in str(exc):
                original = session.get("playtime") or ""
                truncated = original[:MAX_PLAYTIME_LEN]
                session["playtime"] = truncated
                _logger.warning(
                    "playtime_truncated_for_db",
                    user_id=user_id,
                    guild_id=guild_id,
                    original_length=len(original),
                    max_length=MAX_PLAYTIME_LEN
                )
                await self.bot.run_db_query(
                    query, _values_from_session(session), commit=True
                )
            else:
                _logger.error(
                    "db_insertion_failed",
                    user_id=user_id,
                    guild_id=guild_id,
                    error_type=type(exc).__name__,
                    error_msg=str(exc)[:200],
                    exc_info=True
                )
                raise

        locale = session.get("locale", "en-US")

        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                _logger.error(
                    "guild_not_found",
                    guild_id=guild_id,
                    user_id=user_id
                )
                return

            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            motif = session.get("motif")
            _logger.debug(
                "user_motif",
                user_id=user_id,
                guild_id=guild_id,
                motif=motif
            )
            role_id = None
            if motif == "diplomat":
                role_id = roles_config.get("diplomats")
            elif motif == "friends":
                role_id = roles_config.get("friends")
            elif motif == "application":
                role_id = roles_config.get("applicant")

            config_ok_role_id = roles_config.get("config_ok")
            if config_ok_role_id:
                config_ok_role = guild.get_role(config_ok_role_id)
                if config_ok_role and config_ok_role not in member.roles:
                    await member.add_roles(config_ok_role)
                    _logger.debug(
                        "config_ok_role_added",
                        user_id=user_id,
                        guild_id=guild_id,
                        role_name=config_ok_role.name,
                        role_id=config_ok_role.id
                    )
                elif config_ok_role:
                    _logger.debug(
                        "config_ok_role_already_present",
                        user_id=user_id,
                        guild_id=guild_id,
                        role_name=config_ok_role.name
                    )

            if role_id:
                role = guild.get_role(role_id)
                if role and role not in member.roles:
                    await member.add_roles(role)
                    _logger.debug(
                        "role_added_to_user",
                        user_id=user_id,
                        guild_id=guild_id,
                        role_name=role.name,
                        role_id=role.id,
                        motif=motif
                    )
                elif role:
                    _logger.debug(
                        "role_already_present",
                        user_id=user_id,
                        guild_id=guild_id,
                        role_name=role.name,
                        motif=motif
                    )
                else:
                    _logger.error(
                        "role_not_found_in_guild",
                        role_id=role_id,
                        guild_id=guild_id,
                        user_id=user_id,
                        motif=motif
                    )
            else:
                _logger.debug(
                    "no_role_assigned_for_motif",
                    motif=motif,
                    guild_id=guild_id,
                    user_id=user_id
                )
        except Exception:
            _logger.error(
                "error_assigning_role_in_finalize_profile",
                user_id=user_id,
                guild_id=guild_id,
                motif=motif,
                exc_info=True
            )

        try:
            base = _safe_txt(session.get("nickname"), 32)
            if motif == "application":
                tag = PROFILE_SETUP_DATA.get("acronym", {}).get(
                    session.get("locale", "en-US"),
                    PROFILE_SETUP_DATA.get("acronym", {}).get("en-US", "Acronym:")
                )
                new_nickname = f"{tag} {base}"
            elif motif in ["diplomat", "allies"]:
                acr = _safe_txt(session.get("guild_acronym"), 8)
                new_nickname = f"[{acr}] {base}"
            else:
                new_nickname = base

            new_nickname = new_nickname[:32]
            
            old_display = member.display_name
            await member.edit(nick=new_nickname)
            _logger.debug(
                "nickname_updated",
                member_name=member.name,
                member_id=member.id,
                guild_id=guild_id,
                old_nickname=old_display,
                new_nickname=new_nickname,
                motif=motif
            )
        except discord.Forbidden:
            _logger.error(
                "cannot_modify_nickname_missing_permissions",
                member_name=member.name,
                member_id=member.id,
                guild_id=guild_id,
                attempted_nickname=new_nickname
            )
        except Exception as e:
            _logger.error(
                "error_updating_nickname",
                member_name=member.name,
                member_id=member.id,
                guild_id=guild_id,
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )

        _logger.debug(
            "channels_data_retrieved",
            user_id=user_id,
            guild_id=guild_id,
            channels_data_keys=list(channels_data.keys()) if channels_data else None,
            forum_members_channel=channels_data.get("forum_members_channel") if channels_data else None
        )
        
        channels = {
            "member": channels_data.get("forum_members_channel"),
            "application": channels_data.get("forum_recruitment_channel"),
            "diplomat": channels_data.get("forum_diplomats_channel"),
            "allies": channels_data.get("forum_allies_channel"),
            "friends": channels_data.get("forum_friends_channel"),
        }
        channel_id = channels.get(str(motif)) if motif else None
        
        _logger.debug(
            "channel_selection",
            user_id=user_id,
            guild_id=guild_id,
            motif=motif,
            channel_id=channel_id,
            available_channels=channels
        )
        
        if not channel_id:
            _logger.error(
                "unknown_motif_notification_skipped",
                motif=motif,
                user_id=user_id,
                guild_id=guild_id
            )
            return

        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                _logger.error(
                    "unable_to_fetch_channel",
                    channel_id=channel_id,
                    user_id=user_id,
                    guild_id=guild_id,
                    motif=motif
                )
                return

            if motif == "member":
                embed_color = discord.Color.blue()
            elif motif == "application":
                embed_color = discord.Color.purple()
            elif motif == "diplomat":
                embed_color = discord.Color.red()
            elif motif == "allies":
                embed_color = discord.Color.green()
            elif motif == "friends":
                embed_color = discord.Color.gold()
            else:
                embed_color = discord.Color.blue()

            _logger.debug(
                "embed_color_for_motif",
                motif=motif,
                embed_color=str(embed_color),
                user_id=user_id,
                guild_id=guild_id
            )

            embed = discord.Embed(
                title=PROFILE_SETUP_DATA.get("notification", {})
                .get("title", {})
                .get(
                    locale,
                    PROFILE_SETUP_DATA.get("notification", {})
                    .get("title", {})
                    .get("en-US", "📋 New Profile Configured"),
                ),
                color=embed_color,
            )
            embed.add_field(
                name=PROFILE_SETUP_DATA.get("notification", {})
                .get("fields", {})
                .get("user", {})
                .get(
                    locale,
                    PROFILE_SETUP_DATA.get("notification", {})
                    .get("fields", {})
                    .get("user", {})
                    .get("en-US", "User"),
                ),
                value=f"<@{user_id}>",
                inline=False,
            )
            embed.add_field(
                name=PROFILE_SETUP_DATA.get("notification", {})
                .get("fields", {})
                .get("discord_name", {})
                .get(
                    locale,
                    PROFILE_SETUP_DATA.get("notification", {})
                    .get("fields", {})
                    .get("discord_name", {})
                    .get("en-US", "Discord Name"),
                ),
                value=f"`{_safe_txt(session.get('nickname', 'Unknown'))}`",
                inline=False,
            )
            embed.set_footer(
                text=PROFILE_SETUP_DATA.get("footer", {}).get(
                    locale,
                    PROFILE_SETUP_DATA.get("footer", {}).get(
                        "en-US", "Profile configured"
                    ),
                )
            )

            if motif == "member":
                weapons = _safe_txt(session.get("weapons", "N/A"))
                gs = _safe_txt(session.get("gs", "N/A"))
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "weapons"], locale, "Weapons"),
                    value=f"`{weapons}`",
                    inline=True,
                )
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "gs"], locale, "GearScore"),
                    value=f"`{gs}`",
                    inline=True,
                )
            elif motif == "application":
                weapons = _safe_txt(session.get("weapons", "N/A"))
                gs = _safe_txt(session.get("gs", "N/A"))
                playtime = _safe_txt(session.get("playtime", "N/A"))
                game_mode = _safe_txt(session.get("game_mode", "N/A"))
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "weapons"], locale, "Weapons"),
                    value=f"`{weapons}`",
                    inline=True,
                )
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "gs"], locale, "GearScore"),
                    value=f"`{gs}`",
                    inline=True,
                )
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "playtime"], locale, "Playtime"),
                    value=f"`{playtime}`",
                    inline=False,
                )
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "game_mode"], locale, "Game Mode"),
                    value=f"`{game_mode}`",
                    inline=False,
                )
                application_embed = embed.copy()
            elif motif == "diplomat":
                guild_name = _safe_txt(session.get("guild_name", "N/A"))
                guild_acronym = _safe_txt(session.get("guild_acronym", "N/A"))
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "guild"], locale, "Guild"),
                    value=f"`{guild_name}` ({guild_acronym})",
                    inline=False,
                )
            elif motif == "allies":
                guild_name = _safe_txt(session.get("guild_name", "N/A"))
                guild_acronym = _safe_txt(session.get("guild_acronym", "N/A"))
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "allied_guild"], locale, "Allied Guild"),
                    value=f"`{guild_name}` ({guild_acronym})",
                    inline=False,
                )
            elif motif == "friends":
                friend_pseudo = _safe_txt(session.get("friend_pseudo", "N/A"))
                embed.add_field(
                    name=tr(PROFILE_SETUP_DATA, ["notification", "fields", "friend"], locale, "Friend"),
                    value=f"`{friend_pseudo}`",
                    inline=False,
                )

            posted = await self._post(channel, name=f"profile-{user_id}", embed=embed)
            if posted:
                _logger.debug(
                    "notification_sent",
                    channel_name=channel.name,
                    channel_id=channel.id,
                    user_id=user_id,
                    guild_id=guild_id,
                    motif=motif,
                    is_forum_thread=isinstance(channel, discord.ForumChannel)
                )
            else:
                _logger.error(
                    "notification_send_failed",
                    channel_name=channel.name,
                    channel_id=channel.id,
                    user_id=user_id,
                    guild_id=guild_id,
                    motif=motif
                )
        except Exception as e:
            _logger.error(
                "unable_to_send_notification",
                user_id=user_id,
                guild_id=guild_id,
                motif=motif,
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )

        gs_safe = _safe_txt(session.get("gs", "N/A"))
        
        welcome_message = await self.get_welcome_message_for_user(guild_id, user_id)
        if welcome_message:
            info = welcome_message
            try:
                channel = self.bot.get_channel(info["channel"]) or await self.bot.fetch_channel(info["channel"])
                message = await channel.fetch_message(info["message"])
                if not message.embeds:
                    _logger.error(
                        "no_embed_found_in_welcome_message",
                        nickname=_safe_txt(session.get('nickname', 'Unknown')),
                        user_id=user_id,
                        guild_id=guild_id
                    )
                    return
                embed = message.embeds[0]
                colors = {
                    "member": discord.Color.blue(),
                    "application": discord.Color.purple(),
                    "diplomat": discord.Color.red(),
                    "allies": discord.Color.green(),
                    "friends": discord.Color.gold(),
                }
                motif_value = session.get("motif")
                embed.color = colors.get(
                    str(motif_value) if motif_value else "", discord.Color.default()
                )
                now = (
                    datetime.now(pytz.utc)
                    .astimezone(_tz_france)
                    .strftime("%d/%m/%Y à %Hh%M")
                )
                pending_text = PROFILE_SETUP_DATA["pending"].get(
                    guild_lang, PROFILE_SETUP_DATA["pending"].get("en-US")
                )
                if motif == "member":
                    template = PROFILE_SETUP_DATA["accepted_member"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_member"].get("en-US")
                    )
                    new_text = template.format(
                        new_nickname=new_nickname, gs=gs_safe, now=now
                    )
                elif motif == "application":
                    template = PROFILE_SETUP_DATA["accepted_application"].get(
                        guild_lang,
                        PROFILE_SETUP_DATA["accepted_application"].get("en-US"),
                    )
                    new_text = template.format(
                        new_nickname=new_nickname, gs=gs_safe, now=now
                    )
                elif motif == "diplomat":
                    guild_name = _safe_txt(session.get("guild_name", "Unknown"))
                    template = PROFILE_SETUP_DATA["accepted_diplomat"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_diplomat"].get("en-US")
                    )
                    new_text = template.format(
                        new_nickname=new_nickname, guild_name=guild_name, now=now
                    )
                elif motif == "allies":
                    guild_name = _safe_txt(session.get("guild_name", "Unknown"))
                    template = PROFILE_SETUP_DATA["accepted_allies"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_allies"].get("en-US")
                    )
                    new_text = template.format(
                        new_nickname=new_nickname, guild_name=guild_name, now=now
                    )
                elif motif == "friends":
                    friend_pseudo = _safe_txt(session.get("friend_pseudo", "Unknown"))
                    template = PROFILE_SETUP_DATA["accepted_friends"].get(
                        guild_lang, PROFILE_SETUP_DATA["accepted_friends"].get("en-US")
                    )
                    new_text = template.format(
                        new_nickname=new_nickname, friend_pseudo=friend_pseudo, now=now
                    )
                desc = embed.description or ""
                embed.description = desc.replace(pending_text, new_text) if pending_text in desc else new_text
                await message.edit(embed=embed)
                _logger.debug(
                    "welcome_message_updated",
                    nickname=_safe_txt(session.get('nickname', 'Unknown')),
                    motif=motif,
                    user_id=user_id,
                    guild_id=guild_id
                )
            except Exception as e:
                _logger.error(
                    "error_updating_welcome_message",
                    nickname=_safe_txt(session.get('nickname', 'Unknown')),
                    user_id=user_id,
                    guild_id=guild_id,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )
        else:
            _logger.debug(
                "no_welcome_message_cached",
                user_id=user_id,
                guild_id=guild_id
            )

        if motif == "application":
            application_embed = locals().get("application_embed") or discord.Embed(
                title=PROFILE_SETUP_DATA.get("notification", {}).get("title", {}).get(
                    locale, PROFILE_SETUP_DATA.get("notification", {}).get("title", {}).get("en-US", "📋 New Profile Configured")
                ),
                color=discord.Color.purple(),
            )
            
            recruitment_category_id = channels_data.get("external_recruitment_cat")
            if not recruitment_category_id:
                _logger.error(
                    "missing_external_recruitment_category_id",
                    guild_id=guild_id,
                    user_id=user_id
                )
            else:
                recruitment_category = guild.get_channel(recruitment_category_id)
                if recruitment_category is None:
                    _logger.error(
                        "recruitment_category_not_found",
                        recruitment_category_id=recruitment_category_id,
                        guild_id=guild.id,
                        user_id=user_id
                    )
                else:
                    channel_name = _slugify(member.display_name)

                    existing_channel = discord.utils.get(recruitment_category.text_channels, name=channel_name)
                    if existing_channel:
                        _logger.info(
                            "recruitment_channel_exists",
                            channel_id=existing_channel.id,
                            channel_name=existing_channel.name,
                            member_id=member.id,
                            guild_id=guild_id
                        )
                        application_embed = embed.copy()
                        await self._post(
                            existing_channel,
                            name=f"application-{member.display_name}",
                            embed=application_embed,
                            content="@everyone",
                            allowed_mentions=discord.AllowedMentions(everyone=True)
                        )
                        return
                    
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(
                            view_channel=False
                        )
                    }
                    applicant_role_id = roles_config.get("applicant")
                    if applicant_role_id:
                        applicant_role = guild.get_role(applicant_role_id)
                        if applicant_role:
                            overwrites[applicant_role] = discord.PermissionOverwrite(
                                view_channel=False
                            )
                    overwrites[member] = discord.PermissionOverwrite(
                        view_channel=True, send_messages=True, read_message_history=True
                    )
                    for role_name in ["guild_master", "officer", "guardian"]:
                        role_id = roles_config.get(role_name)
                        if role_id:
                            role_obj = guild.get_role(role_id)
                            if role_obj:
                                overwrites[role_obj] = discord.PermissionOverwrite(
                                    view_channel=True,
                                    send_messages=True,
                                    read_message_history=True,
                                    manage_channels=True,
                                )
                    try:
                        new_channel = await guild.create_text_channel(
                            name=channel_name,
                            category=recruitment_category,
                            topic=f"Individual application channel for {member.display_name}",
                            overwrites=overwrites,
                        )
                        await self._post(
                            new_channel,
                            name=f"application-{member.display_name}",
                            embed=application_embed,
                            content="@everyone",
                            allowed_mentions=discord.AllowedMentions(everyone=True)
                        )
                        _logger.info(
                            "recruitment_channel_created",
                            channel_name=new_channel.name,
                            channel_id=new_channel.id,
                            member_id=member.id,
                            guild_id=guild_id,
                            member_display_name=member.display_name
                        )
                    except Exception as e:
                        _logger.error(
                            "error_creating_individual_channel",
                            member_display_name=member.display_name,
                            member_id=member.id,
                            guild_id=guild_id,
                            error_type=type(e).__name__,
                            error_msg=str(e)[:200],
                            exc_info=True
                        )

        elif motif == "diplomat":
            diplomats_category_id = channels_data.get("category_diplomat")
            if not diplomats_category_id:
                _logger.error(
                    "missing_diplomacy_category_id",
                    guild_id=guild_id,
                    user_id=user_id,
                    motif=motif
                )
            else:
                diplomats_category = guild.get_channel(diplomats_category_id)
                if diplomats_category is None:
                    _logger.error(
                        "diplomats_category_not_found",
                        diplomats_category_id=diplomats_category_id,
                        guild_id=guild.id,
                        user_id=user_id
                    )
                else:
                    guild_name = _safe_txt(session.get("guild_name", "Unknown"))

                    validated_guild_name = await self.validate_guild_name_with_llm(
                        guild_name, diplomats_category
                    )
                    if validated_guild_name != guild_name:
                        _logger.warning(
                            "guild_name_similarity_detected",
                            original_guild_name=guild_name,
                            validated_guild_name=validated_guild_name,
                            guild_id=guild_id,
                            user_id=user_id
                        )
                        guild_name = validated_guild_name
                        session["guild_name"] = validated_guild_name

                    normalized_guild_name = _slugify(guild_name)

                    existing_channels = [
                        ch for ch in diplomats_category.channels
                        if isinstance(ch, discord.TextChannel)
                        and ch.name.lower() == f"diplomat-{normalized_guild_name}"
                    ]

                    if existing_channels:
                        existing_channel = existing_channels[0]
                        _logger.info(
                            "found_existing_diplomat_channel",
                            guild_name=guild_name,
                            channel_name=existing_channel.name,
                            channel_id=existing_channel.id,
                            guild_id=guild_id,
                            user_id=user_id
                        )

                        diplomat_role_id = roles_config.get("diplomats")
                        existing_members = [
                            m
                            for m in existing_channel.members
                            if m != guild.me
                            and any(role.id == diplomat_role_id for role in m.roles)
                        ]

                        if existing_members:
                            _logger.warning(
                                "anti_espionage_manual_validation_needed",
                                guild_name=guild_name,
                                existing_diplomat_name=existing_members[0].display_name,
                                existing_diplomat_id=existing_members[0].id,
                                new_diplomat_name=member.display_name,
                                new_diplomat_id=member.id,
                                channel_id=existing_channel.id,
                                guild_id=guild_id
                            )

                            guild_lang = await self.get_guild_lang(guild_id)
                            alert_text = (
                                PROFILE_SETUP_DATA["anti_espionage"]["alert_message"]
                                .get(
                                    guild_lang,
                                    PROFILE_SETUP_DATA["anti_espionage"][
                                        "alert_message"
                                    ].get("en-US"),
                                )
                                .format(
                                    new_diplomat=member.display_name,
                                    guild_name=guild_name,
                                    existing_diplomat=existing_members[0].mention,
                                )
                            )

                            diplomat_embed = embed.copy()

                            view = self.DiplomatValidationView(
                                member,
                                existing_channel,
                                guild_lang,
                                guild_name,
                                self.bot,
                            )
                            message = await self._post(
                                existing_channel,
                                name=f"diplomat-validation-{member.display_name}-{guild_name}",
                                embed=diplomat_embed,
                                content=f"@everyone\n\n{alert_text}",
                                view=view,
                                allowed_mentions=discord.AllowedMentions(everyone=True, users=True)
                            )
                            view.original_message = message

                            await self.save_pending_validation(
                                guild_id,
                                member.id,
                                guild_name,
                                existing_channel.id,
                                message.id,
                            )

                            overwrites = existing_channel.overwrites.copy()
                            overwrites[member] = discord.PermissionOverwrite(
                                view_channel=False
                            )

                            await existing_channel.edit(overwrites=overwrites)

                            user_locale = session.get("locale", "en-US")
                            pending_message = (
                                PROFILE_SETUP_DATA["anti_espionage"][
                                    "pending_notification"
                                ]
                                .get(
                                    user_locale,
                                    PROFILE_SETUP_DATA["anti_espionage"][
                                        "pending_notification"
                                    ].get("en-US"),
                                )
                                .format(
                                    diplomat_name=member.display_name,
                                    guild_name=guild_name,
                                )
                            )

                            try:
                                await member.send(pending_message)
                                _logger.info(
                                    "pending_notification_sent_to_diplomat",
                                    diplomat_name=member.display_name,
                                    diplomat_id=member.id,
                                    guild_name=guild_name,
                                    guild_id=guild_id
                                )
                            except discord.Forbidden:
                                _logger.warning(
                                    "could_not_send_pending_notification_dms_disabled",
                                    diplomat_name=member.display_name,
                                    diplomat_id=member.id,
                                    guild_id=guild_id
                                )
                            except Exception as e:
                                _logger.error(
                                    "error_sending_pending_notification",
                                    diplomat_name=member.display_name,
                                    diplomat_id=member.id,
                                    guild_id=guild_id,
                                    error_type=type(e).__name__,
                                    error_msg=str(e)[:200],
                                    exc_info=True
                                )

                            _logger.info(
                                "diplomat_added_to_pending_validation",
                                diplomat_name=member.display_name,
                                diplomat_id=member.id,
                                guild_name=guild_name,
                                guild_id=guild_id
                            )
                        else:
                            overwrites = existing_channel.overwrites
                            overwrites[member] = discord.PermissionOverwrite(
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                            )
                            await existing_channel.edit(overwrites=overwrites)

                            diplomat_embed = embed.copy()
                            await self._post(
                                existing_channel,
                                name=f"diplomat-{member.display_name}-{guild_name}",
                                embed=diplomat_embed,
                                allowed_mentions=discord.AllowedMentions(everyone=False)
                            )

                            _logger.info(
                                "diplomat_added_to_existing_channel",
                                diplomat_name=member.display_name,
                                diplomat_id=member.id,
                                guild_name=guild_name,
                                channel_id=existing_channel.id,
                                guild_id=guild_id
                            )
                    else:
                        channel_name = f"diplomat-{normalized_guild_name}"
                        overwrites = {
                            guild.default_role: discord.PermissionOverwrite(
                                view_channel=False
                            )
                        }

                        diplomat_role_id = roles_config.get("diplomats")
                        if diplomat_role_id:
                            diplomat_role = guild.get_role(diplomat_role_id)
                            if diplomat_role:
                                overwrites[diplomat_role] = discord.PermissionOverwrite(
                                    view_channel=False
                                )

                        overwrites[member] = discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            read_message_history=True,
                        )

                        for role_name in ["guild_master", "officer", "guardian"]:
                            role_id = roles_config.get(role_name)
                            if role_id:
                                role_obj = guild.get_role(role_id)
                                if role_obj:
                                    overwrites[role_obj] = discord.PermissionOverwrite(
                                        view_channel=True,
                                        send_messages=True,
                                        read_message_history=True,
                                        manage_channels=True,
                                    )

                        try:
                            new_channel = await guild.create_text_channel(
                                name=channel_name,
                                category=diplomats_category,
                                topic=f"Diplomatic channel for guild {guild_name}",
                                overwrites=overwrites,
                            )

                            diplomat_embed = embed.copy()
                            await self._post(
                                new_channel,
                                name=f"diplomat-{member.display_name}-{guild_name}",
                                embed=diplomat_embed,
                                allowed_mentions=discord.AllowedMentions(everyone=False)
                            )

                            _logger.info(
                                "diplomat_channel_created",
                                channel_name=new_channel.name,
                                channel_id=new_channel.id,
                                guild_name=guild_name,
                                diplomat_name=member.display_name,
                                diplomat_id=member.id,
                                guild_id=guild_id
                            )
                        except Exception as e:
                            _logger.error(
                                "error_creating_diplomat_channel",
                                guild_name=guild_name,
                                diplomat_name=member.display_name,
                                diplomat_id=member.id,
                                guild_id=guild_id,
                                error_type=type(e).__name__,
                                error_msg=str(e)[:200],
                                exc_info=True
                            )

        await self.bot.cache.invalidate_category("user_data")

    class LangButton(discord.ui.Button):
        """Button for language selection."""

        def __init__(self, locale: str):
            """
            Initialize language button.

            Args:
                locale: Language locale code
            """
            label = LANGUAGE_NAMES.get(locale, locale)
            super().__init__(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"lang_{locale}",
            )
            self.locale = locale

        @discord_resilient(service_name="discord_api", max_retries=2)
        async def callback(self, interaction: discord.Interaction):
            """
            Handle language selection.

            Args:
                interaction: Discord interaction from button click
            """
            cog: ProfileSetup = self.view.cog
            guild_id = self.view.guild_id
            user_id = interaction.user.id
            session = await cog.load_session(guild_id, user_id)
            session["locale"] = self.locale
            lang_msg = PROFILE_SETUP_DATA["language_saved"].get(
                self.locale, PROFILE_SETUP_DATA["language_saved"].get("en-US")
            )
            await interaction.response.send_message(lang_msg, ephemeral=True)
            try:
                await interaction.user.send(view=ProfileSetup.MotifModalView(cog, self.locale, guild_id))
            except discord.Forbidden:
                _logger.warning("dm_blocked_for_motif_view", user_id=user_id, guild_id=guild_id)
            except Exception as e:
                _logger.error("dm_error_for_motif_view", user_id=user_id, guild_id=guild_id,
                              error_type=type(e).__name__, error_msg=str(e)[:200])

    class LangSelectView(discord.ui.View):
        """View for language selection."""

        def __init__(self, cog: "ProfileSetup", guild_id: int):
            """
            Initialize language selection view.

            Args:
                cog: ProfileSetup cog instance
                guild_id: Discord guild ID
            """
            super().__init__(timeout=180)
            self.cog = cog
            self.guild_id = guild_id
            for locale in SUPPORTED_LOCALES:
                self.add_item(ProfileSetup.LangButton(locale))

    class MotifSelect(discord.ui.Select):
        """Select menu for choosing profile motif."""

        def __init__(self, locale: str, guild_id: int):
            """
            Initialize motif selection.

            Args:
                locale: Language locale code
                guild_id: Discord guild ID
            """
            self.locale = locale
            self.guild_id = guild_id
            options = []
            for item in PROFILE_SETUP_DATA["motif_select_options"]:
                label = item["label"].get(locale, item["label"].get("en-US"))
                value = item["value"]
                description = item["description"].get(
                    locale, item["description"].get("en-US")
                )
                options.append(
                    discord.SelectOption(
                        label=label, value=value, description=description
                    )
                )
            placeholder = PROFILE_SETUP_DATA["motif_select"].get(
                locale, PROFILE_SETUP_DATA["motif_select"].get("en-US")
            )
            super().__init__(
                placeholder=placeholder, min_values=1, max_values=1, options=options
            )

        @discord_resilient(service_name="discord_api", max_retries=2)
        async def callback(self, interaction: discord.Interaction):
            """
            Handle motif selection.

            Args:
                interaction: Discord interaction from select menu
            """
            try:
                cog: ProfileSetup = self.view.cog
                guild_id = self.guild_id
                user_id = interaction.user.id
                _logger.debug(
                    "motif_select_callback",
                    guild_id=guild_id,
                    user_id=user_id,
                    selected_motif=self.values[0]
                )
                session = await cog.load_session(guild_id, user_id)
                session["motif"] = self.values[0]
                message = PROFILE_SETUP_DATA["motif_saved"].get(
                    self.locale, PROFILE_SETUP_DATA["motif_saved"].get("en-US")
                )
                await interaction.response.send_message(message, ephemeral=True)
                try:
                    await interaction.user.send(
                        view=ProfileSetup.QuestionsSelectView(cog, self.locale, guild_id, self.values[0])
                    )
                except discord.Forbidden:
                    _logger.warning("dm_blocked_for_questions_view", user_id=user_id, guild_id=guild_id)
                except Exception as e:
                    _logger.error("dm_error_for_questions_view", user_id=user_id, guild_id=guild_id,
                                  error_type=type(e).__name__, error_msg=str(e)[:200])
            except Exception:
                _logger.error(
                    "error_in_motif_select_callback",
                    guild_id=guild_id,
                    user_id=user_id,
                    exc_info=True
                )

    class MotifModalView(discord.ui.View):
        """View for motif selection modal."""

        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int):
            """
            Initialize motif modal view.

            Args:
                cog: ProfileSetup cog instance
                locale: Language locale code
                guild_id: Discord guild ID
            """
            super().__init__(timeout=180)
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.add_item(ProfileSetup.MotifSelect(locale, guild_id))

    class QuestionsSelect(discord.ui.Modal):
        """Modal for collecting profile information based on motif."""

        def __init__(self, locale: str, guild_id: int, motif: str):
            """
            Initialize questions modal for profile setup.

            Args:
                locale: Language locale code
                guild_id: Discord guild ID
                motif: Profile motif (member, application, diplomat, etc.)
            """
            title = PROFILE_SETUP_DATA["questions_title"].get(
                locale, PROFILE_SETUP_DATA["questions_title"].get("en-US")
            )
            super().__init__(title=title)
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif
            _logger.debug(
                "initializing_questions_select_modal",
                guild_id=guild_id,
                motif=motif,
                locale=locale
            )

            self.nickname = discord.ui.InputText(
                label=PROFILE_SETUP_DATA["nickname_select"].get(
                    locale, PROFILE_SETUP_DATA["nickname_select"].get("en-US")
                ),
                min_length=3,
                max_length=16,
                required=True,
            )
            self.add_item(self.nickname)

            if motif in ["diplomat", "allies"]:
                self.guild_name = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["guild_select"].get(
                        locale, PROFILE_SETUP_DATA["guild_select"].get("en-US")
                    ),
                    min_length=3,
                    max_length=16,
                    required=True,
                )
                self.add_item(self.guild_name)

                self.guild_acronym = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["guild_acronym"].get(
                        locale, PROFILE_SETUP_DATA["guild_acronym"].get("en-US")
                    ),
                    min_length=3,
                    max_length=3,
                    required=True,
                )
                self.add_item(self.guild_acronym)

            if motif == "friends":
                self.friend_pseudo = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["friend_pseudo"].get(
                        locale, PROFILE_SETUP_DATA["friend_pseudo"].get("en-US")
                    ),
                    min_length=3,
                    max_length=16,
                    required=True,
                )
                self.add_item(self.friend_pseudo)

            if motif in ["application", "member"]:
                self.weapons = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["weapons_select"].get(
                        locale, PROFILE_SETUP_DATA["weapons_select"].get("en-US")
                    ),
                    required=True,
                    placeholder="SNS / GS / SP / DG / B / S / W / CB",
                )
                self.add_item(self.weapons)

                self.gs = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["gs"].get(
                        locale, PROFILE_SETUP_DATA["gs"].get("en-US")
                    ),
                    required=True,
                    min_length=1,
                    max_length=5,
                )
                self.add_item(self.gs)

            if motif == "application":
                self.game_mode = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["game_mode_select"].get(
                        locale, PROFILE_SETUP_DATA["game_mode_select"].get("en-US")
                    ),
                    required=True,
                    placeholder="PvE / PvP / PvE + PvP",
                )
                self.add_item(self.game_mode)

                self.playtime = discord.ui.InputText(
                    label=PROFILE_SETUP_DATA["playtime_select"].get(
                        locale, PROFILE_SETUP_DATA["playtime_select"].get("en-US")
                    ),
                    required=True,
                    placeholder="**h / week",
                )
                self.add_item(self.playtime)

        @discord_resilient(service_name="discord_api", max_retries=2)
        async def callback(self, interaction: discord.Interaction):
            """
            Handle profile information submission.

            Args:
                interaction: Discord interaction from modal submission
            """
            await interaction.response.defer(ephemeral=True)

            try:
                _logger.debug(
                    "questions_select_submitted",
                    user_id=interaction.user.id,
                    guild_id=self.guild_id,
                    locale=self.locale,
                    motif=self.motif
                )
                cog: ProfileSetup = interaction.client.get_cog("ProfileSetup")
                if not cog:
                    _logger.error(
                        "profile_setup_cog_not_found",
                        user_id=interaction.user.id,
                        guild_id=self.guild_id
                    )
                    await interaction.followup.send("❌ Error.", ephemeral=True)
                    return
                guild_id = self.guild_id
                user_id = interaction.user.id

                session_key = f"{guild_id}_{user_id}"
                if session_key not in cog.session_locks:
                    cog.session_locks[session_key] = asyncio.Lock()

                async with cog.session_locks[session_key]:
                    session = await cog.load_session(guild_id, user_id)
                    _logger.debug(
                        "session_before_update",
                        user_id=user_id,
                        guild_id=guild_id,
                        session_keys=list(session.keys())
                    )
                    session["nickname"] = self.nickname.value
                    if hasattr(self, "guild_name"):
                        session["guild_name"] = self.guild_name.value
                        session["guild_acronym"] = self.guild_acronym.value
                    if hasattr(self, "friend_pseudo"):
                        session["friend_pseudo"] = self.friend_pseudo.value
                    if hasattr(self, "weapons"):
                        weapons_input = self.weapons.value
                        llm_cog = interaction.client.get_cog("LLMInteraction")
                        try:
                            if llm_cog:
                                weapons_clean = await llm_cog.normalize_weapons(
                                    weapons_input
                                )
                                if not weapons_clean:
                                    weapons_clean = weapons_input
                            else:
                                weapons_clean = weapons_input
                        except Exception as e:
                            _logger.warning(
                                "llm_weapons_normalization_failed",
                                user_id=user_id,
                                guild_id=guild_id,
                                weapons_input=weapons_input[:50],
                                error_type=type(e).__name__,
                                error_msg=str(e)[:200]
                            )
                            weapons_clean = weapons_input
                        session["weapons"] = weapons_clean[:32]

                        try:
                            gs_value = (
                                int(self.gs.value.strip())
                                if self.gs.value.strip()
                                else 0
                            )
                            session["gs"] = min(max(gs_value, 0), 99999)
                        except (ValueError, TypeError):
                            _logger.warning(
                                "invalid_gs_value_using_zero",
                                gs_value=self.gs.value,
                                user_id=user_id,
                                guild_id=guild_id
                            )
                            session["gs"] = 0
                    if hasattr(self, "game_mode"):
                        raw_playtime = self.playtime.value.strip()
                        session["game_mode"] = self.game_mode.value
                        session["playtime"] = raw_playtime[:MAX_PLAYTIME_LEN]
                        if len(raw_playtime) > MAX_PLAYTIME_LEN:
                            _logger.warning(
                                "playtime_truncated_at_modal_input",
                                user_id=user_id,
                                guild_id=guild_id,
                                original_length=len(raw_playtime),
                                max_length=MAX_PLAYTIME_LEN
                            )
                    _logger.debug(
                        "session_after_update",
                        user_id=user_id,
                        guild_id=guild_id,
                        session_keys=list(session.keys()),
                        motif=session.get('motif')
                    )
                    await cog.finalize_profile(guild_id, user_id)
                setup_complete_msg = PROFILE_SETUP_DATA.get("setup_complete", {}).get(
                    self.locale,
                    PROFILE_SETUP_DATA.get("setup_complete", {}).get(
                        "en-US", "✅ Profile setup complete!"
                    ),
                )
                await interaction.followup.send(setup_complete_msg, ephemeral=True)
                _logger.debug(
                    "questions_select_modal_submission_processed",
                    user_id=interaction.user.id,
                    guild_id=self.guild_id,
                    locale=self.locale,
                    motif=self.motif
                )
            except Exception as e:
                _logger.error(
                    "error_in_questions_select_callback",
                    user_id=interaction.user.id,
                    guild_id=self.guild_id,
                    locale=self.locale,
                    motif=self.motif,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )
                error_msg = PROFILE_SETUP_DATA.get("error_occurred", {}).get(
                    self.locale,
                    PROFILE_SETUP_DATA.get("error_occurred", {}).get(
                        "en-US", "❌ An error occurred during profile submission."
                    ),
                )
                try:
                    await interaction.followup.send(error_msg, ephemeral=True)
                except Exception as follow_error:
                    _logger.error(
                        "failed_to_send_error_message",
                        user_id=interaction.user.id,
                        guild_id=self.guild_id,
                        error_type=type(follow_error).__name__,
                        error_msg=str(follow_error)[:200]
                    )

    class QuestionsSelectButton(discord.ui.Button):
        """Button to open profile questions modal."""

        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int, motif: str):
            """
            Initialize questions select button.

            Args:
                cog: ProfileSetup cog instance
                locale: Language locale code
                guild_id: Discord guild ID
                motif: Profile motif type
            """
            label = PROFILE_SETUP_DATA["comp_profile"].get(
                locale, PROFILE_SETUP_DATA["comp_profile"].get("en-US")
            )
            super().__init__(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id="questions_select_button",
            )
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif

        @discord_resilient(service_name="discord_api", max_retries=2)
        async def callback(self, interaction: discord.Interaction):
            """
            Handle button click to show profile modal.

            Args:
                interaction: Discord interaction from button click
            """
            _logger.debug(
                "questions_select_button_clicked",
                user_id=interaction.user.id,
                guild_id=self.guild_id,
                locale=self.locale,
                motif=self.motif
            )
            try:
                modal = ProfileSetup.QuestionsSelect(
                    self.locale, self.guild_id, self.motif
                )
                if len(modal.children) > 5:
                    _logger.error(
                        "modal_exceeds_discord_field_limit",
                        fields_count=len(modal.children),
                        limit=5,
                        user_id=interaction.user.id,
                        guild_id=self.guild_id,
                        motif=self.motif
                    )
                    await interaction.response.send_message(
                        "⚠️ Too many fields in the form! Contact an admin.",
                        ephemeral=True,
                    )
                    return
                await interaction.response.send_modal(modal)
                _logger.debug(
                    "modal_sent_successfully",
                    user_id=interaction.user.id,
                    guild_id=self.guild_id,
                    motif=self.motif
                )
            except Exception:
                _logger.error(
                    "failed_to_send_modal",
                    user_id=interaction.user.id,
                    guild_id=self.guild_id,
                    motif=self.motif,
                    exc_info=True
                )
                await interaction.response.send_message(
                    "❌ Error while displaying the form.", ephemeral=True
                )

    class QuestionsSelectView(discord.ui.View):
        """View containing the profile questions button."""

        def __init__(self, cog: "ProfileSetup", locale: str, guild_id: int, motif: str):
            """
            Initialize questions select view.

            Args:
                cog: ProfileSetup cog instance
                locale: Language locale code
                guild_id: Discord guild ID
                motif: Profile motif type
            """
            super().__init__(timeout=180)
            self.cog = cog
            self.locale = locale
            self.guild_id = guild_id
            self.motif = motif
            _logger.debug(
                "initializing_questions_select_view",
                guild_id=guild_id,
                locale=locale,
                motif=motif
            )
            self.add_item(
                ProfileSetup.QuestionsSelectButton(cog, locale, guild_id, motif)
            )

    class DiplomatValidationButton(discord.ui.Button):
        """Button for validating diplomat access to channels."""

        def __init__(
            self,
            member: discord.Member,
            channel: discord.TextChannel,
            guild_lang: str,
            guild_name: str = "Unknown",
        ):
            """
            Initialize diplomat validation button.

            Args:
                member: Discord member requiring validation
                channel: Discord text channel for validation
                guild_lang: Guild language code
                guild_name: Name of the guild being validated for
            """
            button_text = PROFILE_SETUP_DATA["anti_espionage"]["validation_button"].get(
                guild_lang,
                PROFILE_SETUP_DATA["anti_espionage"]["validation_button"].get("en-US"),
            )
            suffix = hashlib.sha1(guild_name.encode("utf-8")).hexdigest()[:8]
            custom_id = f"validate_diplomat_{member.guild.id}_{member.id}_{suffix}"
            super().__init__(
                label=button_text,
                style=discord.ButtonStyle.success,
                custom_id=custom_id,
            )
            self.member = member
            self.channel = channel
            self.guild_lang = guild_lang
            self.guild_name = guild_name

        @discord_resilient(service_name="discord_api", max_retries=2)
        async def callback(self, interaction: discord.Interaction):
            """
            Handle diplomat validation button callback.

            Args:
                interaction: Discord interaction from button press
            """
            try:
                if interaction.user.id == self.member.id:
                    msg = PROFILE_SETUP_DATA["anti_espionage"].get("permission_denied", {}).get(
                        self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["permission_denied"].get("en-US")
                    )
                    await interaction.response.send_message(msg, ephemeral=True)
                    return

                cog = interaction.client.get_cog("ProfileSetup")
                roles_config = await cog.get_guild_roles(interaction.guild.id) if (cog and interaction.guild) else {}

                staff_role_ids = {
                    role_id for role_name in ["guild_master", "officer", "guardian"]
                    if (role_id := roles_config.get(role_name)) is not None
                }

                channel_perms = self.channel.permissions_for(interaction.user)
                is_staff_perm = channel_perms.manage_channels or channel_perms.administrator
                is_staff_role = any(r.id in staff_role_ids for r in getattr(interaction.user, "roles", []))

                if not (is_staff_perm or is_staff_role):
                    permission_denied_text = PROFILE_SETUP_DATA["anti_espionage"]["permission_denied"].get(
                        self.guild_lang, PROFILE_SETUP_DATA["anti_espionage"]["permission_denied"].get("en-US")
                    )
                    await interaction.response.send_message(permission_denied_text, ephemeral=True)
                    return

                overwrites = self.channel.overwrites
                overwrites[self.member] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

                await self.channel.edit(overwrites=overwrites)

                self.disabled = True
                for item in self.view.children:
                    item.disabled = True

                success_text = (
                    PROFILE_SETUP_DATA["anti_espionage"]["validation_success"]
                    .get(
                        self.guild_lang,
                        PROFILE_SETUP_DATA["anti_espionage"]["validation_success"].get(
                            "en-US"
                        ),
                    )
                    .format(diplomat_name=self.member.display_name)
                )

                validated_by_template = PROFILE_SETUP_DATA["anti_espionage"][
                    "validated_by"
                ].get(
                    self.guild_lang,
                    PROFILE_SETUP_DATA["anti_espionage"]["validated_by"].get("en-US"),
                )
                validation_by_text = f"\n👤 {validated_by_template.format(user=interaction.user.mention)}"
                full_message = success_text + validation_by_text

                await interaction.response.send_message(full_message, view=None)

                try:
                    if self.view.original_message:
                        await self.view.original_message.edit(view=self.view)
                except discord.NotFound:
                    pass
                except Exception as e:
                    _logger.error(
                        "error_updating_original_message",
                        member_id=self.member.id,
                        guild_id=self.member.guild.id,
                        guild_name=self.guild_name,
                        error_type=type(e).__name__,
                        error_msg=str(e)[:200]
                    )

                try:
                    cog = interaction.client.get_cog("ProfileSetup")
                    if cog:
                        query = "SELECT locale FROM user_setup WHERE guild_id = %s AND user_id = %s"
                        result = await interaction.client.run_db_query(
                            query,
                            (interaction.guild.id, self.member.id),
                            fetch_one=True,
                        )
                        user_locale = result[0] if result else "en-US"
                    else:
                        user_locale = "en-US"

                    granted_message = (
                        PROFILE_SETUP_DATA["anti_espionage"][
                            "access_granted_notification"
                        ]
                        .get(
                            user_locale,
                            PROFILE_SETUP_DATA["anti_espionage"][
                                "access_granted_notification"
                            ].get("en-US"),
                        )
                        .format(
                            diplomat_name=self.member.display_name,
                            guild_name=self.guild_name,
                        )
                    )

                    await self.member.send(granted_message)
                    _logger.info(
                        "access_granted_notification_sent",
                        diplomat_name=self.member.display_name,
                        diplomat_id=self.member.id,
                        guild_name=self.guild_name,
                        guild_id=self.member.guild.id
                    )

                except discord.Forbidden:
                    _logger.warning(
                        "could_not_send_access_granted_notification_dms_disabled",
                        diplomat_name=self.member.display_name,
                        diplomat_id=self.member.id,
                        guild_id=self.member.guild.id
                    )
                except Exception as e:
                    _logger.error(
                        "error_sending_access_granted_notification",
                        diplomat_name=self.member.display_name,
                        diplomat_id=self.member.id,
                        guild_id=self.member.guild.id,
                        error_type=type(e).__name__,
                        error_msg=str(e)[:200],
                        exc_info=True
                    )

                cog = interaction.client.get_cog("ProfileSetup")
                if cog:
                    await cog.remove_pending_validation(
                        self.member.guild.id, self.member.id, self.guild_name
                    )

                _logger.info(
                    "diplomat_validated_by_user",
                    diplomat_name=self.member.display_name,
                    diplomat_id=self.member.id,
                    validator_name=interaction.user.display_name,
                    validator_id=interaction.user.id,
                    guild_name=self.guild_name,
                    guild_id=self.member.guild.id
                )

            except Exception as e:
                error_text = (
                    PROFILE_SETUP_DATA["anti_espionage"]["validation_error"]
                    .get(
                        self.guild_lang,
                        PROFILE_SETUP_DATA["anti_espionage"]["validation_error"].get(
                            "en-US"
                        ),
                    )
                    .format(diplomat_name=self.member.display_name)
                )

                await interaction.response.send_message(error_text, ephemeral=True)
                _logger.error(
                    "error_validating_diplomat",
                    diplomat_name=self.member.display_name,
                    diplomat_id=self.member.id,
                    guild_name=self.guild_name,
                    guild_id=self.member.guild.id,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )

    class DiplomatValidationView(discord.ui.View):
        """View for diplomat validation buttons."""

        def __init__(
            self,
            member: discord.Member,
            channel: discord.TextChannel,
            guild_lang: str,
            guild_name: str = "Unknown",
            bot=None,
        ):
            """
            Initialize diplomat validation view.

            Args:
                member: Discord member to validate
                channel: Text channel for validation
                guild_lang: Guild language for translations
                guild_name: Name of the guild (default: Unknown)
                bot: Discord bot instance (optional)
            """
            super().__init__(timeout=86400)
            self.member = member
            self.channel = channel
            self.guild_lang = guild_lang
            self.guild_name = guild_name
            self.original_message = None
            self.bot = bot
            self.add_item(
                ProfileSetup.DiplomatValidationButton(
                    member, channel, guild_lang, guild_name
                )
            )

        async def on_timeout(self):
            """
            Handle view timeout after 24 hours.

            Disables all buttons and updates database to mark validation as expired.
            """
            for item in self.children:
                item.disabled = True

            message_text = PROFILE_SETUP_DATA["anti_espionage"][
                "validation_timeout"
            ].get(
                self.guild_lang,
                PROFILE_SETUP_DATA["anti_espionage"]["validation_timeout"].get("en-US"),
            )

            try:
                if self.bot:
                    cog = self.bot.get_cog("ProfileSetup")
                    if cog:
                        query = """
                            UPDATE pending_diplomat_validations 
                            SET status = 'expired', completed_at = NOW()
                            WHERE guild_id = %s AND member_id = %s AND guild_name = %s AND status = 'pending'
                        """
                        await self.bot.run_db_query(
                            query,
                            (self.member.guild.id, self.member.id, self.guild_name),
                            commit=True,
                        )

                        await cog._remove_pending_from_cache(self.member.guild.id, self.member.id, self.guild_name)

                if self.original_message:
                    try:
                        await self.original_message.edit(view=self)
                    except discord.NotFound:
                        pass

                await self.channel.send(message_text)
                _logger.info(
                    "validation_timeout_for_diplomat",
                    diplomat_name=self.member.display_name,
                    diplomat_id=self.member.id,
                    guild_name=self.guild_name,
                    guild_id=self.member.guild.id
                )
            except Exception as e:
                _logger.error(
                    "error_handling_timeout",
                    diplomat_name=self.member.display_name,
                    diplomat_id=self.member.id,
                    guild_id=self.member.guild.id,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )


def setup(bot: discord.Bot):
    """
    Setup function to add the ProfileSetup cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(ProfileSetup(bot))
