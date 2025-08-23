"""
Contract Manager Cog - Enterprise-grade guild contract selection and publishing system.

This cog provides comprehensive contract management with:

Features:
    - Interactive contract selection with validation
    - Automated contract publishing and cleanup
    - Multi-language support with fallback handling
    - Robust error handling with user feedback
    - Database persistence for contract tracking

Enterprise Patterns:
    - Discord API resilience with retry logic
    - Cache-aware operations with safety guards
    - Centralized permission error handling
    - Structured logging with ComponentLogger
    - Full localization support via JSON translation system
    - Resource cleanup and memory management
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import discord
from discord.ext import commands

from app.core.logger import ComponentLogger
from app.core.reliability import discord_resilient
from app.core.translation import translations as global_translations

_logger = ComponentLogger("contract")
STAFF_TOOLS = global_translations.get("staff_tools", {})
REQUIRED_CATEGORIES = ("monster_elimination", "dynamic_events", "open_dungeon")

async def get_guild_event_channel(bot, guild_id):
    """
    Get event channel ID for a guild from cache with error handling.

    Args:
        bot: Discord bot instance
        guild_id: Discord guild ID

    Returns:
        Event channel ID or None if not found
    """
    try:
        if not hasattr(bot, "cache") or bot.cache is None:
            _logger.debug("no_cache_attached")
            return None
        channels_data = await bot.cache.get_guild_data(guild_id, "channels")
        return channels_data.get("events_channel") if channels_data else None
    except Exception as e:
        _logger.error(
            "error_getting_guild_event_channel",
            guild_id=guild_id,
            error=str(e),
            exc_info=True
        )
        return None

async def save_contract_message(bot, guild_id, message_id):
    """
    Save contract message ID to database with enterprise error handling.

    Args:
        bot: Discord bot instance
        guild_id: Discord guild ID
        message_id: Discord message ID to save

    Raises:
        Exception: If database operation fails
    """
    query = "INSERT INTO contracts (guild_id, message_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE message_id = %s"
    try:
        await bot.run_db_query(query, (guild_id, message_id, message_id), commit=True)
        _logger.debug(
            "contract_message_saved",
            guild_id=guild_id,
            message_id=message_id
        )
    except Exception as e:
        _logger.error(
            "error_saving_contract_message",
            guild_id=guild_id,
            message_id=message_id,
            error=str(e),
            exc_info=True
        )
        raise

async def load_contract_message(bot, guild_id):
    """
    Load contract message ID from database with enterprise error handling.

    Args:
        bot: Discord bot instance
        guild_id: Discord guild ID

    Returns:
        Message ID or None if not found
    """
    query = "SELECT message_id FROM contracts WHERE guild_id = %s"
    try:
        result = await bot.run_db_query(query, (guild_id,), fetch_one=True)
        message_id = result[0] if result else None
        _logger.debug(
            "contract_message_loaded",
            guild_id=guild_id,
            message_id=message_id,
            found=message_id is not None
        )
        return message_id
    except Exception as e:
        _logger.error(
            "error_loading_contract_message",
            guild_id=guild_id,
            error=str(e),
            exc_info=True
        )
        return None

async def delete_contract_message(bot, guild_id):
    """
    Delete contract message record from database with enterprise error handling.

    Args:
        bot: Discord bot instance
        guild_id: Discord guild ID

    Raises:
        Exception: If database operation fails
    """
    query = "DELETE FROM contracts WHERE guild_id = %s"
    try:
        await bot.run_db_query(query, (guild_id,), commit=True)
        _logger.debug(
            "contract_message_deleted",
            guild_id=guild_id
        )
    except Exception as e:
        _logger.error(
            "error_deleting_contract_message",
            guild_id=guild_id,
            error=str(e),
            exc_info=True
        )
        raise

@discord_resilient(service_name="discord_api", max_retries=2)
async def get_channel_safe(bot, channel_id: int) -> Optional[discord.TextChannel]:
    """
    Safely get channel with enterprise error handling and retry logic.

    Args:
        bot: Discord bot instance
        channel_id: Discord channel ID

    Returns:
        Discord TextChannel or None if not found
    """
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound:
            _logger.warning(
                "channel_not_found",
                channel_id=channel_id
            )
            return None
        except discord.Forbidden:
            _logger.warning(
                "channel_access_forbidden",
                channel_id=channel_id
            )
            return None
        except Exception as e:
            _logger.error(
                "error_fetching_channel",
                channel_id=channel_id,
                error=str(e),
                exc_info=True
            )
            return None
    return channel

class ContractSelect(discord.ui.View):
    """Enterprise-grade interactive view for contract selection with validation and error handling."""

    def __init__(self, bot, author, guild_lang):
        """
        Initialize contract selection view with enterprise patterns.

        Args:
            bot: Discord bot instance
            author: Discord user who initiated the view
            guild_lang: Guild language for translations
        """
        super().__init__(timeout=600)
        self.bot = bot
        self.author = author
        self.guild_lang = guild_lang
        self._validated = False
        self.message_ref = None
        self.selected_contracts = {
            REQUIRED_CATEGORIES[0]: [],
            REQUIRED_CATEGORIES[1]: None,
            REQUIRED_CATEGORIES[2]: None,
        }
        contracts_data = STAFF_TOOLS.get("contract_data", {}).get("options", {})

        options_monster = []
        for option in contracts_data.get("monster_elimination", []):
            for key, value in option.items():
                localized_label = value.get(self.guild_lang, value.get("en-US", key))
                options_monster.append(
                    discord.SelectOption(label=localized_label, value=key)
                )
        if options_monster:
            placeholder_monster = (
                STAFF_TOOLS.get("contract_data", {})
                .get("events", {})
                .get("placeholders", {})
                .get("monster_elimination", {})
                .get(self.guild_lang, "Choose up to 2 monster types...")
            )
            select_monster = discord.ui.Select(
                placeholder=placeholder_monster,
                options=options_monster,
                custom_id="monster_elimination",
                min_values=1,
                max_values=2,
            )

            async def monster_callback(interaction: discord.Interaction):
                """Handle monster callback."""
                if not self._validate_author_interaction(interaction):
                    error_msg = (
                        STAFF_TOOLS.get("contract_data", {})
                        .get("events", {})
                        .get("errors", {})
                        .get("not_author", {})
                        .get(self.guild_lang, "You did not initiate this command.")
                    )
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return
                selected = interaction.data.get("values", [])
                if "all" in selected and len(selected) > 1:
                    error_invalid = (
                        STAFF_TOOLS.get("contract_data", {})
                        .get("events", {})
                        .get("errors", {})
                        .get("invalid_selection_all", {})
                        .get(
                            self.guild_lang,
                            "If you select 'All', you cannot choose other options!",
                        )
                    )
                    await interaction.response.send_message(
                        error_invalid, ephemeral=True
                    )
                    return
                self.selected_contracts["monster_elimination"] = selected
                await interaction.response.defer()

            select_monster.callback = monster_callback
            self.add_item(select_monster)
        else:
            _logger.error(
                "no_monster_elimination_options",
                guild_lang=self.guild_lang
            )

        options_dynamic = []
        for option in contracts_data.get("dynamic_events", []):
            for key, value in option.items():
                localized_label = value.get(self.guild_lang, value.get("en-US", key))
                options_dynamic.append(
                    discord.SelectOption(label=localized_label, value=key)
                )
        if options_dynamic:
            placeholder_dynamic = (
                STAFF_TOOLS.get("contract_data", {})
                .get("events", {})
                .get("placeholders", {})
                .get("dynamic_events", {})
                .get(self.guild_lang, "Choose a dynamic event...")
            )
            select_dynamic = discord.ui.Select(
                placeholder=placeholder_dynamic,
                options=options_dynamic,
                custom_id="dynamic_events",
            )

            async def dynamic_callback(interaction: discord.Interaction):
                """Handle dynamic callback."""
                if not self._validate_author_interaction(interaction):
                    error_msg = (
                        STAFF_TOOLS.get("contract_data", {})
                        .get("events", {})
                        .get("errors", {})
                        .get("not_author", {})
                        .get(self.guild_lang, "You did not initiate this command.")
                    )
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return
                selected = interaction.data.get("values", [])
                if selected:
                    self.selected_contracts["dynamic_events"] = selected[0]
                await interaction.response.defer()

            select_dynamic.callback = dynamic_callback
            self.add_item(select_dynamic)
        else:
            _logger.error(
                "no_dynamic_events_options",
                guild_lang=self.guild_lang
            )

        options_dungeon = []
        for option in contracts_data.get("open_dungeon", []):
            for key, value in option.items():
                localized_label = value.get(self.guild_lang, value.get("en-US", key))
                options_dungeon.append(
                    discord.SelectOption(label=localized_label, value=key)
                )
        if options_dungeon:
            placeholder_dungeon = (
                STAFF_TOOLS.get("contract_data", {})
                .get("events", {})
                .get("placeholders", {})
                .get("open_dungeon", {})
                .get(self.guild_lang, "Choose an open dungeon...")
            )
            select_dungeon = discord.ui.Select(
                placeholder=placeholder_dungeon,
                options=options_dungeon,
                custom_id="open_dungeon",
            )

            async def dungeon_callback(interaction: discord.Interaction):
                """Handle dungeon selection callback."""
                if not self._validate_author_interaction(interaction):
                    error_msg = (
                        STAFF_TOOLS.get("contract_data", {})
                        .get("events", {})
                        .get("errors", {})
                        .get("not_author", {})
                        .get(self.guild_lang, "You did not initiate this command.")
                    )
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return
                selected = interaction.data.get("values", [])
                if selected:
                    self.selected_contracts["open_dungeon"] = selected[0]
                await interaction.response.defer()

            select_dungeon.callback = dungeon_callback
            self.add_item(select_dungeon)
        else:
            _logger.error(
                "no_open_dungeon_options",
                guild_lang=self.guild_lang
            )

        validate_label = (
            STAFF_TOOLS.get("contract_data", {})
            .get("events", {})
            .get("validate_label", {})
            .get(self.guild_lang, "Validate")
        )
        self.validate_button = discord.ui.Button(
            label=validate_label, style=discord.ButtonStyle.success, emoji="✅"
        )

        async def validate_callback(interaction: discord.Interaction):
            """Handle validate callback."""
            if not self._validate_author_interaction(interaction):
                error_msg = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("events", {})
                    .get("errors", {})
                    .get("not_author", {})
                    .get(self.guild_lang, "You did not initiate this command.")
                )
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

            if self._validated:
                already_processing = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("events", {})
                    .get("errors", {})
                    .get("already_processing", {})
                    .get(self.guild_lang, "This action is already being processed.")
                )
                await interaction.response.send_message(already_processing, ephemeral=True)
                return
            if (
                self.selected_contracts["dynamic_events"] is None
                or self.selected_contracts["open_dungeon"] is None
                or not self.selected_contracts["monster_elimination"]
            ):
                error_required = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("events", {})
                    .get("errors", {})
                    .get("all_options_required", {})
                    .get(
                        self.guild_lang,
                        "All selections must be made before validation.",
                    )
                )
                await interaction.response.send_message(error_required, ephemeral=True)
                return

            self._validated = True
            for child in self.children:
                child.disabled = True

            try:
                await interaction.message.edit(view=self)
            except Exception as e:
                _logger.debug(
                    "failed_to_disable_buttons",
                    error=str(e)
                )
            
            await interaction.response.defer(ephemeral=True)
            await self.post_event_message(interaction)
            success_msg = (
                STAFF_TOOLS.get("contract_data", {})
                .get("user_messages", {})
                .get("notifications", {})
                .get("contract_published", {})
                .get(self.guild_lang, "Guild contract published successfully.")
            )
            await interaction.followup.send(success_msg, ephemeral=True)
            try:
                await interaction.message.delete()
            except Exception as e:
                _logger.error(
                    "error_deleting_interactive_message",
                    guild_id=getattr(interaction.guild, 'id', None),
                    error=str(e),
                    exc_info=True
                )

        self.validate_button.callback = validate_callback
        self.add_item(self.validate_button)
    
    async def on_timeout(self):
        """
        Called when the view times out. Disables all buttons and updates the message.
        """
        try:
            for child in self.children:
                child.disabled = True
            if self.message_ref:
                await self.message_ref.edit(view=self)
                _logger.debug(
                    "view_timeout_buttons_disabled",
                    guild_id=getattr(self.message_ref.guild, 'id', None)
                )
        except Exception as e:
            _logger.debug(
                "view_timeout_edit_failed",
                error=str(e)
            )

    def _validate_author_interaction(self, interaction: discord.Interaction) -> bool:
        """
        Validate that interaction comes from original command author using ID comparison.

        Args:
            interaction: Discord interaction to validate

        Returns:
            True if interaction is from original author, False otherwise
        """
        return int(interaction.user.id) == int(self.author.id)

    async def post_event_message(self, interaction: discord.Interaction):
        """
        Post the contract message to the guild's event channel.

        Args:
            interaction: Discord interaction context
        """
        guild = interaction.guild
        guild_id = guild.id
        channel_id = await get_guild_event_channel(self.bot, guild_id)
        if not channel_id:
            error_channel = (
                STAFF_TOOLS.get("contract_data", {})
                .get("events", {})
                .get("errors", {})
                .get("no_channel", {})
                .get(self.guild_lang, "No event channel configured for this guild.")
            )
            await interaction.followup.send(error_channel, ephemeral=True)
            return
        channel = await get_channel_safe(self.bot, channel_id)
        if not channel:
            error_msg = (
                STAFF_TOOLS.get("contract_data", {})
                .get("events", {})
                .get("errors", {})
                .get("channel_not_found", {})
                .get(self.guild_lang, "Event channel not found.")
            )
            await interaction.followup.send(error_msg, ephemeral=True)
            return

        perms = channel.permissions_for(channel.guild.me)
        if not perms.send_messages or not perms.embed_links:
            _logger.warning(
                "insufficient_permissions_for_contract",
                guild_id=guild_id,
                channel_id=channel.id,
                can_send=perms.send_messages,
                can_embed=perms.embed_links
            )
            error_msg = (
                STAFF_TOOLS.get("contract_data", {})
                .get("events", {})
                .get("errors", {})
                .get("post_failed", {})
                .get(self.guild_lang, "Failed to publish contract.")
            )
            await interaction.followup.send(error_msg, ephemeral=True)
            return

        contracts_data = STAFF_TOOLS.get("contract_data", {}).get("options", {})
        epoch = int(datetime.now(timezone.utc).timestamp())
        description = f"📆 <t:{epoch}:D>\n\n"
        for category_key, selection in self.selected_contracts.items():
            category_name = (
                STAFF_TOOLS.get("contract_data", {})
                .get("categories", {})
                .get(category_key, {})
                .get(self.guild_lang, category_key)
            )
            if isinstance(selection, list):
                labels = []
                for opt_key in selection:
                    found = False
                    for option in contracts_data.get(category_key, []):
                        if opt_key in option:
                            localized_label = option[opt_key].get(
                                self.guild_lang, option[opt_key].get("en-US", opt_key)
                            )
                            labels.append(localized_label)
                            found = True
                            break
                    if not found:
                        _logger.warning(
                            "unknown_contract_option",
                            category=category_key,
                            option_key=opt_key,
                            guild_id=guild_id
                        )
                        unknown_template = (
                            STAFF_TOOLS.get("contract_data", {})
                            .get("events", {})
                            .get("errors", {})
                            .get("unknown_option", {})
                            .get(self.guild_lang, "Unknown option ({option})")
                        )
                        labels.append(unknown_template.format(option=opt_key))
                description += f"### **{category_name}**\n" + ", ".join(labels) + "\n\n"
            else:
                localized_label = None
                for option in contracts_data.get(category_key, []):
                    if selection in option:
                        localized_label = option[selection].get(
                            self.guild_lang, option[selection].get("en-US", selection)
                        )
                        break
                if not localized_label:
                    _logger.warning(
                        "unknown_contract_option",
                        category=category_key,
                        option_key=selection,
                        guild_id=guild_id
                    )
                    unknown_template = (
                        STAFF_TOOLS.get("contract_data", {})
                        .get("events", {})
                        .get("errors", {})
                        .get("unknown_option", {})
                        .get(self.guild_lang, "Unknown option ({option})")
                    )
                    localized_label = unknown_template.format(option=selection)
                description += f"### **{category_name}**\n{localized_label}\n\n"
        published_by_template = (
            STAFF_TOOLS.get("contract_data", {})
            .get("published_by", {})
            .get(self.guild_lang, "Published by")
        )
        description += f"\n*{published_by_template} {self.author.display_name}*"
        title = (
            STAFF_TOOLS.get("contract_data", {})
            .get("title", {})
            .get(self.guild_lang, "Guild Contracts")
        )
        embed = discord.Embed(
            title=title, description=description, color=discord.Color.green()
        )

        contract_cog = self.bot.get_cog("Contract")
        if not contract_cog:
            _logger.error("contract_cog_not_found_for_lock")
            error_msg = (
                STAFF_TOOLS.get("contract_data", {})
                .get("events", {})
                .get("errors", {})
                .get("post_failed", {})
                .get(self.guild_lang, "Failed to publish contract.")
            )
            await interaction.followup.send(error_msg, ephemeral=True)
            return
        
        lock = contract_cog._guild_lock(guild_id)
        async with lock:
            _logger.debug(
                "acquired_guild_lock",
                guild_id=guild_id
            )

            old_message_id = await load_contract_message(self.bot, guild_id)
            if old_message_id:
                try:
                    old_message = await channel.fetch_message(old_message_id)
                    await old_message.delete()
                    _logger.debug(
                        "old_contract_deleted",
                        guild_id=guild_id,
                        old_message_id=old_message_id
                    )
                except (discord.NotFound, discord.Forbidden) as e:
                    _logger.debug(
                        "old_contract_delete_failed",
                        guild_id=guild_id,
                        old_message_id=old_message_id,
                        error=str(e)
                    )

            try:
                for attempt in range(2):
                    try:
                        event_message = await channel.send(embed=embed)
                        break
                    except discord.HTTPException as e:
                        if e.status >= 500 and attempt == 0:
                            await asyncio.sleep(1.5)
                            continue
                        raise
            
                try:
                    await save_contract_message(self.bot, guild_id, event_message.id)
                    _logger.debug(
                        "contract_message_posted_and_saved",
                        guild_id=guild_id,
                        message_id=event_message.id
                    )
                except Exception as db_error:
                    try:
                        await event_message.delete()
                    except:
                        pass
                    raise db_error
            except discord.Forbidden:
                _logger.warning(
                    "forbidden_posting_contract",
                    guild_id=guild_id,
                    channel_id=channel.id
                )
                error_msg = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("events", {})
                    .get("errors", {})
                    .get("post_failed", {})
                    .get(self.guild_lang, "Failed to publish contract.")
                )
                await interaction.followup.send(error_msg, ephemeral=True)
                return
            except Exception as e:
                _logger.error(
                    "error_posting_contract_message",
                    guild_id=guild_id,
                    channel_id=getattr(channel, 'id', None),
                    error=str(e),
                    exc_info=True
                )
                error_msg = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("events", {})
                    .get("errors", {})
                    .get("post_failed", {})
                    .get(self.guild_lang, "Failed to publish contract.")
                )
                await interaction.followup.send(error_msg, ephemeral=True)
                return

        _logger.debug(
            "released_guild_lock",
            guild_id=guild_id
        )
        
        success_msg = (
            STAFF_TOOLS.get("contract_data", {})
            .get("user_messages", {})
            .get("notifications", {})
            .get("contract_published", {})
            .get(self.guild_lang, "Guild contract published successfully.")
        )
        _logger.info(
            "contract_published_successfully",
            guild_id=guild_id,
            author=self.author.display_name
        )

class Contract(commands.Cog):
    """Enterprise-grade cog for managing guild contract selection and publishing."""

    def __init__(self, bot):
        """
        Initialize the Contract cog with enterprise patterns.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self._locks = {}
        self._register_staff_commands()
        _logger.debug("contract_cog_initialized")

    def _guild_lock(self, guild_id: int):
        """
        Get or create an async lock for the specified guild.
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            asyncio.Lock for the guild
        """
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]
    
    def _register_staff_commands(self):
        """Register contract commands with the centralized staff group."""
        if hasattr(self.bot, "staff_group"):
            self.bot.staff_group.command(
                name=STAFF_TOOLS.get("contract", {})
                .get("name", {})
                .get("en-US", "contract_add"),
                description=STAFF_TOOLS.get("contract", {})
                .get("description", {})
                .get("en-US", "Select and publish guild contracts."),
                name_localizations=STAFF_TOOLS.get("contract", {}).get("name", {}),
                description_localizations=STAFF_TOOLS.get("contract", {}).get(
                    "description", {}
                ),
            )(self.contract)

            self.bot.staff_group.command(
                name=STAFF_TOOLS.get("contract_delete", {})
                .get("name", {})
                .get("en-US", "contract_delete"),
                description=STAFF_TOOLS.get("contract_delete", {})
                .get("description", {})
                .get("en-US", "Delete the guild contract."),
                name_localizations=STAFF_TOOLS.get("contract_delete", {}).get(
                    "name", {}
                ),
                description_localizations=STAFF_TOOLS.get("contract_delete", {}).get(
                    "description", {}
                ),
            )(self.contract_delete)

    def _validate_author(
        self, interaction: discord.Interaction, original_author: discord.Member
    ) -> bool:
        """
        Validate interaction author matches original command author.

        Args:
            interaction: Discord interaction to validate
            original_author: Original command author

        Returns:
            True if authors match, False otherwise
        """
        return interaction.user.id == original_author.id

    async def _get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """
        Get guild settings from centralized cache with error handling.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dictionary with events_channel and guild_lang
        """
        try:
            if not hasattr(self.bot, "cache") or self.bot.cache is None:
                _logger.debug(
                    "no_cache_attached_for_guild_settings",
                    guild_id=guild_id
                )
                return {"events_channel": None, "guild_lang": "en-US"}
            
            channels_data = await self.bot.cache.get_guild_data(guild_id, "channels")
            events_channel = channels_data.get("events_channel") if channels_data else None
            guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang")

            return {"events_channel": events_channel, "guild_lang": guild_lang or "en-US"}
        except Exception as e:
            _logger.error(
                "error_getting_guild_settings",
                guild_id=guild_id,
                error=str(e),
                exc_info=True
            )
            return {"events_channel": None, "guild_lang": "en-US"}

    async def contract(self, ctx: discord.ApplicationContext):
        """
        Command to create and publish guild contracts.

        Args:
            ctx: Discord application context
        """
        if not ctx.guild:
            await ctx.respond(
                "This command can only be used in a guild.", ephemeral=True
            )
            return

        settings = await self._get_guild_settings(ctx.guild.id)
        guild_lang = settings["guild_lang"]
        contracts_options = STAFF_TOOLS.get("contract_data", {}).get("options", {})

        missing_categories = [k for k in REQUIRED_CATEGORIES if not contracts_options.get(k)]
        
        if not contracts_options or missing_categories:
            _logger.error(
                "missing_contract_categories",
                guild_id=ctx.guild.id,
                missing=missing_categories if missing_categories else "all"
            )
            error_loading = (
                STAFF_TOOLS.get("contract_data", {})
                .get("user_messages", {})
                .get("command_usage", {})
                .get("select_contract", {})
                .get(
                    guild_lang,
                    "Unable to load contract options. Please check translations.",
                )
            )
            await ctx.respond(error_loading, ephemeral=True)
            return
        command_name = (
            STAFF_TOOLS.get("contract_data", {})
            .get("command", {})
            .get("name", {})
            .get(guild_lang, "Contract")
        )
        command_name = command_name[0].upper() + command_name[1:]
        usage_msg = (
            STAFF_TOOLS.get("contract_data", {})
            .get("user_messages", {})
            .get("command_usage", {})
            .get("select_contract", {})
            .get(
                guild_lang,
                "Please select a contract for each category. Click ✅ to validate the announcement.",
            )
        )
        embed = discord.Embed(
            title=command_name, description=usage_msg, color=discord.Color.blue()
        )
        view = ContractSelect(self.bot, ctx.author, guild_lang)
        response = await ctx.respond(embed=embed, view=view, delete_after=600)

        try:
            if isinstance(response, discord.Message):
                view.message_ref = response
            else:
                view.message_ref = await ctx.interaction.original_response()
            
            _logger.debug(
                "message_ref_set_for_view",
                guild_id=ctx.guild.id,
                message_type=type(view.message_ref).__name__
            )
        except Exception as e:
            _logger.debug(
                "failed_to_set_message_ref",
                error=str(e)
            )

    async def contract_delete(self, ctx: discord.ApplicationContext):
        """
        Command to delete existing guild contracts.

        Args:
            ctx: Discord application context
        """
        try:
            await ctx.defer(ephemeral=True)
            if not ctx.guild:
                await ctx.followup.send(
                    "This command can only be used in a guild.", ephemeral=True
                )
                return

            guild_id = ctx.guild.id
            settings = await self._get_guild_settings(guild_id)
            guild_lang = settings["guild_lang"]
            channel_id = settings["events_channel"]
            if not channel_id:
                error_channel = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("events", {})
                    .get("errors", {})
                    .get("no_channel", {})
                    .get(guild_lang, "No event channel configured for this guild.")
                )
                await ctx.followup.send(error_channel, ephemeral=True)
                return
            channel = await get_channel_safe(self.bot, channel_id)
            if not channel:
                error_msg = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("events", {})
                    .get("errors", {})
                    .get("channel_not_found", {})
                    .get(guild_lang, "Event channel not found.")
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return
            message_id = await load_contract_message(self.bot, guild_id)
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                    try:
                        await delete_contract_message(self.bot, guild_id)
                    except Exception as db_error:
                        _logger.error(
                            "db_cleanup_failed_after_deletion",
                            guild_id=guild_id,
                            error=str(db_error),
                            exc_info=True
                        )

                    success_deleted = (
                        STAFF_TOOLS.get("contract_data", {})
                        .get("user_messages", {})
                        .get("notifications", {})
                        .get("contract_deleted", {})
                        .get(guild_lang, "Guild contract deleted successfully.")
                    )
                    _logger.info(
                        "contract_deleted_successfully",
                        guild_id=guild_id,
                        message_id=message_id
                    )
                    await ctx.followup.send(success_deleted, ephemeral=True)
                except discord.NotFound:
                    try:
                        await delete_contract_message(self.bot, guild_id)
                    except:
                        pass
                    _logger.warning(
                        "contract_already_deleted",
                        guild_id=guild_id,
                        message_id=message_id
                    )
                    already_deleted_msg = (
                        STAFF_TOOLS.get("contract_data", {})
                        .get("user_messages", {})
                        .get("notifications", {})
                        .get("contract_already_deleted", {})
                        .get(guild_lang, "Contract already deleted.")
                    )
                    await ctx.followup.send(already_deleted_msg, ephemeral=True)
            else:
                no_contract_msg = (
                    STAFF_TOOLS.get("contract_data", {})
                    .get("user_messages", {})
                    .get("notifications", {})
                    .get("no_contract_to_delete", {})
                    .get(guild_lang, "No contract to delete.")
                )
                await ctx.followup.send(no_contract_msg, ephemeral=True)
        except Exception as e:
            _logger.error(
                "error_in_contract_delete_command",
                guild_id=getattr(ctx.guild, 'id', None),
                error=str(e),
                exc_info=True
            )
            try:
                settings = await self._get_guild_settings(ctx.guild.id)
                guild_lang = settings["guild_lang"]
            except:
                guild_lang = "en-US"

            error_msg = (
                STAFF_TOOLS.get("contract_data", {})
                .get("user_messages", {})
                .get("notifications", {})
                .get("delete_error", {})
                .get(guild_lang, "An error occurred while deleting the contract.")
            )
            await ctx.followup.send(error_msg, ephemeral=True)

    async def contract_delete_cron(self):
        """
        Automated task to clean up old contracts across all guilds.

        Returns:
            None
        """
        failed_guilds = []
        processed = 0

        for guild in self.bot.guilds:
            try:
                guild_id = guild.id
                settings = await self._get_guild_settings(guild_id)
                channel_id = settings.get("events_channel")

                if not channel_id:
                    _logger.debug(
                        "no_event_channel_configured_cron",
                        guild_id=guild_id
                    )
                    continue

                channel = await get_channel_safe(self.bot, channel_id)
                if not channel:
                    _logger.warning(
                        "event_channel_not_accessible_cron",
                        guild_id=guild_id,
                        channel_id=channel_id
                    )
                    continue

                message_id = await load_contract_message(self.bot, guild_id)
                if message_id:
                    try:
                        message = await channel.fetch_message(message_id)
                        await message.delete()
                        try:
                            await delete_contract_message(self.bot, guild_id)
                        except Exception as db_error:
                            _logger.error(
                                "db_cleanup_failed_cron",
                                guild_id=guild_id,
                                error=str(db_error),
                                exc_info=True
                            )
                        _logger.info(
                            "contract_deleted_cron",
                            guild_id=guild_id
                        )
                        processed += 1
                    except discord.NotFound:
                        try:
                            await delete_contract_message(self.bot, guild_id)
                        except:
                            pass
                        _logger.debug(
                            "contract_already_deleted_cron",
                            guild_id=guild_id
                        )

                if processed % 10 == 0:
                    await asyncio.sleep(1)

            except Exception as e:
                failed_guilds.append(guild_id)
                _logger.error(
                    "error_processing_guild_cron",
                    guild_id=guild_id,
                    error=str(e),
                    exc_info=True
                )
                continue

        if failed_guilds:
            _logger.warning(
                "cron_failed_guilds",
                failed_count=len(failed_guilds),
                failed_guilds=failed_guilds
            )

        _logger.info(
            "cron_completed",
            processed_count=processed,
            failed_count=len(failed_guilds)
        )
    
    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        Clean up guild-specific locks when bot leaves a guild.
        
        Args:
            guild: Discord guild the bot is leaving
        """
        if guild.id in self._locks:
            self._locks.pop(guild.id, None)
            _logger.debug(
                "guild_lock_released_on_leave",
                guild_id=guild.id,
                guild_name=guild.name
            )

def setup(bot: discord.Bot):
    """
    Setup function to add the Contract cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(Contract(bot))
