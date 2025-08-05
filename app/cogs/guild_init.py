"""
Guild Init Cog - Manages Discord server initialization and setup processes.
"""

import asyncio
import logging
from typing import Any, Dict, Tuple

import discord
from discord.ext import commands

from core.functions import get_user_message
from core.rate_limiter import admin_rate_limit
from core.reliability import discord_resilient
from core.translation import translations as global_translations

GUILD_INIT_DATA = global_translations.get("guild_init", {})

class GuildInit(commands.Cog):
    """
    Cog for managing Discord server initialization and setup processes.
    
    This cog provides functionality to initialize Discord servers with predefined
    roles and channels structure for guild management.
    """
    
    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the GuildInit cog.
        
        Args:
            bot: The Discord bot instance
        """
        self.bot = bot

        self._register_admin_commands()
    
    def _register_admin_commands(self):
        """Register guild init commands with the centralized admin_bot group."""
        if hasattr(self.bot, 'admin_group'):

            self.bot.admin_group.command(
                name=GUILD_INIT_DATA["name"]["en-US"],
                description=GUILD_INIT_DATA["description"]["en-US"],
                name_localizations=GUILD_INIT_DATA["name"],
                description_localizations=GUILD_INIT_DATA["description"]
            )(self.discord_setup)

    @admin_rate_limit(cooldown_seconds=600)
    @discord_resilient(service_name='discord_api', max_retries=3)
    async def discord_setup(
        self,
        ctx: discord.ApplicationContext,
        config_mode: str = discord.Option(
            description=GUILD_INIT_DATA["options"]["config_mode"]["description"]["en-US"],
            description_localizations=GUILD_INIT_DATA["options"]["config_mode"]["description"],
            choices=[
                discord.OptionChoice(name=choice["name_localizations"]["en-US"],value=choice["value"],name_localizations=choice["name_localizations"],)
                for choice in GUILD_INIT_DATA["options"]["config_mode"]["choices"].values()
            ]
        )
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
        guild = ctx.guild
        guild_id = guild.id if guild else None

        if not guild_id:
            logging.error("[GuildInit] No guild context available")
            msg = get_user_message(
                ctx, GUILD_INIT_DATA, "messages.error_no_guild"
            )
            return await ctx.followup.send(msg, ephemeral=True)

        try:
            await self.bot.cache_loader.ensure_category_loaded('guild_settings')
            guild_settings = await self.bot.cache.get_guild_data(guild_id, 'guild_lang')
            if not guild_settings:
                response = get_user_message(ctx, GUILD_INIT_DATA, "messages.not_initialized")
                return await ctx.followup.send(response, ephemeral=True)
        except Exception as e:
            logging.error("[GuildInit] Cache check failed for guild %s: %s", guild_id, e)
            response = get_user_message(ctx, GUILD_INIT_DATA, "messages.error", error="Database error")
            return await ctx.followup.send(response, ephemeral=True)

        community_mode = "COMMUNITY" in guild.features
        logging.info("[GuildInit] Community mode status: %s", community_mode)

        if config_mode == "existing":
            ###########################################################################
            ###########################################################################
            ###########################################################################
            ###########################################################################
            ###########################################################################
            ###########################################################################
            roles = ctx.guild.roles
            channels = ctx.guild.channels

            response = get_user_message(ctx, GUILD_INIT_DATA, "messages.setup_existing")

        elif config_mode == "complete":
            try:
                await self.bot.cache_loader.ensure_category_loaded('guild_settings')
                guild_lang = await self.bot.cache.get_guild_data(guild_id, 'guild_lang') or "en-US"

                everyone = guild.default_role
                perms = everyone.permissions
                perms.update(send_messages=False)
                await everyone.edit(permissions=perms)

                role_colors: Dict[str, discord.Color] = {
                    "guild_master": discord.Color(int("354fb6", 16)),
                    "officer": discord.Color(int("384fa1", 16)),
                    "guardian": discord.Color(int("4b5fa8", 16)),
                    "members": discord.Color(int("7289da", 16)),
                    "absent_members": discord.Color(int("96ACF9", 16)),
                    "allies": discord.Color(int("2E8B57", 16)),
                    "diplomats": discord.Color(int("DC143C", 16)),
                    "friends": discord.Color(int("FFD700", 16)),
                    "applicant": discord.Color(int("ba55d3", 16)),
                    "config_ok": discord.Color(int("646464", 16))
                }
                role_names = GUILD_INIT_DATA.get("role_names", {})
                created_roles = {}

                for key, names in role_names.items():
                    name = names.get(guild_lang, names.get("en-US"))
                    color = role_colors.get(key, discord.Color.default())
                    role = await guild.create_role(name=name, color=color)
                    created_roles[key] = role.id
                    logging.info("[GuildInit] Created role '%s' (%s)", name, role.id)

                role_values = (
                    guild_id,
                    *[created_roles.get(k) for k in ["guild_master", "officer", "guardian","members", "absent_members", "allies","diplomats", "friends", "applicant","config_ok", "rules_ok"]]
                )

                role_query = """
                INSERT INTO guild_roles (
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
                    guild_master = VALUES(guild_master),
                    officer = VALUES(officer),
                    guardian = VALUES(guardian),
                    members = VALUES(members),
                    absent_members = VALUES(absent_members),
                    allies = VALUES(allies),
                    diplomats = VALUES(diplomats),
                    friends = VALUES(friends),
                    applicant = VALUES(applicant),
                    config_ok = VALUES(config_ok),
                    rules_ok = VALUES(rules_ok)
                """

                await self.bot.run_db_query(role_query, role_values, commit=True)
                
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
                    "rules_ok": created_roles.get("rules_ok")
                }
                await self.bot.cache.set_guild_data(guild_id, 'roles', roles_data)

                channel_names = GUILD_INIT_DATA.get("channel_names", {})

                rules_name = channel_names["rules"].get(guild_lang)
                rules_channel = await guild.create_text_channel(name=rules_name)
                rules_text = channel_names["rules_message"].get(guild_lang)
                rules_msg = await rules_channel.send(rules_text)
                await rules_msg.add_reaction("✅")

                guild_cat = await guild.create_category(name=channel_names["cat_guild"].get(guild_lang))
                announce_ch = await guild.create_text_channel(name=channel_names["announcements"].get(guild_lang), category=guild_cat)
                await guild.create_text_channel(name=channel_names["tavern"].get(guild_lang),category=guild_cat)
                await guild.create_text_channel(name=channel_names["hall_of_fame"].get(guild_lang),category=guild_cat)
                voice_tavern = await guild.create_voice_channel(name=channel_names["tavern_voc"].get(guild_lang),category=guild_cat)
                afk = await guild.create_voice_channel(name="💤 AFK", category=guild_cat)
                await guild.edit(afk_channel=afk, afk_timeout=900)
                create_room = await guild.create_voice_channel(name=channel_names["create_room"].get(guild_lang),category=guild_cat)

                org_cat = await guild.create_category(name=channel_names["cat_org"].get(guild_lang))
                events = await guild.create_text_channel(name=channel_names["events"].get(guild_lang),category=org_cat)
                groups = await guild.create_text_channel(name=channel_names["groups"].get(guild_lang),category=org_cat)
                members_ch = await guild.create_text_channel(name=channel_names["members"].get(guild_lang),category=org_cat)
                members_msgs = await asyncio.gather(*(members_ch.send(".") for _ in range(5)))
                m_ids = [msg.id for msg in members_msgs]

                static_groups = global_translations.get("static_groups", {})
                statics_name = static_groups["channel"]["name"].get(guild_lang, static_groups["channel"]["name"].get("en-US"))
                statics_ch = await guild.create_text_channel(name=statics_name, category=org_cat)
                
                title = static_groups["channel"]["placeholder"]["title"].get(guild_lang, static_groups["channel"]["placeholder"]["title"].get("en-US"))
                description = static_groups["channel"]["placeholder"]["description"].get(guild_lang, static_groups["channel"]["placeholder"]["description"].get("en-US"))
                placeholder_embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
                statics_msg = await statics_ch.send(embed=placeholder_embed)
                abs_ch = await guild.create_text_channel(name=channel_names["abs"].get(guild_lang),category=org_cat)
                await abs_ch.send(channel_names["absences_message"].get(guild_lang))
                loot = await guild.create_text_channel(name=channel_names["loot"].get(guild_lang),category=org_cat)

                wishlist_translations = global_translations.get("loot_wishlist", {}).get("placeholder", {})
                wishlist_title = wishlist_translations.get("title", {}).get(guild_lang, wishlist_translations.get("title", {}).get("en-US", "🌟 Epic T2 Items Wishlist"))
                wishlist_description = wishlist_translations.get("description", {}).get(guild_lang, wishlist_translations.get("description", {}).get("en-US", "Most wanted Epic T2 items by guild members"))
                wishlist_empty = wishlist_translations.get("empty", {}).get(guild_lang, wishlist_translations.get("empty", {}).get("en-US", "No items in wishlist yet. Use `/wishlist add` to add your desired Epic T2 items!"))
                wishlist_footer = wishlist_translations.get("footer", {}).get(guild_lang, wishlist_translations.get("footer", {}).get("en-US", "Updated every day at 9 AM and 10 PM • Max 3 items per member"))
                
                wishlist_embed = discord.Embed(
                    title=wishlist_title,
                    description=wishlist_description,
                    color=discord.Color.gold()
                )
                wishlist_embed.add_field(name="📋 Current Wishlist", value=wishlist_empty, inline=False)
                wishlist_embed.set_footer(text=wishlist_footer)
                loot_msg = await loot.send(embed=wishlist_embed)

                council_cat = await guild.create_category(name=channel_names["cat_council"].get(guild_lang))
                await guild.create_text_channel(name=channel_names["rounded_table"].get(guild_lang),category=council_cat)
                await guild.create_text_channel(name=channel_names["reports"].get(guild_lang),category=council_cat)
                notif_ch = await guild.create_text_channel(name=channel_names["notifications"].get(guild_lang),category=council_cat)
                await guild.edit(system_channel=notif_ch)
                await guild.create_voice_channel(name=channel_names["staff"].get(guild_lang),category=council_cat)

                recruitment_cat = await guild.create_category(name=channel_names["cat_recruitment"].get(guild_lang))
                ext_recruitment = await guild.create_text_channel(name=channel_names["ext_recruitment"].get(guild_lang),category=recruitment_cat)
                embed = discord.Embed(title=channel_names["recruitment_message"].get(guild_lang),description=".",color=discord.Color.blurple(),)
                ext_msg = await ext_recruitment.send(embed=embed)
                await guild.create_voice_channel(name=channel_names["waiting_room"].get(guild_lang),category=recruitment_cat)
                await guild.create_voice_channel(name=channel_names["recruitment"].get(guild_lang),category=recruitment_cat)

                diplomat_cat = await guild.create_category(name=channel_names["cat_diplomacy"].get(guild_lang))
                await guild.create_voice_channel(name=channel_names["waiting_room"].get(guild_lang),category=diplomat_cat)
                await guild.create_voice_channel(name=channel_names["diplomacy"].get(guild_lang),category=diplomat_cat)

                ami_cat = await guild.create_category(name=channel_names["cat_ami"].get(guild_lang))
                await guild.create_text_channel(name=channel_names["ami_tavern"].get(guild_lang),category=ami_cat)
                await guild.create_voice_channel(name=channel_names["ami_tavern_voc"].get(guild_lang),category=ami_cat)

                if not community_mode:
                    await ctx.followup.send(get_user_message(ctx, GUILD_INIT_DATA,"messages.community_required"))
                    try:
                        await guild.edit(
                            community=True,
                            verification_level=discord.VerificationLevel.medium,
                            explicit_content_filter=discord.ContentFilter.all_members,
                            rules_channel=rules_channel,
                            public_updates_channel=notif_ch,
                            preferred_locale=guild_lang,
                        )
                        logging.info("[GuildInit] Set server to community mode")
                    except Exception as e:
                        logging.error("[GuildInit] Failed to enable community mode: %s", e)
                        response = get_user_message(ctx, GUILD_INIT_DATA,"messages.error", error="Discord configuration error")
                        return await ctx.followup.send(response, ephemeral=True)

                war_conf = await guild.create_voice_channel("⚔️ WAR",type=discord.ChannelType.stage_voice,category=guild_cat)

                tutorial_channel = await ctx.guild.create_forum_channel(name=channel_names["tutorial"].get(guild_lang),category=org_cat,position=99)

                forum_org = await council_cat.create_forum_channel(name=channel_names["forum_org"].get(guild_lang),position=99)
                thread_data = [
                    ("topic_ally", "message_ally"),
                    ("topic_friends", "message_friends"),
                    ("topic_diplomats", "message_diplomats"),
                    ("topic_recruitment", "message_recruitment"),
                    ("topic_members", "message_members"),
                ]
                forum_ids = []
                for topic_key, msg_key in thread_data:
                    thread = await forum_org.create_thread(
                        name=channel_names[topic_key].get(guild_lang),
                        content=channel_names[msg_key].get(guild_lang),
                        auto_archive_duration=1440,
                    )
                    forum_ids.append(thread.id)

                await announce_ch.edit(type=discord.ChannelType.news)

                channels_values = (
                    ctx.guild.id,
                    rules_channel.id,
                    rules_msg.id,
                    announce_ch.id,
                    voice_tavern.id,
                    war_conf.id,
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
                    ext_recruitment.id,
                    ext_msg.id,
                    diplomat_cat.id
                )

                insert_query = """
                INSERT INTO guild_channels (
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
                    tutorial_channel,
                    forum_allies_channel,
                    forum_friends_channel,
                    forum_diplomats_channel,
                    forum_recruitment_channel,
                    forum_members_channel,
                    notifications_channel,
                    external_recruitment_channel,
                    external_recruitment_message,
                    category_diplomat
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rules_channel = VALUES(rules_channel),
                    rules_message = VALUES(rules_message),
                    announcements_channel = VALUES(announcements_channel),
                    voice_tavern_channel = VALUES(voice_tavern_channel),
                    voice_war_channel = VALUES(voice_war_channel),
                    create_room_channel = VALUES(create_room_channel),
                    events_channel = VALUES(events_channel),
                    members_channel = VALUES(members_channel),
                    members_m1 = VALUES(members_m1),
                    members_m2 = VALUES(members_m2),
                    members_m3 = VALUES(members_m3),
                    members_m4 = VALUES(members_m4),
                    members_m5 = VALUES(members_m5),
                    groups_channel = VALUES(groups_channel),
                    statics_channel = VALUES(statics_channel),
                    statics_message = VALUES(statics_message),
                    abs_channel = VALUES(abs_channel),
                    loot_channel = VALUES(loot_channel),
                    loot_message = VALUES(loot_message),
                    tutorial_channel = VALUES(tutorial_channel),
                    forum_allies_channel = VALUES(forum_allies_channel),
                    forum_friends_channel = VALUES(forum_friends_channel),
                    forum_diplomats_channel = VALUES(forum_diplomats_channel),
                    forum_recruitment_channel = VALUES(forum_recruitment_channel),
                    forum_members_channel = VALUES(forum_members_channel),
                    notifications_channel = VALUES(notifications_channel),
                    external_recruitment_channel = VALUES(external_recruitment_channel),
                    external_recruitment_message = VALUES(external_recruitment_message),
                    category_diplomat = VALUES(category_diplomat)
                """

                await self.bot.run_db_query(insert_query, channels_values, commit=True)
                
                channels_data = {
                    "rules_channel": rules_channel.id,
                    "rules_message": rules_msg.id,
                    "announcements_channel": announce_ch.id,
                    "voice_tavern_channel": voice_tavern.id,
                    "voice_war_channel": war_conf.id,
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
                    "tutorial_channel": tutorial_channel.id,
                    "forum_allies_channel": forum_ids[0],
                    "forum_friends_channel": forum_ids[1],
                    "forum_diplomats_channel": forum_ids[2],
                    "forum_recruitment_channel": forum_ids[3],
                    "forum_members_channel": forum_ids[4],
                    "notifications_channel": notif_ch.id,
                    "external_recruitment_channel": ext_recruitment.id,
                    "external_recruitment_message": ext_msg.id,
                    "category_diplomat": diplomat_cat.id
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
                    add_reactions=True
                )

                try:
                    await self.bot.cache.invalidate_guild(guild_id)
                    await self.bot.cache_loader.ensure_category_loaded('guild_roles')
                    await self.bot.cache_loader.ensure_category_loaded('guild_channels')
                    await self.bot.cache_loader.ensure_category_loaded('guild_settings')
                    logging.info("[GuildInit] Cache invalidated and reloaded for guild %s", guild_id)
                except Exception as e:
                    logging.error("[GuildInit] Error reloading caches: %s", e)

                response = get_user_message(ctx, GUILD_INIT_DATA, "messages.setup_complete")
            except Exception as e:
                logging.error("[GuildInit] Error during complete config for guild %s: %s",guild_id,e)
                response = get_user_message(ctx, GUILD_INIT_DATA, "messages.error", error="Configuration error")
        else:
            logging.warning("[GuildInit] Unknown config mode '%s' for guild %s",config_mode,guild_id,)
            response = get_user_message(ctx, GUILD_INIT_DATA, "messages.unknown_mode")

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
        asyncio.create_task(self.load_guild_init_data())
        logging.debug("[GuildInit] Cache loading tasks started in on_ready.")

    async def load_guild_init_data(self) -> None:
        """
        Ensure all required data is loaded via centralized cache loader.
        
        Loads guild settings, channels, and roles data into the cache to ensure
        all necessary information is available for guild initialization operations.
        
        Returns:
            None
            
        Raises:
            Exception: When cache loading operations fail
        """
        logging.debug("[GuildInit] Loading guild init data")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        await self.bot.cache_loader.ensure_category_loaded('guild_channels')
        await self.bot.cache_loader.ensure_category_loaded('guild_roles')
        
        logging.debug("[GuildInit] Guild init data loading completed")

def setup(bot: discord.Bot) -> None:
    """
    Setup function for the cog.
    
    Registers the GuildInit cog with the Discord bot instance.
    
    Args:
        bot: The Discord bot instance to add the cog to
        
    Returns:
        None
    """
    bot.add_cog(GuildInit(bot))
