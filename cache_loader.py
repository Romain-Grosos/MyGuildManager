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
        query = "SELECT guild_id, guild_ptb, guild_lang, guild_name, guild_game, guild_server, initialized, premium FROM guild_settings"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, guild_ptb, guild_lang, guild_name, guild_game, guild_server, initialized, premium = row

                    await self.bot.cache.set_guild_data(guild_id, 'guild_ptb', guild_ptb)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_lang', guild_lang)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_name', guild_name)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_game', guild_game)
                    await self.bot.cache.set_guild_data(guild_id, 'guild_server', guild_server)
                    await self.bot.cache.set_guild_data(guild_id, 'initialized', initialized)
                    await self.bot.cache.set_guild_data(guild_id, 'premium', premium)

                    await self.bot.cache.set_guild_data(guild_id, 'settings', {
                        'guild_ptb': guild_ptb,
                        'guild_lang': guild_lang,
                        'guild_name': guild_name,
                        'guild_game': guild_game,
                        'guild_server': guild_server,
                        'initialized': initialized,
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
        query = "SELECT guild_id, guild_master, officer, guardian, members, absent_members, allies, diplomats, friends, applicant, config_ok, rules_ok FROM guild_roles"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, guild_master, officer, guardian, members, absent_members, allies, diplomats, friends, applicant, config_ok, rules_ok = row

                    roles_data = {
                        'guild_master': guild_master,
                        'officer': officer,
                        'guardian': guardian,
                        'members': members,
                        'absent_members': absent_members,
                        'allies': allies,
                        'diplomats': diplomats,
                        'friends': friends,
                        'applicant': applicant,
                        'config_ok': config_ok,
                        'rules_ok': rules_ok
                    }
                    await self.bot.cache.set_guild_data(guild_id, 'roles', roles_data)

                    if members:
                        await self.bot.cache.set_guild_data(guild_id, 'members_role', members)
                    if absent_members:
                        await self.bot.cache.set_guild_data(guild_id, 'absent_members_role', absent_members)
                    if rules_ok:
                        await self.bot.cache.set_guild_data(guild_id, 'rules_ok_role', rules_ok)
                    
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
            SELECT guild_id, rules_channel, rules_message, announcements_channel, voice_tavern_channel, 
                   voice_war_channel, create_room_channel, events_channel, members_channel, 
                   members_m1, members_m2, members_m3, members_m4, members_m5, groups_channel,
                   statics_channel, statics_message, abs_channel, loot_channel, tuto_channel,
                   forum_allies_channel, forum_friends_channel, forum_diplomats_channel,
                   forum_recruitment_channel, forum_members_channel, notifications_channel,
                   external_recruitment_cat, category_diplomat, external_recruitment_channel, 
                   external_recruitment_message
            FROM guild_channels
        """
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, rules_channel, rules_message, announcements_channel, voice_tavern_channel, voice_war_channel, create_room_channel, events_channel, members_channel, members_m1, members_m2, members_m3, members_m4, members_m5, groups_channel, statics_channel, statics_message, abs_channel, loot_channel, tuto_channel, forum_allies_channel, forum_friends_channel, forum_diplomats_channel, forum_recruitment_channel, forum_members_channel, notifications_channel, external_recruitment_cat, category_diplomat, external_recruitment_channel, external_recruitment_message = row

                    channels_data = {
                        'rules_channel': rules_channel,
                        'rules_message': rules_message,
                        'announcements_channel': announcements_channel,
                        'voice_tavern_channel': voice_tavern_channel,
                        'voice_war_channel': voice_war_channel,
                        'create_room_channel': create_room_channel,
                        'events_channel': events_channel,
                        'members_channel': members_channel,
                        'members_m1': members_m1,
                        'members_m2': members_m2,
                        'members_m3': members_m3,
                        'members_m4': members_m4,
                        'members_m5': members_m5,
                        'groups_channel': groups_channel,
                        'statics_channel': statics_channel,
                        'statics_message': statics_message,
                        'abs_channel': abs_channel,
                        'loot_channel': loot_channel,
                        'tuto_channel': tuto_channel,
                        'forum_allies_channel': forum_allies_channel,
                        'forum_friends_channel': forum_friends_channel,
                        'forum_diplomats_channel': forum_diplomats_channel,
                        'forum_recruitment_channel': forum_recruitment_channel,
                        'forum_members_channel': forum_members_channel,
                        'notifications_channel': notifications_channel,
                        'external_recruitment_cat': external_recruitment_cat,
                        'category_diplomat': category_diplomat,
                        'external_recruitment_channel': external_recruitment_channel,
                        'external_recruitment_message': external_recruitment_message
                    }
                    await self.bot.cache.set_guild_data(guild_id, 'channels', channels_data)
                    
                    if members_channel:
                        await self.bot.cache.set_guild_data(guild_id, 'members_channel', members_channel)
                        await self.bot.cache.set_guild_data(guild_id, 'members_m1', members_m1)
                        await self.bot.cache.set_guild_data(guild_id, 'members_m2', members_m2)
                        await self.bot.cache.set_guild_data(guild_id, 'members_m3', members_m3)
                        await self.bot.cache.set_guild_data(guild_id, 'members_m4', members_m4)
                        await self.bot.cache.set_guild_data(guild_id, 'members_m5', members_m5)
                    
                    if external_recruitment_channel:
                        await self.bot.cache.set_guild_data(guild_id, 'external_recruitment_channel', external_recruitment_channel)
                        await self.bot.cache.set_guild_data(guild_id, 'external_recruitment_message', external_recruitment_message)

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
        query = "SELECT guild_id, member_id, username, language, class, GS, build, weapons, DKP, nb_events, registrations, attendances FROM guild_members"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                guild_members_cache = {}
                for row in rows:
                    guild_id, member_id, username, language, member_class, gs, build, weapons, dkp, nb_events, registrations, attendances = row
                    
                    member_data = {
                        'username': username,
                        'language': language,
                        'class': member_class,
                        'GS': gs,
                        'build': build,
                        'weapons': weapons,
                        'DKP': dkp or 0,
                        'nb_events': nb_events or 0,
                        'registrations': registrations or 0,
                        'attendances': attendances or 0
                    }

                    key = (guild_id, member_id)
                    guild_members_cache[key] = member_data

                await self.bot.cache.set('roster_data', guild_members_cache, 'guild_members')
                    
                logging.info(f"[CacheLoader] Loaded guild members: {len(rows)} members")
                self._loaded_categories.add('guild_members')
            else:
                logging.warning("[CacheLoader] No guild members found in database")
                await self.bot.cache.set('roster_data', {}, 'guild_members')
                self._loaded_categories.add('guild_members')
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
        """Load static groups data and mark other static data as on-demand."""
        if 'static_data' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading static groups via centralized loader")

        try:
            await self.ensure_static_groups_loaded()
            logging.debug("[CacheLoader] Static groups loaded via centralized cache loader")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading static groups: {e}", exc_info=True)

        self._loaded_categories.add('static_data')
    
    async def ensure_static_groups_loaded(self) -> None:
        """Load static groups data for all guilds."""
        if 'static_groups' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading static groups from database")
        
        query = """
            SELECT g.guild_id, g.group_name, g.leader_id, 
                   GROUP_CONCAT(m.member_id ORDER BY m.position_order) as member_ids
            FROM guild_static_groups g
            LEFT JOIN guild_static_members m ON g.id = m.group_id
            WHERE g.is_active = TRUE
            GROUP BY g.guild_id, g.group_name, g.leader_id
        """
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)

            guild_static_groups = {}
            for row in rows:
                guild_id, group_name, leader_id, member_ids_str = row

                member_ids = []
                if member_ids_str:
                    member_ids = [int(mid) for mid in member_ids_str.split(',') if mid.strip()]

                if guild_id not in guild_static_groups:
                    guild_static_groups[guild_id] = {}

                guild_static_groups[guild_id][group_name] = {
                    "leader_id": leader_id,
                    "member_ids": member_ids
                }

            for guild_id, groups_data in guild_static_groups.items():
                await self.bot.cache.set_guild_data(guild_id, 'static_groups', groups_data)
            
            logging.info(f"[CacheLoader] Loaded static groups for {len(guild_static_groups)} guilds")
            self._loaded_categories.add('static_groups')
            
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading static groups: {e}", exc_info=True)
    
    async def ensure_user_setup_loaded(self) -> None:
        """Load user setup data for all users."""
        if 'user_setup' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading user setup data for all users")
        query = "SELECT guild_id, user_id, locale, gs, weapons FROM user_setup"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                for row in rows:
                    guild_id, user_id, locale, gs, weapons = row
                    
                    setup_data = {
                        'locale': locale,
                        'gs': gs,
                        'weapons': weapons
                    }
                    
                    await self.bot.cache.set_user_data(guild_id, user_id, 'setup', setup_data)
                    
                logging.info(f"[CacheLoader] Loaded user setup data: {len(rows)} users")
                self._loaded_categories.add('user_setup')
            else:
                logging.warning("[CacheLoader] No user setup data found in database")
                self._loaded_categories.add('user_setup')
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading user setup data: {e}", exc_info=True)
    
    async def ensure_weapons_loaded(self) -> None:
        """Load weapons data for all games."""
        if 'weapons' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading weapons data for all games")
        query = "SELECT game_id, code, name FROM weapons ORDER BY game_id"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                weapons_by_game = {}
                for row in rows:
                    game_id, code, name = row
                    
                    if game_id not in weapons_by_game:
                        weapons_by_game[game_id] = {}
                    
                    weapons_by_game[game_id][code] = name
                
                await self.bot.cache.set_static_data('weapons', weapons_by_game)
                    
                logging.info(f"[CacheLoader] Loaded weapons data: {len(rows)} weapons for {len(weapons_by_game)} games")
                self._loaded_categories.add('weapons')
            else:
                logging.warning("[CacheLoader] No weapons data found in database")
                await self.bot.cache.set_static_data('weapons', {})
                self._loaded_categories.add('weapons')
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading weapons data: {e}", exc_info=True)
    
    async def ensure_weapons_combinations_loaded(self) -> None:
        """Load weapons combinations data for all games."""
        if 'weapons_combinations' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading weapons combinations data for all games")
        query = "SELECT game_id, role, weapon1, weapon2 FROM weapons_combinations ORDER BY game_id"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                combinations_by_game = {}
                for row in rows:
                    game_id, role, weapon1, weapon2 = row
                    
                    if game_id not in combinations_by_game:
                        combinations_by_game[game_id] = []
                    
                    combinations_by_game[game_id].append({
                        'role': role,
                        'weapon1': weapon1.upper(),
                        'weapon2': weapon2.upper()
                    })
                
                await self.bot.cache.set_static_data('weapons_combinations', combinations_by_game)
                    
                logging.info(f"[CacheLoader] Loaded weapons combinations: {len(rows)} combinations for {len(combinations_by_game)} games")
                self._loaded_categories.add('weapons_combinations')
            else:
                logging.warning("[CacheLoader] No weapons combinations found in database")
                await self.bot.cache.set_static_data('weapons_combinations', {})
                self._loaded_categories.add('weapons_combinations')
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading weapons combinations: {e}", exc_info=True)
    
    async def ensure_guild_ideal_staff_loaded(self) -> None:
        """Load guild ideal staff data for all guilds."""
        if 'guild_ideal_staff' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading guild ideal staff data for all guilds")
        query = "SELECT guild_id, class_name, ideal_count FROM guild_ideal_staff"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                ideal_staff = {}
                for row in rows:
                    guild_id, class_name, ideal_count = row
                    
                    if guild_id not in ideal_staff:
                        ideal_staff[guild_id] = {}
                    ideal_staff[guild_id][class_name] = ideal_count
                
                await self.bot.cache.set('guild_data', ideal_staff, 'ideal_staff')
                    
                logging.info(f"[CacheLoader] Loaded guild ideal staff: {len(rows)} class configurations for {len(ideal_staff)} guilds")
                self._loaded_categories.add('guild_ideal_staff')
            else:
                logging.warning("[CacheLoader] No guild ideal staff data found in database")
                await self.bot.cache.set('guild_data', {}, 'ideal_staff')
                self._loaded_categories.add('guild_ideal_staff')
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading guild ideal staff: {e}", exc_info=True)
    
    async def ensure_games_list_loaded(self) -> None:
        """Load games list data for all games."""
        if 'games_list' in self._loaded_categories:
            return
            
        logging.debug("[CacheLoader] Loading games list data")
        query = "SELECT id, game_name, max_members FROM games_list"
        
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            if rows:
                games_data = {}
                for row in rows:
                    game_id, game_name, max_members = row
                    
                    games_data[game_id] = {
                        'game_name': game_name,
                        'max_members': max_members
                    }
                
                await self.bot.cache.set_static_data('games_list', games_data)
                    
                logging.info(f"[CacheLoader] Loaded games list: {len(rows)} games")
                self._loaded_categories.add('games_list')
            else:
                logging.warning("[CacheLoader] No games list data found in database")
                await self.bot.cache.set_static_data('games_list', {})
                self._loaded_categories.add('games_list')
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading games list: {e}", exc_info=True)

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
            self.ensure_user_setup_loaded(),
            self.ensure_weapons_loaded(),
            self.ensure_weapons_combinations_loaded(),
            self.ensure_guild_ideal_staff_loaded(),
            self.ensure_games_list_loaded(),
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
        elif category == 'static_groups':
            await self.ensure_static_groups_loaded()
        elif category == 'user_setup':
            await self.ensure_user_setup_loaded()
        elif category == 'weapons':
            await self.ensure_weapons_loaded()
        elif category == 'weapons_combinations':
            await self.ensure_weapons_combinations_loaded()
        elif category == 'guild_ideal_staff':
            await self.ensure_guild_ideal_staff_loaded()
        elif category == 'games_list':
            await self.ensure_games_list_loaded()
        elif category == 'guild_ptb_settings':
            await self.ensure_guild_ptb_settings_loaded()
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

    async def ensure_guild_ptb_settings_loaded(self) -> None:
        """Ensure guild PTB settings are loaded."""
        if 'guild_ptb_settings' in self._loaded_categories:
            return
        
        query = """
        SELECT guild_id, ptb_guild_id, info_channel_id,
               g1_role_id, g1_channel_id, g2_role_id, g2_channel_id,
               g3_role_id, g3_channel_id, g4_role_id, g4_channel_id,
               g5_role_id, g5_channel_id, g6_role_id, g6_channel_id,
               g7_role_id, g7_channel_id, g8_role_id, g8_channel_id,
               g9_role_id, g9_channel_id, g10_role_id, g10_channel_id,
               g11_role_id, g11_channel_id, g12_role_id, g12_channel_id
        FROM guild_ptb_settings
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id = int(row[0])
                ptb_settings = {
                    "ptb_guild_id": int(row[1]),
                    "info_channel_id": int(row[2]),
                    "groups": {}
                }
                
                # Process groups G1-G12
                for i in range(1, 13):
                    role_idx = 2 + (i-1) * 2 + 1
                    channel_idx = role_idx + 1
                    
                    if row[role_idx] and row[channel_idx]:
                        ptb_settings["groups"][f"G{i}"] = {
                            "role_id": int(row[role_idx]),
                            "channel_id": int(row[channel_idx])
                        }

                await self.bot.cache.set_guild_data(guild_id, 'ptb_settings', ptb_settings)
            
            self._loaded_categories.add('guild_ptb_settings')
            logging.debug(f"[CacheLoader] PTB settings loaded for {len(rows) if rows else 0} guilds")
        except Exception as e:
            logging.error(f"[CacheLoader] Error loading guild PTB settings: {e}", exc_info=True)

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