import discord
import logging
from discord.ext import commands
import asyncio
import time
import re

class DynamicVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dynamic_channels = set()
        self.create_room_channels = {}
        self.user_channels = {}
        self.max_channels_per_user = 5
        self.user_cooldowns = {}
        self.cooldown_seconds = 5

    def sanitize_channel_name(self, name: str) -> str:
        name = re.sub(r'[^\w\s-]', '', name)[:100]
        if not name.strip():
            return "Private Channel"
        return name.strip()

    def get_safe_username(self, member):
        return f"User#{member.discriminator}" if hasattr(member, 'discriminator') else f"User{member.id}"

    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.load_create_room_channels())
        logging.debug("[DynamicVoice] 'load_create_room_channels' task started from on_ready")
        asyncio.create_task(self.load_persistent_channels())
        logging.debug("[DynamicVoice] 'load_persistent_channels' task started from on_ready")

    async def load_create_room_channels(self):
        logging.debug("[DynamicVoice] Starting load_create_room_channels")
        query = "SELECT guild_id, create_room_channel FROM guild_channels;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, channel_id = row
                if guild_id not in self.create_room_channels:
                    self.create_room_channels[guild_id] = set()
                self.create_room_channels[guild_id].add(channel_id)
            logging.debug(f"[DynamicVoice] Monitored create room channels loaded from DB: {self.create_room_channels}")
        except Exception as e:
            logging.error(f"[DynamicVoice] Error loading create room channels from DB: {e}", exc_info=True)

    async def load_persistent_channels(self):
        logging.debug("[DynamicVoice] Loading persistent dynamic channels from DB")
        query = "SELECT channel_id FROM dynamic_voice_channels;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                channel_id = row[0]
                self.dynamic_channels.add(channel_id)
            logging.debug(f"[DynamicVoice] Persistent dynamic channels loaded from DB: {self.dynamic_channels}")
        except Exception as e:
            logging.error(f"[DynamicVoice] Error loading persistent channels: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        monitored_channels = self.create_room_channels.get(guild.id, set())
        safe_name = self.get_safe_username(member)
        logging.debug(f"[DynamicVoice] on_voice_state_update: {safe_name} - Before: {before.channel.id if before.channel else None}, After: {after.channel.id if after.channel else None}")
        logging.debug(f"[DynamicVoice] Monitored channels for guild {guild.id}: {monitored_channels}")
        
        now = time.time()
        self.user_cooldowns = {uid: ts for uid, ts in self.user_cooldowns.items() if now - ts < 3600}

        if after.channel and after.channel.id in monitored_channels:
            safe_name = self.get_safe_username(member)
            logging.debug(f"[DynamicVoice] {safe_name} joined monitored channel {after.channel.id}. Preparing to create a temporary channel.")
            
            user_channel_count = len(self.user_channels.get(member.id, []))
            if user_channel_count >= self.max_channels_per_user:
                logging.warning(f"[DynamicVoice] {safe_name} reached max channels limit ({self.max_channels_per_user})")
                return
            
            now = time.time()
            if member.id in self.user_cooldowns:
                if now - self.user_cooldowns[member.id] < self.cooldown_seconds:
                    logging.warning(f"[DynamicVoice] {safe_name} is on cooldown")
                    return
            self.user_cooldowns[member.id] = now

            query = """
            SELECT gs.guild_lang, gr.members, gr.absent_members
            FROM guild_settings gs
            LEFT JOIN guild_roles gr ON gs.guild_id = gr.guild_id
            WHERE gs.guild_id = ?
            """
            try:
                result = await self.bot.run_db_query(query, (guild.id,), fetch_one=True)
            except Exception as e:
                logging.error(f"[DynamicVoice] Error retrieving guild settings for guild {guild.id}: {e}", exc_info=True)
                result = None
            if result:
                guild_lang, role_members_id, role_absent_members_id = result
            else:
                guild_lang = "en-US"
                role_members_id = role_absent_members_id = None
            
            room_name_template = self.bot.translations.get("dynamic_voice", {}).get(guild_lang, "Channel of {username}")
            try:
                channel_name = room_name_template.format(username=member.display_name)
            except Exception as e:
                logging.error(f"[DynamicVoice] Error formatting channel name: {e}", exc_info=True)
                channel_name = f"Channel of {member.display_name}"
            
            channel_name = self.sanitize_channel_name(channel_name)
            logging.debug(f"[DynamicVoice] Channel name obtained from JSON: '{channel_name}'")
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(manage_channels=True, mute_members=True, deafen_members=True)
            }
            if role_members_id:
                role_members = guild.get_role(role_members_id)
                if role_members:
                    overwrites[role_members] = discord.PermissionOverwrite(view_channel=True, connect=True)
            if role_absent_members_id:
                role_absent = guild.get_role(role_absent_members_id)
                if role_absent:
                    overwrites[role_absent] = discord.PermissionOverwrite(view_channel=True, connect=True)
            try:
                await asyncio.sleep(0.2)
                logging.debug(f"[DynamicVoice] Attempting to create a temporary channel for {safe_name} with name '{channel_name}'")
                new_channel = await asyncio.wait_for(
                    guild.create_voice_channel(
                        name=channel_name,
                        category=after.channel.category,
                        overwrites=overwrites
                    ),
                    timeout=10
                )
                logging.debug(f"[DynamicVoice] Temporary channel created: {new_channel.name} (ID: {new_channel.id})")
                try:
                    await member.move_to(new_channel)
                except discord.HTTPException as e:
                    logging.error(f"[DynamicVoice] Failed to move {safe_name} to new channel: {e}", exc_info=True)
                except Exception as e:
                    logging.error(f"[DynamicVoice] Unexpected error moving {safe_name}: {e}", exc_info=True)
                self.dynamic_channels.add(new_channel.id)
                
                if member.id not in self.user_channels:
                    self.user_channels[member.id] = []
                self.user_channels[member.id].append(new_channel.id)
                try:
                    query_insert = "INSERT INTO dynamic_voice_channels (channel_id, guild_id) VALUES (?, ?)"
                    await self.bot.run_db_query(query_insert, (new_channel.id, guild.id), commit=True)
                    logging.debug(f"[DynamicVoice] Persistent channel registered in DB for {safe_name}")
                except Exception as e:
                    logging.error(f"[DynamicVoice] Error saving channel {new_channel.id} to DB: {e}", exc_info=True)
            except asyncio.TimeoutError:
                logging.error(f"[DynamicVoice] Timeout while creating channel for {safe_name}", exc_info=True)
            except Exception as e:
                logging.error(f"[DynamicVoice] Error while creating channel for {safe_name}: {e}", exc_info=True)

        if before.channel and before.channel.id in self.dynamic_channels:
            channel = before.channel
            if len(channel.members) == 0:
                try:
                    await channel.delete()
                    if channel.id in self.dynamic_channels:
                        self.dynamic_channels.remove(channel.id)
                    
                    for user_id, channels in list(self.user_channels.items()):
                        if channel.id in channels:
                            channels.remove(channel.id)
                            if not channels:
                                del self.user_channels[user_id]
                    
                    logging.debug(f"[DynamicVoice] Voice channel deleted: {channel.name} (ID: {channel.id})")
                    
                    try:
                        query_delete = "DELETE FROM dynamic_voice_channels WHERE channel_id = ?"
                        await self.bot.run_db_query(query_delete, (channel.id,), commit=True)
                        logging.debug(f"[DynamicVoice] Database record removed for channel {channel.id}")
                    except Exception as e:
                        logging.error(f"[DynamicVoice] Error removing channel {channel.id} from DB: {e}", exc_info=True)
                        
                except discord.Forbidden:
                    logging.error(f"[DynamicVoice] Insufficient permissions to delete channel {channel.name}.", exc_info=True)
                except Exception as e:
                    logging.error(f"[DynamicVoice] Error while deleting channel {channel.name}: {e}", exc_info=True)

def setup(bot: discord.Bot):
    bot.add_cog(DynamicVoice(bot))