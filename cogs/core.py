import discord
from discord.ext import commands
import logging
from functions import get_user_message
from translation import translations as global_translations
import asyncio

APP_INITIALIZE_DATA = global_translations.get("commands", {}).get("app_initialize", {})
APP_MODIFICATION_DATA = global_translations.get("commands", {}).get("app_modify", {})
APP_RESET_DATA = global_translations.get("commands", {}).get("app_reset", {})

class Core(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        if not hasattr(bot, "synced"):
            bot.synced = False

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.bot.synced:
            try:
                await self.bot.sync_commands()
                self.bot.synced = True
                logging.info("[CoreManager] ✅ Slash commands synced successfully.")
            except Exception as e:
                logging.error(f"[CoreManager] ❌ Failed to sync slash commands: {e}")
        logging.info(f"[CoreManager] 🚀 Bot is connected as {self.bot.user}")

    @commands.Cog.listener()
    async def on_app_command_error(self, ctx: discord.ApplicationContext, error: Exception):
        response = get_user_message(ctx, self.bot.translations, "global_error", error=error)
        try:
            if ctx.response.is_done():
                await ctx.followup.send(response, ephemeral=True)
            else:
                await ctx.respond(response, ephemeral=True)
        except Exception as e:
            logging.error("[CoreManager] ❌ Failed to send global error message.", exc_info=e)
        logging.error(f"[CoreManager] ❌ Global error in command: {error}")

    @discord.slash_command(
        name=APP_INITIALIZE_DATA["name"]["en-US"],
        description=APP_INITIALIZE_DATA["description"]["en-US"],
        name_localizations=APP_INITIALIZE_DATA["name"],
        description_localizations=APP_INITIALIZE_DATA["description"]
    )
    @commands.has_permissions(administrator=True)
    async def app_initialize(
        self,
        ctx: discord.ApplicationContext,
        guild_name: str = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_name"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_name"]["description"]
        ),
        guild_lang: str = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_lang"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_lang"]["description"],
            choices=["en-US", "fr", "es-ES", "de", "it"]
        ),
        guild_game: int = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_game"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_game"]["description"],
            choices=[
                discord.OptionChoice(choice_name, choice_value)
                for choice_name, choice_value in APP_INITIALIZE_DATA["options"]["guild_game"]["choices"].items()
            ]
        ),
        guild_server: str = discord.Option(
            description=APP_INITIALIZE_DATA["options"]["guild_server"]["description"]["en-US"],
            description_localizations=APP_INITIALIZE_DATA["options"]["guild_server"]["description"]
        )
    ):
        guild_id = ctx.guild.id
        guild_game_int = int(guild_game)
        
        try:
            query = "SELECT COUNT(*) FROM guild_settings WHERE guild_id = ?"
            result = await self.bot.run_db_query(query, (guild_id,), fetch_one=True)
            count = result[0] if result else 0
            if count > 0:
                logging.info(f"[CoreManager] Guild {guild_id} already exists in the database.")
                response = get_user_message(ctx, self.bot.translations, "commands.app_initialize.messages.already_declared")
            else:
                insert_query = """
                    INSERT INTO guild_settings 
                    (guild_id, guild_name, guild_lang, guild_game, guild_server, initialized, premium)
                    VALUES (?, ?, ?, ?, ?, TRUE, 0)
                """
                await self.bot.run_db_query(insert_query, (guild_id, guild_name, guild_lang, guild_game_int, guild_server), commit=True)
                logging.info(f"[CoreManager] Guild {guild_id} successfully initialized in the database.")

                rename_templates = APP_INITIALIZE_DATA.get("rename_templates", {})
                template = rename_templates.get(guild_lang, rename_templates.get("en-US"))
                new_nickname = template.format(guild_name=guild_name)
                await ctx.guild.me.edit(nick=new_nickname)

                response = get_user_message(ctx, self.bot.translations, "commands.app_initialize.messages.success")
        except Exception as e:
            logging.error("[CoreManager] ❌ Error during guild initialization: %s", e)
            response = get_user_message(ctx, self.bot.translations, "commands.app_initialize.messages.error", error=e)
        await ctx.respond(response, ephemeral=True)

    @discord.slash_command(
        name=APP_MODIFICATION_DATA["name"]["en-US"],
        description=APP_MODIFICATION_DATA["description"]["en-US"],
        name_localizations=APP_MODIFICATION_DATA["name"],
        description_localizations=APP_MODIFICATION_DATA["description"]
    )
    @commands.has_permissions(administrator=True)
    async def app_modify(
        self,
        ctx: discord.ApplicationContext,
        guild_name: str = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_name"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_name"]["description"]
        ),
        guild_lang: str = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_lang"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_lang"]["description"],
            choices=["en-US", "fr", "es-ES", "de", "it"]
        ),
        guild_game: int = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_game"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_game"]["description"],
            choices=[
                discord.OptionChoice(choice_name, choice_value)
                for choice_name, choice_value in APP_MODIFICATION_DATA["options"]["guild_game"]["choices"].items()
            ]
        ),
        guild_server: str = discord.Option(
            default=None,
            description=APP_MODIFICATION_DATA["options"]["guild_server"]["description"]["en-US"],
            description_localizations=APP_MODIFICATION_DATA["options"]["guild_server"]["description"]
        )
    ):
        guild_id = ctx.guild.id
        query = "SELECT guild_name, guild_lang, guild_game, guild_server FROM guild_settings WHERE guild_id = ?"
        result = await self.bot.run_db_query(query, (guild_id,), fetch_one=True)
        if not result:
            response = get_user_message(ctx, self.bot.translations, "commands.app_modify.messages.need_init")
            return await ctx.respond(response, ephemeral=True)

        current_guild_name, current_guild_lang, current_guild_game, current_guild_server = result
        new_guild_name = guild_name if guild_name is not None else current_guild_name
        new_guild_lang = guild_lang if guild_lang is not None else current_guild_lang
        new_guild_game = int(guild_game) if guild_game is not None else current_guild_game
        new_guild_server = guild_server if guild_server is not None else current_guild_server

        try:
            update_query = """
                UPDATE guild_settings
                SET guild_name = ?, guild_lang = ?, guild_game = ?, guild_server = ?
                WHERE guild_id = ?
            """
            await self.bot.run_db_query(update_query, (new_guild_name, new_guild_lang, new_guild_game, new_guild_server, guild_id), commit=True)
            logging.info(f"[CoreManager] Guild {guild_id} successfully modified in the database.")

            rename_templates = APP_MODIFICATION_DATA.get("rename_templates", APP_INITIALIZE_DATA.get("rename_templates", {}))
            template = rename_templates.get(new_guild_lang, rename_templates.get("en-US"))
            new_nickname = template.format(guild_name=new_guild_name)
            await ctx.guild.me.edit(nick=new_nickname)

            response = get_user_message(ctx, self.bot.translations, "commands.app_modify.messages.success")
        except Exception as e:
            logging.error(f"[CoreManager] ❌ Error during guild modification: {e}")
            response = get_user_message(ctx, self.bot.translations, "commands.app_modify.messages.error", error=e)
        await ctx.respond(response, ephemeral=True)

    @discord.slash_command(
        name=APP_RESET_DATA["name"]["en-US"],
        description=APP_RESET_DATA["description"]["en-US"],
        name_localizations=APP_RESET_DATA["name"],
        description_localizations=APP_RESET_DATA["description"]
    )
    @commands.has_permissions(administrator=True)
    async def app_reset(
        self,
        ctx: discord.ApplicationContext,
        confirmation: str = discord.Option(
            description=APP_RESET_DATA["options"]["confirmation"]["description"]["en-US"],
            description_localizations=APP_RESET_DATA["options"]["confirmation"]["description"]
        )
    ):
        guild_id = ctx.guild.id

        if confirmation != "DELETE":
            response = get_user_message(ctx, self.bot.translations, "commands.app_reset.messages.bad_parameter")
            return await ctx.respond(response, ephemeral=True)

        select_query = "SELECT COUNT(*) FROM guild_settings WHERE guild_id = ?"
        result = await self.bot.run_db_query(select_query, (guild_id,), fetch_one=True)
        count = result[0] if result else 0
        if count == 0:
            response = get_user_message(ctx, self.bot.translations, "commands.app_reset.messages.need_init")
            return await ctx.respond(response, ephemeral=True)

        try:
            delete_query_settings = "DELETE FROM guild_settings WHERE guild_id = ?"
            delete_query_roles = "DELETE FROM guild_roles WHERE guild_id = ?"
            delete_query_channels = "DELETE FROM guild_channels WHERE guild_id = ?"
            await asyncio.gather(
                self.bot.run_db_query(delete_query_settings, (guild_id,), commit=True),
                self.bot.run_db_query(delete_query_roles, (guild_id,), commit=True),
                self.bot.run_db_query(delete_query_channels, (guild_id,), commit=True)
            )
            logging.info(f"[CoreManager] Guild {guild_id} data has been deleted from the database.")
            await ctx.guild.me.edit(nick="My Guild Manager")
            response = get_user_message(ctx, self.bot.translations, "commands.app_reset.messages.success")
        except Exception as e:
            logging.error("[CoreManager] ❌ Error during guild reset: %s", e)
            response = get_user_message(ctx, self.bot.translations, "commands.app_reset.messages.error", error=e)
        await ctx.respond(response, ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        guild_id = guild.id
        logging.info(f"[CoreManager] Bot removed from guild {guild_id}. Deleting associated data from the database.")
        delete_query_settings = "DELETE FROM guild_settings WHERE guild_id = ?"
        delete_query_roles = "DELETE FROM guild_roles WHERE guild_id = ?"
        delete_query_channels = "DELETE FROM guild_channels WHERE guild_id = ?"
        delete_welcome_messages = "DELETE FROM welcome_messages WHERE guild_id = ?"

        try:
            await asyncio.gather(
                self.bot.run_db_query(delete_query_settings, (guild_id,), commit=True),
                self.bot.run_db_query(delete_query_roles, (guild_id,), commit=True),
                self.bot.run_db_query(delete_query_channels, (guild_id,), commit=True),
                self.bot.run_db_query(delete_welcome_messages, (guild_id,), commit=True)
            )
            logging.info(f"[CoreManager] Data for guild {guild_id} successfully deleted from the database.")
        except Exception as e:
            logging.error(f"[CoreManager] Error while deleting data for guild {guild_id}: {e}")

def setup(bot: discord.Bot):
    bot.add_cog(Core(bot))