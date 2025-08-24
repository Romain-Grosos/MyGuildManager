"""
Loot Wishlist Cog - Enterprise-grade Epic/Legendary items wishlist management for guild members.

This cog provides comprehensive wishlist management with:

WISHLIST FEATURES:
- Personal Epic/Legendary items wishlists with priority levels
- Intelligent item search with fuzzy matching
- Real-time wishlist synchronization and validation
- Multi-language support for item names and commands

ENTERPRISE PATTERNS:
- ComponentLogger structured logging with correlation tracking
- Discord API resilience with retry logic
- Database transactions with rollback protection
- Comprehensive error handling and recovery
- Performance monitoring and timeout management

RELIABILITY:
- Timeout protection for database operations
- Graceful degradation on item lookup failures
- Database integrity with constraint validation
- Cache synchronization with epic items data
- User input sanitization and validation

Architecture: Enterprise-grade with comprehensive monitoring, automatic cleanup,
and production-ready reliability patterns.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import discord
from discord.ext import commands
from discord.utils import escape_markdown

from app.core.logger import ComponentLogger
from app.core.reliability import discord_resilient
from app.db import run_db_query
from app.core.functions import get_user_message, get_guild_message
from app.core.translation import translations as global_translations

LOOT_SYSTEM = global_translations.get("loot_system", {})
LOOT_WISHLIST_DATA = LOOT_SYSTEM

_logger = ComponentLogger("loot_wishlist")

class LootWishlist(commands.Cog):
    """
    Enterprise-grade Epic/Legendary items wishlist management cog.

    This cog provides comprehensive wishlist functionality with enterprise patterns:
    - ComponentLogger structured logging with correlation tracking
    - Discord API resilience with @discord_resilient decorators
    - Database transactions with rollback protection
    - Anti-concurrent execution protection with asyncio.Lock
    - Intelligent item search with fuzzy matching and autocomplete
    - Real-time wishlist synchronization and validation
    """

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the Loot Wishlist cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self._user_locks = {}
        self._guild_refresh_tasks: Dict[int, asyncio.Task] = {}

        self._register_loot_commands()
        self._register_staff_commands()

    def _register_loot_commands(self):
        """Register loot wishlist commands with the centralized loot group."""
        if hasattr(self.bot, "loot_group"):
            self.bot.loot_group.command(
                name=LOOT_SYSTEM.get("wishlist_add", {})
                .get("name", {})
                .get("en-US", "wishlist_add"),
                description=LOOT_SYSTEM.get("wishlist_add", {})
                .get("description", {})
                .get("en-US", "Add an Epic/Legendary item to your wishlist"),
                name_localizations=LOOT_SYSTEM.get("wishlist_add", {}).get("name", {}),
                description_localizations=LOOT_SYSTEM.get("wishlist_add", {}).get(
                    "description", {}
                ),
            )(self.wishlist_add)

            self.bot.loot_group.command(
                name=LOOT_SYSTEM.get("wishlist_remove", {})
                .get("name", {})
                .get("en-US", "wishlist_remove"),
                description=LOOT_SYSTEM.get("wishlist_remove", {})
                .get("description", {})
                .get("en-US", "Remove an item from your wishlist"),
                name_localizations=LOOT_SYSTEM.get("wishlist_remove", {}).get(
                    "name", {}
                ),
                description_localizations=LOOT_SYSTEM.get("wishlist_remove", {}).get(
                    "description", {}
                ),
            )(self.wishlist_remove)

            self.bot.loot_group.command(
                name=LOOT_SYSTEM.get("wishlist_list", {})
                .get("name", {})
                .get("en-US", "wishlist_show"),
                description=LOOT_SYSTEM.get("wishlist_list", {})
                .get("description", {})
                .get("en-US", "View your current wishlist"),
                name_localizations=LOOT_SYSTEM.get("wishlist_list", {}).get("name", {}),
                description_localizations=LOOT_SYSTEM.get("wishlist_list", {}).get(
                    "description", {}
                ),
            )(self.wishlist_list)

    def _register_staff_commands(self):
        """Register staff wishlist commands with the centralized staff group."""
        if hasattr(self.bot, "staff_group"):
            self.bot.staff_group.command(
                name=LOOT_SYSTEM.get("wishlist_admin", {})
                .get("name", {})
                .get("en-US", "wishlist_mod"),
                description=LOOT_SYSTEM.get("wishlist_admin", {})
                .get("description", {})
                .get("en-US", "[MOD] View global wishlist statistics"),
                name_localizations=LOOT_SYSTEM.get("wishlist_admin", {}).get(
                    "name", {}
                ),
                description_localizations=LOOT_SYSTEM.get("wishlist_admin", {}).get(
                    "description", {}
                ),
            )(self.wishlist_admin)

    def _get_user_lock(self, guild_id: int, user_id: int) -> asyncio.Lock:
        """
        Get or create a lock for a specific user to prevent race conditions.
        
        Args:
            guild_id: The Discord guild ID
            user_id: The Discord user ID
            
        Returns:
            asyncio.Lock for the specific user
        """
        key = (guild_id, user_id)
        return self._user_locks.setdefault(key, asyncio.Lock())

    def _schedule_refresh(self, guild_id: int, delay: float = 1.5):
        """Schedule a debounced refresh of the wishlist message for the guild."""
        t = self._guild_refresh_tasks.get(guild_id)
        if t and not t.done():
            t.cancel()
        async def _run():
            try:
                await asyncio.sleep(delay)
                await self.update_wishlist_message(guild_id)
            except asyncio.CancelledError:
                pass
        self._guild_refresh_tasks[guild_id] = asyncio.create_task(_run())


    async def autocomplete_epic_items(
        self, ctx: discord.AutocompleteContext
    ) -> List[str]:
        """
        Autocomplete callback for Epic/Legendary item names with smart wildcard matching.

        Supports multiple search patterns:
        - Exact start match (highest priority)
        - Word start match (medium priority)
        - Substring match (lowest priority)
        - Multilingue support (EN/FR/ES/DE)

        Args:
            ctx: The autocomplete context containing user input

        Returns:
            List of up to 25 matching Epic/Legendary item names sorted by relevance
        """
        try:
            user_input = ctx.value.lower().strip() if ctx.value else ""
            epic_items = await self.bot.cache.get_static_data("epic_items")

            if not epic_items:
                _logger.debug("no_epic_items_cache_autocomplete")
                return []

            if not user_input:
                suggestions = [
                    item.get("item_name_en", "")
                    for item in epic_items[:50]
                    if item.get("item_name_en")
                ]
                suggestions.sort()
                return suggestions[:25]

            _logger.debug("autocomplete_search_started",
                user_input=user_input[:50],
                input_length=len(user_input)
            )

            scored_suggestions = []

            for item in epic_items:
                english_name = item.get("item_name_en", "")
                if not english_name:
                    continue

                item_names = [
                    item.get("item_name_en", ""),
                    item.get("item_name_fr", ""),
                    item.get("item_name_es", ""),
                    item.get("item_name_de", ""),
                ]

                best_score = 0

                for item_name in item_names:
                    if not item_name:
                        continue

                    item_name_lower = item_name.lower()
                    score = 0

                    if item_name_lower.startswith(user_input):
                        score = 100
                    elif any(
                        word.startswith(user_input) for word in item_name_lower.split()
                    ):
                        score = 80
                    elif user_input in item_name_lower:
                        score = 60
                        pos = item_name_lower.find(user_input)
                        if pos <= 5:
                            score = 70

                    if item_name == english_name and score > 0:
                        score += 5

                    if score > best_score:
                        best_score = score

                if best_score > 0:
                    scored_suggestions.append((english_name, best_score))

            unique_suggestions = {}
            for name, score in scored_suggestions:
                if name not in unique_suggestions or score > unique_suggestions[name]:
                    unique_suggestions[name] = score

            final_suggestions = [
                (name, score) for name, score in unique_suggestions.items()
            ]
            final_suggestions.sort(key=lambda x: (-x[1], x[0]))

            result = [suggestion[0] for suggestion in final_suggestions[:25]]
            _logger.debug("autocomplete_matches_found",
                user_input=user_input[:50],
                matches_count=len(result),
                total_suggestions=len(final_suggestions)
            )

            return result

        except Exception as e:
            _logger.error("autocomplete_search_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_input=user_input[:50]
            )
            return []

    async def autocomplete_remove_items(
        self, ctx: discord.AutocompleteContext
    ) -> List[str]:
        """
        Autocomplete callback for removing items - prioritizes user's wishlist items.

        Args:
            ctx: The autocomplete context containing user input and interaction data

        Returns:
            List of up to 25 items from the user's current wishlist that match the input
        """
        try:
            guild_id = ctx.interaction.guild_id
            user_id = ctx.interaction.user.id
            user_input = ctx.value.lower() if ctx.value else ""

            if guild_id and user_id:
                user_items = await self.get_user_wishlist(guild_id, user_id)
                suggestions = []

                for item in user_items:
                    item_name = item.get("item_name", "")
                    if not user_input or user_input in item_name.lower():
                        suggestions.append(item_name)

                suggestions.sort()
                return suggestions[:25]

            return []

        except Exception as e:
            uid = getattr(getattr(ctx, "interaction", None), "user", None)
            uid = getattr(uid, "id", None)
            _logger.error("remove_autocomplete_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=uid
            )
            return []

    async def get_user_wishlist(
        self, guild_id: int, user_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get user's current wishlist items.

        Args:
            guild_id: The Discord guild ID
            user_id: The Discord user ID

        Returns:
            List of dictionaries containing item_name, item_id, priority, and created_at
        """
        query = """
        SELECT item_name, item_id, priority, created_at 
        FROM loot_wishlist 
        WHERE guild_id = %s AND user_id = %s 
        ORDER BY priority DESC, created_at ASC
        """

        try:
            results = await run_db_query(query, (guild_id, user_id), fetch_all=True)
            if results:
                return [
                    {
                        "item_name": row[0],
                        "item_id": row[1],
                        "priority": row[2],
                        "created_at": row[3],
                    }
                    for row in results
                ]
            return []
        except Exception as e:
            _logger.error("get_user_wishlist_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=user_id,
                guild_id=guild_id
            )
            return []

    async def get_wishlist_stats(self, guild_id: int) -> List[Dict[str, Any]]:
        """
        Get top 10 most wanted items for the guild.

        Args:
            guild_id: The Discord guild ID

        Returns:
            List of dictionaries with item statistics including demand_count, user_ids,
            avg_priority, and item_icon_url, ordered by demand and priority
        """
        query = """
        WITH ranked AS (
            SELECT w.item_id, w.user_id, w.priority,
                   ROW_NUMBER() OVER (PARTITION BY w.item_id ORDER BY w.priority DESC, w.created_at ASC) AS rn
            FROM loot_wishlist w
            WHERE w.guild_id = %s
        )
        SELECT e.item_name_en AS item_name,
               r.item_id,
               COUNT(DISTINCT w.user_id) AS demand_count,
               GROUP_CONCAT(DISTINCT r.user_id ORDER BY r.rn ASC SEPARATOR ',') AS user_ids,
               AVG(w.priority) AS avg_priority,
               e.item_icon_url
        FROM ranked r
        JOIN loot_wishlist w ON w.item_id = r.item_id AND w.guild_id = %s
        JOIN epic_items e ON r.item_id = e.item_id
        WHERE r.rn <= 10
        GROUP BY r.item_id, e.item_name_en, e.item_icon_url
        ORDER BY demand_count DESC, avg_priority DESC
        LIMIT 10
        """

        try:
            results = await run_db_query(query, (guild_id, guild_id), fetch_all=True)
            if results:
                return [
                    {
                        "item_name": row[0],
                        "item_id": row[1],
                        "demand_count": row[2],
                        "user_ids": [int(uid) for uid in (row[3] or "").split(",") if uid],
                        "avg_priority": float(row[4]),
                        "item_icon_url": row[5] or "",
                    }
                    for row in results
                ]
            return []
        except Exception as e:
            _logger.error("wishlist_stats_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                guild_id=guild_id
            )
            return []

    async def is_valid_epic_item(self, item_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if item exists in Epic/Legendary database and return item_id.
        Uses the same smart matching logic as autocomplete.

        Args:
            item_name: The name of the item to validate

        Returns:
            Tuple of (is_valid, item_id) where is_valid is True if item exists,
            and item_id is the database ID of the item or None if not found
        """
        try:
            epic_items = await self.bot.cache.get_static_data("epic_items")
            user_input_lower = item_name.lower().strip()

            best_item = None
            if epic_items:
                best_score = 0
                for item in epic_items:
                    english_name = item.get("item_name_en", "")
                    if not english_name:
                        continue
                    for item_lang_name in (
                        item.get("item_name_en", ""),
                        item.get("item_name_fr", ""),
                        item.get("item_name_es", ""),
                        item.get("item_name_de", ""),
                    ):
                        if not item_lang_name:
                            continue
                        name_lower = item_lang_name.lower()
                        score = (
                            100 if name_lower == user_input_lower else
                            90  if name_lower.startswith(user_input_lower) else
                            80  if any(w.startswith(user_input_lower) for w in name_lower.split()) else
                            60  if user_input_lower in name_lower else
                            0
                        )
                        if score > best_score:
                            best_score = score
                            best_item = item

                if best_item and best_item.get("item_id"):
                    _logger.debug("item_match_found",
                                  input_name=item_name[:50],
                                  matched_id=best_item["item_id"])
                    return True, best_item["item_id"]

            query = """
            SELECT item_id FROM epic_items 
            WHERE LOWER(item_name_en) = LOWER(%s) OR LOWER(item_name_fr) = LOWER(%s)
               OR LOWER(item_name_es) = LOWER(%s) OR LOWER(item_name_de) = LOWER(%s)
               OR LOWER(item_name_en) LIKE LOWER(%s)
               OR LOWER(item_name_fr) LIKE LOWER(%s)
               OR LOWER(item_name_es) LIKE LOWER(%s)
               OR LOWER(item_name_de) LIKE LOWER(%s)
            LIMIT 1
            """
            like_pattern = f"%{item_name}%"
            result = await run_db_query(query, (item_name, item_name, item_name, item_name,
                                                like_pattern, like_pattern, like_pattern, like_pattern),
                                        fetch_one=True)
            return (True, result[0]) if result else (False, None)

        except Exception as e:
            _logger.error("item_validation_failed", error_type=type(e).__name__, error_msg=str(e)[:200])
            return False, None

    @discord_resilient(service_name="wishlist_update", max_retries=2)
    async def update_wishlist_message(self, guild_id: int) -> bool:
        """
        Update the wishlist placeholder message with current data.

        Args:
            guild_id: The Discord guild ID

        Returns:
            True if the message was successfully updated, False otherwise
        """
        try:
            guild_ptb_config = await self.bot.cache.get_guild_data(
                guild_id, "ptb_settings"
            )
            if guild_ptb_config and guild_ptb_config.get("ptb_guild_id") == guild_id:
                _logger.debug("ptb_guild_loot_update_skipped",
                    guild_id=guild_id
                )
                return False

            await self.bot.cache_loader.ensure_guild_channels_loaded()
            loot_data = await self.bot.cache.get_guild_data(guild_id, "loot_message")

            if not loot_data:
                _logger.debug("no_loot_message_data",
                    guild_id=guild_id
                )
                return False

            channel_id = loot_data.get("channel")
            message_id = loot_data.get("message")

            if not channel_id or not message_id:
                _logger.warning("invalid_loot_message_data",
                    guild_id=guild_id,
                    has_channel_id=bool(channel_id),
                    has_message_id=bool(message_id)
                )
                return False

            channel = self.bot.get_channel(channel_id)
            if not channel:
                _logger.error("loot_channel_not_found",
                    guild_id=guild_id,
                    channel_id=channel_id
                )
                return False

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                _logger.error("loot_message_not_found",
                    guild_id=guild_id,
                    channel_id=channel_id,
                    message_id=message_id
                )
                return False

            stats = await self.get_wishlist_stats(guild_id)

            await self.bot.cache_loader.ensure_guild_settings_loaded()

            title = await get_guild_message(
                self.bot, guild_id, LOOT_WISHLIST_DATA, "placeholder.title"
            )
            description = await get_guild_message(
                self.bot, guild_id, LOOT_WISHLIST_DATA, "placeholder.description"
            )
            empty_msg = await get_guild_message(
                self.bot, guild_id, LOOT_WISHLIST_DATA, "placeholder.empty"
            )
            footer_text = await get_guild_message(
                self.bot, guild_id, LOOT_WISHLIST_DATA, "placeholder.footer"
            )

            main_embed = discord.Embed(
                title=f"⚔️ {title}",
                description=description,
                color=discord.Color.gold(),
                timestamp=datetime.now(),
            )

            if not stats:
                current_list_title = await get_guild_message(
                    self.bot, guild_id, LOOT_WISHLIST_DATA, "placeholder.current_list_title"
                )
                main_embed.add_field(
                    name=f"📋 {current_list_title}", value=empty_msg, inline=False
                )
                main_embed.set_footer(text=footer_text)
                await message.edit(embeds=[main_embed])
                actual_embeds_count = 1
            else:
                total_wishlists = sum(item["demand_count"] for item in stats)
                stats_summary = await get_guild_message(
                    self.bot,
                    guild_id,
                    LOOT_WISHLIST_DATA,
                    "messages.statistics_summary",
                    total_wishes=total_wishlists,
                    unique_items=len(stats),
                )
                stats_title = await get_guild_message(
                    self.bot,
                    guild_id,
                    LOOT_WISHLIST_DATA,
                    "messages.statistics_field_title",
                )
                main_embed.add_field(
                    name=stats_title, value=stats_summary, inline=False
                )
                main_embed.set_footer(text=footer_text)

                item_embeds = [main_embed]

                for i, item_data in enumerate(stats[:15], 1):
                    priority_emojis = {1: "🔵", 2: "🟡", 3: "🔴"}
                    avg_priority = round(item_data["avg_priority"])
                    priority_emoji = priority_emojis.get(avg_priority, "⚪")

                    if i == 1:
                        color = discord.Color.gold()
                    elif i <= 3:
                        color = discord.Color.from_rgb(192, 192, 192)
                    elif i <= 5:
                        color = discord.Color.from_rgb(205, 127, 50)
                    else:
                        color = discord.Color.blue()

                    safe_item_name = escape_markdown(item_data['item_name'])
                    item_embed = discord.Embed(
                        title=f"{priority_emoji} #{i} - {safe_item_name}",
                        color=color,
                    )

                    if item_data.get("item_icon_url"):
                        item_embed.set_thumbnail(url=item_data["item_icon_url"])

                    info_text = await get_guild_message(
                        self.bot,
                        guild_id,
                        LOOT_WISHLIST_DATA,
                        "messages.item_demand_info",
                        member_count=item_data["demand_count"],
                        avg_priority=f"{item_data['avg_priority']:.1f}",
                    )

                    demand_title = await get_guild_message(
                        self.bot,
                        guild_id,
                        LOOT_WISHLIST_DATA,
                        "messages.demand_field_title",
                    )

                    item_embed.add_field(
                        name=demand_title, value=info_text, inline=False
                    )

                    user_names = []
                    guild = self.bot.get_guild(guild_id)
                    for j, user_id in enumerate(item_data["user_ids"][:10]):
                        try:
                            if guild:
                                member = guild.get_member(user_id)
                                if member:
                                    user_names.append(escape_markdown(member.display_name))
                                    continue

                            user = self.bot.get_user(user_id)
                            if user:
                                user_names.append(escape_markdown(user.display_name))
                            else:
                                user_names.append(f"User-{user_id}")
                        except:
                            user_names.append(f"User-{user_id}")

                    members_list = "\n".join(f"• {name}" for name in user_names)
                    remaining = item_data["demand_count"] - len(item_data["user_ids"])
                    if remaining > 0:
                        remaining_text = await get_guild_message(
                            self.bot, guild_id, LOOT_WISHLIST_DATA, "messages.remaining_others",
                            count=remaining
                        )
                        members_list += f"\n*{remaining_text}*"

                    no_members_text = await get_guild_message(
                        self.bot, guild_id, LOOT_WISHLIST_DATA, "messages.no_members"
                    )
                    members_formatted = await get_guild_message(
                        self.bot,
                        guild_id,
                        LOOT_WISHLIST_DATA,
                        "messages.members_list_format",
                        members_list=members_list or no_members_text,
                    )

                    members_title = await get_guild_message(
                        self.bot,
                        guild_id,
                        LOOT_WISHLIST_DATA,
                        "messages.members_field_title",
                    )

                    item_embed.add_field(
                        name=members_title, value=members_formatted, inline=False
                    )

                    rank_emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
                    rank_emoji = rank_emojis.get(i, "🏅")
                    position_text = await get_guild_message(
                        self.bot, guild_id, LOOT_WISHLIST_DATA, "messages.position_footer",
                        position=i, total=len(stats)
                    )
                    item_embed.set_footer(
                        text=f"{rank_emoji} {position_text}"
                    )

                    item_embeds.append(item_embed)

                if len(stats) > 15:
                    info_title = await get_guild_message(
                        self.bot, guild_id, LOOT_WISHLIST_DATA, "messages.info_title"
                    )
                    info_description_15 = await get_guild_message(
                        self.bot, guild_id, LOOT_WISHLIST_DATA, "messages.info_description_15",
                        remaining_count=len(stats) - 15
                    )
                    info_embed = discord.Embed(
                        title=f"ℹ️ {info_title}",
                        description=info_description_15,
                        color=discord.Color.greyple(),
                    )
                    item_embeds.append(info_embed)

                if len(item_embeds) <= 10:
                    await message.edit(embeds=item_embeds)
                    actual_embeds_count = len(item_embeds)
                else:
                    final_embeds = item_embeds[:8]
                    info_title = await get_guild_message(
                        self.bot, guild_id, LOOT_WISHLIST_DATA, "messages.info_title"
                    )
                    info_description_8 = await get_guild_message(
                        self.bot, guild_id, LOOT_WISHLIST_DATA, "messages.info_description_8"
                    )
                    info_embed = discord.Embed(
                        title=f"ℹ️ {info_title}",
                        description=info_description_8,
                        color=discord.Color.greyple(),
                    )
                    final_embeds.append(info_embed)
                    await message.edit(embeds=final_embeds)
                    actual_embeds_count = len(final_embeds)

            _logger.info("wishlist_message_updated",
                guild_id=guild_id,
                embeds_count=actual_embeds_count
            )
            return True

        except Exception as e:
            _logger.error("wishlist_message_update_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                guild_id=guild_id
            )
            return False

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="loot_wishlist", max_retries=2)
    async def wishlist_add(
        self,
        ctx: discord.ApplicationContext,
        item_name: str = discord.Option(
            description="Name of the Epic/Legendary item you want to add",
            description_localizations=LOOT_WISHLIST_DATA.get("commands", {})
            .get("wishlist_add", {})
            .get("options", {})
            .get("item_name", {})
            .get("description", {}),
            required=True,
            autocomplete=discord.utils.basic_autocomplete(
                lambda ctx: ctx.bot.get_cog("LootWishlist").autocomplete_epic_items(ctx)
            ),
        ),
        priority: str = discord.Option(
            description="Priority level (1=Low, 2=Medium, 3=High)",
            description_localizations=LOOT_WISHLIST_DATA.get("commands", {})
            .get("wishlist_add", {})
            .get("options", {})
            .get("priority", {})
            .get("description", {}),
            choices=[
                discord.OptionChoice(
                    name="Low",
                    name_localizations=LOOT_WISHLIST_DATA.get("messages", {}).get(
                        "priority_low", {}
                    ),
                    value="1",
                ),
                discord.OptionChoice(
                    name="Medium",
                    name_localizations=LOOT_WISHLIST_DATA.get("messages", {}).get(
                        "priority_medium", {}
                    ),
                    value="2",
                ),
                discord.OptionChoice(
                    name="High",
                    name_localizations=LOOT_WISHLIST_DATA.get("messages", {}).get(
                        "priority_high", {}
                    ),
                    value="3",
                ),
            ],
            default="2",
        ),
    ):
        """
        Add an item to user's wishlist.

        Args:
            ctx: The Discord application context
            item_name: Name of the Epic/Legendary item to add (with autocomplete)
            priority: Priority level as string ("1"=Low, "2"=Medium, "3"=High)

        Raises:
            Various exceptions related to database operations or Discord API calls
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        user_lock = self._get_user_lock(guild_id, user_id)
        async with user_lock:
            try:
                is_valid, item_id = await self.is_valid_epic_item(item_name)
                if not is_valid:
                    message = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        "messages.item_not_valid",
                        item_name=item_name,
                    )
                    await ctx.followup.send(message, ephemeral=True)
                    return

                current_items = await self.get_user_wishlist(guild_id, user_id)

                existing = next((it for it in current_items if it["item_id"] == item_id), None)

                if len(current_items) >= 3 and not existing:
                    message = await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, "messages.wishlist_full"
                    )
                    await ctx.followup.send(message, ephemeral=True)
                    return

                upsert_query = """
                INSERT INTO loot_wishlist (guild_id, user_id, item_name, item_id, priority)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                  priority = VALUES(priority),
                  item_name = VALUES(item_name),
                  updated_at = CURRENT_TIMESTAMP
                """

                priority_int = max(1, min(3, int(priority)))
                try:
                    await run_db_query(
                        upsert_query,
                        (guild_id, user_id, item_name, item_id, priority_int),
                        commit=True,
                    )

                    priority_key = {1: "priority_low", 2: "priority_medium", 3: "priority_high"}[priority_int]
                    priority_text = await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, f"messages.{priority_key}"
                    )
                    message_key = "item_updated" if existing else "item_added"

                    updated_items = await self.get_user_wishlist(guild_id, user_id)
                    
                    message = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        f"messages.{message_key}",
                        item_name=item_name,
                        priority=priority_text,
                        count=len(updated_items),
                    )
                    await ctx.followup.send(message, ephemeral=True)

                    cache_key = f"wishlist_stats_{guild_id}"
                    if hasattr(self.bot, "cache") and hasattr(self.bot.cache, "invalidate"):
                        await self.bot.cache.invalidate(cache_key)

                    self._schedule_refresh(guild_id)

                except Exception as db_error:
                    uid = getattr(getattr(ctx, "interaction", None), "user", None)
                    uid = getattr(uid, "id", None) or getattr(getattr(ctx, "author", None), "id", None)
                    _logger.error("database_error_adding_item",
                        error_type=type(db_error).__name__,
                        error_msg=str(db_error)[:200],
                        user_id=uid,
                        guild_id=ctx.guild.id
                    )
                    message = await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, "messages.database_error_add"
                    )
                    await ctx.followup.send(message, ephemeral=True)

            except Exception as e:
                uid = getattr(getattr(ctx, "interaction", None), "user", None)
                uid = getattr(uid, "id", None) or getattr(getattr(ctx, "author", None), "id", None)
                _logger.error("add_item_wishlist_failed",
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    user_id=uid,
                    guild_id=ctx.guild.id
                )
                message = await get_user_message(
                    ctx,
                    LOOT_WISHLIST_DATA,
                    "messages.general_error",
                    action="adding the item",
                )
                await ctx.followup.send(message, ephemeral=True)

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="loot_wishlist", max_retries=2)
    async def wishlist_remove(
        self,
        ctx: discord.ApplicationContext,
        item_name: str = discord.Option(
            description="Name of the item to remove from your wishlist",
            description_localizations=LOOT_WISHLIST_DATA.get("commands", {})
            .get("wishlist_remove", {})
            .get("options", {})
            .get("item_name", {})
            .get("description", {}),
            required=True,
            autocomplete=discord.utils.basic_autocomplete(
                lambda ctx: ctx.bot.get_cog("LootWishlist").autocomplete_remove_items(
                    ctx
                )
            ),
        ),
    ):
        """
        Remove an item from user's wishlist.

        Args:
            ctx: The Discord application context
            item_name: Name of the item to remove (with autocomplete from user's wishlist)

        Raises:
            Various exceptions related to database operations or Discord API calls
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        user_lock = self._get_user_lock(guild_id, user_id)
        async with user_lock:
            try:
                current_items = await self.get_user_wishlist(guild_id, user_id)
                names = [it["item_name"] for it in current_items]

                def _pick_best_name(q: str, candidates: List[str]) -> Optional[str]:
                    ql = q.lower().strip()
                    best, best_score = None, 0
                    for c in candidates:
                        cl = c.lower()
                        score = 0
                        if cl == ql: score = 100
                        elif cl.startswith(ql): score = 90
                        elif any(w.startswith(ql) for w in cl.split()): score = 80
                        elif ql in cl: score = 60
                        if score > best_score:
                            best, best_score = c, score
                    return best

                picked_name = _pick_best_name(item_name, names)
                if not picked_name:
                    message = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        "messages.item_not_in_wishlist",
                        item_name=item_name,
                    )
                    await ctx.followup.send(message, ephemeral=True)
                    return

                item_id = next(it["item_id"] for it in current_items if it["item_name"] == picked_name)

                delete_query = """
                DELETE FROM loot_wishlist 
                WHERE guild_id = %s AND user_id = %s AND item_id = %s
                """

                try:
                    await run_db_query(
                        delete_query, (guild_id, user_id, item_id), commit=True
                    )

                    message = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        "messages.item_removed",
                        item_name=picked_name,
                        count=len(current_items) - 1,
                    )
                    await ctx.followup.send(message, ephemeral=True)

                    cache_key = f"wishlist_stats_{guild_id}"
                    if hasattr(self.bot, "cache") and hasattr(self.bot.cache, "invalidate"):
                        await self.bot.cache.invalidate(cache_key)

                    updated_items = await self.get_user_wishlist(guild_id, user_id)
                    if not updated_items:
                        self._user_locks.pop((guild_id, user_id), None)

                    self._schedule_refresh(guild_id)

                except Exception as db_error:
                    uid = getattr(getattr(ctx, "interaction", None), "user", None)
                    uid = getattr(uid, "id", None) or getattr(getattr(ctx, "author", None), "id", None)
                    _logger.error("database_error_removing_item",
                        error_type=type(db_error).__name__,
                        error_msg=str(db_error)[:200],
                        user_id=uid,
                        guild_id=ctx.guild.id
                    )
                    message = await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, "messages.database_error_remove"
                    )
                    await ctx.followup.send(message, ephemeral=True)

            except Exception as e:
                uid = getattr(getattr(ctx, "interaction", None), "user", None)
                uid = getattr(uid, "id", None) or getattr(getattr(ctx, "author", None), "id", None)
                _logger.error("remove_item_wishlist_failed",
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    user_id=uid,
                    guild_id=ctx.guild.id
                )
                message = await get_user_message(
                    ctx,
                    LOOT_WISHLIST_DATA,
                    "messages.general_error",
                    action="removing the item",
                )
                await ctx.followup.send(message, ephemeral=True)

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="loot_wishlist", max_retries=2)
    async def wishlist_list(self, ctx: discord.ApplicationContext):
        """
        Show user's current wishlist.

        Args:
            ctx: The Discord application context

        Raises:
            Various exceptions related to database operations or Discord API calls
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        user_id = ctx.author.id

        try:
            current_items = await self.get_user_wishlist(guild_id, user_id)

            title = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.wishlist_title",
                user=ctx.author.display_name,
            )
            embed = discord.Embed(title=title, color=discord.Color.gold())

            if not current_items:
                embed.description = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.wishlist_empty"
                )
            else:
                wishlist_text = ""
                priority_emojis = {1: "🔵", 2: "🟡", 3: "🔴"}
                priority_names = {
                    1: await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, "messages.priority_low"
                    ),
                    2: await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, "messages.priority_medium"
                    ),
                    3: await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, "messages.priority_high"
                    ),
                }

                for i, item in enumerate(current_items, 1):
                    priority_emoji = priority_emojis.get(item["priority"], "⚪")
                    priority_name = priority_names.get(item["priority"], "Unknown")

                    display_name = item["item_name"]
                    if len(display_name) > 35:
                        display_name = display_name[:32] + "..."
                    display_name = escape_markdown(display_name)

                    wishlist_text += f"`{i:>1}.` **{display_name}**\n"
                    wishlist_text += f"    {priority_emoji} *{priority_name}*\n\n"

                field_name = await get_user_message(
                    ctx,
                    LOOT_WISHLIST_DATA,
                    "messages.your_items",
                    count=len(current_items),
                )
                embed.add_field(name=field_name, value=wishlist_text, inline=False)

            footer_text = await get_user_message(
                ctx, LOOT_WISHLIST_DATA, "messages.wishlist_footer"
            )
            embed.set_footer(text=footer_text)
            await ctx.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            uid = getattr(getattr(ctx, "interaction", None), "user", None)
            uid = getattr(uid, "id", None) or getattr(getattr(ctx, "author", None), "id", None)
            _logger.error("list_user_wishlist_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=uid,
                guild_id=ctx.guild.id
            )
            message = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.general_error",
                action="retrieving your wishlist",
            )
            await ctx.followup.send(message, ephemeral=True)

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="loot_wishlist", max_retries=2)
    async def wishlist_admin(self, ctx: discord.ApplicationContext):
        """
        Show global wishlist statistics for moderators.

        Args:
            ctx: The Discord application context

        Raises:
            Various exceptions related to database operations or Discord API calls
        """
        await ctx.defer()

        guild_id = ctx.guild.id

        try:
            query = """
            SELECT user_id, item_name, item_id, priority, created_at
            FROM loot_wishlist 
            WHERE guild_id = %s
            ORDER BY user_id, priority DESC, created_at ASC
            """

            results = await run_db_query(query, (guild_id,), fetch_all=True)

            if not results:
                message = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.admin_no_wishlists"
                )
                await ctx.followup.send(message)
                return

            user_wishlists = {}
            for row in results:
                user_id, item_name, item_id, priority, created_at = row
                if user_id not in user_wishlists:
                    user_wishlists[user_id] = []
                user_wishlists[user_id].append(
                    {
                        "item_name": item_name,
                        "item_id": item_id,
                        "priority": priority,
                        "created_at": created_at,
                    }
                )

            stats = await self.get_wishlist_stats(guild_id)

            title = await get_user_message(
                ctx, LOOT_WISHLIST_DATA, "messages.admin_title"
            )
            stats_embed = discord.Embed(
                title=f"📊 {title}",
                color=discord.Color.blue(),
                timestamp=datetime.now(),
            )

            overview_name = await get_user_message(
                ctx, LOOT_WISHLIST_DATA, "messages.admin_overview"
            )
            overview_content = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.admin_overview_content",
                members=len(user_wishlists),
                total_items=len(results),
                unique_items=len(stats),
            )
            stats_embed.add_field(
                name=overview_name, value=overview_content, inline=False
            )

            if stats:
                priority_counts = {1: 0, 2: 0, 3: 0}
                for user_id, items in user_wishlists.items():
                    for item in items:
                        priority_counts[item["priority"]] = (
                            priority_counts.get(item["priority"], 0) + 1
                        )

                high_priority_text = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.high_priority_label"
                )
                medium_priority_text = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.medium_priority_label"
                )
                low_priority_text = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.low_priority_label"
                )
                items_label = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.items_count_label"
                )
                priority_distribution_title = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.priority_distribution_title"
                )

                stats_text = (
                    f"🔴 {high_priority_text}: **{priority_counts.get(3, 0)}** {items_label}\n"
                )
                stats_text += (
                    f"🟡 {medium_priority_text}: **{priority_counts.get(2, 0)}** {items_label}\n"
                )
                stats_text += (
                    f"🔵 {low_priority_text}: **{priority_counts.get(1, 0)}** {items_label}"
                )

                stats_embed.add_field(
                    name=f"📈 {priority_distribution_title}", value=stats_text, inline=True
                )

            footer_text = await get_user_message(
                ctx, LOOT_WISHLIST_DATA, "messages.admin_footer"
            )
            stats_embed.set_footer(text=footer_text)

            await ctx.followup.send(embed=stats_embed)

            if stats:
                item_embeds = []
                for i, item_data in enumerate(stats[:10], 1):
                    priority_emojis = {1: "🔵", 2: "🟡", 3: "🔴"}
                    avg_priority = round(item_data["avg_priority"])
                    priority_emoji = priority_emojis.get(avg_priority, "⚪")

                    safe_item_name = escape_markdown(item_data['item_name'])
                    item_embed = discord.Embed(
                        title=f"{priority_emoji} #{i} - {safe_item_name}",
                        color=discord.Color.gold() if i <= 3 else discord.Color.blue(),
                    )

                    if item_data.get("item_icon_url"):
                        item_embed.set_thumbnail(url=item_data["item_icon_url"])

                    stats_value = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        "messages.item_demand_info",
                        member_count=item_data["demand_count"],
                        avg_priority=f"{item_data['avg_priority']:.1f}",
                    )

                    stats_title = await get_user_message(
                        ctx, LOOT_WISHLIST_DATA, "messages.statistics_field_title"
                    )

                    item_embed.add_field(
                        name=stats_title, value=stats_value, inline=False
                    )

                    members_details = []
                    for user_id in item_data["user_ids"]:
                        user_priority = None
                        if user_id in user_wishlists:
                            for it in user_wishlists[user_id]:
                                if it["item_id"] == item_data["item_id"]:
                                    user_priority = it["priority"]
                                    break

                        try:
                            member = ctx.guild.get_member(user_id)
                            if member:
                                name = escape_markdown(member.display_name)
                            else:
                                user = self.bot.get_user(user_id)
                                name = escape_markdown(user.display_name) if user else f"User-{user_id}"
                        except:
                            name = f"User-{user_id}"

                        if user_priority:
                            p_emoji = priority_emojis.get(user_priority, "⚪")
                            members_details.append(f"{p_emoji} {name}")
                        else:
                            members_details.append(f"⚪ {name}")

                    members_list = "\n".join(members_details[:10])
                    remaining = item_data["demand_count"] - len(item_data["user_ids"])
                    if remaining > 0:
                        remaining_text = await get_user_message(
                            ctx, LOOT_WISHLIST_DATA, "messages.remaining_others",
                            count=remaining
                        )
                        members_list += f"\n*{remaining_text}*"
                        
                    members_formatted = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        "messages.members_list_format",
                        members_list=members_list,
                    )
                    interested_members_title = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        "messages.interested_members_field_title",
                    )
                    item_embed.add_field(
                        name=interested_members_title,
                        value=members_formatted,
                        inline=False,
                    )

                    item_embeds.append(item_embed)

                if item_embeds:
                    for i in range(0, len(item_embeds), 10):
                        await ctx.channel.send(embeds=item_embeds[i : i + 10])

            members_title = await get_user_message(
                ctx, LOOT_WISHLIST_DATA, "messages.members_with_wishlist_title"
            )
            members_embed = discord.Embed(
                title=f"👥 {members_title}",
                color=discord.Color.green(),
                timestamp=datetime.now(),
            )

            sorted_users = sorted(
                user_wishlists.items(), key=lambda x: len(x[1]), reverse=True
            )

            members_text = ""
            for user_id, items in sorted_users[:20]:
                try:
                    member = ctx.guild.get_member(user_id)
                    if member:
                        name = escape_markdown(member.display_name)
                    else:
                        user = self.bot.get_user(user_id)
                        name = escape_markdown(user.display_name) if user else f"User-{user_id}"
                except:
                    name = f"User-{user_id}"

                priority_emojis = {1: "🔵", 2: "🟡", 3: "🔴"}
                items_emojis = [
                    priority_emojis.get(item["priority"], "⚪") for item in items
                ]

                items_label = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.items_count_label"
                )
                members_text += (
                    f"**{name}** ({len(items)} {items_label}): {' '.join(items_emojis)}\n"
                )

            if len(sorted_users) > 20:
                remaining_members_text = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.remaining_members",
                    count=len(sorted_users) - 20
                )
                members_text += f"\n*{remaining_members_text}*"

            members_list_title = await get_user_message(
                ctx, LOOT_WISHLIST_DATA, "messages.members_list_title"
            )
            no_members_text = await get_user_message(
                ctx, LOOT_WISHLIST_DATA, "messages.no_members"
            )
            members_embed.add_field(
                name=members_list_title,
                value=members_text or no_members_text,
                inline=False,
            )

            await ctx.channel.send(embed=members_embed)

        except Exception as e:
            _logger.error("admin_wishlist_data_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                guild_id=ctx.guild.id
            )
            message = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.general_error",
                action="retrieving wishlist data",
            )
            await ctx.followup.send(message, ephemeral=True)

    @discord_resilient(service_name="wishlist_cleanup", max_retries=1)
    async def cleanup_member_wishlist(self, guild_id: int, user_id: int) -> None:
        """
        Remove all wishlist items for a member who left the guild.
        Called from notification.py when a member leaves.

        Args:
            guild_id: The Discord guild ID
            user_id: The Discord user ID of the departed member
        """
        try:
            delete_query = (
                "DELETE FROM loot_wishlist WHERE guild_id = %s AND user_id = %s"
            )
            await run_db_query(delete_query, (guild_id, user_id), commit=True)

            cache_key = f"wishlist_stats_{guild_id}"
            if hasattr(self.bot, "cache") and hasattr(self.bot.cache, "invalidate"):
                await self.bot.cache.invalidate(cache_key)

            self._user_locks.pop((guild_id, user_id), None)
            self._schedule_refresh(guild_id)

            _logger.info("member_wishlist_cleanup_completed",
                user_id=user_id,
                guild_id=guild_id
            )

        except Exception as e:
            _logger.error("member_wishlist_cleanup_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                user_id=user_id,
                guild_id=guild_id
            )

    def cog_unload(self):
        """Clean up pending refresh tasks when the cog is unloaded."""
        for t in self._guild_refresh_tasks.values():
            if t and not t.done():
                t.cancel()

def setup(bot: discord.Bot) -> None:
    """
    Setup function for the cog.

    Args:
        bot: The Discord bot instance to add the cog to
    """
    bot.add_cog(LootWishlist(bot))
