import discord
import logging
import asyncio
from datetime import datetime
from discord.ext import commands
from translation import translations

CONTRACT_DATA = translations.get("contract", {})

async def get_guild_event_channel(bot, guild_id):
    query = "SELECT events_channel FROM guild_channels WHERE guild_id = ?"
    result = await bot.run_db_query(query, (guild_id,), fetch_one=True)
    return result[0] if result else None

async def get_guild_language(bot, guild_id):
    query = "SELECT guild_lang FROM guild_settings WHERE guild_id = ?"
    result = await bot.run_db_query(query, (guild_id,), fetch_one=True)
    return result[0] if result else "en-US"

async def save_contract_message(bot, guild_id, message_id):
    query = "INSERT INTO contracts (guild_id, message_id) VALUES (?, ?) ON DUPLICATE KEY UPDATE message_id = ?"
    await bot.run_db_query(query, (guild_id, message_id, message_id), commit=True)

async def load_contract_message(bot, guild_id):
    query = "SELECT message_id FROM contracts WHERE guild_id = ?"
    result = await bot.run_db_query(query, (guild_id,), fetch_one=True)
    return result[0] if result else None

async def delete_contract_message(bot, guild_id):
    query = "DELETE FROM contracts WHERE guild_id = ?"
    await bot.run_db_query(query, (guild_id,), commit=True)

# Vue interactive pour la sélection des contrats
class ContractSelect(discord.ui.View):
    def __init__(self, bot, author, guild_lang):
        super().__init__(timeout=600)
        self.bot = bot
        self.author = author
        self.guild_lang = guild_lang
        self.selected_contracts = {
            "monster_elimination": [],
            "dynamic_events": None,
            "open_dungeon": None
        }
        # Récupérer les options depuis CONTRACT_DATA
        contracts_data = CONTRACT_DATA.get("options", {})

        # --- Élimination de Monstres ---
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
                if interaction.user != self.author:
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
            logging.error("[ContractManager] ❌ No options found for 'monster_elimination' in translations.json.")

        # --- Évènements Dynamiques ---
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
                if interaction.user != self.author:
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
            logging.error("[ContractManager] ❌ No options found for 'dynamic_events' in translations.json.")

        # --- Donjon Ouvert ---
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
                if interaction.user != self.author:
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
            logging.error("[ContractManager] ❌ No options found for 'open_dungeon' in translations.json.")

        # --- Bouton de validation ---
        self.validate_button = discord.ui.Button(label="✅ OK", style=discord.ButtonStyle.success)
        async def validate_callback(interaction: discord.Interaction):
            if interaction.user != self.author:
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
            # Différer la réponse pour gagner du temps
            await interaction.response.defer(ephemeral=True)
            await self.post_event_message(interaction)
            success_msg = CONTRACT_DATA.get("user_messages", {})\
                .get("notifications", {})\
                .get("contract_published", {})\
                .get(self.guild_lang, "Guild contract published successfully.")
            await interaction.followup.send(success_msg, ephemeral=True)
            # Supprimer le message interactif
            try:
                await interaction.message.delete()
            except Exception as e:
                logging.error(f"[ContractManager] Erreur lors de la suppression du message interactif : {e}")
                
        self.validate_button.callback = validate_callback
        self.add_item(self.validate_button)

    async def post_event_message(self, interaction: discord.Interaction):
        guild = interaction.guild
        guild_id = guild.id
        channel_id = await get_guild_event_channel(self.bot, guild_id)
        if not channel_id:
            error_channel = CONTRACT_DATA.get("events", {})\
                .get("errors", {})\
                .get("no_channel", {})\
                .get(self.guild_lang, "No event channel configured for this guild.")
            await interaction.response.send_message(error_channel, ephemeral=True)
            return
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

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
        description += f"\n*Publié par {self.author.display_name}*"
        title = CONTRACT_DATA.get("title", {}).get(self.guild_lang, "Guild Contracts")
        embed = discord.Embed(title=title, description=description, color=discord.Color.green())
        event_message = await channel.send(embed=embed)

        try:
            await save_contract_message(self.bot, guild_id, event_message.id)
            logging.debug(f"Contract message saved for guild {guild_id} with message ID {event_message.id}.")
        except Exception as e:
            logging.debug(f"Failed to save contract message for guild {guild_id}: {e}")

        success_msg = CONTRACT_DATA.get("user_messages", {})\
            .get("notifications", {})\
            .get("contract_published", {})\
            .get(self.guild_lang, "Guild contract published successfully.")
        logging.info(success_msg)

# Cog Contract avec commandes slash localisées
class Contract(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name=CONTRACT_DATA.get("command", {}).get("name", {}).get("en-US", "contrat"),
        description=CONTRACT_DATA.get("command", {}).get("description", {}).get("en-US", "Select and publish guild contracts."),
        name_localizations=CONTRACT_DATA.get("command", {}).get("name", {}),
        description_localizations=CONTRACT_DATA.get("command", {}).get("description", {})
    )
    async def contrat(self, ctx: discord.ApplicationContext):
        guild_lang = await get_guild_language(self.bot, ctx.guild.id)
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
            .get(guild_lang, "Contrat")
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
    async def contrat_delete(self, ctx: discord.ApplicationContext):
        try:
            await ctx.defer(ephemeral=True)
            if not ctx.guild:
                await ctx.followup.send("Cette commande ne peut être utilisée que dans une guilde.", ephemeral=True)
                return
            guild_id = ctx.guild.id
            guild_lang = await get_guild_language(self.bot, guild_id)
            channel_id = await get_guild_event_channel(self.bot, guild_id)
            if not channel_id:
                error_channel = CONTRACT_DATA.get("events", {})\
                    .get("errors", {})\
                    .get("no_channel", {})\
                    .get(guild_lang, "No event channel configured for this guild.")
                await ctx.followup.send(error_channel, ephemeral=True)
                return
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            message_id = await load_contract_message(self.bot, guild_id)
            if message_id:
                try:
                    message = await channel.fetch_message(message_id)
                    await message.delete()
                    await delete_contract_message(self.bot, guild_id)
                    success_deleted = CONTRACT_DATA.get("user_messages", {})\
                        .get("notifications", {})\
                        .get("contract_deleted", {})\
                        .get(guild_lang, "Guild contract deleted successfully.")
                    logging.info(success_deleted)
                    await ctx.followup.send(success_deleted)
                except discord.NotFound:
                    logging.warning("⚠️ Contract already deleted.")
                    await ctx.followup.send("⚠️ Contract already deleted.", ephemeral=True)
            else:
                await ctx.followup.send("❌ No contract to delete.", ephemeral=True)
        except Exception as e:
            logging.error(f"[ContractManager] Erreur dans la commande /contrat_delete : {e}")
            await ctx.followup.send("Une erreur est survenue lors de la suppression du contrat.", ephemeral=True)

    async def contrat_delete_cron(self):
        for guild in self.bot.guilds:
            guild_id = guild.id
            channel_id = await get_guild_event_channel(self.bot, guild_id)
            if channel_id:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                message_id = await load_contract_message(self.bot, guild_id)
                if message_id:
                    try:
                        message = await channel.fetch_message(message_id)
                        await message.delete()
                        await delete_contract_message(self.bot, guild_id)
                        logging.info(f"Guild contract deleted for guild {guild_id}.")
                    except discord.NotFound:
                        logging.warning(f"Contract already deleted for guild {guild_id}.")
            else:
                logging.info(f"No event channel configured for guild {guild_id}.")

def setup(bot: discord.Bot):
    bot.add_cog(Contract(bot))
