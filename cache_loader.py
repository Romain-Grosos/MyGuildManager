"""
Centralized Cache Loader - Manages loading of shared data into global cache.
"""

import logging
from typing import Dict, Any, Optional
import asyncio

class CacheLoader:
    """Centralized loader for shared guild data to eliminate redundant DB queries."""
    
    def __init__(self, bot):
        self.bot = bot
        self._loaded_categories = set()
        
    async def ensure_guild_settings_loaded(self) -> None:
        """Load guild settings (language, name, game, server) for all guilds."""
        if 'guild_settings' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading guild settings for all guilds")
        query = "SELECT guild_id, guild_lang, guild_name, guild_game, guild_server, premium FROM guild_settings"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, guild_lang, guild_name, guild_game, guild_server, premium = row

                    await self.bot.cache.set_guild_data(guild_id, 'guild_lang', guild_lang)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_name', guild_name)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_game', guild_game)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_server', guild_server)
                    await self.bot.cache.set_guild_data(guild_id, 'premium', premium)

                    await self.bot.cache.set_guild_data(guild_id, 'settings', {
                        'guild_lang': guild_lang,
                        'guild_name': guild_name,
                        'guild_game': guild_game,
                        'guild_server': guild_server,
                        'premium': premium
                    })
                    
                logging.info(f"[CacheLoader] Loaded settings for {len(rows)} guilds")
                self._loaded_categories.add('guild_settings')
            else:
                logging.warning("[CacheLoader] No guild settings found in database")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading guild settings: {e}", exc_info=True)
    
    async def ensure_guild_roles_loaded(self) -> None:
        """Load guild roles (members, absent_members, rules_ok) for all guilds."""
        if 'guild_roles' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading guild roles for all guilds")
        query = "SELECT guild_id, members, absent_members, rules_ok FROM guild_roles"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, members_role, absent_members_role, rules_ok_role = row

                    roles_data = {
                        'members': members_role,
                        'absent_members': absent_members_role,
                        'rules_ok': rules_ok_role
                    }
                    await self.bot.cache.set_guild_data(guild_id, 'roles', roles_data)

                    if members_role:
                        await self.bot.cache.set_guild_data(guild_id, 'members_role', members_role)
                    if absent_members_role:
                        await self.bot.cache.set_guild_data(guild_id, 'absent_members_role', absent_members_role)
                    if rules_ok_role:
                        await self.bot.cache.set_guild_data(guild_id, 'rules_ok_role', rules_ok_role)
                    
                logging.info(f"[CacheLoader] Loaded roles for {len(rows)} guilds")
                self._loaded_categories.add('guild_roles')
            else:
                logging.warning("[CacheLoader] No guild roles found in database")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading guild roles: {e}", exc_info=True)
    
    async def ensure_guild_channels_loaded(self) -> None:
        """Load guild channels (rules, absence, events, etc.) for all guilds."""
        if 'guild_channels' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading guild channels for all guilds")
        query = """
            SELECT guild_id, rules_channel, rules_message, abs_channel, forum_members_channel,
                   events_channel, statics_channel, statics_message, create_room_channel
            FROM guild_channels
        """
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, rules_channel, rules_message, abs_channel, forum_members_channel, events_channel, statics_channel, statics_message, create_room_channel = row

                    channels_data = {
                        'rules_channel': rules_channel,
                        'rules_message': rules_message,
                        'abs_channel': abs_channel,
                        'forum_members_channel': forum_members_channel,
                        'events_channel': events_channel,
                        'statics_channel': statics_channel,
                        'statics_message': statics_message,
                        'create_room_channel': create_room_channel
                    }
                    await self.bot.cache.set_guild_data(guild_id, 'channels', channels_data)

                    if rules_channel and rules_message:
                        await self.bot.cache.set_guild_data(guild_id, 'rules_message', {
                            'channel': rules_channel,
                            'message': rules_message
                        })
                    
                    if abs_channel:
                        await self.bot.cache.set_guild_data(guild_id, 'absence_channels', {
                            'abs_channel': abs_channel,
                            'forum_members_channel': forum_members_channel
                        })
                    
                    if events_channel:
                        await self.bot.cache.set_guild_data(guild_id, 'events_channel', events_channel)
                    
                    if create_room_channel:
                        await self.bot.cache.set_guild_data(guild_id, 'create_room_channel', create_room_channel)
                    
                logging.info(f"[CacheLoader] Loaded channels for {len(rows)} guilds")
                self._loaded_categories.add('guild_channels')
            else:
                logging.warning("[CacheLoader] No guild channels found in database")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading guild channels: {e}", exc_info=True)
    
    async def ensure_welcome_messages_loaded(self) -> None:
        """Load welcome messages for autorole functionality."""
        if 'welcome_messages' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading welcome messages from database")
        query = "SELECT guild_id, member_id, channel_id, message_id FROM welcome_messages"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, member_id, channel_id, message_id = row
                    await self.bot.cache.set_user_data(guild_id, member_id, 'welcome_message', {
                        "channel": channel_id, 
                        "message": message_id
                    })
                logging.info(f"[CacheLoader] Loaded {len(rows)} welcome messages")
                self._loaded_categories.add('welcome_messages')
            else:
                logging.warning("[CacheLoader] No welcome messages found in database")
                self._loaded_categories.add('welcome_messages')
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading welcome messages: {e}", exc_info=True)
    
    async def ensure_absence_messages_loaded(self) -> None:
        """Mark absence messages as 'loaded' - these are managed directly in DB due to high frequency changes."""
        if 'absence_messages' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Absence messages will be managed directly via DB (high frequency data)")
        self._loaded_categories.add('absence_messages')

    async def ensure_guild_members_loaded(self) -> None:
        """Load guild members data for all guilds."""
        if 'guild_members' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading guild members for all guilds")
        query = "SELECT guild_id, member_id, class, GS, weapons, DKP, nb_events, registrations, attendances FROM guild_members"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, member_id, member_class, gs, weapons, dkp, nb_events, registrations, attendances = row
                    
                    member_data = {
                        'class': member_class,
                        'GS': gs,
                        'weapons': weapons,
                        'DKP': dkp or 0,
                        'nb_events': nb_events or 0,
                        'registrations': registrations or 0,
                        'attendances': attendances or 0
                    }
                    
                    await self.bot.cache.set_guild_data(guild_id, f'member_{member_id}', member_data)
                    
                logging.info(f"[CacheLoader] Loaded guild members: {len(rows)} members")
                self._loaded_categories.add('guild_members')
            else:
                logging.warning("[CacheLoader] No guild members found in database")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading guild members: {e}", exc_info=True)
    
    async def ensure_events_data_loaded(self) -> None:
        """Load events data for all guilds."""
        if 'events_data' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading events data for all guilds")
        query = """
            SELECT guild_id, event_id, name, event_date, event_time, duration, 
                   dkp_value, status, registrations, actual_presence
            FROM events_data
        """
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, event_id, name, event_date, event_time, duration, dkp_value, status, registrations, actual_presence = row
                    
                    event_data = {
                        'event_id': event_id,
                        'name': name,
                        'event_date': event_date,
                        'event_time': event_time,
                        'duration': duration,
                        'dkp_value': dkp_value,
                        'status': status,
                        'registrations': registrations,
                        'actual_presence': actual_presence
                    }
                    
                    await self.bot.cache.set_guild_data(guild_id, f'event_{event_id}', event_data)
                    
                logging.info(f"[CacheLoader] Loaded events data: {len(rows)} events")
                self._loaded_categories.add('events_data')
            else:
                logging.warning("[CacheLoader] No events data found in database")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading events data: {e}", exc_info=True)
    
    async def ensure_static_data_loaded(self) -> None:
        """Load static groups data via GuildEvents cog and mark other static data as on-demand."""
        if 'static_data' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading static groups and marking other static data as on-demand")

        try:
            guild_events_cog = self.bot.get_cog('GuildEvents')
            if guild_events_cog and hasattr(guild_events_cog, 'load_static_groups_cache'):
                await guild_events_cog.load_static_groups_cache()
                logging.debug("[CacheLoader] Static groups loaded via GuildEvents cog")
            else:
                logging.warning("[CacheLoader] GuildEvents cog not found or missing load_static_groups_cache method")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading static groups: {e}", exc_info=True)

        self._loaded_categories.add('static_data')

    async def load_all_shared_data(self) -> None:
        """Load all shared data categories in parallel."""
        logging.info("[CacheLoader] Loading all shared data categories")
        
        await asyncio.gather(
            self.ensure_guild_settings_loaded(),
            self.ensure_guild_roles_loaded(),
            self.ensure_guild_channels_loaded(),
            self.ensure_welcome_messages_loaded(),
            self.ensure_absence_messages_loaded(),
            self.ensure_guild_members_loaded(),
            self.ensure_events_data_loaded(),
            self.ensure_static_data_loaded(),
            return_exceptions=True
        )
        
        logging.info("[CacheLoader] Shared data loading completed")
    
    async def ensure_category_loaded(self, category: str) -> None:
        """Ensure a specific category is loaded."""
        if category == 'guild_settings':
            await self.ensure_guild_settings_loaded()
        elif category == 'guild_roles':
            await self.ensure_guild_roles_loaded()
        elif category == 'guild_channels':
            await self.ensure_guild_channels_loaded()
        elif category == 'welcome_messages':
            await self.ensure_welcome_messages_loaded()
        elif category == 'absence_messages':
            await self.ensure_absence_messages_loaded()
        elif category == 'guild_members':
            await self.ensure_guild_members_loaded()
        elif category == 'events_data':
            await self.ensure_events_data_loaded()
        elif category == 'static_data':
            await self.ensure_static_data_loaded()
        else:
            logging.warning(f"[CacheLoader] Unknown category: {category}")
    
    def is_category_loaded(self, category: str) -> bool:
        """Check if a category has been loaded."""
        return category in self._loaded_categories
    
    async def reload_category(self, category: str) -> None:
        """Force reload a specific category."""
        if category in self._loaded_categories:
            self._loaded_categories.remove(category)
        await self.ensure_category_loaded(category)
    
    def get_loaded_categories(self) -> set:
        """Get list of loaded categories."""
        return self._loaded_categories.copy()

# #################################################################################### #
#                            Global Cache Loader Instance
# #################################################################################### #
_cache_loader = None

def get_cache_loader(bot=None):
    """Get the global cache loader instance."""
    global _cache_loader
    if _cache_loader is None and bot:
        _cache_loader = CacheLoader(bot)
    return _cache_loader