"""
Loot Wishlist Cog - Manages Epic T2 item wishlists for guild members.
Allows users to add/remove items from their wishlist and provides centralized tracking.
"""

import asyncio
import logging
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import discord
from discord.ext import commands

import db
from core.translation import translations as global_translations
from core.reliability import discord_resilient
from core.functions import get_user_message, get_guild_message

LOOT_SYSTEM = global_translations.get("loot_system", {})
LOOT_WISHLIST_DATA = LOOT_SYSTEM


class LootWishlist(commands.Cog):
    """
    Cog for managing Epic T2 item wishlists.

    This cog provides functionality for guild members to create and manage
    personal wishlists of Epic T2 items, with priority levels and automatic
    message updates for guild-wide visibility.
    """

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the Loot Wishlist cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot

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
                .get("en-US", "Add an Epic T2 item to your wishlist"),
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

    def sanitize_for_discord(self, text: str) -> str:
        """
        Remove accents and special characters for Discord compatibility.

        Args:
            text: The text string to sanitize

        Returns:
            The sanitized text with ASCII characters only
        """
        if not text:
            return text
        normalized = unicodedata.normalize("NFD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return ascii_text

    async def autocomplete_epic_items(
        self, ctx: discord.AutocompleteContext
    ) -> List[str]:
        """
        Autocomplete callback for Epic T2 item names with smart wildcard matching.

        Supports multiple search patterns:
        - Exact start match (highest priority)
        - Word start match (medium priority)
        - Substring match (lowest priority)
        - Multilingue support (EN/FR/ES/DE)

        Args:
            ctx: The autocomplete context containing user input

        Returns:
            List of up to 25 matching Epic T2 item names sorted by relevance
        """
        try:
            user_input = ctx.value.lower().strip() if ctx.value else ""
            epic_items = await self.bot.cache.get_static_data("epic_items_t2")

            if not epic_items:
                logging.debug("[LootWishlist] No epic items in cache for autocomplete")
                return []

            if not user_input:
                suggestions = [
                    item.get("item_name_en", "")
                    for item in epic_items[:50]
                    if item.get("item_name_en")
                ]
                suggestions.sort()
                return suggestions[:25]

            logging.debug(f"[LootWishlist] Autocomplete search for: '{user_input}'")

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
            logging.debug(
                f"[LootWishlist] Autocomplete found {len(result)} matches for '{user_input}'"
            )

            return result

        except Exception as e:
            logging.error(f"[LootWishlist] Autocomplete error: {e}")
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
            logging.error(f"[LootWishlist] Remove autocomplete error: {e}")
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
        WHERE guild_id = ? AND user_id = ? 
        ORDER BY priority DESC, created_at ASC
        """

        try:
            results = await db.run_db_query(query, (guild_id, user_id), fetch_all=True)
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
            logging.error(f"[LootWishlist] Error getting user wishlist: {e}")
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
        SELECT w.item_name, w.item_id, COUNT(*) as demand_count,
               GROUP_CONCAT(DISTINCT w.user_id ORDER BY w.priority DESC, w.created_at ASC) as user_ids,
               AVG(w.priority) as avg_priority,
               e.item_icon_url
        FROM loot_wishlist w
        LEFT JOIN epic_items_t2 e ON w.item_id = e.item_id
        WHERE w.guild_id = ? 
        GROUP BY w.item_name, w.item_id, e.item_icon_url
        ORDER BY demand_count DESC, avg_priority DESC 
        LIMIT 10
        """

        try:
            results = await db.run_db_query(query, (guild_id,), fetch_all=True)
            if results:
                return [
                    {
                        "item_name": row[0],
                        "item_id": row[1],
                        "demand_count": row[2],
                        "user_ids": [int(uid) for uid in row[3].split(",")],
                        "avg_priority": float(row[4]),
                        "item_icon_url": row[5] or "",
                    }
                    for row in results
                ]
            return []
        except Exception as e:
            logging.error(f"[LootWishlist] Error getting wishlist stats: {e}")
            return []

    async def is_valid_epic_item(self, item_name: str) -> Tuple[bool, Optional[str]]:
        """
        Check if item exists in Epic T2 database and return item_id.
        Uses the same smart matching logic as autocomplete.

        Args:
            item_name: The name of the item to validate

        Returns:
            Tuple of (is_valid, item_id) where is_valid is True if item exists,
            and item_id is the database ID of the item or None if not found
        """
        try:
            epic_items = await self.bot.cache.get_static_data("epic_items_t2")

            if epic_items:
                logging.debug(f"[LootWishlist] Cache has {len(epic_items)} epic items")
                user_input_lower = item_name.lower().strip()

                best_score = 0
                best_item = None

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

                    for item_lang_name in item_names:
                        if not item_lang_name:
                            continue

                        item_name_lower = item_lang_name.lower()
                        score = 0

                        if item_name_lower == user_input_lower:
                            score = 100
                        elif item_name_lower.startswith(user_input_lower):
                            score = 90
                        elif any(
                            word.startswith(user_input_lower)
                            for word in item_name_lower.split()
                        ):
                            score = 80
                        elif user_input_lower in item_name_lower:
                            score = 60

                        if score > best_score:
                            best_score = score
                            best_item = item

                if best_item and best_item.get("item_id"):
                    logging.debug(
                        f"[LootWishlist] Found match: {item_name} -> {best_item.get('item_id')} (score: {best_score})"
                    )
                    return True, best_item.get("item_id")

                logging.debug(
                    f"[LootWishlist] No match found in cache for: {item_name}"
                )
                return False, None

            query = """
            SELECT item_id, item_name_en FROM epic_items_t2 
            WHERE LOWER(item_name_en) = LOWER(?) 
               OR LOWER(item_name_fr) = LOWER(?) 
               OR LOWER(item_name_es) = LOWER(?) 
               OR LOWER(item_name_de) = LOWER(?)
               OR LOWER(item_name_en) LIKE LOWER(?)
               OR LOWER(item_name_fr) LIKE LOWER(?)
               OR LOWER(item_name_es) LIKE LOWER(?)
               OR LOWER(item_name_de) LIKE LOWER(?)
            LIMIT 1
            """

            like_pattern = f"%{item_name}%"
            result = await db.run_db_query(
                query,
                (
                    item_name,
                    item_name,
                    item_name,
                    item_name,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                ),
                fetch_one=True,
            )
            if result:
                return True, result[0]
            return False, None

        except Exception as e:
            logging.error(f"[LootWishlist] Error validating Epic item: {e}")
            return False, None

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
                logging.debug(
                    f"[LootWishlist] Skipping loot update for PTB guild {guild_id}"
                )
                return False

            await self.bot.cache_loader.ensure_guild_channels_loaded()
            loot_data = await self.bot.cache.get_guild_data(guild_id, "loot_message")

            if not loot_data:
                logging.debug(
                    f"[LootWishlist] No loot message data found for guild {guild_id}"
                )
                return False

            channel_id = loot_data.get("channel")
            message_id = loot_data.get("message")

            if not channel_id or not message_id:
                logging.warning(
                    f"[LootWishlist] Invalid loot message data for guild {guild_id}"
                )
                return False

            channel = self.bot.get_channel(channel_id)
            if not channel:
                logging.error(f"[LootWishlist] Loot channel {channel_id} not found")
                return False

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                logging.error(f"[LootWishlist] Loot message {message_id} not found")
                return False

            stats = await self.get_wishlist_stats(guild_id)

            await self.bot.cache_loader.ensure_guild_settings_loaded()
            guild_lang = (
                await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
            )

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
                main_embed.add_field(
                    name="📋 Liste actuelle", value=empty_msg, inline=False
                )
                main_embed.set_footer(text=footer_text)
                await message.edit(embeds=[main_embed])
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

                    item_embed = discord.Embed(
                        title=f"{priority_emoji} #{i} - {item_data['item_name']}",
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
                                    user_names.append(member.display_name)
                                    continue

                            user = self.bot.get_user(user_id)
                            if user:
                                user_names.append(user.display_name)
                            else:
                                user_names.append(f"User-{user_id}")
                        except:
                            user_names.append(f"User-{user_id}")

                    members_list = "\n".join(f"• {name}" for name in user_names)
                    if len(item_data["user_ids"]) > 10:
                        members_list += (
                            f"\n*... et {len(item_data['user_ids']) - 10} autres*"
                        )

                    members_formatted = await get_guild_message(
                        self.bot,
                        guild_id,
                        LOOT_WISHLIST_DATA,
                        "messages.members_list_format",
                        members_list=members_list or "Aucun membre",
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
                    item_embed.set_footer(
                        text=f"{rank_emoji} Position {i}/{len(stats)}"
                    )

                    item_embeds.append(item_embed)

                if len(stats) > 15:
                    info_embed = discord.Embed(
                        title="ℹ️ Information",
                        description=f"Seuls les **15 premiers objets** sont affichés.\nIl y a **{len(stats) - 15}** autres objets dans la liste complète.",
                        color=discord.Color.greyple(),
                    )
                    item_embeds.append(info_embed)

                if len(item_embeds) <= 10:
                    await message.edit(embeds=item_embeds)
                else:
                    final_embeds = item_embeds[:9]
                    info_embed = discord.Embed(
                        title="ℹ️ Information",
                        description=f"Affichage limité aux **8 premiers objets** pour éviter le spam.\nUtilisez `/wishlist_admin` pour voir la liste complète.",
                        color=discord.Color.greyple(),
                    )
                    final_embeds.append(info_embed)
                    await message.edit(embeds=final_embeds)

            logging.info(
                f"[LootWishlist] Updated wishlist message for guild {guild_id}"
            )
            return True

        except Exception as e:
            logging.error(f"[LootWishlist] Error updating wishlist message: {e}")
            return False

    @discord_resilient(service_name="discord_api", max_retries=3)
    async def wishlist_add(
        self,
        ctx: discord.ApplicationContext,
        item_name: str = discord.Option(
            description="Name of the Epic T2 item you want to add",
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
            item_name: Name of the Epic T2 item to add (with autocomplete)
            priority: Priority level as string ("1"=Low, "2"=Medium, "3"=High)

        Raises:
            Various exceptions related to database operations or Discord API calls
        """
        await ctx.defer(ephemeral=True)

        guild_id = ctx.guild.id
        user_id = ctx.author.id

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
            if len(current_items) >= 3:
                message = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.wishlist_full"
                )
                await ctx.followup.send(message, ephemeral=True)
                return

            for item in current_items:
                if item["item_name"].lower() == item_name.lower():
                    message = await get_user_message(
                        ctx,
                        LOOT_WISHLIST_DATA,
                        "messages.item_already_exists",
                        item_name=item_name,
                    )
                    await ctx.followup.send(message, ephemeral=True)
                    return

            insert_query = """
            INSERT INTO loot_wishlist (guild_id, user_id, item_name, item_id, priority)
            VALUES (?, ?, ?, ?, ?)
            """

            priority_int = int(priority)
            try:
                await db.run_db_query(
                    insert_query,
                    (guild_id, user_id, item_name, item_id, priority_int),
                    commit=True,
                )

                priority_key = {
                    "1": "priority_low",
                    "2": "priority_medium",
                    "3": "priority_high",
                }[priority]
                priority_text = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, f"messages.{priority_key}"
                )
                message = await get_user_message(
                    ctx,
                    LOOT_WISHLIST_DATA,
                    "messages.item_added",
                    item_name=item_name,
                    priority=priority_text,
                    count=len(current_items) + 1,
                )
                await ctx.followup.send(message, ephemeral=True)

                asyncio.create_task(self.update_wishlist_message(guild_id))

            except Exception as db_error:
                logging.error(f"[LootWishlist] Database error adding item: {db_error}")
                message = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.database_error_add"
                )
                await ctx.followup.send(message, ephemeral=True)

        except Exception as e:
            logging.error(f"[LootWishlist] Error adding item to wishlist: {e}")
            message = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.general_error",
                action="adding the item",
            )
            await ctx.followup.send(message, ephemeral=True)

    @discord_resilient(service_name="discord_api", max_retries=3)
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

        try:
            current_items = await self.get_user_wishlist(guild_id, user_id)
            item_found = False

            for item in current_items:
                if item["item_name"].lower() == item_name.lower():
                    item_found = True
                    break

            if not item_found:
                message = await get_user_message(
                    ctx,
                    LOOT_WISHLIST_DATA,
                    "messages.item_not_in_wishlist",
                    item_name=item_name,
                )
                await ctx.followup.send(message, ephemeral=True)
                return

            delete_query = """
            DELETE FROM loot_wishlist 
            WHERE guild_id = ? AND user_id = ? AND LOWER(item_name) = LOWER(?)
            """

            try:
                await db.run_db_query(
                    delete_query, (guild_id, user_id, item_name), commit=True
                )

                message = await get_user_message(
                    ctx,
                    LOOT_WISHLIST_DATA,
                    "messages.item_removed",
                    item_name=item_name,
                    count=len(current_items) - 1,
                )
                await ctx.followup.send(message, ephemeral=True)

                asyncio.create_task(self.update_wishlist_message(guild_id))

            except Exception as db_error:
                logging.error(
                    f"[LootWishlist] Database error removing item: {db_error}"
                )
                message = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.database_error_remove"
                )
                await ctx.followup.send(message, ephemeral=True)

        except Exception as e:
            logging.error(f"[LootWishlist] Error removing item from wishlist: {e}")
            message = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.general_error",
                action="removing the item",
            )
            await ctx.followup.send(message, ephemeral=True)

    @discord_resilient(service_name="discord_api", max_retries=3)
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
            logging.error(f"[LootWishlist] Error listing user wishlist: {e}")
            message = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.general_error",
                action="retrieving your wishlist",
            )
            await ctx.followup.send(message, ephemeral=True)

    @discord_resilient(service_name="discord_api", max_retries=3)
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
            SELECT user_id, item_name, priority, created_at
            FROM loot_wishlist 
            WHERE guild_id = ?
            ORDER BY user_id, priority DESC, created_at ASC
            """

            results = await db.run_db_query(query, (guild_id,), fetch_all=True)

            if not results:
                message = await get_user_message(
                    ctx, LOOT_WISHLIST_DATA, "messages.admin_no_wishlists"
                )
                await ctx.followup.send(message)
                return

            user_wishlists = {}
            for row in results:
                user_id, item_name, priority, created_at = row
                if user_id not in user_wishlists:
                    user_wishlists[user_id] = []
                user_wishlists[user_id].append(
                    {
                        "item_name": item_name,
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

                stats_text = (
                    f"🔴 Haute priorité: **{priority_counts.get(3, 0)}** objets\n"
                )
                stats_text += (
                    f"🟡 Priorité moyenne: **{priority_counts.get(2, 0)}** objets\n"
                )
                stats_text += (
                    f"🔵 Faible priorité: **{priority_counts.get(1, 0)}** objets"
                )

                stats_embed.add_field(
                    name="📈 Répartition des priorités", value=stats_text, inline=True
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

                    item_embed = discord.Embed(
                        title=f"{priority_emoji} #{i} - {item_data['item_name']}",
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
                            for item in user_wishlists[user_id]:
                                if item["item_name"] == item_data["item_name"]:
                                    user_priority = item["priority"]
                                    break

                        try:
                            member = ctx.guild.get_member(user_id)
                            if member:
                                name = member.display_name
                            else:
                                user = self.bot.get_user(user_id)
                                name = user.display_name if user else f"User-{user_id}"
                        except:
                            name = f"User-{user_id}"

                        if user_priority:
                            p_emoji = priority_emojis.get(user_priority, "⚪")
                            members_details.append(f"{p_emoji} {name}")
                        else:
                            members_details.append(f"⚪ {name}")

                    if len(members_details) <= 10:
                        members_list = "\n".join(members_details)
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
                    else:
                        half = len(members_details) // 2
                        members_part1 = await get_user_message(
                            ctx,
                            LOOT_WISHLIST_DATA,
                            "messages.members_list_format",
                            members_list="\n".join(members_details[:half]),
                        )
                        members_part2 = await get_user_message(
                            ctx,
                            LOOT_WISHLIST_DATA,
                            "messages.members_list_format",
                            members_list="\n".join(members_details[half:]),
                        )
                        members_part1_title = await get_user_message(
                            ctx,
                            LOOT_WISHLIST_DATA,
                            "messages.members_part1_field_title",
                        )
                        members_part2_title = await get_user_message(
                            ctx,
                            LOOT_WISHLIST_DATA,
                            "messages.members_part2_field_title",
                        )
                        item_embed.add_field(
                            name=members_part1_title, value=members_part1, inline=True
                        )
                        item_embed.add_field(
                            name=members_part2_title, value=members_part2, inline=True
                        )

                    item_embeds.append(item_embed)

                if item_embeds:
                    for i in range(0, len(item_embeds), 10):
                        await ctx.channel.send(embeds=item_embeds[i : i + 10])

            members_embed = discord.Embed(
                title="👥 Membres avec liste de souhaits",
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
                        name = member.display_name
                    else:
                        user = self.bot.get_user(user_id)
                        name = user.display_name if user else f"User-{user_id}"
                except:
                    name = f"User-{user_id}"

                priority_emojis = {1: "🔵", 2: "🟡", 3: "🔴"}
                items_emojis = [
                    priority_emojis.get(item["priority"], "⚪") for item in items
                ]

                members_text += (
                    f"**{name}** ({len(items)} objets): {' '.join(items_emojis)}\n"
                )

            if len(sorted_users) > 20:
                members_text += f"\n*... et {len(sorted_users) - 20} autres membres*"

            members_embed.add_field(
                name="Liste des membres",
                value=members_text or "Aucun membre",
                inline=False,
            )

            await ctx.channel.send(embed=members_embed)

        except Exception as e:
            logging.error(f"[LootWishlist] Error getting admin wishlist data: {e}")
            message = await get_user_message(
                ctx,
                LOOT_WISHLIST_DATA,
                "messages.general_error",
                action="retrieving wishlist data",
            )
            await ctx.followup.send(message, ephemeral=True)

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
                "DELETE FROM loot_wishlist WHERE guild_id = ? AND user_id = ?"
            )
            await db.run_db_query(delete_query, (guild_id, user_id), commit=True)

            cache_key = f"wishlist_stats_{guild_id}"
            if hasattr(self.bot, "cache") and hasattr(self.bot.cache, "invalidate"):
                await self.bot.cache.invalidate(cache_key)

            logging.info(
                f"[LootWishlist] Cleaned up wishlist for departed member {user_id} from guild {guild_id}"
            )

        except Exception as e:
            logging.error(
                f"[LootWishlist] Error cleaning up wishlist for member {user_id}: {e}"
            )


def setup(bot: discord.Bot) -> None:
    """
    Setup function for the cog.

    Args:
        bot: The Discord bot instance to add the cog to
    """
    bot.add_cog(LootWishlist(bot))
