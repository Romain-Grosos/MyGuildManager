import discord
from discord.ext import commands
import logging
from functions import get_user_message
from translation import translations as global_translations

GUILD_INIT_DATA = global_translations.get("guild_init", {})

class GuildInit(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

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
                discord.OptionChoice(
                    name=choice_data["name_localizations"]["en-US"],
                    value=choice_data["value"],
                    name_localizations=choice_data["name_localizations"]
                )
                for key, choice_data in GUILD_INIT_DATA["options"]["config_mode"]["choices"].items()
            ]
        )
    ):
        await ctx.defer(ephemeral=True)
        guild_id = ctx.guild.id

        # Vérifier si la guilde a été initialisée via /app_init
        init_query = "SELECT COUNT(*) FROM guild_settings WHERE guild_id = ?"
        init_result = await self.bot.run_db_query(init_query, (ctx.guild.id,), fetch_one=True)
        if not init_result or init_result[0] == 0:
            response = get_user_message(ctx, self.bot.translations, "guild_init.messages.not_initialized")
            return await ctx.followup.send(response, ephemeral=True)

        # Vérifier si le serveur est en mode communauté
        community_activated = "COMMUNITY" in ctx.guild.features
        logging.info(f"[GuildInit] Community mode activated: {community_activated}")

        # Basculer selon le mode de configuration choisi
        if config_mode == "existing":
            # Mode 1 : Utiliser les rôles et channels existants
            # Récupérer les rôles et channels
            roles = ctx.guild.roles  # Liste de tous les rôles
            channels = ctx.guild.channels  # Liste de tous les channels
            # Ici, vous devriez implémenter la logique pour que l'utilisateur associe ces rôles et channels aux fonctions attendues.
            # Par exemple, envoyer un message avec la liste et inviter l'utilisateur à sélectionner via des boutons ou des menus.
            response = get_user_message(ctx, self.bot.translations, "guild_init.messages.setup_existing")
            # Vous pouvez stocker les IDs correspondants dans la base via une requête SQL.
        elif config_mode == "complete":
            try:
                # Récupérer la langue de la guilde depuis la BDD
                query_lang = "SELECT guild_lang FROM guild_settings WHERE guild_id = ?"
                result = await self.bot.run_db_query(query_lang, (ctx.guild.id,), fetch_one=True)
                if result:
                    guild_lang = result[0]
                else:
                    guild_lang = "en-US"

                # --- Création des rôles ---
                everyone = ctx.guild.default_role
                new_perms = everyone.permissions
                new_perms.update(send_messages=False)
                await everyone.edit(permissions=new_perms)

                role_colors = {
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
                role_names_data = GUILD_INIT_DATA.get("role_names", {})
                created_roles = {}
                for key, translations_dict in role_names_data.items():
                    role_name = translations_dict.get(guild_lang, translations_dict.get("en-US"))
                    role_color = role_colors.get(key, discord.Color.default())
                    role = await ctx.guild.create_role(name=role_name, color=role_color)
                    created_roles[key] = role.id
                    logging.info(f"[GuildInit] Created role '{role_name}' with ID {role.id}")

                # Enregistrement dans la base de données
                values = (
                    guild_id,
                    created_roles.get("guild_master"),
                    created_roles.get("officer"),
                    created_roles.get("guardian"),
                    created_roles.get("members"),
                    created_roles.get("absent_members"),
                    created_roles.get("allies"),
                    created_roles.get("diplomats"),
                    created_roles.get("friends"),
                    created_roles.get("applicant"),
                    created_roles.get("config_ok"),
                    created_roles.get("rules_ok")
                )

                insert_query = """
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

                await self.bot.run_db_query(insert_query, values, commit=True)

                # Création des channels et catégories
                channel_names = GUILD_INIT_DATA.get("channel_names", {})

                # Créer le canal "rules"
                rules_name = channel_names.get("rules", {}).get(guild_lang)
                rules_channel = await ctx.guild.create_text_channel(name=rules_name)

                rules_text = channel_names.get("rules_message", {}).get(guild_lang)
                rules_message = await rules_channel.send(rules_text)

                await rules_message.add_reaction("✅")

                # Créer la catégorie "guilde" et la peupler
                cat_guild_name = channel_names.get("cat_guild", {}).get(guild_lang)
                category_guilde = await ctx.guild.create_category(name=cat_guild_name)

                announcements_name = channel_names.get("announcements", {}).get(guild_lang)
                announcements_channel = await ctx.guild.create_text_channel(name=announcements_name,category=category_guilde)

                tavern_name = channel_names.get("tavern", {}).get(guild_lang)
                await ctx.guild.create_text_channel(name=tavern_name,category=category_guilde)

                hof_name = channel_names.get("hall_of_fame", {}).get(guild_lang)
                await ctx.guild.create_text_channel(name=hof_name,category=category_guilde)

                tavern_voc_name = channel_names.get("tavern_voc", {}).get(guild_lang)
                voice_tavern_channel = await ctx.guild.create_voice_channel(name=tavern_voc_name,category=category_guilde)

                afk_channel = await ctx.guild.create_voice_channel(name="💤 AFK",category=category_guilde)
                await ctx.guild.edit(afk_channel=afk_channel, afk_timeout=900) 

                create_room_name = channel_names.get("create_room", {}).get(guild_lang)
                create_room_channel = await ctx.guild.create_voice_channel(name=create_room_name,category=category_guilde)

                # Créer la catégorie "organisation" et la peupler
                cat_org_name = channel_names.get("cat_org", {}).get(guild_lang)
                category_org = await ctx.guild.create_category(name=cat_org_name)

                events_name = channel_names.get("events", {}).get(guild_lang)
                events_channel = await ctx.guild.create_text_channel(name=events_name,category=category_org)

                members_name = channel_names.get("members", {}).get(guild_lang)
                members_channel = await ctx.guild.create_text_channel(name=members_name,category=category_org)
                members_text = "."
                members_m1 = members_channel.send(members_text)
                members_m2 = members_channel.send(members_text)
                members_m3 = members_channel.send(members_text)
                members_m4 = members_channel.send(members_text)
                members_m5 = members_channel.send(members_text)

                groups_name = channel_names.get("groups", {}).get(guild_lang)
                groups_channel = await ctx.guild.create_text_channel(name=groups_name,category=category_org)

                abs_name = channel_names.get("abs", {}).get(guild_lang)
                abs_channel = await ctx.guild.create_text_channel(name=abs_name,category=category_org)

                abs_text = channel_names.get("absences_message", {}).get(guild_lang)
                await abs_channel.send(abs_text)

                loot_name = channel_names.get("loot", {}).get(guild_lang)
                loot_channel = await ctx.guild.create_text_channel(name=loot_name,category=category_org)

                # Créer la catégorie "conseil" et la peupler
                cat_conseil_name = channel_names.get("cat_conseil", {}).get(guild_lang)
                category_conseil = await ctx.guild.create_category(name=cat_conseil_name)

                rounded_tab_name = channel_names.get("rounded_table", {}).get(guild_lang)
                await ctx.guild.create_text_channel(name=rounded_tab_name,category=category_conseil)

                CR_name = channel_names.get("compte_rendus", {}).get(guild_lang)
                await ctx.guild.create_text_channel(name=CR_name,category=category_conseil)

                notifications_name = channel_names.get("notifications", {}).get(guild_lang)
                notifications_channel = await ctx.guild.create_text_channel(name=notifications_name,category=category_conseil)
                await ctx.guild.edit(system_channel=notifications_channel)

                staff_voc_name = channel_names.get("staff", {}).get(guild_lang)
                await ctx.guild.create_voice_channel(name=staff_voc_name,category=category_conseil)

                # Créer la catégorie "recrutement" et la peupler
                cat_recrut_name = channel_names.get("cat_recrut", {}).get(guild_lang)
                category_recrut = await ctx.guild.create_category(name=cat_recrut_name)

                external_recruitment_name = channel_names.get("ext_recrut", {}).get(guild_lang)
                external_recruitment_channel = await ctx.guild.create_text_channel(name=external_recruitment_name,category=category_recrut)

                embed = discord.Embed(
                    title=channel_names.get("recrut_message", {}).get(guild_lang),
                    description=".",
                    color=discord.Color.blurple()
                )
                external_recruitment_message = await external_recruitment_channel.send(embed=embed)

                # Créer la catégorie "diplomatie"
                cat_diplo_name = channel_names.get("cat_diplo", {}).get(guild_lang)
                category_diplo = await ctx.guild.create_category(name=cat_diplo_name)

                # Créer la catégorie "amis" et la peupler
                cat_ami_name = channel_names.get("cat_ami", {}).get(guild_lang)
                category_ami = await ctx.guild.create_category(name=cat_ami_name)

                tavern_amis_name = channel_names.get("ami_tavern", {}).get(guild_lang)
                await ctx.guild.create_text_channel(name=tavern_amis_name,category=category_ami)

                tavern_amis_voc_name = channel_names.get("ami_tavern_voc", {}).get(guild_lang)
                await ctx.guild.create_voice_channel(name=tavern_amis_voc_name,category=category_ami)

                # Vérifier si le serveur n'est pas déjà en mode communauté
                if "COMMUNITY" not in ctx.guild.features:
                    await ctx.followup.send(get_user_message(ctx, self.bot.translations, "guild_init.messages.community_required"))
                    try:
                        # Activation du mode communauté en fournissant les IDs des canaux requis
                        await ctx.guild.edit(
                            community=True,
                            verification_level=discord.VerificationLevel.medium,
                            explicit_content_filter=discord.ContentFilter.all_members,
                            rules_channel=rules_channel,
                            public_updates_channel=notifications_channel,
                            preferred_locale=guild_lang
                        )
                        logging.info("[GuildInit] Server set to community mode.")
                    except Exception as e:
                        logging.error("[GuildInit] Failed to set community mode: %s", e)
                        return await ctx.followup.send(get_user_message(ctx, self.bot.translations, "guild_init.messages.error", error=e), ephemeral=True)

                # Activation des fonctions spécifiques communauté après activation
                tuto_name = channel_names.get("tuto", {}).get(guild_lang)
                tuto_channel = await ctx.guild.create_forum_channel(name=tuto_name,category=category_org,position=99)

                forum_name = channel_names.get("forum_org", {}).get(guild_lang)
                forum_org = await ctx.guild.create_forum_channel(name=forum_name, category=category_conseil,position=99)

                forum_allies_channel = await forum_org.create_thread(
                    name = channel_names.get("topic_ally", {}).get(guild_lang),
                    content = channel_names.get("message_ally", {}).get(guild_lang),
                    auto_archive_duration=1440
                )

                forum_friends_channel = await forum_org.create_thread(
                    name = channel_names.get("topic_friends", {}).get(guild_lang),
                    content = channel_names.get("message_friends", {}).get(guild_lang),
                    auto_archive_duration=1440
                )

                forum_diplomats_channel = await forum_org.create_thread(
                    name = channel_names.get("topic_diplomats", {}).get(guild_lang),
                    content = channel_names.get("message_diplomats", {}).get(guild_lang),
                    auto_archive_duration=1440
                )

                forum_recruitment_channel = await forum_org.create_thread(
                    name = channel_names.get("topic_recruitment", {}).get(guild_lang),
                    content = channel_names.get("message_recruitment", {}).get(guild_lang),
                    auto_archive_duration=1440
                )

                forum_members_channel = await forum_org.create_thread(
                    name = channel_names.get("topic_members", {}).get(guild_lang),
                    content = channel_names.get("message_members", {}).get(guild_lang),
                    auto_archive_duration=1440
                )

                await announcements_channel.edit(type=discord.ChannelType.news)

                # Insertions dans la base de données
                channels_values = (
                    ctx.guild.id,
                    rules_channel.id,
                    rules_message.id,
                    announcements_channel.id,
                    voice_tavern_channel.id,
                    create_room_channel.id,
                    events_channel.id,
                    members_channel.id,
                    members_m1.id,
                    members_m2.id,
                    members_m3.id,
                    members_m4.id,
                    members_m5.id,
                    groups_channel.id,
                    abs_channel.id,
                    loot_channel.id,
                    tuto_channel.id,
                    forum_allies_channel.id,
                    forum_friends_channel.id,
                    forum_diplomats_channel.id,
                    forum_recruitment_channel.id,
                    forum_members_channel.id,
                    notifications_channel.id,
                    external_recruitment_channel.id,
                    external_recruitment_message.id,
                    category_diplo.id
                )

                insert_query = """
                INSERT INTO guild_channels (
                    guild_id,
                    rules_channel,
                    rules_message,
                    announcements_channel,
                    voice_tavern_channel,
                    create_room_channel,
                    events_channel,
                    members_channel,
                    members_m1,
                    members_m2,
                    members_m3,
                    members_m4,
                    members_m5,
                    groups_channel,
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    rules_channel = VALUES(rules_channel),
                    rules_message = VALUES(rules_message),
                    announcements_channel = VALUES(announcements_channel),
                    voice_tavern_channel = VALUES(voice_tavern_channel),
                    create_room_channel = VALUES(create_room_channel),
                    events_channel = VALUES(events_channel),
                    members_channel = VALUES(members_channel),
                    members_m1 = VALUES(members_m1),
                    members_m2 = VALUES(members_m2),
                    members_m3 = VALUES(members_m3),
                    members_m4 = VALUES(members_m4),
                    members_m5 = VALUES(members_m5),
                    groups_channel = VALUES(groups_channel),
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

                notification_cog = self.bot.get_cog("Notification")
                if notification_cog:
                    await notification_cog.load_notification_channels()

                autorole_cog = self.bot.get_cog("AutoRole")
                if autorole_cog:
                    await autorole_cog.load_rules_messages()
                    await autorole_cog.load_rules_ok_roles()
                    await autorole_cog.load_guild_lang()

                guildmembers_cog = self.bot.get_cog("GuildMembers")
                if guildmembers_cog:
                    await guildmembers_cog.load_forum_channels()

                profilesetup_cog = self.bot.get_cog("ProfileSetup")
                if profilesetup_cog:
                    await profilesetup_cog.load_roles()
                    await profilesetup_cog.load_forum_channels()

                dynamic_voice_cog = self.bot.get_cog("DynamicVoice")
                if dynamic_voice_cog:
                    await dynamic_voice_cog.load_create_room_channels()

                absence_cog = self.bot.get_cog("AbsenceManager")
                if absence_cog:
                    await absence_cog.load_absence_channels()

                response = get_user_message(ctx, self.bot.translations, "guild_init.messages.setup_complete")
            except Exception as e:
                logging.error("[GuildInit] Error during complete configuration: %s", e)
                response = get_user_message(ctx, self.bot.translations, "guild_init.messages.error", error=e)
        else:
            response = get_user_message(ctx, self.bot.translations, "guild_init.messages.unknown_mode")

        await ctx.followup.send(response, ephemeral=True)

def setup(bot: discord.Bot):
    bot.add_cog(GuildInit(bot))
