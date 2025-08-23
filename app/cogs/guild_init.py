"""
Guild Init Cog - Manages Discord server initialization and setup processes.
"""

import asyncio
import logging
import re
from typing import Any, Dict, Tuple, Protocol

import discord
from discord.ext import commands
from discord.utils import get

from core.functions import get_user_message
from core.rate_limiter import admin_rate_limit
from core.reliability import discord_resilient
from core.translation import translations as global_translations

_logger = logging.getLogger(__name__)

GUILD_INIT_DATA = global_translations.get("guild_init", {})


def tr(dic: dict, key: str, locale: str, default: str = "") -> str:
    """Safe translation fallback helper."""
    node = dic.get(key, {})
    return (node.get(locale) or node.get("en-US") or default) if isinstance(node, dict) else (node or default)


def sanitize_channel_name(s: str, max_len: int = 100) -> str:
    """Sanitize channel name for Discord limits."""
    s = s.strip()
    s = re.sub(r"\s+", "-", s.lower())
    s = re.sub(r"[^a-z0-9\-\u2600-\u26FF]", "-", s)
    return s[:max_len]


async def get_or_create_role(guild: discord.Guild, name: str, **kwargs) -> discord.Role:
    """Get existing role or create new one."""
    role = get(guild.roles, name=name)
    return role or await guild.create_role(name=name, reason="Guild initialization", **kwargs)


async def get_or_create_text_channel(guild: discord.Guild, name: str, category=None, **kwargs):
    """Get existing text channel or create new one."""
    ch = get(guild.text_channels, name=name, category=category)
    return ch or await guild.create_text_channel(name=name, category=category, reason="Guild initialization", **kwargs)


async def get_or_create_voice_channel(guild: discord.Guild, name: str, category=None, **kwargs):
    """Get existing voice channel or create new one."""
    ch = get(guild.voice_channels, name=name, category=category)
    return ch or await guild.create_voice_channel(name=name, category=category, reason="Guild initialization", **kwargs)


async def get_or_create_stage_channel(guild: discord.Guild, name: str, category=None, **kwargs):
    """Get existing stage channel or create new one."""
    ch = get(guild.stage_channels, name=name, category=category)
    return ch or await guild.create_stage_channel(name=name, category=category, reason="Guild initialization", **kwargs)


async def get_or_create_forum_channel(guild: discord.Guild, name: str, category=None, **kwargs):
    """Get existing forum channel or create new one."""
    ch = get([c for c in guild.channels if c.type == discord.ChannelType.forum], name=name, category=category)
    return ch or await guild.create_forum_channel(name=name, category=category, reason="Guild initialization", **kwargs)


async def get_or_create_category(guild: discord.Guild, name: str, **kwargs):
    """Get existing category or create new one."""
    cat = get(guild.categories, name=name)
    return cat or await guild.create_category(name=name, reason="Guild initialization", **kwargs)


class CacheProto(Protocol):
    """Protocol for bot cache interface."""
    async def get_guild_data(self, guild_id: int, key: str) -> Any: ...
    async def set_guild_data(self, guild_id: int, key: str, value: Any) -> None: ...
    async def invalidate_category(self, category: str) -> None: ...


class BotProto(Protocol):
    """Protocol for bot interface."""
    cache: CacheProto
    admin_group: Any
    cache_loader: Any
    
    async def run_db_query(self, query: str, values: Tuple, commit: bool = False) -> Any: ...


class GuildInit(commands.Cog):
    """
    Cog for managing Discord server initialization and setup processes.

    This cog provides functionality to initialize Discord servers with predefined
    roles and channels structure for guild management.
    """

    def __init__(self, bot: BotProto) -> None:
        """
        Initialize the GuildInit cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self._register_admin_commands()

    def _register_admin_commands(self):
        """Register guild init commands with the centralized admin_bot group."""
        if hasattr(self.bot, "admin_group"):

            self.bot.admin_group.command(
                name=GUILD_INIT_DATA["name"]["en-US"],
                description=GUILD_INIT_DATA["description"]["en-US"],
                name_localizations=GUILD_INIT_DATA["name"],
                description_localizations=GUILD_INIT_DATA["description"],
            )(self.discord_setup)

    @admin_rate_limit(cooldown_seconds=600)
    @discord_resilient(service_name="discord_api", max_retries=3)
    async def discord_setup(
        self,
        ctx: discord.ApplicationContext,
        config_mode: str = discord.Option(str,
            description=GUILD_INIT_DATA["options"]["config_mode"]["description"][
                "en-US"
            ],
            description_localizations=GUILD_INIT_DATA["options"]["config_mode"][
                "description"
            ],
            choices=[
                discord.OptionChoice(
                    name=choice["name_localizations"]["en-US"],
                    value=choice["value"],
                    name_localizations=choice["name_localizations"],
                )
                for choice in GUILD_INIT_DATA["options"]["config_mode"][
                    "choices"
                ].values()
            ],
        ),
    ):
        """
        Initialize Discord server with roles and channels.

        Creates a complete guild structure with predefined roles, channels, and categories
        based on the selected configuration mode. Supports both existing configuration
        preservation and complete server setup.

        Args:
            ctx: The Discord application context
            config_mode: Configuration mode ('existing' or 'complete')

        Returns:
            None

        Raises:
            Exception: When database operations fail or Discord API errors occur
        """
        await ctx.defer(ephemeral=True)

        if not getattr(ctx.user, "guild_permissions", None) or not (
            ctx.user.guild_permissions.manage_guild or ctx.user.guild_permissions.administrator
        ):
            return await ctx.respond("❌ You need Manage Server permission.", ephemeral=True)
        
        guild = ctx.guild
        
        if not guild:
            _logger.error("guild_init_no_context")
            msg = await get_user_message(
                ctx, GUILD_INIT_DATA, "messages.error_no_guild"
            )
            return await ctx.followup.send(msg, ephemeral=True)
        
        try:
            guild_id = int(guild.id)
        except (ValueError, TypeError):
            _logger.error("guild_init_invalid_id")
            msg = await get_user_message(
                ctx, GUILD_INIT_DATA, "messages.error_no_guild"
            )
            return await ctx.followup.send(msg, ephemeral=True)
        
        if not guild_id:
            _logger.error("guild_init_no_guild_id")
            msg = await get_user_message(
                ctx, GUILD_INIT_DATA, "messages.error_no_guild"
            )
            return await ctx.followup.send(msg, ephemeral=True)

        try:
            guild_settings = await self.bot.cache.get_guild_data(guild_id, "guild_lang")
            if not guild_settings:
                response = await get_user_message(
                    ctx, GUILD_INIT_DATA, "messages.not_initialized"
                )
                return await ctx.followup.send(response, ephemeral=True)
        except Exception as e:
            _logger.error(
                "guild_init_cache_check_failed", exc_info=True
            )
            response = await get_user_message(
                ctx, GUILD_INIT_DATA, "messages.error", error="Database error"
            )
            return await ctx.followup.send(response, ephemeral=True)

        community_mode = "COMMUNITY" in guild.features
        _logger.info("guild_init_community_mode", extra={"community": ("COMMUNITY" in guild.features)})

        if config_mode == "existing":
            try:
                guild_lang = (
                    await self.bot.cache.get_guild_data(guild_id, "guild_lang")
                    or "en-US"
                )
                
                role_names = GUILD_INIT_DATA.get("role_names", {})
                channel_names = GUILD_INIT_DATA.get("channel_names", {})

                existing_roles = {}
                role_keys = ["guild_master", "officer", "guardian", "members", "absent_members", 
                           "allies", "diplomats", "friends", "applicant", "config_ok", "rules_ok"]
                
                for key in role_keys:
                    expected_name = tr(role_names, key, guild_lang, key.replace("_", " ").title())
                    role = get(guild.roles, name=expected_name)
                    existing_roles[key] = role.id if role else None

                existing_channels = {}

                text_channel_map = {
                    "rules_channel": "rules",
                    "announcements_channel": "announcements", 
                    "events_channel": "events",
                    "members_channel": "members",
                    "groups_channel": "groups",
                    "statics_channel": "statics",
                    "abs_channel": "abs",
                    "loot_channel": "loot",
                    "tuto_channel": "tutorial",
                    "notifications_channel": "notifications",
                    "external_recruitment_channel": "ext_recruitment"
                }
                
                for db_key, name_key in text_channel_map.items():
                    expected_name = sanitize_channel_name(tr(channel_names, name_key, guild_lang, name_key))
                    ch = get(guild.text_channels, name=expected_name)
                    existing_channels[db_key] = ch.id if ch else None

                voice_channel_map = {
                    "voice_tavern_channel": "tavern_voc",
                    "create_room_channel": "create_room"
                }
                
                for db_key, name_key in voice_channel_map.items():
                    expected_name = tr(channel_names, name_key, guild_lang, name_key.replace("_", " ").title())
                    ch = get(guild.voice_channels, name=expected_name)
                    existing_channels[db_key] = ch.id if ch else None

                if community_mode:
                    stage_ch = get(guild.stage_channels, name="⚔️ WAR")
                    existing_channels["voice_war_channel"] = stage_ch.id if stage_ch else None
                else:
                    existing_channels["voice_war_channel"] = None

                category_map = {
                    "external_recruitment_cat": "cat_recruitment",
                    "category_diplomat": "cat_diplomacy"
                }
                
                for db_key, name_key in category_map.items():
                    expected_name = tr(channel_names, name_key, guild_lang, name_key.replace("cat_", "").title())
                    cat = get(guild.categories, name=expected_name)
                    existing_channels[db_key] = cat.id if cat else None

                missing_channels = [
                    "rules_message", "members_m1", "members_m2", "members_m3", "members_m4", 
                    "members_m5", "statics_message", "loot_message", "forum_allies_channel",
                    "forum_friends_channel", "forum_diplomats_channel", "forum_recruitment_channel",
                    "forum_members_channel", "external_recruitment_message"
                ]
                
                for key in missing_channels:
                    existing_channels[key] = None

                role_values = (
                    guild_id,
                    *[existing_roles.get(k) for k in role_keys]
                )
                
                role_query = """
                INSERT INTO guild_roles AS new (
                    guild_id, guild_master, officer, guardian, members, absent_members,
                    allies, diplomats, friends, applicant, config_ok, rules_ok
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    guild_master = new.guild_master,
                    officer = new.officer,
                    guardian = new.guardian,
                    members = new.members,
                    absent_members = new.absent_members,
                    allies = new.allies,
                    diplomats = new.diplomats,
                    friends = new.friends,
                    applicant = new.applicant,
                    config_ok = new.config_ok,
                    rules_ok = new.rules_ok
                """
                
                try:
                    await self.bot.run_db_query(role_query, role_values, commit=True)
                    _logger.info("guild_init_existing_roles_saved")
                except Exception as db_err:
                    _logger.error("guild_init_existing_roles_save_failed", exc_info=True)
                    raise

                channel_keys = [
                    "rules_channel", "rules_message", "announcements_channel", "voice_tavern_channel",
                    "voice_war_channel", "create_room_channel", "events_channel", "members_channel",
                    "members_m1", "members_m2", "members_m3", "members_m4", "members_m5",
                    "groups_channel", "statics_channel", "statics_message", "abs_channel",
                    "loot_channel", "loot_message", "tuto_channel", "forum_allies_channel",
                    "forum_friends_channel", "forum_diplomats_channel", "forum_recruitment_channel",
                    "forum_members_channel", "notifications_channel", "external_recruitment_cat",
                    "external_recruitment_channel", "external_recruitment_message", "category_diplomat"
                ]
                
                channels_values = (
                    guild_id,
                    *[existing_channels.get(k) for k in channel_keys]
                )
                
                insert_query = """
                INSERT INTO guild_channels AS new (
                    guild_id, rules_channel, rules_message, announcements_channel,
                    voice_tavern_channel, voice_war_channel, create_room_channel,
                    events_channel, members_channel, members_m1, members_m2, members_m3,
                    members_m4, members_m5, groups_channel, statics_channel, statics_message,
                    abs_channel, loot_channel, loot_message, tuto_channel,
                    forum_allies_channel, forum_friends_channel, forum_diplomats_channel,
                    forum_recruitment_channel, forum_members_channel, notifications_channel,
                    external_recruitment_cat, external_recruitment_channel, external_recruitment_message,
                    category_diplomat
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rules_channel = new.rules_channel,
                    rules_message = new.rules_message,
                    announcements_channel = new.announcements_channel,
                    voice_tavern_channel = new.voice_tavern_channel,
                    voice_war_channel = new.voice_war_channel,
                    create_room_channel = new.create_room_channel,
                    events_channel = new.events_channel,
                    members_channel = new.members_channel,
                    members_m1 = new.members_m1,
                    members_m2 = new.members_m2,
                    members_m3 = new.members_m3,
                    members_m4 = new.members_m4,
                    members_m5 = new.members_m5,
                    groups_channel = new.groups_channel,
                    statics_channel = new.statics_channel,
                    statics_message = new.statics_message,
                    abs_channel = new.abs_channel,
                    loot_channel = new.loot_channel,
                    loot_message = new.loot_message,
                    tuto_channel = new.tuto_channel,
                    forum_allies_channel = new.forum_allies_channel,
                    forum_friends_channel = new.forum_friends_channel,
                    forum_diplomats_channel = new.forum_diplomats_channel,
                    forum_recruitment_channel = new.forum_recruitment_channel,
                    forum_members_channel = new.forum_members_channel,
                    notifications_channel = new.notifications_channel,
                    external_recruitment_cat = new.external_recruitment_cat,
                    external_recruitment_channel = new.external_recruitment_channel,
                    external_recruitment_message = new.external_recruitment_message,
                    category_diplomat = new.category_diplomat
                """
                
                try:
                    await self.bot.run_db_query(insert_query, channels_values, commit=True)
                    _logger.info("guild_init_existing_channels_saved")
                except Exception as db_err:
                    _logger.error("guild_init_existing_channels_save_failed", exc_info=True)
                    raise

                await self.bot.cache.set_guild_data(guild_id, "roles", existing_roles)
                for key, value in existing_channels.items():
                    if value is not None:
                        await self.bot.cache.set_guild_data(guild_id, key, value)
                
                response = await get_user_message(
                    ctx, GUILD_INIT_DATA, "messages.setup_existing"
                )
                
            except Exception as e:
                _logger.error("guild_init_existing_mapping_failed", exc_info=True)
                response = await get_user_message(
                    ctx, GUILD_INIT_DATA, "messages.error", error="Configuration mapping error"
                )

        elif config_mode == "complete":
            try:
                guild_lang = (
                    await self.bot.cache.get_guild_data(guild_id, "guild_lang")
                    or "en-US"
                )

                everyone = guild.default_role
                perms = everyone.permissions
                perms.update(send_messages=False)
                await everyone.edit(permissions=perms, reason="Guild initialization")

                role_colors: Dict[str, discord.Color] = {
                    "guild_master": discord.Color(0x354fb6),
                    "officer": discord.Color(0x384fa1),
                    "guardian": discord.Color(0x4b5fa8),
                    "members": discord.Color(0x7289da),
                    "absent_members": discord.Color(0x96ACF9),
                    "allies": discord.Color(0x2E8B57),
                    "diplomats": discord.Color(0xDC143C),
                    "friends": discord.Color(0xFFD700),
                    "applicant": discord.Color(0xba55d3),
                    "config_ok": discord.Color(0x646464),
                    "rules_ok": discord.Color(0x808080),
                }
                role_names = GUILD_INIT_DATA.get("role_names", {})
                created_roles = {}

                for key, names in role_names.items():
                    name = tr(role_names, key, guild_lang, key.replace("_", " ").title())
                    color = role_colors.get(key, discord.Color.default())

                    permissions = discord.Permissions.none()

                    if key == "guild_master":
                        permissions.update(administrator=True)
                    elif key == "officer":
                        permissions.update(
                            manage_roles=True,
                            manage_nicknames=True,
                            ban_members=True,
                            kick_members=True,
                            create_public_threads=True,
                            priority_speaker=True,
                            mute_members=True,
                            deafen_members=True,
                            move_members=True,
                            use_external_apps=True,
                            request_to_speak=True,
                            create_events=True,
                            manage_events=True,
                        )
                    elif key == "guardian":
                        permissions.update(
                            manage_roles=True,
                            manage_nicknames=True,
                            kick_members=True,
                            create_public_threads=True,
                            priority_speaker=True,
                            mute_members=True,
                            move_members=True,
                            use_external_apps=True,
                            request_to_speak=True,
                            create_events=True,
                            manage_events=True,
                        )

                    role = await get_or_create_role(
                        guild, name=name, color=color, permissions=permissions, reason="Guild initialization"
                    )
                    created_roles[key] = role.id
                    _logger.info(
                        "guild_init_role_created"
                    )
                    await asyncio.sleep(0.1)

                role_values = (
                    guild_id,
                    *[
                        created_roles.get(k)
                        for k in [
                            "guild_master",
                            "officer",
                            "guardian",
                            "members",
                            "absent_members",
                            "allies",
                            "diplomats",
                            "friends",
                            "applicant",
                            "config_ok",
                            "rules_ok",
                        ]
                    ],
                )

                role_query = """
                INSERT INTO guild_roles AS new (
                    guild_id,
                    guild_master,
                    officer,
                    guardian,
                    members,
                    absent_members,
                    allies,
                    diplomats,
                    friends,
                    applicant,
                    config_ok,
                    rules_ok
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    guild_master = new.guild_master,
                    officer = new.officer,
                    guardian = new.guardian,
                    members = new.members,
                    absent_members = new.absent_members,
                    allies = new.allies,
                    diplomats = new.diplomats,
                    friends = new.friends,
                    applicant = new.applicant,
                    config_ok = new.config_ok,
                    rules_ok = new.rules_ok
                """

                try:
                    await self.bot.run_db_query(role_query, role_values, commit=True)
                    _logger.info("guild_init_roles_saved")
                except Exception as db_err:
                    _logger.error(
                        "guild_init_roles_save_failed", exc_info=True
                    )
                    raise

                roles_data = {
                    "guild_master": created_roles.get("guild_master"),
                    "officer": created_roles.get("officer"),
                    "guardian": created_roles.get("guardian"),
                    "members": created_roles.get("members"),
                    "absent_members": created_roles.get("absent_members"),
                    "allies": created_roles.get("allies"),
                    "diplomats": created_roles.get("diplomats"),
                    "friends": created_roles.get("friends"),
                    "applicant": created_roles.get("applicant"),
                    "config_ok": created_roles.get("config_ok"),
                    "rules_ok": created_roles.get("rules_ok"),
                }
                await self.bot.cache.set_guild_data(guild_id, "roles", roles_data)

                channel_names = GUILD_INIT_DATA.get("channel_names", {})

                rules_name = sanitize_channel_name(tr(channel_names, "rules", guild_lang, "rules"))
                rules_channel = await get_or_create_text_channel(guild, name=rules_name)
                rules_text = tr(channel_names, "rules_message", guild_lang, "Please read and accept the rules.")
                rules_msg = await rules_channel.send(rules_text)
                await rules_msg.add_reaction("✅")

                guild_cat = await get_or_create_category(
                    guild, name=tr(channel_names, "cat_guild", guild_lang, "Guild")
                )
                announce_ch = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "announcements", guild_lang, "announcements")),
                    category=guild_cat,
                )
                await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "tavern", guild_lang, "tavern")), category=guild_cat
                )
                await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "hall_of_fame", guild_lang, "hall-of-fame")),
                    category=guild_cat,
                )
                voice_tavern = await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "tavern_voc", guild_lang, "Voice Tavern"), category=guild_cat
                )
                afk = await get_or_create_voice_channel(
                    guild, name="💤 AFK", category=guild_cat
                )
                await guild.edit(afk_channel=afk, afk_timeout=900, reason="Guild initialization")
                await asyncio.sleep(0.2)
                create_room = await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "create_room", guild_lang, "Create Room"),
                    category=guild_cat,
                )

                org_cat = await get_or_create_category(
                    guild, name=tr(channel_names, "cat_org", guild_lang, "Organization")
                )
                events = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "events", guild_lang, "events")), category=org_cat
                )
                groups = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "groups", guild_lang, "groups")), category=org_cat
                )
                members_ch = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "members", guild_lang, "members")), category=org_cat
                )
                members_msgs = await asyncio.gather(
                    *(members_ch.send(".") for _ in range(5))
                )
                m_ids = [msg.id for msg in members_msgs]
                await asyncio.sleep(0.2)

                statics_ch = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "statics", guild_lang, "statics")), category=org_cat
                )

                title = tr(channel_names, "statics_placeholder_title", guild_lang, "Statistics")
                description = tr(channel_names, "statics_placeholder_description", guild_lang, "Guild statistics will appear here.")
                placeholder_embed = discord.Embed(
                    title=title, description=description, color=discord.Color.blue()
                )
                statics_msg = await statics_ch.send(embed=placeholder_embed)
                abs_ch = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "abs", guild_lang, "absences")), category=org_cat
                )
                await abs_ch.send(tr(channel_names, "absences_message", guild_lang, "Report your absences here."))
                loot = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "loot", guild_lang, "loot")), category=org_cat
                )

                wishlist_translations = global_translations.get(
                    "loot_wishlist", {}
                ).get("placeholder", {})
                wishlist_title = wishlist_translations.get("title", {}).get(
                    guild_lang,
                    wishlist_translations.get("title", {}).get(
                        "en-US", "🌟 Epic T2 Items Wishlist"
                    ),
                )
                wishlist_description = wishlist_translations.get("description", {}).get(
                    guild_lang,
                    wishlist_translations.get("description", {}).get(
                        "en-US", "Most wanted Epic T2 items by guild members"
                    ),
                )
                wishlist_empty = wishlist_translations.get("empty", {}).get(
                    guild_lang,
                    wishlist_translations.get("empty", {}).get(
                        "en-US",
                        "No items in wishlist yet. Use `/wishlist add` to add your desired Epic T2 items!",
                    ),
                )
                wishlist_footer = wishlist_translations.get("footer", {}).get(
                    guild_lang,
                    wishlist_translations.get("footer", {}).get(
                        "en-US",
                        "Updated every day at 9 AM and 10 PM • Max 3 items per member",
                    ),
                )

                wishlist_embed = discord.Embed(
                    title=wishlist_title,
                    description=wishlist_description,
                    color=discord.Color.gold(),
                )
                wishlist_embed.add_field(
                    name="📋 Current Wishlist", value=wishlist_empty, inline=False
                )
                wishlist_embed.set_footer(text=wishlist_footer)
                loot_msg = await loot.send(embed=wishlist_embed)

                council_cat = await get_or_create_category(
                    guild, name=tr(channel_names, "cat_council", guild_lang, "Council")
                )
                await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "rounded_table", guild_lang, "round-table")),
                    category=council_cat,
                )
                await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "reports", guild_lang, "reports")), category=council_cat
                )
                notif_ch = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "notifications", guild_lang, "notifications")),
                    category=council_cat,
                )
                await guild.edit(system_channel=notif_ch, reason="Guild initialization")
                await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "staff", guild_lang, "Staff"), category=council_cat
                )

                recruitment_cat = await get_or_create_category(
                    guild, name=tr(channel_names, "cat_recruitment", guild_lang, "Recruitment")
                )
                ext_recruitment = await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "ext_recruitment", guild_lang, "external-recruitment")),
                    category=recruitment_cat,
                )
                embed = discord.Embed(
                    title=tr(channel_names, "recruitment_message", guild_lang, "Recruitment"),
                    description=".",
                    color=discord.Color.blurple(),
                )
                ext_msg = await ext_recruitment.send(embed=embed)
                await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "waiting_room", guild_lang, "Waiting Room"),
                    category=recruitment_cat,
                )
                await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "recruitment", guild_lang, "Recruitment"),
                    category=recruitment_cat,
                )

                diplomat_cat = await get_or_create_category(
                    guild, name=tr(channel_names, "cat_diplomacy", guild_lang, "Diplomacy")
                )
                await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "waiting_room", guild_lang, "Waiting Room"),
                    category=diplomat_cat,
                )
                await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "diplomacy", guild_lang, "Diplomacy"),
                    category=diplomat_cat,
                )

                ami_cat = await get_or_create_category(
                    guild, name=tr(channel_names, "cat_ami", guild_lang, "Friends")
                )
                await get_or_create_text_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "ami_tavern", guild_lang, "friends-tavern")), category=ami_cat
                )
                await get_or_create_voice_channel(
                    guild, name=tr(channel_names, "ami_tavern_voc", guild_lang, "Friends Voice"),
                    category=ami_cat,
                )

                community_enabled = community_mode
                if not community_mode:
                    await ctx.followup.send(
                        await get_user_message(
                            ctx, GUILD_INIT_DATA, "messages.community_required"
                        ),
                        ephemeral=True
                    )
                    try:
                        await guild.edit(
                            community=True,
                            verification_level=discord.VerificationLevel.medium,
                            explicit_content_filter=discord.ContentFilter.all_members,
                            rules_channel=rules_channel,
                            public_updates_channel=notif_ch,
                            preferred_locale=guild_lang,
                            reason="Guild initialization - Enable community mode",
                        )
                        _logger.info("guild_init_community_enabled")
                        community_enabled = True
                    except Exception as e:
                        _logger.error(
                            "guild_init_community_failed", exc_info=True
                        )
                        response = await get_user_message(
                            ctx,
                            GUILD_INIT_DATA,
                            "messages.error",
                            error="Discord configuration error",
                        )
                        community_enabled = False

                war_conf = None
                if community_enabled:
                    war_conf = await get_or_create_stage_channel(
                        guild, "⚔️ WAR",
                        category=guild_cat,
                        topic="War coordination and strategic discussions",
                    )
                    await asyncio.sleep(0.2)

                tutorial_channel = await get_or_create_forum_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "tutorial", guild_lang, "tutorial")),
                    category=org_cat,
                    position=99,
                )

                forum_org = await get_or_create_forum_channel(
                    guild, name=sanitize_channel_name(tr(channel_names, "forum_org", guild_lang, "organization")), 
                    category=council_cat, position=99
                )
                thread_data = [
                    ("topic_ally", "message_ally"),
                    ("topic_friends", "message_friends"),
                    ("topic_diplomats", "message_diplomats"),
                    ("topic_recruitment", "message_recruitment"),
                    ("topic_members", "message_members"),
                ]
                forum_ids = []
                for topic_key, msg_key in thread_data:
                    thread_name = tr(channel_names, topic_key, guild_lang, topic_key.replace("topic_", "").replace("_", " ").title())
                    thread_content = tr(channel_names, msg_key, guild_lang, f"Discussion about {thread_name.lower()}")
                    thread = await forum_org.create_thread(
                        name=thread_name,
                        content=thread_content,
                        auto_archive_duration=1440,
                    )
                    forum_ids.append(thread.id)
                    await asyncio.sleep(0.1)

                try:
                    await announce_ch.edit(type=discord.ChannelType.news, reason="Guild initialization")
                except Exception as e:
                    _logger.warning("guild_init_news_channel_failed", extra={"error": str(e)})
                await asyncio.sleep(0.2)

                channels_values = (
                    ctx.guild.id,
                    rules_channel.id,
                    rules_msg.id,
                    announce_ch.id,
                    voice_tavern.id,
                    war_conf.id if war_conf else None,
                    create_room.id,
                    events.id,
                    members_ch.id,
                    *m_ids,
                    groups.id,
                    statics_ch.id,
                    statics_msg.id,
                    abs_ch.id,
                    loot.id,
                    loot_msg.id,
                    tutorial_channel.id,
                    *forum_ids,
                    notif_ch.id,
                    recruitment_cat.id,
                    ext_recruitment.id,
                    ext_msg.id,
                    diplomat_cat.id,
                )

                insert_query = """
                INSERT INTO guild_channels AS new (
                    guild_id,
                    rules_channel,
                    rules_message,
                    announcements_channel,
                    voice_tavern_channel,
                    voice_war_channel,
                    create_room_channel,
                    events_channel,
                    members_channel,
                    members_m1,
                    members_m2,
                    members_m3,
                    members_m4,
                    members_m5,
                    groups_channel,
                    statics_channel,
                    statics_message,
                    abs_channel,
                    loot_channel,
                    loot_message,
                    tuto_channel,
                    forum_allies_channel,
                    forum_friends_channel,
                    forum_diplomats_channel,
                    forum_recruitment_channel,
                    forum_members_channel,
                    notifications_channel,
                    external_recruitment_cat,
                    external_recruitment_channel,
                    external_recruitment_message,
                    category_diplomat
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rules_channel = new.rules_channel,
                    rules_message = new.rules_message,
                    announcements_channel = new.announcements_channel,
                    voice_tavern_channel = new.voice_tavern_channel,
                    voice_war_channel = new.voice_war_channel,
                    create_room_channel = new.create_room_channel,
                    events_channel = new.events_channel,
                    members_channel = new.members_channel,
                    members_m1 = new.members_m1,
                    members_m2 = new.members_m2,
                    members_m3 = new.members_m3,
                    members_m4 = new.members_m4,
                    members_m5 = new.members_m5,
                    groups_channel = new.groups_channel,
                    statics_channel = new.statics_channel,
                    statics_message = new.statics_message,
                    abs_channel = new.abs_channel,
                    loot_channel = new.loot_channel,
                    loot_message = new.loot_message,
                    tuto_channel = new.tuto_channel,
                    forum_allies_channel = new.forum_allies_channel,
                    forum_friends_channel = new.forum_friends_channel,
                    forum_diplomats_channel = new.forum_diplomats_channel,
                    forum_recruitment_channel = new.forum_recruitment_channel,
                    forum_members_channel = new.forum_members_channel,
                    notifications_channel = new.notifications_channel,
                    external_recruitment_cat = new.external_recruitment_cat,
                    external_recruitment_channel = new.external_recruitment_channel,
                    external_recruitment_message = new.external_recruitment_message,
                    category_diplomat = new.category_diplomat
                """

                try:
                    await self.bot.run_db_query(insert_query, channels_values, commit=True)
                    _logger.info("guild_init_channels_saved")
                except Exception as db_err:
                    _logger.error(
                        "guild_init_channels_save_failed", exc_info=True
                    )
                    raise

                channels_data = {
                    "rules_channel": rules_channel.id,
                    "rules_message": rules_msg.id,
                    "announcements_channel": announce_ch.id,
                    "voice_tavern_channel": voice_tavern.id,
                    "voice_war_channel": war_conf.id if war_conf else None,
                    "create_room_channel": create_room.id,
                    "events_channel": events.id,
                    "members_channel": members_ch.id,
                    "members_m1": m_ids[0],
                    "members_m2": m_ids[1],
                    "members_m3": m_ids[2],
                    "members_m4": m_ids[3],
                    "members_m5": m_ids[4],
                    "groups_channel": groups.id,
                    "statics_channel": statics_ch.id,
                    "statics_message": statics_msg.id,
                    "abs_channel": abs_ch.id,
                    "loot_channel": loot.id,
                    "loot_message": loot_msg.id,
                    "tuto_channel": tutorial_channel.id,
                    "forum_allies_channel": forum_ids[0],
                    "forum_friends_channel": forum_ids[1],
                    "forum_diplomats_channel": forum_ids[2],
                    "forum_recruitment_channel": forum_ids[3],
                    "forum_members_channel": forum_ids[4],
                    "notifications_channel": notif_ch.id,
                    "external_recruitment_cat": recruitment_cat.id,
                    "external_recruitment_channel": ext_recruitment.id,
                    "external_recruitment_message": ext_msg.id,
                    "category_diplomat": diplomat_cat.id,
                }
                for key, value in channels_data.items():
                    await self.bot.cache.set_guild_data(guild_id, key, value)

                await rules_channel.set_permissions(
                    guild.default_role,
                    view_channel=True,
                    read_message_history=True,
                    send_messages=False,
                    create_public_threads=False,
                    create_private_threads=False,
                    send_messages_in_threads=False,
                    add_reactions=True,
                    reason="Guild initialization",
                )

                try:
                    await self.bot.cache.invalidate_category("guild_data")
                    await self.bot.cache.invalidate_category("roster_data")
                    await self.bot.cache.invalidate_category("events_data")
                    await self.bot.cache.invalidate_category("user_data")
                    await self.bot.cache.invalidate_category("discord_entities")
                    _logger.info(
                        "guild_init_cache_invalidated"
                    )
                except Exception as e:
                    _logger.error(
                        "guild_init_cache_reload_failed", exc_info=True
                    )

                response = await get_user_message(
                    ctx, GUILD_INIT_DATA, "messages.setup_complete"
                )
            except Exception as e:
                _logger.error(
                    "guild_init_complete_config_failed", exc_info=True
                )
                response = await get_user_message(
                    ctx, GUILD_INIT_DATA, "messages.error", error="Configuration error"
                )
        else:
            _logger.warning(
                "guild_init_unknown_mode"
            )
            response = await get_user_message(
                ctx, GUILD_INIT_DATA, "messages.unknown_mode"
            )

        await ctx.followup.send(response, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Initialize guild init data on bot ready.

        Creates a background task to load all required guild initialization data
        when the bot becomes ready.

        Returns:
            None
        """
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        _logger.debug("guild_init_cache_wait")


def setup(bot: BotProto) -> None:
    """
    Setup function for the cog.

    Registers the GuildInit cog with the Discord bot instance.

    Args:
        bot: The Discord bot instance to add the cog to

    Returns:
        None
    """
    bot.add_cog(GuildInit(bot))
