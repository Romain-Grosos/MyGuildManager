"""
Guild PTB Cog - Manages Public Test Branch servers for guild event coordination.
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, TypedDict

import discord
import pytz
from discord.ext import commands

from core.logger import ComponentLogger
from core.reliability import discord_resilient
from core.translation import translations as global_translations

GUILD_PTB = global_translations.get("guild_ptb", {})

_logger = ComponentLogger("guild_ptb")


class ActiveEventData(TypedDict):
    """Type definition for active event data structure."""
    groups_data: Dict[str, List[int]]
    assigned_members: List[int]
    start_time: str

def _safe_guild_id(guild_id: Any) -> Optional[int]:
    """Safely convert and validate guild ID."""
    try:
        if isinstance(guild_id, int):
            return guild_id if guild_id > 0 else None
        if isinstance(guild_id, str) and guild_id.isdigit():
            converted = int(guild_id)
            return converted if converted > 0 else None
        return None
    except (ValueError, TypeError):
        return None

def _safe_event_id(event_id: Any) -> Optional[int]:
    """Safely convert and validate event ID."""
    try:
        if isinstance(event_id, int):
            return event_id if event_id > 0 else None
        if isinstance(event_id, str) and event_id.isdigit():
            converted = int(event_id)
            return converted if converted > 0 else None
        return None
    except (ValueError, TypeError):
        return None

def _validate_groups_data(groups_data: Dict) -> bool:
    """Validate groups data structure."""
    if not isinstance(groups_data, dict):
        return False
    
    for group_name, member_ids in groups_data.items():
        if not (isinstance(group_name, str) and group_name.lower().startswith("g") and group_name[1:].isdigit()):
            return False
        
        # Enforce G1-G12 bounds
        try:
            group_num = int(group_name[1:])
            if not (1 <= group_num <= 12):
                return False
        except (ValueError, IndexError):
            return False
        if not isinstance(member_ids, (list, set, tuple)):
            return False
        if not all(isinstance(mid, int) and mid > 0 for mid in member_ids):
            return False
    
    return True

def _get_ptb_message(message_key: str, lang: str = "en-US", default: str = "") -> str:
    """Safely get PTB command message with fallback."""
    messages = (
        GUILD_PTB.get("commands", {})
        .get("ptb_init", {})
        .get("messages", {})
        .get(message_key, {})
    )
    if isinstance(messages, dict):
        return messages.get(lang, messages.get("en-US", default))
    return default

class GuildPTB(commands.Cog):
    """
    Cog for managing Public Test Branch servers for guild event coordination.

    This cog handles the creation, management, and coordination of Public Test Branch (PTB)
    Discord servers that are used for guild event organization and member coordination.
    It provides functionality for setting up PTB servers, managing member permissions,
    and coordinating events across main and PTB guilds.
    """

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the GuildPTB cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot

        self._ptb_settings_cache: Dict[int, Tuple[Dict, float]] = {}
        self._active_events_cache: Optional[Tuple[Dict[str, Any], float]] = None
        self._cache_ttl: float = 300.0

        self._events_locks: Dict[int, asyncio.Lock] = {}
        
        self._ptb_reverse_index_cache: Optional[Tuple[Dict[int, int], float]] = None
        
        self._register_admin_commands()
    
    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        """Get or create a lock for the given guild ID to prevent concurrent event modifications."""
        if guild_id not in self._events_locks:
            self._events_locks[guild_id] = asyncio.Lock()
        return self._events_locks[guild_id]
    
    async def _get_ptb_reverse_index(self) -> Dict[int, int]:
        """Get reverse index of ptb_guild_id -> main_guild_id with caching."""
        current_time = time.monotonic()
        
        if (self._ptb_reverse_index_cache is None or 
            current_time - self._ptb_reverse_index_cache[1] > self._cache_ttl):
            
            ptb_settings = await self.get_ptb_settings()
            reverse_index = {}
            
            for main_guild_id, settings in ptb_settings.items():
                ptb_guild_id = settings.get("ptb_guild_id")
                if ptb_guild_id:
                    reverse_index[ptb_guild_id] = main_guild_id
            
            self._ptb_reverse_index_cache = (reverse_index, current_time)
            _logger.debug("ptb_reverse_index_cached", entries=len(reverse_index))
        
        return self._ptb_reverse_index_cache[0]
    
    def _invalidate_ptb_reverse_index_cache(self) -> None:
        """Invalidate the PTB reverse index cache."""
        self._ptb_reverse_index_cache = None

    def _register_admin_commands(self):
        """Register PTB commands with the centralized admin_bot group."""
        if not hasattr(self.bot, "admin_group"):
            return

        cmd = GUILD_PTB.get("commands", {}).get("ptb_init", {})
        name = cmd.get("name", {}).get("en-US", "ptb-init")
        desc = cmd.get("description", {}).get("en-US", "Configure this guild as a PTB for a main guild.")
        name_loc = cmd.get("name", {}) or None
        desc_loc = cmd.get("description", {}) or None

        if getattr(self.bot, "_ptb_cmd_registered", False):
            return
            
        self.bot.admin_group.command(
            name=name,
            description=desc,
            name_localizations=name_loc,
            description_localizations=desc_loc,
        )(self.ptb_init)
        
        self.bot._ptb_cmd_registered = True

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Initialize PTB data when the bot becomes ready.

        This method is called when the bot has finished logging in and is ready
        to receive events. It starts the process of loading PTB data from cache.
        """
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        _logger.debug("waiting_for_initial_cache_load")

    def _is_cache_valid(self, timestamp: float) -> bool:
        """Check if cached data is still valid based on TTL."""
        return time.monotonic() - timestamp < self._cache_ttl

    def _invalidate_ptb_settings_cache(self, guild_id: Optional[int] = None) -> None:
        """Invalidate PTB settings cache for a specific guild or all guilds."""
        if guild_id is not None:
            self._ptb_settings_cache.pop(guild_id, None)
            _logger.debug("ptb_settings_cache_invalidated", guild_id=guild_id)
        else:
            self._ptb_settings_cache.clear()
            _logger.debug("all_ptb_settings_cache_invalidated")

    def _invalidate_active_events_cache(self) -> None:
        """Invalidate active events cache."""
        self._active_events_cache = None
        _logger.debug("active_events_cache_invalidated")

    async def get_ptb_settings(self) -> Dict:
        """
        Get PTB settings for all guilds from centralized cache.

        Returns:
            Dict: A dictionary mapping guild IDs to their PTB settings,
                 containing only guilds that have PTB configurations
        """
        all_ptb_settings = {}
        for guild in self.bot.guilds:
            guild_ptb_settings = await self.bot.cache.get_guild_data(
                guild.id, "ptb_settings"
            )
            if guild_ptb_settings:
                all_ptb_settings[guild.id] = guild_ptb_settings

        return all_ptb_settings

    async def get_guild_ptb_settings(self, guild_id: int) -> Dict:
        """
        Get PTB settings for a specific guild with local cache optimization.

        Args:
            guild_id: The ID of the guild to get PTB settings for

        Returns:
            Dict: The PTB settings for the specified guild, or empty dict if none found
        """
        if guild_id in self._ptb_settings_cache:
            cached_data, timestamp = self._ptb_settings_cache[guild_id]
            if self._is_cache_valid(timestamp):
                _logger.debug("ptb_settings_cache_hit", guild_id=guild_id)
                return cached_data
            else:
                del self._ptb_settings_cache[guild_id]
                _logger.debug("ptb_settings_cache_expired", guild_id=guild_id)

        result = await self.bot.cache.get_guild_data(guild_id, "ptb_settings")
        if not result:
            _logger.debug("no_ptb_settings_found", guild_id=guild_id)
            result = {}

        self._ptb_settings_cache[guild_id] = (result, time.monotonic())
        _logger.debug("ptb_settings_cached", guild_id=guild_id)
        
        return result

    async def get_active_events(self) -> Dict:
        """
        Get active events with local cache optimization.

        Returns:
            Dict: Dictionary of active PTB events, organized by guild ID and event ID
        """
        if self._active_events_cache is not None:
            cached_data, timestamp = self._active_events_cache
            if self._is_cache_valid(timestamp):
                _logger.debug("active_events_cache_hit")
                return cached_data
            else:
                self._active_events_cache = None
                _logger.debug("active_events_cache_expired")

        active_events = await self.bot.cache.get("temporary", "ptb_active_events")
        if not active_events:
            active_events = {}

        self._active_events_cache = (active_events, time.monotonic())
        _logger.debug("active_events_cached")
        
        return active_events

    async def set_active_events(self, active_events: Dict) -> None:
        """
        Set active events in temporary cache and update local cache.

        Args:
            active_events: Dictionary of active events to store in cache
        """
        await self.bot.cache.set("temporary", active_events, "ptb_active_events")

        self._active_events_cache = (active_events, time.monotonic())
        _logger.debug("active_events_updated_and_cached")

    async def _verify_ptb_ownership(
        self, main_guild_id: int, ptb_guild_id: int
    ) -> bool:
        """
        Verify PTB guild ownership and permissions.

        This method ensures that the bot has proper access and permissions in the PTB guild,
        and that the PTB guild is correctly associated with the main guild.

        Args:
            main_guild_id: The ID of the main guild that owns the PTB
            ptb_guild_id: The ID of the PTB guild to verify

        Returns:
            bool: True if ownership and permissions are valid, False otherwise
        """
        try:
            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                _logger.error("ptb_guild_not_found", ptb_guild_id=ptb_guild_id)
                return False

            bot_member = ptb_guild.get_member(self.bot.user.id)
            if not bot_member:
                _logger.error("bot_not_member_of_ptb_guild", ptb_guild_id=ptb_guild_id)
                return False

            if (
                ptb_guild.owner_id != self.bot.user.id
                and not bot_member.guild_permissions.administrator
            ):
                _logger.error("bot_lacks_permissions_in_ptb", ptb_guild_id=ptb_guild_id)
                return False

            guild_ptb_settings = await self.get_guild_ptb_settings(main_guild_id)
            if not guild_ptb_settings:
                _logger.error("no_ptb_settings_for_main_guild", main_guild_id=main_guild_id)
                return False

            stored_ptb_guild_id = guild_ptb_settings.get("ptb_guild_id")
            if stored_ptb_guild_id != ptb_guild_id:
                _logger.error("ptb_guild_id_mismatch", main_guild_id=main_guild_id, expected=ptb_guild_id, actual=stored_ptb_guild_id)
                return False

            expected_roles = [f"G{i}" for i in range(1, 13)]
            existing_roles = [
                role.name
                for role in ptb_guild.roles
                if role.name.startswith("G") and role.name[1:].isdigit()
            ]

            if len(existing_roles) < 12:
                _logger.warning("ptb_guild_missing_roles", ptb_guild_id=ptb_guild_id, found_roles=len(existing_roles), expected_roles=12)

            return True

        except Exception as e:
            _logger.error("error_verifying_ptb_ownership", error=str(e), exc_info=True)
            return False

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def initialize_ptb_server(
        self, main_guild_id: int, authorized_user_id: Optional[int] = None
    ) -> bool:
        """
        Initialize a new PTB server for a main guild.

        NOTE: This method is disabled as bots cannot reliably create guilds in production.
        Use the /ptb_init command instead to configure an existing guild as a PTB.

        Args:
            main_guild_id: The ID of the main guild to create a PTB for
            authorized_user_id: The ID of the user authorizing the PTB creation

        Returns:
            bool: Always returns False as this feature is disabled

        Raises:
            Exception: If there's an error during PTB creation or setup
        """
        _logger.warning(
            "ptb_auto_creation_disabled_use_ptb_init", 
            main_guild_id=main_guild_id,
            authorized_user_id=authorized_user_id,
            alternative="Use /ptb_init command to configure an existing guild as PTB"
        )
        return False

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def _setup_ptb_structure(
        self, main_guild_id: int, ptb_guild: discord.Guild
    ) -> bool:
        """
        Setup the structure of a PTB guild with roles and channels.

        Creates all necessary roles (G1-G12), voice channels, and an info channel
        with appropriate permissions for the PTB guild.

        Args:
            main_guild_id: The ID of the main guild this PTB belongs to
            ptb_guild: The PTB guild object to set up

        Returns:
            bool: True if structure was successfully set up, False otherwise

        Raises:
            Exception: If there's an error during structure setup
        """
        try:
            roles = {}
            for i in range(1, 13):
                group_name = f"G{i}"
                existing_role = discord.utils.get(ptb_guild.roles, name=group_name)
                
                if existing_role:
                    roles[group_name] = existing_role
                    _logger.debug("ptb_role_exists", group=group_name, role_id=existing_role.id)
                else:
                    role = await ptb_guild.create_role(
                        name=group_name, mentionable=True, reason="PTB Group Role"
                    )
                    roles[group_name] = role
                    _logger.debug("ptb_role_created", group=group_name, role_id=role.id)

            ptb_category = discord.utils.get(ptb_guild.categories, name="PTB")
            
            if not ptb_category:
                category_overwrites = {
                    ptb_guild.default_role: discord.PermissionOverwrite(
                        view_channel=False,
                        create_instant_invite=False,
                    )
                }
                ptb_category = await ptb_guild.create_category(
                    name="PTB", 
                    overwrites=category_overwrites,
                    reason="PTB Category"
                )
                _logger.debug("ptb_category_created", category_id=ptb_category.id)
            else:
                _logger.debug("ptb_category_exists", category_id=ptb_category.id)

            existing_info_channel = discord.utils.get(ptb_guild.text_channels, name="infos")
            
            if existing_info_channel:
                info_channel = existing_info_channel
                if info_channel.category != ptb_category:
                    await info_channel.edit(category=ptb_category)
                _logger.debug("ptb_info_channel_exists", channel_id=info_channel.id)
            else:
                info_overwrites = {
                    ptb_guild.default_role: discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=False,
                        add_reactions=True,
                        read_message_history=True,
                        create_instant_invite=False,
                    )
                }

                info_channel = await ptb_guild.create_text_channel(
                    name="infos", 
                    overwrites=info_overwrites, 
                    category=ptb_category,
                    reason="PTB Info Channel"
                )
                _logger.debug("ptb_info_channel_created", channel_id=info_channel.id)

            channels = {}
            for i in range(1, 13):
                group_name = f"G{i}"
                chan = discord.utils.get(ptb_guild.voice_channels, name=group_name)

                overwrites = {
                    ptb_guild.default_role: discord.PermissionOverwrite(
                        view_channel=False,
                        create_instant_invite=False,
                    ),
                    roles[group_name]: discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True, use_voice_activation=True
                    ),
                }

                if chan:
                    await chan.edit(category=ptb_category, overwrites=overwrites, reason="PTB Group Voice Channel")
                    channels[group_name] = chan
                    _logger.debug("ptb_voice_channel_updated", group=group_name, channel_id=chan.id)
                else:
                    chan = await ptb_guild.create_voice_channel(
                        name=group_name, category=ptb_category, overwrites=overwrites, reason="PTB Group Voice Channel"
                    )
                    channels[group_name] = chan
                    _logger.debug("ptb_voice_channel_created", group=group_name, channel_id=chan.id)

            try:
                new_permissions = ptb_guild.default_role.permissions
                new_permissions.update(change_nickname=False)
                await ptb_guild.default_role.edit(
                    permissions=new_permissions,
                    reason="PTB Configuration - Disable nickname changes for @everyone",
                )
                _logger.debug("removed_change_nickname_permission")
            except Exception as e:
                _logger.warning("could_not_remove_change_nickname", error=str(e))

            await self._save_ptb_settings(
                main_guild_id, ptb_guild.id, info_channel.id, roles, channels
            )

            return True

        except Exception as e:
            _logger.error("error_setting_up_ptb_structure", error=str(e), exc_info=True)
            return False

    async def _save_ptb_settings(
        self,
        main_guild_id: int,
        ptb_guild_id: int,
        info_channel_id: int,
        roles: Dict[str, discord.Role],
        channels: Dict[str, discord.VoiceChannel],
    ) -> None:
        """
        Save PTB settings to database and update cache.

        Stores all PTB configuration data including role IDs, channel IDs,
        and other settings in the database and updates the cache.

        Args:
            main_guild_id: The ID of the main guild
            ptb_guild_id: The ID of the PTB guild
            info_channel_id: The ID of the info channel
            roles: Dictionary mapping group names to Discord role objects
            channels: Dictionary mapping group names to Discord voice channel objects

        Raises:
            Exception: If there's an error saving settings to database
        """
        try:
            data = {
                "guild_id": main_guild_id,
                "ptb_guild_id": ptb_guild_id,
                "info_channel_id": info_channel_id,
            }

            for i in range(1, 13):
                group_key = f"G{i}"
                data[f"g{i}_role_id"] = roles[group_key].id
                data[f"g{i}_channel_id"] = channels[group_key].id

            query = """
            INSERT INTO guild_ptb_settings (
                guild_id, ptb_guild_id, info_channel_id,
                g1_role_id, g1_channel_id, g2_role_id, g2_channel_id,
                g3_role_id, g3_channel_id, g4_role_id, g4_channel_id,
                g5_role_id, g5_channel_id, g6_role_id, g6_channel_id,
                g7_role_id, g7_channel_id, g8_role_id, g8_channel_id,
                g9_role_id, g9_channel_id, g10_role_id, g10_channel_id,
                g11_role_id, g11_channel_id, g12_role_id, g12_channel_id
            ) VALUES (
                %(guild_id)s, %(ptb_guild_id)s, %(info_channel_id)s,
                %(g1_role_id)s, %(g1_channel_id)s, %(g2_role_id)s, %(g2_channel_id)s,
                %(g3_role_id)s, %(g3_channel_id)s, %(g4_role_id)s, %(g4_channel_id)s,
                %(g5_role_id)s, %(g5_channel_id)s, %(g6_role_id)s, %(g6_channel_id)s,
                %(g7_role_id)s, %(g7_channel_id)s, %(g8_role_id)s, %(g8_channel_id)s,
                %(g9_role_id)s, %(g9_channel_id)s, %(g10_role_id)s, %(g10_channel_id)s,
                %(g11_role_id)s, %(g11_channel_id)s, %(g12_role_id)s, %(g12_channel_id)s
            )
            ON DUPLICATE KEY UPDATE
                ptb_guild_id = VALUES(ptb_guild_id),
                info_channel_id = VALUES(info_channel_id),
                g1_role_id = VALUES(g1_role_id), g1_channel_id = VALUES(g1_channel_id),
                g2_role_id = VALUES(g2_role_id), g2_channel_id = VALUES(g2_channel_id),
                g3_role_id = VALUES(g3_role_id), g3_channel_id = VALUES(g3_channel_id),
                g4_role_id = VALUES(g4_role_id), g4_channel_id = VALUES(g4_channel_id),
                g5_role_id = VALUES(g5_role_id), g5_channel_id = VALUES(g5_channel_id),
                g6_role_id = VALUES(g6_role_id), g6_channel_id = VALUES(g6_channel_id),
                g7_role_id = VALUES(g7_role_id), g7_channel_id = VALUES(g7_channel_id),
                g8_role_id = VALUES(g8_role_id), g8_channel_id = VALUES(g8_channel_id),
                g9_role_id = VALUES(g9_role_id), g9_channel_id = VALUES(g9_channel_id),
                g10_role_id = VALUES(g10_role_id), g10_channel_id = VALUES(g10_channel_id),
                g11_role_id = VALUES(g11_role_id), g11_channel_id = VALUES(g11_channel_id),
                g12_role_id = VALUES(g12_role_id), g12_channel_id = VALUES(g12_channel_id)
            """

            await self.bot.run_db_query(query, data, commit=True)

            await self.bot.cache.delete_guild_data(main_guild_id, "ptb_settings")
            await self.bot.cache_loader.reload_category("guild_ptb_settings")

            self._invalidate_ptb_settings_cache(main_guild_id)
            self._invalidate_ptb_reverse_index_cache()

            _logger.info("ptb_settings_saved", main_guild_id=main_guild_id)

        except Exception as e:
            _logger.error("error_saving_ptb_settings", error=str(e), exc_info=True)
            raise

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def assign_event_permissions(
        self, main_guild_id: int, event_id: int, groups_data: Dict
    ) -> bool:
        """
        Assign event permissions to PTB guild members based on group assignments.

        Assigns roles to members in the PTB guild based on their group assignments
        for a specific event, sends event recap, and invites missing members.

        Args:
            main_guild_id: The ID of the main guild
            event_id: The ID of the event
            groups_data: Dictionary mapping group names to lists of member IDs

        Returns:
            bool: True if permissions were successfully assigned, False otherwise
        """
        try:
            safe_main_guild_id = _safe_guild_id(main_guild_id)
            safe_event_id = _safe_event_id(event_id)
            
            if not safe_main_guild_id or not safe_event_id:
                _logger.error("invalid_input_for_event_permissions", main_guild_id=main_guild_id, event_id=event_id)
                return False
                
            if not _validate_groups_data(groups_data):
                _logger.error("invalid_groups_data_structure", main_guild_id=safe_main_guild_id, event_id=safe_event_id)
                return False

            main_guild_id = safe_main_guild_id
            event_id = safe_event_id
            
            ptb_settings = await self.get_guild_ptb_settings(main_guild_id)
            if not ptb_settings:
                _logger.error("no_ptb_configuration_found", main_guild_id=main_guild_id)
                return False
            
            ptb_guild_id = ptb_settings.get("ptb_guild_id")
            if not ptb_guild_id:
                _logger.error("no_ptb_guild_id_in_settings", main_guild_id=main_guild_id)
                return False

            if not await self._verify_ptb_ownership(main_guild_id, ptb_guild_id):
                _logger.error("ptb_ownership_verification_failed", main_guild_id=main_guild_id)
                return False

            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                _logger.error("ptb_guild_not_found_after_verification", ptb_guild_id=ptb_guild_id)
                return False

            async with self._lock_for(main_guild_id):
                active_events = await self.get_active_events()
                if main_guild_id not in active_events:
                    active_events[main_guild_id] = {}

                normalized_groups = {
                    k: list(v) if not isinstance(v, list) else v
                    for k, v in groups_data.items()
                }

                active_events[main_guild_id][event_id] = {
                    "groups_data": normalized_groups,
                    "assigned_members": [],
                    "start_time": datetime.now(pytz.utc).isoformat()
                }
                await self.set_active_events(active_events)

            missing_groups = []
            for group_name in normalized_groups.keys():
                group_num = group_name.lower()
                role_key = f"{group_num}_role_id"
                if role_key not in ptb_settings:
                    missing_groups.append(group_name)

            if missing_groups:
                _logger.debug("missing_group_configs_reloading", 
                            missing_groups=missing_groups,
                            missing_groups_count=len(missing_groups))
                await self.bot.cache_loader.reload_category("guild_ptb_settings")
                await self.bot.cache.delete_guild_data(main_guild_id, "ptb_settings")
                self._invalidate_ptb_settings_cache(main_guild_id)
                ptb_settings = await self.get_guild_ptb_settings(main_guild_id)
                if not ptb_settings:
                    _logger.error("no_ptb_settings_after_reload", main_guild_id=main_guild_id)
                    return False

            info_channel_id = ptb_settings.get("info_channel_id")
            if not info_channel_id:
                _logger.warning("no_info_channel_id_in_settings", main_guild_id=main_guild_id)

            tasks = [
                self._assign_roles_to_members(ptb_guild, ptb_settings, normalized_groups),
                self._send_invitations_to_missing_members(main_guild_id, ptb_guild, normalized_groups),
            ]

            if info_channel_id:
                tasks.append(self._send_event_recap(ptb_guild, info_channel_id, event_id, normalized_groups))
            
            await asyncio.gather(*tasks, return_exceptions=True)

            _logger.info("event_permissions_assigned", event_id=event_id, main_guild_id=main_guild_id)
            return True

        except Exception as e:
            _logger.error("error_assigning_event_permissions", error=str(e), exc_info=True)
            return False

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def _assign_roles_to_members(
        self, ptb_guild: discord.Guild, ptb_settings: Dict, groups_data: Dict[str, List[int]]
    ) -> None:
        """
        Assign roles to PTB guild members based on group data.

        Args:
            ptb_guild: The PTB guild object
            ptb_settings: Dictionary containing PTB configuration settings
            groups_data: Dictionary mapping group names to lists of member IDs
        """
        try:
            role_tasks = []
            total_groups = 0
            
            for group_name, member_ids in groups_data.items():
                group_num = group_name.lower()
                role_key = f"{group_num}_role_id"

                role_id = ptb_settings.get(role_key)
                if not role_id:
                    _logger.warning("group_role_not_found_in_ptb_settings", group_name=group_name, role_key=role_key)
                    continue

                role = ptb_guild.get_role(role_id)

                if not role:
                    _logger.error("role_not_found_in_ptb_guild", group_name=group_name)
                    continue

                group_additions = 0
                for member_id in member_ids:
                    member = ptb_guild.get_member(member_id)
                    if member and role not in member.roles:
                        role_tasks.append(self._add_role_to_member_safe(member, role, group_name))
                        group_additions += 1
                
                if group_additions > 0:
                    total_groups += 1

            batch_size = 25
            for i in range(0, len(role_tasks), batch_size):
                batch = role_tasks[i:i + batch_size]
                await asyncio.gather(*batch, return_exceptions=True)

                if i + batch_size < len(role_tasks):
                    await asyncio.sleep(0.5)

            _logger.info("role_assignment_summary", 
                        total_role_additions=len(role_tasks), 
                        groups_processed=total_groups)

        except Exception as e:
            _logger.error("error_assigning_roles_to_members", error=str(e), exc_info=True)

    async def _add_role_to_member_safe(self, member: discord.Member, role: discord.Role, group_name: str) -> None:
        """Safely add role to member with error handling."""
        try:
            await member.add_roles(role, reason=f"Event group assignment: {group_name}")
            _logger.debug("role_added_to_member", group_name=group_name, member_id=member.id, member_name=member.display_name)
        except Exception as e:
            _logger.error("error_adding_role_to_member", member_id=member.id, member_name=member.display_name, error=str(e))

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def _send_event_recap(
        self,
        ptb_guild: discord.Guild,
        info_channel_id: int,
        event_id: int,
        groups_data: Dict[str, List[int]],
    ) -> None:
        """
        Send event recap to PTB info channel.

        Creates and sends an embed message to the PTB info channel with details
        about the event and group assignments.

        Args:
            ptb_guild: The PTB guild object
            info_channel_id: The ID of the info channel
            event_id: The ID of the event
            groups_data: Dictionary mapping group names to lists of member IDs
        """
        try:
            info_channel = ptb_guild.get_channel(info_channel_id)
            if not info_channel:
                _logger.error("info_channel_not_found", info_channel_id=info_channel_id)
                return

            guild_lang = "en-US"

            reverse_index = await self._get_ptb_reverse_index()
            main_guild_id = reverse_index.get(ptb_guild.id)

            if main_guild_id:
                guild_lang = (
                    await self.bot.cache.get_guild_data(main_guild_id, "guild_lang")
                    or "en-US"
                )

            title_template = (
                GUILD_PTB.get("event_recap", {})
                .get("title", {})
                .get(guild_lang) or 
                GUILD_PTB.get("event_recap", {})
                .get("title", {})
                .get("en-US", "Event Recap - {event_id}")
            )
            title = title_template.format(event_id=event_id)
            
            description = (
                GUILD_PTB.get("event_recap", {})
                .get("description", {})
                .get(guild_lang) or 
                GUILD_PTB.get("event_recap", {})
                .get("description", {})
                .get("en-US", "Groups assigned for this event")
            )
            
            footer_text = (
                GUILD_PTB.get("event_recap", {})
                .get("footer", {})
                .get(guild_lang) or 
                GUILD_PTB.get("event_recap", {})
                .get("footer", {})
                .get("en-US", "Event summary")
            )

            embed = discord.Embed(
                title=title,
                description=description,
                color=0x00FF00,
                timestamp=datetime.now(pytz.utc),
            )

            for group_name, member_ids in groups_data.items():
                members_list = []
                for member_id in member_ids:
                    member = ptb_guild.get_member(member_id)
                    if member:
                        members_list.append(member.display_name)
                    else:
                        members_list.append(f"<@{member_id}>")

                if members_list:
                    if len(members_list) <= 10:
                        value = "\n".join(members_list)
                    else:
                        members_count_template = (
                            GUILD_PTB.get("event_recap", {})
                            .get("members_count", {})
                            .get(guild_lang) or 
                            GUILD_PTB.get("event_recap", {})
                            .get("members_count", {})
                            .get("en-US", "{count} members")
                        )
                        members_count_text = members_count_template.format(count=len(members_list))
                        value = members_count_text

                    embed.add_field(name=f"🎯 {group_name}", value=value, inline=True)

            embed.set_footer(text=footer_text)

            perms = info_channel.permissions_for(ptb_guild.me)
            if not (perms.send_messages and perms.embed_links):
                _logger.error("missing_send_or_embed_permissions", channel_id=info_channel.id)
                return

            await info_channel.send(embed=embed)
            _logger.debug("event_recap_sent", event_id=event_id)

        except Exception as e:
            _logger.error("error_sending_event_recap", error=str(e), exc_info=True)

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def _send_invitations_to_missing_members(
        self, main_guild_id: int, ptb_guild: discord.Guild, groups_data: Dict[str, List[int]]
    ) -> None:
        """
        Send invitations to members who are not yet in the PTB guild.

        Creates an invite link and sends it via DM to members who are assigned
        to groups but are not yet present in the PTB guild.

        Args:
            main_guild_id: The ID of the main guild
            ptb_guild: The PTB guild object
            groups_data: Dictionary mapping group names to lists of member IDs
        """
        try:
            main_guild = self.bot.get_guild(main_guild_id)
            if not main_guild:
                return

            info_channel = None

            infos_channel = discord.utils.get(ptb_guild.text_channels, name="infos")
            if infos_channel and infos_channel.permissions_for(ptb_guild.me).create_instant_invite:
                info_channel = infos_channel
            else:
                for channel in ptb_guild.text_channels:
                    if channel.permissions_for(ptb_guild.me).create_instant_invite:
                        info_channel = channel
                        break

            if not info_channel:
                _logger.error("no_suitable_channel_for_invite")
                return

            invite = await info_channel.create_invite(
                max_age=3600, max_uses=0, reason="Event group assignment invitation"
            )

            all_member_ids = set()
            for member_ids in groups_data.values():
                all_member_ids.update(member_ids)

            guild_lang = (
                await self.bot.cache.get_guild_data(main_guild_id, "guild_lang")
                or "en-US"
            )

            invitation_message = (
                GUILD_PTB["invitation"]["dm_message"]
                .get(guild_lang, GUILD_PTB["invitation"]["dm_message"].get("en-US"))
                .format(invite_url=invite.url)
            )

            dm_count = 0
            for member_id in all_member_ids:
                ptb_member = ptb_guild.get_member(member_id)
                if not ptb_member:
                    main_member = main_guild.get_member(member_id)
                    if main_member:
                        try:
                            await main_member.send(invitation_message)
                            dm_count += 1
                            _logger.debug("ptb_invitation_sent", member_id=main_member.id, member_name=main_member.display_name)

                            if dm_count % 25 == 0:
                                await asyncio.sleep(0.5)
                                
                        except discord.HTTPException as e:
                            if e.status == 403:
                                _logger.warning("dm_forbidden", member_id=main_member.id)
                            else:
                                _logger.warning("dm_http_error", member_id=main_member.id, status=e.status, text=getattr(e, "text", None))
                        except discord.Forbidden:
                            _logger.warning("cannot_send_dm_to_member", member_id=main_member.id, member_name=main_member.display_name)
                        except Exception as e:
                            _logger.error("error_sending_invitation", member_id=main_member.id, member_name=main_member.display_name, error=str(e))

        except Exception as e:
            _logger.error("error_sending_invitations", error=str(e), exc_info=True)

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def remove_event_permissions(self, main_guild_id: int, event_id: int) -> bool:
        """
        Remove event permissions from PTB guild members after event ends.

        Removes all group roles from members and cleans up active event data
        when an event concludes.

        Args:
            main_guild_id: The ID of the main guild
            event_id: The ID of the event that ended

        Returns:
            bool: True if permissions were successfully removed, False otherwise
        """
        try:
            safe_main_guild_id = _safe_guild_id(main_guild_id)
            safe_event_id = _safe_event_id(event_id)
            
            if not safe_main_guild_id or not safe_event_id:
                _logger.error("invalid_input_for_remove_permissions", main_guild_id=main_guild_id, event_id=event_id)
                return False

            main_guild_id, event_id = safe_main_guild_id, safe_event_id

            ptb_settings = await self.get_guild_ptb_settings(main_guild_id)
            if not ptb_settings:
                _logger.error("no_ptb_settings_found_for_removal", main_guild_id=main_guild_id)
                return False

            ptb_guild_id = ptb_settings.get("ptb_guild_id")
            if not ptb_guild_id or not await self._verify_ptb_ownership(main_guild_id, ptb_guild_id):
                _logger.error("ptb_ownership_verification_failed_during_cleanup", main_guild_id=main_guild_id)
                return False

            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                _logger.error("ptb_guild_not_found_after_verification_cleanup", ptb_guild_id=ptb_guild_id)
                return False

            async with self._lock_for(main_guild_id):
                active_events = await self.get_active_events()
                if main_guild_id not in active_events or event_id not in active_events[main_guild_id]:
                    _logger.warning("no_active_event_found", main_guild_id=main_guild_id, event_id=event_id)
                    return False

                groups_data = active_events[main_guild_id][event_id]["groups_data"]
                total_role_removals = 0
                total_groups = 0

                for group_name, member_ids in groups_data.items():
                    role_id = ptb_settings.get(f"{group_name.lower()}_role_id")
                    if not role_id:
                        continue
                    role = ptb_guild.get_role(role_id)
                    if not role:
                        continue

                    group_removals = 0
                    for member_id in member_ids:
                        member = ptb_guild.get_member(member_id)
                        if member and role in member.roles:
                            try:
                                await member.remove_roles(role, reason=f"Event {event_id} ended")
                                group_removals += 1
                                total_role_removals += 1
                                _logger.debug("role_removed_from_member", group_name=group_name, member_id=member.id, member_name=member.display_name)
                            except Exception as e:
                                _logger.error("error_removing_role_from_member", member_id=member.id, member_name=member.display_name, error=str(e))
                    
                    if group_removals > 0:
                        total_groups += 1

                del active_events[main_guild_id][event_id]
                if not active_events[main_guild_id]:
                    del active_events[main_guild_id]
                await self.set_active_events(active_events)

            _logger.info("event_permissions_removed", 
                        event_id=event_id, 
                        total_role_removals=total_role_removals, 
                        groups_processed=total_groups)
            return True

        except Exception as e:
            _logger.error("error_removing_event_permissions", error=str(e), exc_info=True)
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Handle member joining PTB guild - auto-assign roles if part of active event.

        When a member joins a PTB guild, automatically assigns appropriate roles
        if they are part of any active events, and syncs their nickname from the main guild.

        Args:
            member: The Discord member who joined the guild
        """
        try:
            ptb_guild_id = member.guild.id

            reverse_index = await self._get_ptb_reverse_index()
            main_guild_id = reverse_index.get(ptb_guild_id)

            if not main_guild_id:
                _logger.debug("member_joined_non_ptb_guild", member_id=member.id, member_name=member.display_name, guild_id=ptb_guild_id)
                return

            _logger.info("member_joined_ptb_guild", member_id=member.id, member_name=member.display_name, ptb_guild_id=ptb_guild_id, main_guild_id=main_guild_id)

            active_events = await self.get_active_events()
            if main_guild_id in active_events:
                guild_ptb_settings = await self.get_guild_ptb_settings(main_guild_id)

                for event_id, event_data in active_events[main_guild_id].items():
                    groups_data = event_data["groups_data"]

                    for group_name, member_ids in groups_data.items():
                        if member.id in member_ids:
                            group_num = group_name.lower()
                            role_key = f"{group_num}_role_id"

                            role_id = guild_ptb_settings.get(role_key)
                            if role_id:
                                role = member.guild.get_role(role_id)

                                if role and role not in member.roles:
                                    try:
                                        await member.add_roles(
                                            role,
                                            reason=f"Auto-assignment for event {event_id}",
                                        )
                                        _logger.info("auto_assigned_role_for_event", group_name=group_name, member_id=member.id, member_name=member.display_name, event_id=event_id)
                                    except Exception as e:
                                        _logger.error("failed_auto_role_assignment", member_id=member.id, error=str(e))

            await self._sync_nickname_from_main(member, main_guild_id)

        except Exception as e:
            _logger.error("error_handling_member_join", error=str(e), exc_info=True)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """Clean up caches when bot leaves a guild."""
        self._events_locks.pop(guild.id, None)
        self._ptb_settings_cache.pop(guild.id, None)
        self._invalidate_ptb_reverse_index_cache()
        _logger.info("guild_cleanup_on_leave", guild_id=guild.id)

    @discord_resilient(service_name="discord_api", max_retries=2)
    async def _sync_nickname_from_main(
        self, ptb_member: discord.Member, main_guild_id: int
    ):
        """
        Synchronize nickname from main guild to PTB guild.

        Updates the member's nickname in the PTB guild to match their
        display name in the main guild.

        Args:
            ptb_member: The member in the PTB guild
            main_guild_id: The ID of the main guild to sync from
        """
        try:
            _logger.debug("attempting_nickname_sync", member_id=ptb_member.id, member_name=ptb_member.display_name, main_guild_id=main_guild_id)

            main_guild = self.bot.get_guild(main_guild_id)
            if not main_guild:
                _logger.warning("main_guild_not_found_for_nickname_sync", main_guild_id=main_guild_id)
                return

            main_member = main_guild.get_member(ptb_member.id)
            if not main_member:
                _logger.warning("member_not_found_in_main_guild_for_sync", member_id=ptb_member.id, main_guild_id=main_guild_id)
                return

            main_display_name = main_member.display_name
            _logger.debug("nickname_comparison", main_nickname=main_display_name, ptb_nickname=ptb_member.display_name)

            if ptb_member.display_name != main_display_name:
                try:
                    old_nickname = ptb_member.display_name
                    await ptb_member.edit(
                        nick=main_display_name,
                        reason="Synchronization from the main Discord",
                    )
                    _logger.info("nickname_synchronized", member_id=ptb_member.id, old_nickname=old_nickname, new_nickname=main_display_name)
                except discord.Forbidden:
                    _logger.warning("cannot_change_nickname_insufficient_permissions", member_id=ptb_member.id)
                except Exception as e:
                    _logger.error("error_changing_nickname", member_id=ptb_member.id, error=str(e))
            else:
                _logger.debug("nickname_already_synchronized", member_id=ptb_member.id)

        except Exception as e:
            _logger.error("error_synchronizing_nickname", error=str(e), exc_info=True)

    async def ptb_init(
        self,
        ctx: discord.ApplicationContext,
        main_guild_id: str = discord.Option(
            description=(
                GUILD_PTB.get("commands", {})
                .get("ptb_init", {})
                .get("options", {})
                .get("main_guild_id", {})
                .get("description", {})
                .get("en-US", "The ID of the main guild to configure PTB for")
            ),
            description_localizations=(
                GUILD_PTB.get("commands", {})
                .get("ptb_init", {})
                .get("options", {})
                .get("main_guild_id", {})
                .get("description", {})
                or None
            ),
        ),
    ):
        """
        Initialize PTB configuration for a main guild.

        This slash command allows authorized users to configure the current guild
        as a PTB (Public Test Branch) server for a specified main guild.

        Args:
            ctx: The Discord application context
            main_guild_id: The ID of the main guild to configure PTB for
        """
        try:
            guild_lang = "en-US"

            if (
                not ctx.author.guild_permissions.manage_guild
                and ctx.author.id != ctx.guild.owner_id
            ):
                error_msg = _get_ptb_message(
                    "no_permissions", 
                    guild_lang, 
                    "You don't have permission to use this command."
                )
                await ctx.respond(error_msg, ephemeral=True)
                return

            await ctx.defer()

            main_guild_id_int = _safe_guild_id(main_guild_id)
            if not main_guild_id_int:
                error_msg = _get_ptb_message(
                    "error", 
                    guild_lang, 
                    "Error: {error}"
                ).format(error="Invalid guild ID format")
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            main_guild = self.bot.get_guild(main_guild_id_int)
            if not main_guild:
                error_msg = _get_ptb_message(
                    "main_guild_not_found",
                    guild_lang,
                    "Main guild {guild_id} not found."
                ).format(guild_id=main_guild_id)
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            guild_lang = (
                await self.bot.cache.get_guild_data(main_guild_id_int, "guild_lang")
                or "en-US"
            )
            initialized = await self.bot.cache.get_guild_data(
                main_guild_id_int, "initialized"
            )

            if not initialized:
                error_msg = _get_ptb_message(
                    "main_guild_not_initialized",
                    guild_lang,
                    "Main guild {guild_id} is not initialized."
                ).format(guild_id=main_guild_id)
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            ptb_guild_id = await self.bot.cache.get_guild_data(
                main_guild_id_int, "guild_ptb"
            )
            if ptb_guild_id:
                error_msg = _get_ptb_message(
                    "main_guild_already_has_ptb",
                    guild_lang,
                    "Main guild {guild_id} already has a PTB configured."
                ).format(guild_id=main_guild_id)
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            ptb_settings = await self.get_ptb_settings()
            for existing_main_guild_id, settings in ptb_settings.items():
                if settings.get("ptb_guild_id") == ctx.guild.id:
                    error_msg = _get_ptb_message(
                        "ptb_already_configured",
                        guild_lang,
                        "This server is already configured as a PTB for guild {main_guild_id}."
                    ).format(main_guild_id=existing_main_guild_id)
                    await ctx.followup.send(error_msg, ephemeral=True)
                    return

            success = await self._setup_ptb_structure(main_guild_id_int, ctx.guild)

            if success:
                await self.bot.run_db_query(
                    "UPDATE guild_settings SET guild_ptb = %s WHERE guild_id = %s",
                    (ctx.guild.id, main_guild_id_int),
                    commit=True,
                )

                await self.bot.cache.set_guild_data(
                    main_guild_id_int, "guild_ptb", ctx.guild.id
                )

                success_msg = _get_ptb_message(
                    "success",
                    guild_lang,
                    "Successfully configured {ptb_name} as PTB for {main_guild_name}."
                ).format(ptb_name=ctx.guild.name, main_guild_name=main_guild.name)

                await ctx.followup.send(success_msg, ephemeral=True)
                _logger.info("ptb_configured_via_slash_command", author_id=ctx.author.id, ptb_guild_id=ctx.guild.id, main_guild_id=main_guild_id_int)
            else:
                error_msg = _get_ptb_message(
                    "error",
                    guild_lang,
                    "Error: {error}"
                ).format(error="PTB structure setup failed")

                await ctx.followup.send(error_msg, ephemeral=True)

        except Exception as e:
            error_msg = _get_ptb_message(
                "error",
                guild_lang,
                "Error: {error}"
            ).format(error=str(e))

            if ctx.response.is_done():
                await ctx.followup.send(error_msg, ephemeral=True)
            else:
                await ctx.respond(error_msg, ephemeral=True)

            _logger.error("error_in_ptb_init_command", error=str(e), exc_info=True)

    async def audit_ptb_security(self, main_guild_id: int) -> Dict:
        """
        Perform security audit on PTB configuration for a guild.

        Checks the PTB configuration for security issues, missing components,
        and proper permissions setup.

        Args:
            main_guild_id: The ID of the main guild to audit

        Returns:
            Dict: Audit report containing status, issues, and recommendations
        """
        audit_report = {
            "main_guild_id": main_guild_id,
            "status": "unknown",
            "issues": [],
            "recommendations": [],
        }

        try:
            ptb_guild_id = await self.bot.cache.get_guild_data(
                main_guild_id, "guild_ptb"
            )
            if not ptb_guild_id:
                audit_report["status"] = "no_ptb"
                audit_report["issues"].append("PTB guild ID not found in settings")
                return audit_report

            ownership_ok = await self._verify_ptb_ownership(main_guild_id, ptb_guild_id)
            if not ownership_ok:
                audit_report["status"] = "security_issue"
                audit_report["issues"].append("PTB ownership verification failed")
                audit_report["recommendations"].append(
                    "Re-initialize PTB or check bot permissions"
                )
                return audit_report

            ptb_guild = self.bot.get_guild(ptb_guild_id)
            main_guild = self.bot.get_guild(main_guild_id)

            if not ptb_guild or not main_guild:
                audit_report["status"] = "access_issue"
                audit_report["issues"].append("Cannot access PTB or main guild")
                return audit_report

            ptb_bot_member = ptb_guild.get_member(self.bot.user.id)
            main_bot_member = main_guild.get_member(self.bot.user.id)

            if not ptb_bot_member or not ptb_bot_member.guild_permissions.administrator:
                audit_report["issues"].append(
                    "Bot lacks administrator permissions in PTB"
                )

            if (
                not main_bot_member
                or not main_bot_member.guild_permissions.administrator
            ):
                audit_report["issues"].append(
                    "Bot lacks administrator permissions in main guild"
                )

            expected_roles = [f"G{i}" for i in range(1, 13)]
            existing_roles = [
                r.name for r in ptb_guild.roles if r.name in expected_roles
            ]
            missing_roles = set(expected_roles) - set(existing_roles)

            if missing_roles:
                audit_report["issues"].append(
                    f"Missing PTB roles: {', '.join(missing_roles)}"
                )

            expected_channels = [f"G{i}" for i in range(1, 13)] + ["infos"]
            existing_channels = [
                c.name for c in ptb_guild.channels if c.name in expected_channels
            ]
            missing_channels = set(expected_channels) - set(existing_channels)

            if missing_channels:
                audit_report["issues"].append(
                    f"Missing PTB channels: {', '.join(missing_channels)}"
                )

            if not audit_report["issues"]:
                audit_report["status"] = "secure"
            elif len(audit_report["issues"]) <= 2:
                audit_report["status"] = "minor_issues"
                audit_report["recommendations"].append(
                    "Address minor configuration issues"
                )
            else:
                audit_report["status"] = "major_issues"
                audit_report["recommendations"].append("Consider re-initializing PTB")

            audit_report["ptb_guild_id"] = ptb_guild_id
            audit_report["ptb_guild_name"] = ptb_guild.name
            audit_report["member_count"] = ptb_guild.member_count

        except Exception as e:
            audit_report["status"] = "error"
            audit_report["issues"].append(f"Audit failed: {str(e)}")
            _logger.error("error_during_security_audit", error=str(e), exc_info=True)

        return audit_report

def setup(bot: discord.Bot):
    """
    Setup function for the cog.

    Args:
        bot: The Discord bot instance to add the cog to
    """
    bot.add_cog(GuildPTB(bot))
