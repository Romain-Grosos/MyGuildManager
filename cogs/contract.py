"""
Contract Manager Cog - Manages guild contract selection and publishing system.
"""

import discord
import logging
import asyncio
from datetime import datetime
from discord.ext import commands
from translation import translations
from typing import Optional, Dict, Any

CONTRACT_DATA = translations.get("contract", {})

async def get_guild_event_channel(bot, guild_id):
    """Get event channel ID for a guild from cache."""
    channels_data = await bot.cache.get_guild_data(guild_id, 'channels')
    return channels_data.get('events_channel') if channels_data else None


async def save_contract_message(bot, guild_id, message_id):
    """Save contract message ID to database."""
    query = "INSERT INTO contracts (guild_id, message_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE message_id = %s"
    try:
        await bot.run_db_query(query, (guild_id, message_id, message_id), commit=True)
    except Exception as e:
        logging.error(f"[ContractManager] Error saving contract message for guild {guild_id}: {e}", exc_info=True)
        raise

async def load_contract_message(bot, guild_id):
    """Load contract message ID from database."""
    query = "SELECT message_id FROM contracts WHERE guild_id = %s"
    try:
        result = await bot.run_db_query(query, (guild_id,), fetch_one=True)
    except Exception as e:
        logging.error(f"[ContractManager] Error loading contract message for guild {guild_id}: {e}", exc_info=True)
        return None
    return result[0] if result else None

async def delete_contract_message(bot, guild_id):
    """Delete contract message record from database."""
    query = "DELETE FROM contracts WHERE guild_id = %s"
    try:
        await bot.run_db_query(query, (guild_id,), commit=True)
    except Exception as e:
        logging.error(f"[ContractManager] Error deleting contract message for guild {guild_id}: {e}", exc_info=True)
        raise

class ContractSelect(discord.ui.View):
    """Interactive view for contract selection with dropdowns and validation."""
    
    def __init__(self, bot, author, guild_lang):
        """Initialize contract selection view."""
        super().__init__(timeout=1800)
        self.bot = bot
        self.author = author
        self.guild_lang = guild_lang
        self.selected_contracts = {
            "monster_elimination": [],
            "dynamic_events": None,
            "open_dungeon": None
        }
        contracts_data = CONTRACT_DATA.get("options", {})

        options_monster = []
        for option in contracts_data.get("monster_elimination", []):
            for key, value in option.items():
                localized_label = value.get(self.guild_lang, value.get("en-US", key))
                options_monster.append(discord.SelectOption(label=localized_label, value=key))
        if options_monster:
            placeholder_monster = CONTRACT_DATA.get("events", {})\
                .get("placeholders", {})\
                .get("monster_elimination", {})\
                .get(self.guild_lang, "Choose up to 2 monster types...")
            select_monster = discord.ui.Select(
                placeholder=placeholder_monster,
                options=options_monster,
                custom_id="monster_elimination",
                min_values=1,
                max_values=2
            )
            async def monster_callback(interaction: discord.Interaction):
                """Handle monster callback."""
                if not self._validate_author_interaction(interaction):
                    error_msg = CONTRACT_DATA.get("events", {})\
                        .get("errors", {})\
                        .get("not_author", {})\
                        .get(self.guild_lang, "You did not initiate this command.")
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return
                selected = interaction.data.get("values", [])
                if "all" in selected and len(selected) > 1:
                    error_invalid = CONTRACT_DATA.get("events", {})\
                        .get("errors", {})\
                        .get("invalid_selection_all", {})\
                        .get(self.guild_lang, "If you select 'All', you cannot choose other options!")
                    await interaction.response.send_message(error_invalid, ephemeral=True)
                    return
                self.selected_contracts["monster_elimination"] = selected
                await interaction.response.defer()
            select_monster.callback = monster_callback
            self.add_item(select_monster)
        else:
            logging.error("[ContractManager] No options found for 'monster_elimination' in translations.")

        options_dynamic = []
        for option in contracts_data.get("dynamic_events", []):
            for key, value in option.items():
                localized_label = value.get(self.guild_lang, value.get("en-US", key))
                options_dynamic.append(discord.SelectOption(label=localized_label, value=key))
        if options_dynamic:
            placeholder_dynamic = CONTRACT_DATA.get("events", {})\
                .get("placeholders", {})\
                .get("dynamic_events", {})\
                .get(self.guild_lang, "Choose a dynamic event...")
            select_dynamic = discord.ui.Select(
                placeholder=placeholder_dynamic,
                options=options_dynamic,
                custom_id="dynamic_events"
            )
            async def dynamic_callback(interaction: discord.Interaction):
                """Handle dynamic callback."""
                if not self._validate_author_interaction(interaction):
                    error_msg = CONTRACT_DATA.get("events", {})\
                        .get("errors", {})\
                        .get("not_author", {})\
                        .get(self.guild_lang, "You did not initiate this command.")
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return
                selected = interaction.data.get("values", [])
                if selected:
                    self.selected_contracts["dynamic_events"] = selected[0]
                await interaction.response.defer()
            select_dynamic.callback = dynamic_callback
            self.add_item(select_dynamic)
        else:
            logging.error("[ContractManager] No options found for 'dynamic_events' in translations.")

        options_dungeon = []
        for option in contracts_data.get("open_dungeon", []):
            for key, value in option.items():
                localized_label = value.get(self.guild_lang, value.get("en-US", key))
                options_dungeon.append(discord.SelectOption(label=localized_label, value=key))
        if options_dungeon:
            placeholder_dungeon = CONTRACT_DATA.get("events", {})\
                .get("placeholders", {})\
                .get("open_dungeon", {})\
                .get(self.guild_lang, "Choose an open dungeon...")
            select_dungeon = discord.ui.Select(
                placeholder=placeholder_dungeon,
                options=options_dungeon,
                custom_id="open_dungeon"
            )
            async def dungeon_callback(interaction: discord.Interaction):
                """Handle dungeon callback."""
                if not self._validate_author_interaction(interaction):
                    error_msg = CONTRACT_DATA.get("events", {})\
                        .get("errors", {})\
                        .get("not_author", {})\
                        .get(self.guild_lang, "You did not initiate this command.")
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return
                selected = interaction.data.get("values", [])
                if selected:
                    self.selected_contracts["open_dungeon"] = selected[0]
                await interaction.response.defer()
            select_dungeon.callback = dungeon_callback
            self.add_item(select_dungeon)
        else:
            logging.error("[ContractManager] No options found for 'open_dungeon' in translations.")

        self.validate_button = discord.ui.Button(label="OK", style=discord.ButtonStyle.success)
        async def validate_callback(interaction: discord.Interaction):
            """Handle validate callback."""
            if not self._validate_author_interaction(interaction):
                error_msg = CONTRACT_DATA.get("events", {})\
                    .get("errors", {})\
                    .get("not_author", {})\
                    .get(self.guild_lang, "You did not initiate this command.")
                await interaction.response.send_message(error_msg, ephemeral=True)
                return
            if (self.selected_contracts["dynamic_events"] is None or
                self.selected_contracts["open_dungeon"] is None or
                not self.selected_contracts["monster_elimination"]):
                error_required = CONTRACT_DATA.get("events", {})\
                    .get("errors", {})\
                    .get("all_options_required", {})\
                    .get(self.guild_lang, "All selections must be made before validation.")
                await interaction.response.send_message(error_required, ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            await self.post_event_message(interaction)
            success_msg = CONTRACT_DATA.get("user_messages", {})\
                .get("notifications", {})\
                .get("contract_published", {})\
                .get(self.guild_lang, "Guild contract published successfully.")
            await interaction.followup.send(success_msg, ephemeral=True)
            try:
                await interaction.message.delete()
            except Exception as e:
                logging.error(f"[ContractManager] Error deleting interactive message: {e}", exc_info=True)
        self.validate_button.callback = validate_callback
        self.add_item(self.validate_button)

    async def _get_channel_safe(self, channel_id: int) -> Optional[discord.TextChannel]:
        """Safely get channel with caching and error handling."""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                logging.error(f"[ContractManager] Error fetching channel {channel_id}: {e}")
                return None
        return channel
    
    def _validate_author_interaction(self, interaction: discord.Interaction) -> bool:
        """Validate that interaction comes from original command author."""
        if interaction.user != self.author:
            error_msg = CONTRACT_DATA.get("events", {})\
                .get("errors", {})\
                .get("not_author", {})\
                .get(self.guild_lang, "You did not initiate this command.")
            return False
        return True
    
    async def post_event_message(self, interaction: discord.Interaction):
        """Post the contract message to the guild's event channel."""
        guild = interaction.guild
        guild_id = guild.id
        channel_id = await get_guild_event_channel(self.bot, guild_id)
        if not channel_id:
            error_channel = CONTRACT_DATA.get("events", {})\
                .get("errors", {})\
                .get("no_channel", {})\
                .get(self.guild_lang, "No event channel configured for this guild.")
            await interaction.followup.send(error_channel, ephemeral=True)
            return
        channel = await self._get_channel_safe(channel_id)
        if not channel:
            error_msg = CONTRACT_DATA.get("events", {}).get("errors", {}).get("channel_not_found", {}).get(self.guild_lang, "Event channel not found.")
            await interaction.followup.send(error_msg, ephemeral=True)
            return

        contracts_data = CONTRACT_DATA.get("options", {})
        today_date = datetime.now().strftime("%d/%m/%Y")
        description = f"📆 {today_date}\n\n"
        for category_key, selection in self.selected_contracts.items():
            category_name = CONTRACT_DATA.get("categories", {})\
                .get(category_key, {})\
                .get(self.guild_lang, category_key)
            if isinstance(selection, list):
                labels = []
                for opt_key in selection:
                    for option in contracts_data.get(category_key, []):
                        if opt_key in option:
                            localized_label = option[opt_key].get(self.guild_lang, option[opt_key].get("en-US", opt_key))
                            labels.append(localized_label)
                            break
                description += f"### **{category_name}**\n" + ", ".join(labels) + "\n\n"
            else:
                localized_label = ""
                for option in contracts_data.get(category_key, []):
                    if selection in option:
                        localized_label = option[selection].get(self.guild_lang, option[selection].get("en-US", selection))
                        break
                description += f"### **{category_name}**\n{localized_label}\n\n"
        published_by_template = CONTRACT_DATA.get("published_by", {}).get(self.guild_lang, "Published by")
        description += f"\n*{published_by_template} {self.author.display_name}*"
        title = CONTRACT_DATA.get("title", {}).get(self.guild_lang, "Guild Contracts")
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        try:
            event_message = await channel.send(embed=embed)
            try:
                await save_contract_message(self.bot, guild_id, event_message.id)
                logging.debug(f"[ContractManager] Contract message saved for guild {guild_id} with message ID {event_message.id}.")
            except Exception as db_error:
                try:
                    await event_message.delete()
                except:
                    pass
                raise db_error
        except Exception as e:
            logging.error(f"[ContractManager] Failed to post or save contract message for guild {guild_id}: {e}", exc_info=True)
            error_msg = CONTRACT_DATA.get("events", {}).get("errors", {}).get("post_failed", {}).get(self.guild_lang, "Failed to publish contract.")
            await interaction.followup.send(error_msg, ephemeral=True)
            return

        success_msg = CONTRACT_DATA.get("user_messages", {})\
            .get("notifications", {})\
            .get("contract_published", {})\
            .get(self.guild_lang, "Guild contract published successfully.")
        logging.info(success_msg)

class Contract(commands.Cog):
    """Cog for managing guild contract selection and publishing."""
    
    def __init__(self, bot):
        """Initialize the Contract cog."""
        self.bot = bot
    
    def _validate_author(self, interaction: discord.Interaction, original_author: discord.Member) -> bool:
        """Validate interaction author matches original command author."""
        return interaction.user.id == original_author.id
    
    async def _get_channel_safe(self, channel_id: int) -> Optional[discord.TextChannel]:
        """Safely get channel with optimized fetching."""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                logging.error(f"[ContractManager] Error fetching channel {channel_id}: {e}")
                return None
        return channel
    
    async def _get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Get guild settings from centralized cache."""
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        
        channels_data = await self.bot.cache.get_guild_data(guild_id, 'channels')
        events_channel = channels_data.get('events_channel') if channels_data else None
        guild_lang = await self.bot.cache.get_guild_data(guild_id, 'guild_lang')
        
        return {
            'events_channel': events_channel,
            'guild_lang': guild_lang or 'en-US'
        }

    @discord.slash_command(
        name=CONTRACT_DATA.get("command", {}).get("name", {}).get("en-US", "contract"),
        description=CONTRACT_DATA.get("command", {}).get("description", {}).get("en-US", "Select and publish guild contracts."),
        name_localizations=CONTRACT_DATA.get("command", {}).get("name", {}),
        description_localizations=CONTRACT_DATA.get("command", {}).get("description", {})
    )
    @commands.has_permissions(manage_messages=True)
    async def contract(self, ctx: discord.ApplicationContext):
        """Command to create and publish guild contracts."""
        if not ctx.guild:
            await ctx.respond("This command can only be used in a guild.", ephemeral=True)
            return
            
        settings = await self._get_guild_settings(ctx.guild.id)
        guild_lang = settings['guild_lang']
        contracts_options = CONTRACT_DATA.get("options", {})
        if not contracts_options:
            error_loading = CONTRACT_DATA.get("user_messages", {})\
                .get("command_usage", {})\
                .get("select_contract", {})\
                .get(guild_lang, "Unable to load contract options. Please check translations.")
            await ctx.respond(error_loading, ephemeral=True)
            return
        command_name = CONTRACT_DATA.get("command", {})\
            .get("name", {})\
            .get(guild_lang, "Contract")
        command_name = command_name[0].upper() + command_name[1:]
        usage_msg = CONTRACT_DATA.get("user_messages", {})\
            .get("command_usage", {})\
            .get("select_contract", {})\
            .get(guild_lang, "Please select a contract for each category. Click ✅ to validate the announcement.")
        embed = discord.Embed(
            title=command_name,
            description=usage_msg,
            color=discord.Color.blue()
        )
        view = ContractSelect(self.bot, ctx.author, guild_lang)
        await ctx.respond(embed=embed, view=view, delete_after=600)

    @discord.slash_command(
        name=CONTRACT_DATA.get("command_delete", {}).get("name", {}).get("en-US", "contract_delete"),
        description=CONTRACT_DATA.get("command_delete", {}).get("description", {}).get("en-US", "Delete the guild contract."),
        name_localizations=CONTRACT_DATA.get("command_delete", {}).get("name", {}),
        description_localizations=CONTRACT_DATA.get("command_delete", {}).get("description", {})
    )
    @commands.has_permissions(manage_messages=True)
    async def contract_delete(self, ctx: discord.ApplicationContext):
        """Command to delete existing guild contracts."""
        try:
            await ctx.defer(ephemeral=True)
            if not ctx.guild:
                await ctx.followup.send("This command can only be used in a guild.", ephemeral=True)
                return
            
            guild_id = ctx.guild.id
            settings = await self._get_guild_settings(guild_id)
            guild_lang = settings['guild_lang']
            channel_id = settings['events_channel']
            if not channel_id:
                error_channel = CONTRACT_DATA.get("events", {})\
                    .get("errors", {})\
                    .get("no_channel", {})\
                    .get(guild_lang, "No event channel configured for this guild.")
                await ctx.followup.send(error_channel, ephemeral=True)
                return
            channel = await self._get_channel_safe(channel_id)
            if not channel:
                error_msg = CONTRACT_DATA.get("events", {}).get("errors", {}).get("channel_not_found", {}).get(guild_lang, "Event channel not found.")
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
                        logging.error(f"[ContractManager] DB cleanup failed after message deletion: {db_error}")
                    
                    success_deleted = CONTRACT_DATA.get("user_messages", {})\
                        .get("notifications", {})\
                        .get("contract_deleted", {})\
                        .get(guild_lang, "Guild contract deleted successfully.")
                    logging.info(f"[ContractManager] : {success_deleted}")
                    await ctx.followup.send(success_deleted)
                except discord.NotFound:
                    try:
                        await delete_contract_message(self.bot, guild_id)
                    except:
                        pass
                    logging.warning("[ContractManager] Contract already deleted.")
                    already_deleted_msg = CONTRACT_DATA.get("user_messages", {})\
                        .get("notifications", {})\
                        .get("contract_already_deleted", {})\
                        .get(guild_lang, "Contract already deleted.")
                    await ctx.followup.send(already_deleted_msg, ephemeral=True)
            else:
                no_contract_msg = CONTRACT_DATA.get("user_messages", {})\
                    .get("notifications", {})\
                    .get("no_contract_to_delete", {})\
                    .get(guild_lang, "No contract to delete.")
                await ctx.followup.send(no_contract_msg, ephemeral=True)
        except Exception as e:
            logging.error(f"[ContractManager] Error in /contract_delete command: {e}", exc_info=True)
            try:
                settings = await self._get_guild_settings(ctx.guild.id)
                guild_lang = settings['guild_lang']
            except:
                guild_lang = "en-US"
            
            error_msg = CONTRACT_DATA.get("user_messages", {})\
                .get("notifications", {})\
                .get("delete_error", {})\
                .get(guild_lang, "An error occurred while deleting the contract.")
            await ctx.followup.send(error_msg, ephemeral=True)

    async def contract_delete_cron(self):
        """Automated task to clean up old contracts across all guilds."""
        failed_guilds = []
        processed = 0
        
        for guild in self.bot.guilds:
            try:
                guild_id = guild.id
                settings = await self._get_guild_settings(guild_id)
                channel_id = settings.get('events_channel')
                
                if not channel_id:
                    logging.debug(f"[ContractManager] No event channel configured for guild {guild_id}")
                    continue

                channel = await self._get_channel_safe(channel_id)
                if not channel:
                    logging.warning(f"[ContractManager] Event channel {channel_id} not accessible for guild {guild_id}")
                    continue

                message_id = await load_contract_message(self.bot, guild_id)
                if message_id:
                    try:
                        message = await channel.fetch_message(message_id)
                        await message.delete()
                        try:
                            await delete_contract_message(self.bot, guild_id)
                        except Exception as db_error:
                            logging.error(f"[ContractManager] DB cleanup failed for guild {guild_id}: {db_error}")
                        logging.info(f"[ContractManager] Contract deleted for guild {guild_id}")
                        processed += 1
                    except discord.NotFound:
                        try:
                            await delete_contract_message(self.bot, guild_id)
                        except:
                            pass
                        logging.debug(f"[ContractManager] Contract already deleted for guild {guild_id}")

                if processed % 10 == 0:
                    await asyncio.sleep(1)
      
            except Exception as e:
                failed_guilds.append(guild_id)
                logging.error(f"[ContractManager] Error processing guild {guild_id} in cron: {e}", exc_info=True)
                continue

        if failed_guilds:
            logging.warning(f"[ContractManager] Cron failed for {len(failed_guilds)} guilds: {failed_guilds}")

        logging.info(f"[ContractManager] Cron completed: {processed} contracts processed, {len(failed_guilds)} failures")

def setup(bot: discord.Bot):
    """Setup function to add the Contract cog to the bot."""
    bot.add_cog(Contract(bot))
