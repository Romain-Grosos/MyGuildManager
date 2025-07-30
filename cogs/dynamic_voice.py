"""
Dynamic Voice Cog - Manages temporary voice channel creation and cleanup.
"""

import discord
import logging
from discord.ext import commands
import asyncio
import time
import re

class DynamicVoice(commands.Cog):
    """Cog for managing dynamic temporary voice channels."""
    
    def __init__(self, bot):
        """Initialize the DynamicVoice cog."""
        self.bot = bot
        self.max_channels_per_user = 5
        self.cool_down_seconds = 5

    def sanitize_channel_name(self, name: str) -> str:
        """Sanitize channel name by removing invalid characters."""
        name = re.sub(r'[^\w\s-]', '', name)[:100]
        if not name.strip():
            return "Private Channel"
        return name.strip()

    def get_safe_username(self, member):
        """Get safe username for logging purposes."""
        return f"User#{member.discriminator}" if hasattr(member, 'discriminator') else f"User{member.id}"

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize dynamic voice data on bot ready."""
        asyncio.create_task(self.load_create_room_channels())
        logging.debug("[DynamicVoice] 'load_create_room_channels' task started from on_ready")
        asyncio.create_task(self.load_persistent_channels())
        logging.debug("[DynamicVoice] 'load_persistent_channels' task started from on_ready")

    async def load_create_room_channels(self):
        """Ensure create room channels are loaded via centralized cache loader."""
        logging.debug("[DynamicVoice] Loading create room channels via centralized cache")
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        logging.debug("[DynamicVoice] Create room channels loading completed")

    async def load_persistent_channels(self):
        """Load persistent dynamic channels from database into cache."""
        logging.debug("[DynamicVoice] Loading persistent dynamic channels from DB")
        query = "SELECT channel_id FROM dynamic_voice_channels;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            dynamic_channels = set()
            for row in rows:
                channel_id = row[0]
                dynamic_channels.add(channel_id)
            await self.bot.cache.set('temporary', 'dynamic_voice_channels', dynamic_channels)
            logging.debug(f"[DynamicVoice] Persistent dynamic channels loaded from DB: {dynamic_channels}")
        except Exception as e:
            logging.error(f"[DynamicVoice] Error loading persistent channels: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Handle voice state updates for dynamic channel creation and cleanup."""
        guild = member.guild
        create_room_channel = await self.bot.cache.get_guild_data(guild.id, 'create_room_channel')
        monitored_channels = {create_room_channel} if create_room_channel else set()
        safe_name = self.get_safe_username(member)
        logging.debug(f"[DynamicVoice] on_voice_state_update: {safe_name} - Before: {before.channel.id if before.channel else None}, After: {after.channel.id if after.channel else None}")
        logging.debug(f"[DynamicVoice] Monitored channels for guild {guild.id}: {monitored_channels}")
        
        now = time.time()
        self.user_cool_downs = {uid: ts for uid, ts in self.user_cool_downs.items() if now - ts < 3600}

        if after.channel and after.channel.id in monitored_channels:
            safe_name = self.get_safe_username(member)
            logging.debug(f"[DynamicVoice] {safe_name} joined monitored channel {after.channel.id}. Preparing to create a temporary channel.")
            
            user_channels = await self.bot.cache.get('temporary', f'user_channels_{member.id}') or []
            user_channel_count = len(user_channels)
            if user_channel_count >= self.max_channels_per_user:
                logging.warning(f"[DynamicVoice] {safe_name} reached max channels limit ({self.max_channels_per_user})")
                return
            
            now = time.time()
            last_action = await self.bot.cache.get('temporary', f'cooldown_{member.id}') or 0
            if now - last_action < self.cool_down_seconds:
                logging.warning(f"[DynamicVoice] {safe_name} is on cool down")
                return
            await self.bot.cache.set('temporary', f'cooldown_{member.id}', now)

            await self.bot.cache_loader.ensure_category_loaded('guild_settings')
            await self.bot.cache_loader.ensure_category_loaded('guild_roles')
            
            guild_lang = await self.bot.cache.get_guild_data(guild.id, 'guild_lang') or "en-US"
            role_members_id = await self.bot.cache.get_guild_data(guild.id, 'members_role')
            role_absent_members_id = await self.bot.cache.get_guild_data(guild.id, 'absent_members_role')
            
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
                dynamic_channels = await self.bot.cache.get('temporary', 'dynamic_voice_channels') or set()
                dynamic_channels.add(new_channel.id)
                await self.bot.cache.set('temporary', 'dynamic_voice_channels', dynamic_channels)

                user_channels = await self.bot.cache.get('temporary', f'user_channels_{member.id}') or []
                user_channels.append(new_channel.id)
                await self.bot.cache.set('temporary', f'user_channels_{member.id}', user_channels)
                try:
                    query_insert = "INSERT INTO dynamic_voice_channels (channel_id, guild_id) VALUES (%s, %s)"
                    await self.bot.run_db_query(query_insert, (new_channel.id, guild.id), commit=True)
                    logging.debug(f"[DynamicVoice] Persistent channel registered in DB for {safe_name}")
                except Exception as e:
                    logging.error(f"[DynamicVoice] Error saving channel {new_channel.id} to DB: {e}", exc_info=True)
            except asyncio.TimeoutError:
                logging.error(f"[DynamicVoice] Timeout while creating channel for {safe_name}", exc_info=True)
            except Exception as e:
                logging.error(f"[DynamicVoice] Error while creating channel for {safe_name}: {e}", exc_info=True)

        dynamic_channels = await self.bot.cache.get('temporary', 'dynamic_voice_channels') or set()
        if before.channel and before.channel.id in dynamic_channels:
            channel = before.channel
            if len(channel.members) == 0:
                try:
                    await channel.delete()
                    if channel.id in dynamic_channels:
                        dynamic_channels.remove(channel.id)
                        await self.bot.cache.set('temporary', 'dynamic_voice_channels', dynamic_channels)

                    for guild_member in guild.members:
                        user_channels = await self.bot.cache.get('temporary', f'user_channels_{guild_member.id}') or []
                        if channel.id in user_channels:
                            user_channels.remove(channel.id)
                            if user_channels:
                                await self.bot.cache.set('temporary', f'user_channels_{guild_member.id}', user_channels)
                            else:
                                await self.bot.cache.delete('temporary', f'user_channels_{guild_member.id}')
                    
                    logging.debug(f"[DynamicVoice] Voice channel deleted: {channel.name} (ID: {channel.id})")
                    
                    try:
                        query_delete = "DELETE FROM dynamic_voice_channels WHERE channel_id = %s"
                        await self.bot.run_db_query(query_delete, (channel.id,), commit=True)
                        logging.debug(f"[DynamicVoice] Database record removed for channel {channel.id}")
                    except Exception as e:
                        logging.error(f"[DynamicVoice] Error removing channel {channel.id} from DB: {e}", exc_info=True)
                        
                except discord.Forbidden:
                    logging.error(f"[DynamicVoice] Insufficient permissions to delete channel {channel.name}.", exc_info=True)
                except Exception as e:
                    logging.error(f"[DynamicVoice] Error while deleting channel {channel.name}: {e}", exc_info=True)

def setup(bot: discord.Bot):
    """Setup function to add the DynamicVoice cog to the bot."""
    bot.add_cog(DynamicVoice(bot))