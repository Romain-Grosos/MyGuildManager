import discord
from discord.ext import commands
import logging
from typing import Any, Dict, Tuple
from functions import get_user_message
from translation import translations as global_translations
import asyncio

GUILD_INIT_DATA = global_translations.get("guild_init", {})

class GuildInit(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.translations = bot.translations

    @discord.slash_command(
        name=GUILD_INIT_DATA["name"]["en-US"],
        description=GUILD_INIT_DATA["description"]["en-US"],
        name_localizations=GUILD_INIT_DATA["name"],
        description_localizations=GUILD_INIT_DATA["description"]
    )
    @commands.has_permissions(administrator=True)
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
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        guild_id = guild.id if guild else None

        if not guild_id:
            logging.error("[GuildInit] No guild context available")
            msg = get_user_message(
                ctx, self.translations, "guild_init.messages.error_no_guild"
            )
            return await ctx.followup.send(msg, ephemeral=True)

        try:
            query = "SELECT COUNT(*) FROM guild_settings WHERE guild_id = %s"
            result = await self.bot.run_db_query(query, (guild_id,), fetch_one=True)
            if not result or result[0] == 0:
                response = get_user_message(ctx, self.translations, "guild_init.messages.not_initialized")
                return await ctx.followup.send(response, ephemeral=True)
        except Exception as e:
            logging.error("[GuildInit] DB check failed for guild %s: %s", guild_id, e)
            response = get_user_message(ctx, self.translations, "guild_init.messages.error", error=e)
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
            # TO BE DONE
            roles = ctx.guild.roles
            channels = ctx.guild.channels

            response = get_user_message(ctx, self.bot.translations, "guild_init.messages.setup_existing")

        elif config_mode == "complete":
            try:
                lang_query = ("SELECT guild_lang FROM guild_settings WHERE guild_id = %s")
                lang_res = await self.bot.run_db_query(lang_query, (guild_id,), fetch_one=True)
                guild_lang = lang_res[0] if lang_res and lang_res[0] else "en-US"

                everyone = guild.default_role
                perms = everyone.permissions
                perms.update(send_messages=False)
                await everyone.edit(permissions=perms)

                role_colors: Dict[str, discord.Color] = {
                    "guild_master": discord.Color(int("354fb6", 16)),
                    "officer": discord.Color(int("384fa1", 16)),
                    "guardian": discord.Color(int("4b5fa8", 16)),
                    "members": discord.Color(int("7289da", 16)),
                    "absent_members": discord.Color(int("96acff", 16)),
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

                conseil_cat = await guild.create_category(name=channel_names["cat_conseil"].get(guild_lang))
                await guild.create_text_channel(name=channel_names["rounded_table"].get(guild_lang),category=conseil_cat)
                await guild.create_text_channel(name=channel_names["compte_rendus"].get(guild_lang),category=conseil_cat)
                notif_ch = await guild.create_text_channel(name=channel_names["notifications"].get(guild_lang),category=conseil_cat)
                await guild.edit(system_channel=notif_ch)
                await guild.create_voice_channel(name=channel_names["staff"].get(guild_lang),category=conseil_cat)

                recrut_cat = await guild.create_category(name=channel_names["cat_recrut"].get(guild_lang))
                ext_recrut = await guild.create_text_channel(name=channel_names["ext_recrut"].get(guild_lang),category=recrut_cat)
                embed = discord.Embed(title=channel_names["recrut_message"].get(guild_lang),description=".",color=discord.Color.blurple(),)
                ext_msg = await ext_recrut.send(embed=embed)
                await guild.create_voice_channel(name=channel_names["waiting_room"].get(guild_lang),category=recrut_cat)
                await guild.create_voice_channel(name=channel_names["recruitment"].get(guild_lang),category=recrut_cat)

                diplo_cat = await guild.create_category(name=channel_names["cat_diplo"].get(guild_lang))
                await guild.create_voice_channel(name=channel_names["waiting_room"].get(guild_lang),category=diplo_cat)
                await guild.create_voice_channel(name=channel_names["diplomacy"].get(guild_lang),category=diplo_cat)

                ami_cat = await guild.create_category(name=channel_names["cat_ami"].get(guild_lang))
                await guild.create_text_channel(name=channel_names["ami_tavern"].get(guild_lang),category=ami_cat)
                await guild.create_voice_channel(name=channel_names["ami_tavern_voc"].get(guild_lang),category=ami_cat)

                if not community_mode:
                    await ctx.followup.send(get_user_message(ctx, self.translations,"guild_init.messages.community_required"))
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
                        response = get_user_message(ctx, self.translations,"guild_init.messages.error", error=e)
                        return await ctx.followup.send(response, ephemeral=True)

                war_conf = await guild.create_voice_channel("⚔️ WAR",type=discord.ChannelType.stage_voice,category=guild_cat)

                tuto_channel = await ctx.guild.create_forum_channel(name=channel_names["tuto"].get(guild_lang),category=org_cat,position=99)

                forum_org = await conseil_cat.create_forum_channel(name=channel_names["forum_org"].get(guild_lang),position=99)
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
                    tuto_channel.id,
                    *forum_ids,
                    notif_ch.id,
                    ext_recrut.id,
                    ext_msg.id,
                    diplo_cat.id
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
                    tuto_channel,
                    forum_allies_channel,
                    forum_friends_channel,
                    forum_diplomats_channel,
                    forum_recruitment_channel,
                    forum_members_channel,
                    notifications_channel,
                    external_recruitment_channel,
                    external_recruitment_message,
                    category_diplo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    tuto_channel = VALUES(tuto_channel),
                    forum_allies_channel = VALUES(forum_allies_channel),
                    forum_friends_channel = VALUES(forum_friends_channel),
                    forum_diplomats_channel = VALUES(forum_diplomats_channel),
                    forum_recruitment_channel = VALUES(forum_recruitment_channel),
                    forum_members_channel = VALUES(forum_members_channel),
                    notifications_channel = VALUES(notifications_channel),
                    external_recruitment_channel = VALUES(external_recruitment_channel),
                    external_recruitment_message = VALUES(external_recruitment_message),
                    category_diplo = VALUES(category_diplo)
                """

                await self.bot.run_db_query(insert_query, channels_values, commit=True)

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

                for cog_name, methods in {
                    "Notification": ["load_notification_channels"],
                    "AutoRole": ["load_rules_messages", "load_rules_ok_roles", "load_guild_lang"],
                    "GuildMembers": ["load_forum_channels"],
                    "ProfileSetup": ["load_roles", "load_forum_channels"],
                    "DynamicVoice": ["load_create_room_channels"],
                    "AbsenceManager": ["load_absence_channels"],
                }.items():
                    cog = self.bot.get_cog(cog_name)
                    if cog:
                        for m in methods:
                            try:
                                await getattr(cog, m)()
                            except Exception as e:
                                logging.error(
                                    "[GuildInit] %s.%s failed: %s", cog_name, m, e
                                )

                response = get_user_message(ctx, self.translations, "guild_init.messages.setup_complete")
            except Exception as e:
                logging.error("[GuildInit] Error during complete config for guild %s: %s",guild_id,e)
                response = get_user_message(ctx, self.translations, "guild_init.messages.error", error=e)
        else:
            logging.warning("[GuildInit] Unknown config mode '%s' for guild %s",config_mode,guild_id,)
            response = get_user_message(ctx, self.translations, "guild_init.messages.unknown_mode")

        await ctx.followup.send(response, ephemeral=True)

def setup(bot: discord.Bot):
    bot.add_cog(GuildInit(bot))
