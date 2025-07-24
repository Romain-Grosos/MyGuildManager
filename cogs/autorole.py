import discord
import logging
from discord.ext import commands
from typing import Dict, Tuple
import asyncio
import pytz
import time
from datetime import datetime
from translation import translations as global_translations

WELCOME_MP_DATA = global_translations.get("welcome_mp", {})

def update_welcome_embed(embed: discord.Embed, lang: str, translations: dict) -> discord.Embed:
    try:
        tz_france = pytz.timezone("Europe/Paris")
        now = datetime.now(pytz.utc).astimezone(tz_france).strftime("%d/%m/%Y at %Hh%M")
        pending_text = translations["welcome"]["pending"].get(lang)
        accepted_template = translations["welcome"]["accepted"].get(lang)
        if not pending_text or not accepted_template:
            logging.error(f"[AutoRole] ❌ Missing translation keys for language '{lang}'.")
            return embed
        new_text = accepted_template.format(date=now)
        if embed.description:
            embed.description = embed.description.replace(pending_text, new_text)
        else:
            embed.description = new_text
        embed.color = discord.Color.dark_grey()
    except Exception as e:
        logging.error(f"[AutoRole] ❌ Error updating welcome embed: {e}", exc_info=True)
    return embed

class AutoRole(commands.Cog):
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
        self.rules_messages: Dict[int, Dict[str, int]] = {}
        self.welcome_messages: Dict[Tuple[int, int], Dict[str, int]] = {}
        self.rules_ok_roles: Dict[int, int] = {}
        self.guild_langs: Dict[int, str] = {}
        self._profile_setup_cog = None
        self._recent_reactions: Dict[Tuple[int, int, int], float] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.load_rules_messages())
        asyncio.create_task(self.load_welcome_messages_cache())
        asyncio.create_task(self.load_rules_ok_roles())
        asyncio.create_task(self.load_guild_lang())
        logging.debug("[AutoRole] Cache loading tasks started from on_ready.")

    async def load_rules_messages(self) -> None:
        logging.debug("[AutoRole] Loading rule messages from the database.")
        query = "SELECT guild_id, rules_channel, rules_message FROM guild_channels WHERE rules_message IS NOT NULL"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, channel_id, message_id = row
                    self.rules_messages[guild_id] = {"channel": channel_id, "message": message_id}
                logging.debug(f"[AutoRole] Loaded rule messages: {self.rules_messages}")
            else:
                logging.warning("[AutoRole] No rule messages found in the database.")
        except Exception as e:
            logging.error(f"[AutoRole] Error loading rule messages: {e}", exc_info=True)

    async def load_welcome_messages_cache(self) -> None:
        logging.debug("[AutoRole] Loading welcome messages from the database.")
        query = "SELECT guild_id, member_id, channel_id, message_id FROM welcome_messages"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, member_id, channel_id, message_id = row
                    self.welcome_messages[(guild_id, member_id)] = {"channel": channel_id, "message": message_id}
                logging.debug(f"[AutoRole] Loaded welcome messages: {self.welcome_messages}")
            else:
                logging.warning("[AutoRole] No welcome messages found in the database.")
        except Exception as e:
            logging.error(f"[AutoRole] Error loading welcome messages: {e}", exc_info=True)

    async def load_rules_ok_roles(self) -> None:
        logging.debug("[AutoRole] Loading acceptance roles from the database.")
        query = "SELECT guild_id, rules_ok FROM guild_roles WHERE rules_ok IS NOT NULL"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, rules_ok_role_id = row
                    self.rules_ok_roles[guild_id] = rules_ok_role_id
                logging.debug(f"[AutoRole] Loaded acceptance roles: {self.rules_ok_roles}")
            else:
                logging.warning("[AutoRole] No acceptance roles found in the database.")
        except Exception as e:
            logging.error(f"[AutoRole] Error loading acceptance roles: {e}", exc_info=True)

    async def load_guild_lang(self) -> None:
        logging.debug("[AutoRole] Loading guild languages from the database.")
        query = "SELECT guild_id, guild_lang FROM guild_settings"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, lang = row
                    self.guild_langs[guild_id] = lang
                logging.debug(f"[AutoRole] Loaded guild languages: {self.guild_langs}")
            else:
                logging.warning("[AutoRole] No guild languages found in the database.")
        except Exception as e:
            logging.error(f"[AutoRole] Error loading guild languages: {e}", exc_info=True)

    def _check_rate_limit(self, guild_id: int, user_id: int, message_id: int) -> bool:
        key = (guild_id, user_id, message_id)
        current_time = time.time()
        
        if key in self._recent_reactions:
            if current_time - self._recent_reactions[key] < 5.0:
                return False
        
        self._recent_reactions[key] = current_time

        cutoff = current_time - 3600
        self._recent_reactions = {k: v for k, v in self._recent_reactions.items() if v > cutoff}
        
        return True

    def _get_profile_setup_cog(self):
        if self._profile_setup_cog is None:
            self._profile_setup_cog = self.bot.get_cog("ProfileSetup")
        return self._profile_setup_cog

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        logging.debug(f"[AutoRole - on_raw_reaction_add] Processing reaction: user={payload.user_id}, message={payload.message_id}, emoji={payload.emoji}")
        
        if not payload.guild_id:
            logging.debug("[AutoRole - on_raw_reaction_add] No guild_id, skipping")
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            logging.debug(f"[AutoRole - on_raw_reaction_add] Guild {payload.guild_id} not found")
            return

        rules_info = self.rules_messages.get(guild.id)
        if not rules_info or payload.message_id != rules_info.get("message"):
            logging.debug(f"[AutoRole - on_raw_reaction_add] Message {payload.message_id} is not rules message for guild {guild.id}")
            return

        if str(payload.emoji) != "✅":
            return

        if not self._check_rate_limit(guild.id, payload.user_id, payload.message_id):
            logging.debug(f"[AutoRole] Rate limited reaction from user {payload.user_id}")
            return

        role_id = self.rules_ok_roles.get(guild.id)
        if not role_id:
            logging.warning(f"[AutoRole] No rules_ok role configured for guild {guild.id}")
            return
            
        role = guild.get_role(role_id)
        if not role:
            logging.warning(f"[AutoRole] Rules_ok role {role_id} not found in guild {guild.id}")
            return

        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except Exception as e:
            logging.error(f"[AutoRole] Error fetching member with ID {payload.user_id}: {e}", exc_info=True)
            return

        if member and role and role not in member.roles:
            try:
                await member.add_roles(role)
                logging.debug(f"[AutoRole] ✅ Role added to {member.name} ({member.id}).")
            except Exception as e:
                logging.error(f"[AutoRole] Error adding role to {member.name}: {e}", exc_info=True)
                return

            key = (guild.id, member.id)
            if key in self.welcome_messages:
                info = self.welcome_messages[key]
                try:
                    channel = self.bot.get_channel(info["channel"])
                    if not channel:
                        channel = await self.bot.fetch_channel(info["channel"])
                    
                    if not channel:
                        logging.warning(f"[AutoRole] Channel {info['channel']} not found, removing from cache")
                        del self.welcome_messages[key]
                        return
                    
                    try:
                        message = await channel.fetch_message(info["message"])
                    except discord.NotFound:
                        logging.warning(f"[AutoRole] Message {info['message']} not found, removing from cache")
                        del self.welcome_messages[key]
                        return

                    if not message.embeds:
                        logging.warning(f"[AutoRole] No embeds found in welcome message for {member.name}")
                        return
                        
                    lang = self.guild_langs.get(guild.id, "en-US")
                    embed = update_welcome_embed(message.embeds[0], lang, self.bot.translations)
                    await message.edit(embed=embed)
                    logging.debug(f"[AutoRole] ✅ Welcome message updated for {member.name} (ID: {member.id}).")
                except discord.Forbidden:
                    logging.warning(f"[AutoRole] No permission to edit message for {member.name}")
                except Exception as e:
                    logging.error("[AutoRole] ❌ Error updating welcome message", exc_info=True)
            else:
                logging.debug(f"[AutoRole] No welcome message in cache for key {key}.")

            query = "SELECT user_id FROM user_setup WHERE guild_id = %s AND user_id = %s"
            try:
                result = await self.bot.run_db_query(query, (guild.id, member.id), fetch_one=True)
            except Exception as e:
                logging.error(f"[AutoRole] Error checking user profile for {guild.id}_{member.id}: {e}", exc_info=True)
                return

            if result is not None:
                logging.debug(f"[AutoRole] Profile already exists for {guild.id}_{member.id}; no DM sent for registration.")
                return

            profile_setup_cog = self._get_profile_setup_cog()
            if profile_setup_cog is None:
                logging.error("[AutoRole] ProfileSetup cog not found!")
                return
            try:
                await member.send(view=profile_setup_cog.LangSelectView(profile_setup_cog, guild.id))
                logging.debug(f"[AutoRole] 📩 DM sent to {member.name} ({member.id}) to start the profile setup process for guild {guild.id}.")
            except discord.Forbidden:
                logging.warning(f"[AutoRole] ⚠️ Cannot send DM to {member.name} - DMs disabled for guild {guild.id}")
            except Exception as e:
                logging.error(f"[AutoRole] ❌ Error sending DM to {member.name}: {e} in guild {guild.id}.", exc_info=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        rules_info = self.rules_messages.get(guild.id)
        if not rules_info or payload.message_id != rules_info.get("message"):
            return

        if str(payload.emoji) != "✅":
            return

        if not self._check_rate_limit(guild.id, payload.user_id, payload.message_id):
            logging.debug(f"[AutoRole] Rate limited reaction removal from user {payload.user_id}")
            return

        role_id = self.rules_ok_roles.get(guild.id)
        if not role_id:
            logging.warning(f"[AutoRole] No rules_ok role configured for guild {guild.id}")
            return

        role = guild.get_role(role_id)
        if not role:
            logging.warning(f"[AutoRole] Rules_ok role {role_id} not found in guild {guild.id}")
            return

        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
        except Exception as e:
            logging.error(f"[AutoRole] Error fetching member with ID {payload.user_id}: {e}", exc_info=True)
            return

        if member and role and role in member.roles:
            try:
                await member.remove_roles(role)
                logging.debug(f"[AutoRole] ✅ Role removed from {member.name} ({member.id}).")
            except Exception as e:
                logging.error(f"[AutoRole] ❌ Error removing role from {member.name}: {e}", exc_info=True)

def setup(bot: discord.Bot):
    bot.add_cog(AutoRole(bot))