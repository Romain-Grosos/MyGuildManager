import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import pytz

from translation import translations as global_translations

GUILD_PTB = global_translations.get("guild_ptb", {})

class GuildPTB(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild_settings = {}
        self.ptb_settings = {}
        self.active_events = {}
        
    async def cog_load(self):
        logging.info("[GuildPTB] Cog loaded successfully. Caches will be loaded on bot ready.")
    
    async def cog_unload(self):
        logging.info("[GuildPTB] Cog unloaded.")
    
    @commands.Cog.listener()
    async def on_ready(self):
        asyncio.create_task(self.load_guild_settings())
        asyncio.create_task(self.load_ptb_settings())
        logging.debug("[GuildPTB] Cache loading tasks started in on_ready.")
    
    async def load_guild_settings(self) -> None:
        query = """
        SELECT guild_id, guild_ptb, guild_lang, initialized
        FROM guild_settings
        """
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            self.guild_settings = {}
            for row in rows:
                guild_id = int(row[0])
                self.guild_settings[guild_id] = {
                    "ptb_guild_id": int(row[1]) if row[1] else None,
                    "guild_lang": row[2] or "en-US",
                    "initialized": bool(row[3])
                }
            logging.debug(f"[GuildPTB] Guild settings loaded: {len(self.guild_settings)} guilds")
        except Exception as e:
            logging.error(f"[GuildPTB] Error loading guild settings: {e}", exc_info=True)
            self.guild_settings = {}
    
    async def load_ptb_settings(self) -> None:
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
            self.ptb_settings = {}
            for row in rows:
                guild_id = int(row[0])
                self.ptb_settings[guild_id] = {
                    "ptb_guild_id": int(row[1]),
                    "info_channel_id": int(row[2]),
                    "groups": {}
                }
                
                for i in range(1, 13):
                    role_idx = 2 + (i-1) * 2 + 1
                    channel_idx = role_idx + 1
                    
                    if row[role_idx] and row[channel_idx]:
                        self.ptb_settings[guild_id]["groups"][f"G{i}"] = {
                            "role_id": int(row[role_idx]),
                            "channel_id": int(row[channel_idx])
                        }
                        
            logging.debug(f"[GuildPTB] PTB settings loaded: {len(self.ptb_settings)} configurations")
        except Exception as e:
            logging.error(f"[GuildPTB] Error loading PTB settings: {e}", exc_info=True)
    
    async def _verify_ptb_ownership(self, main_guild_id: int, ptb_guild_id: int) -> bool:
        try:
            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                logging.error(f"[GuildPTB] PTB guild {ptb_guild_id} not found or bot has no access")
                return False

            bot_member = ptb_guild.get_member(self.bot.user.id)
            if not bot_member:
                logging.error(f"[GuildPTB] Bot is not a member of PTB guild {ptb_guild_id}")
                return False
            
            if ptb_guild.owner_id != self.bot.user.id and not bot_member.guild_permissions.administrator:
                logging.error(f"[GuildPTB] Bot lacks sufficient permissions in PTB guild {ptb_guild_id}")
                return False

            if main_guild_id not in self.ptb_settings:
                logging.error(f"[GuildPTB] No PTB settings found for main guild {main_guild_id}")
                return False
            
            if self.ptb_settings[main_guild_id]["ptb_guild_id"] != ptb_guild_id:
                logging.error(f"[GuildPTB] PTB guild ID mismatch in database for guild {main_guild_id}")
                return False

            expected_roles = [f"G{i}" for i in range(1, 13)]
            existing_roles = [role.name for role in ptb_guild.roles if role.name.startswith("G") and role.name[1:].isdigit()]
            
            if len(existing_roles) < 12:
                logging.warning(f"[GuildPTB] PTB guild {ptb_guild_id} missing some expected roles (found {len(existing_roles)}/12)")
            
            return True
            
        except Exception as e:
            logging.error(f"[GuildPTB] Error verifying PTB ownership: {e}", exc_info=True)
            return False
    
    async def initialize_ptb_server(self, main_guild_id: int, authorized_user_id: int = None) -> bool:
        try:
            main_guild = self.bot.get_guild(main_guild_id)
            if not main_guild:
                logging.error(f"[GuildPTB] Main guild {main_guild_id} not found")
                return False

            bot_member = main_guild.get_member(self.bot.user.id)
            if not bot_member or not bot_member.guild_permissions.administrator:
                logging.error(f"[GuildPTB] Bot lacks administrator permissions in main guild {main_guild_id}")
                return False

            if authorized_user_id:
                authorized_member = main_guild.get_member(authorized_user_id)
                if not authorized_member or (
                    authorized_member.id != main_guild.owner_id and 
                    not authorized_member.guild_permissions.manage_guild
                ):
                    logging.error(f"[GuildPTB] User {authorized_user_id} not authorized to initialize PTB for guild {main_guild_id}")
                    return False

            if main_guild_id not in self.guild_settings:
                await self.load_guild_settings()
            
            if main_guild_id not in self.guild_settings or not self.guild_settings[main_guild_id]["initialized"]:
                logging.error(f"[GuildPTB] Main guild {main_guild_id} is not properly initialized")
                return False

            if self.guild_settings[main_guild_id]["ptb_guild_id"]:
                logging.warning(f"[GuildPTB] PTB already exists for guild {main_guild_id}")
                return False

            ptb_guild = await self.bot.create_guild(
                name=f"{main_guild.name} - PTB",
                region=main_guild.region if hasattr(main_guild, 'region') else None
            )
            
            logging.info(f"[GuildPTB] Created PTB server {ptb_guild.id} for main guild {main_guild_id}")

            success = await self._setup_ptb_structure(main_guild_id, ptb_guild)
            
            if success:
                await self.bot.run_db_query(
                    "UPDATE guild_settings SET guild_ptb = %s WHERE guild_id = %s",
                    (ptb_guild.id, main_guild_id),
                    commit=True
                )

                self.guild_settings[main_guild_id]["ptb_guild_id"] = ptb_guild.id
                
                logging.info(f"[GuildPTB] Successfully initialized PTB server for guild {main_guild_id}")
                return True
            else:
                await ptb_guild.delete()
                logging.error(f"[GuildPTB] Failed to setup PTB structure, deleted server")
                return False
                
        except Exception as e:
            logging.error(f"[GuildPTB] Error initializing PTB server: {e}", exc_info=True)
            return False
    
    async def _setup_ptb_structure(self, main_guild_id: int, ptb_guild: discord.Guild) -> bool:
        try:
            roles = {}
            for i in range(1, 13):
                role = await ptb_guild.create_role(
                    name=f"G{i}",
                    mentionable=True,
                    reason="PTB Group Role"
                )
                roles[f"G{i}"] = role
                logging.debug(f"[GuildPTB] Created role G{i} ({role.id})")

            channels = {}
            for i in range(1, 13):
                overwrites = {
                    ptb_guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    roles[f"G{i}"]: discord.PermissionOverwrite(
                        view_channel=True,
                        connect=True,
                        speak=True,
                        use_voice_activation=True
                    )
                }
                
                channel = await ptb_guild.create_voice_channel(
                    name=f"G{i}",
                    overwrites=overwrites,
                    reason="PTB Group Voice Channel"
                )
                channels[f"G{i}"] = channel
                logging.debug(f"[GuildPTB] Created voice channel G{i} ({channel.id})")

            info_overwrites = {
                ptb_guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    add_reactions=True,
                    read_message_history=True
                )
            }
            
            info_channel = await ptb_guild.create_text_channel(
                name="infos",
                overwrites=info_overwrites,
                reason="PTB Info Channel"
            )
            logging.debug(f"[GuildPTB] Created info channel ({info_channel.id})")

            try:
                await ptb_guild.default_role.edit(
                    permissions=ptb_guild.default_role.permissions.update(change_nickname=False),
                    reason="PTB Configuration - Disable nickname changes for @everyone"
                )
                logging.debug("[GuildPTB] Removed change_nickname permission from @everyone")
            except Exception as e:
                logging.warning(f"[GuildPTB] Could not remove change_nickname permission: {e}")

            await self._save_ptb_settings(main_guild_id, ptb_guild.id, info_channel.id, roles, channels)
            
            return True
            
        except Exception as e:
            logging.error(f"[GuildPTB] Error setting up PTB structure: {e}", exc_info=True)
            return False
    
    async def _save_ptb_settings(self, main_guild_id: int, ptb_guild_id: int, info_channel_id: int, 
                                roles: Dict[str, discord.Role], channels: Dict[str, discord.VoiceChannel]) -> None:
        try:
            data = {
                "guild_id": main_guild_id,
                "ptb_guild_id": ptb_guild_id,
                "info_channel_id": info_channel_id
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
            """
            
            await self.bot.run_db_query(query, data, commit=True)

            self.ptb_settings[main_guild_id] = {
                "ptb_guild_id": ptb_guild_id,
                "info_channel_id": info_channel_id,
                "groups": {}
            }
            
            for i in range(1, 13):
                group_key = f"G{i}"
                self.ptb_settings[main_guild_id]["groups"][group_key] = {
                    "role_id": roles[group_key].id,
                    "channel_id": channels[group_key].id
                }
            
            logging.info(f"[GuildPTB] Saved PTB settings for guild {main_guild_id}")
            
        except Exception as e:
            logging.error(f"[GuildPTB] Error saving PTB settings: {e}", exc_info=True)
            raise
    
    async def assign_event_permissions(self, main_guild_id: int, event_id: int, groups_data: Dict) -> bool:
        try:
            if main_guild_id not in self.ptb_settings:
                logging.error(f"[GuildPTB] No PTB configuration found for guild {main_guild_id}")
                return False
            
            ptb_settings = self.ptb_settings[main_guild_id]
            ptb_guild_id = ptb_settings["ptb_guild_id"]

            if not await self._verify_ptb_ownership(main_guild_id, ptb_guild_id):
                logging.error(f"[GuildPTB] PTB ownership verification failed for guild {main_guild_id}")
                return False
            
            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                logging.error(f"[GuildPTB] PTB guild not found after verification: {ptb_guild_id}")
                return False

            if main_guild_id not in self.active_events:
                self.active_events[main_guild_id] = {}
            
            self.active_events[main_guild_id][event_id] = {
                "groups_data": groups_data,
                "assigned_members": set(),
                "start_time": datetime.now()
            }

            await self._assign_roles_to_members(ptb_guild, ptb_settings, groups_data)

            await self._send_event_recap(ptb_guild, ptb_settings["info_channel_id"], event_id, groups_data)

            await self._send_invitations_to_missing_members(main_guild_id, ptb_guild, groups_data)
            
            logging.info(f"[GuildPTB] Assigned event permissions for event {event_id} in guild {main_guild_id}")
            return True
            
        except Exception as e:
            logging.error(f"[GuildPTB] Error assigning event permissions: {e}", exc_info=True)
            return False
    
    async def _assign_roles_to_members(self, ptb_guild: discord.Guild, ptb_settings: Dict, groups_data: Dict) -> None:
        try:
            for group_name, member_ids in groups_data.items():
                if group_name not in ptb_settings["groups"]:
                    logging.warning(f"[GuildPTB] Group {group_name} not found in PTB settings")
                    continue
                
                role_id = ptb_settings["groups"][group_name]["role_id"]
                role = ptb_guild.get_role(role_id)
                
                if not role:
                    logging.error(f"[GuildPTB] Role {group_name} not found in PTB guild")
                    continue
                
                for member_id in member_ids:
                    member = ptb_guild.get_member(member_id)
                    if member and role not in member.roles:
                        try:
                            await member.add_roles(role, reason=f"Event group assignment: {group_name}")
                            logging.debug(f"[GuildPTB] Added role {group_name} to {member.display_name}")
                        except Exception as e:
                            logging.error(f"[GuildPTB] Error adding role to {member.display_name}: {e}")
                            
        except Exception as e:
            logging.error(f"[GuildPTB] Error assigning roles to members: {e}", exc_info=True)
    
    async def _send_event_recap(self, ptb_guild: discord.Guild, info_channel_id: int, event_id: int, groups_data: Dict) -> None:
        try:
            info_channel = ptb_guild.get_channel(info_channel_id)
            if not info_channel:
                logging.error(f"[GuildPTB] Info channel not found: {info_channel_id}")
                return

            guild_lang = "en-US"
            main_guild_id = None
            for guild_id, settings in self.ptb_settings.items():
                if settings["ptb_guild_id"] == ptb_guild.id:
                    main_guild_id = guild_id
                    break
            
            if main_guild_id and main_guild_id in self.guild_settings:
                guild_lang = self.guild_settings[main_guild_id].get("guild_lang", "en-US")

            title = GUILD_PTB["event_recap"]["title"].get(guild_lang, 
                GUILD_PTB["event_recap"]["title"].get("en-US")).format(event_id=event_id)
            description = GUILD_PTB["event_recap"]["description"].get(guild_lang,
                GUILD_PTB["event_recap"]["description"].get("en-US"))
            footer_text = GUILD_PTB["event_recap"]["footer"].get(guild_lang,
                GUILD_PTB["event_recap"]["footer"].get("en-US"))
            
            embed = discord.Embed(
                title=title,
                description=description,
                color=0x00ff00,
                timestamp=datetime.now()
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
                        members_count_text = GUILD_PTB["event_recap"]["members_count"].get(guild_lang,
                            GUILD_PTB["event_recap"]["members_count"].get("en-US")).format(count=len(members_list))
                        value = members_count_text
                    
                    embed.add_field(
                        name=f"🎯 {group_name}",
                        value=value,
                        inline=True
                    )
            
            embed.set_footer(text=footer_text)
            
            await info_channel.send(embed=embed)
            logging.debug(f"[GuildPTB] Sent event recap for event {event_id}")
            
        except Exception as e:
            logging.error(f"[GuildPTB] Error sending event recap: {e}", exc_info=True)
    
    async def _send_invitations_to_missing_members(self, main_guild_id: int, ptb_guild: discord.Guild, groups_data: Dict) -> None:
        try:
            main_guild = self.bot.get_guild(main_guild_id)
            if not main_guild:
                return

            info_channel = None
            for channel in ptb_guild.text_channels:
                if channel.permissions_for(ptb_guild.me).create_instant_invite:
                    info_channel = channel
                    break
            
            if not info_channel:
                logging.error(f"[GuildPTB] No suitable channel found for creating invite")
                return
            
            invite = await info_channel.create_invite(
                max_age=3600,
                max_uses=0,
                reason="Event group assignment invitation"
            )

            all_member_ids = set()
            for member_ids in groups_data.values():
                all_member_ids.update(member_ids)

            guild_lang = "en-US"
            if main_guild_id in self.guild_settings:
                guild_lang = self.guild_settings[main_guild_id].get("guild_lang", "en-US")

            invitation_message = GUILD_PTB["invitation"]["dm_message"].get(guild_lang,
                GUILD_PTB["invitation"]["dm_message"].get("en-US")).format(invite_url=invite.url)
            
            for member_id in all_member_ids:
                ptb_member = ptb_guild.get_member(member_id)
                if not ptb_member:
                    main_member = main_guild.get_member(member_id)
                    if main_member:
                        try:
                            await main_member.send(invitation_message)
                            logging.debug(f"[GuildPTB] Sent PTB invitation to {main_member.display_name}")
                        except discord.Forbidden:
                            logging.warning(f"[GuildPTB] Cannot send DM to {main_member.display_name}")
                        except Exception as e:
                            logging.error(f"[GuildPTB] Error sending invitation to {main_member.display_name}: {e}")
                            
        except Exception as e:
            logging.error(f"[GuildPTB] Error sending invitations: {e}", exc_info=True)
    
    async def remove_event_permissions(self, main_guild_id: int, event_id: int) -> bool:
        try:
            if (main_guild_id not in self.active_events or 
                event_id not in self.active_events[main_guild_id]):
                logging.warning(f"[GuildPTB] No active event found: {main_guild_id}_{event_id}")
                return False
            
            ptb_settings = self.ptb_settings.get(main_guild_id)
            if not ptb_settings:
                logging.error(f"[GuildPTB] No PTB settings found for guild {main_guild_id}")
                return False
            
            ptb_guild_id = ptb_settings["ptb_guild_id"]

            if not await self._verify_ptb_ownership(main_guild_id, ptb_guild_id):
                logging.error(f"[GuildPTB] PTB ownership verification failed during cleanup for guild {main_guild_id}")
                return False
            
            ptb_guild = self.bot.get_guild(ptb_guild_id)
            if not ptb_guild:
                logging.error(f"[GuildPTB] PTB guild not found after verification")
                return False
            
            event_data = self.active_events[main_guild_id][event_id]
            groups_data = event_data["groups_data"]

            for group_name, member_ids in groups_data.items():
                if group_name not in ptb_settings["groups"]:
                    continue
                
                role_id = ptb_settings["groups"][group_name]["role_id"]
                role = ptb_guild.get_role(role_id)
                
                if not role:
                    continue
                
                for member_id in member_ids:
                    member = ptb_guild.get_member(member_id)
                    if member and role in member.roles:
                        try:
                            await member.remove_roles(role, reason=f"Event {event_id} ended")
                            logging.debug(f"[GuildPTB] Removed role {group_name} from {member.display_name}")
                        except Exception as e:
                            logging.error(f"[GuildPTB] Error removing role from {member.display_name}: {e}")

            del self.active_events[main_guild_id][event_id]
            if not self.active_events[main_guild_id]:
                del self.active_events[main_guild_id]
            
            logging.info(f"[GuildPTB] Removed event permissions for event {event_id}")
            return True
            
        except Exception as e:
            logging.error(f"[GuildPTB] Error removing event permissions: {e}", exc_info=True)
            return False
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            ptb_guild_id = member.guild.id
            main_guild_id = None
            
            for guild_id, settings in self.ptb_settings.items():
                if settings["ptb_guild_id"] == ptb_guild_id:
                    main_guild_id = guild_id
                    break
            
            if not main_guild_id or main_guild_id not in self.active_events:
                return

            for event_id, event_data in self.active_events[main_guild_id].items():
                groups_data = event_data["groups_data"]

                for group_name, member_ids in groups_data.items():
                    if member.id in member_ids:
                        ptb_settings = self.ptb_settings[main_guild_id]
                        if group_name in ptb_settings["groups"]:
                            role_id = ptb_settings["groups"][group_name]["role_id"]
                            role = member.guild.get_role(role_id)
                            
                            if role:
                                await member.add_roles(role, reason=f"Auto-assignment for event {event_id}")
                                logging.info(f"[GuildPTB] Auto-assigned role {group_name} to {member.display_name} for event {event_id}")
                        break

            await self._sync_nickname_from_main(member, main_guild_id)
                        
        except Exception as e:
            logging.error(f"[GuildPTB] Error handling member join: {e}", exc_info=True)
    
    async def _sync_nickname_from_main(self, ptb_member: discord.Member, main_guild_id: int):
        try:
            main_guild = self.bot.get_guild(main_guild_id)
            if not main_guild:
                return
            
            main_member = main_guild.get_member(ptb_member.id)
            if not main_member:
                return

            main_display_name = main_member.display_name

            if ptb_member.display_name != main_display_name:
                try:
                    await ptb_member.edit(nick=main_display_name, reason="Synchronisation depuis le Discord principal")
                    logging.info(f"[GuildPTB] Synchronized nickname for {ptb_member.id}: '{ptb_member.display_name}' -> '{main_display_name}'")
                except discord.Forbidden:
                    logging.warning(f"[GuildPTB] Cannot change nickname for {ptb_member.id} - insufficient permissions")
                except Exception as e:
                    logging.error(f"[GuildPTB] Error changing nickname for {ptb_member.id}: {e}")
                    
        except Exception as e:
            logging.error(f"[GuildPTB] Error synchronizing nickname: {e}", exc_info=True)
    
    @discord.slash_command(
        name=GUILD_PTB["commands"]["ptb_init"]["name"]["en-US"],
        description=GUILD_PTB["commands"]["ptb_init"]["description"]["en-US"],
        name_localizations=GUILD_PTB["commands"]["ptb_init"]["name"],
        description_localizations=GUILD_PTB["commands"]["ptb_init"]["description"]
    )
    @commands.has_permissions(manage_guild=True)
    async def ptb_init(self, 
                      ctx: discord.ApplicationContext, 
                      main_guild_id: discord.Option(
                          str, 
                          description=GUILD_PTB["commands"]["ptb_init"]["options"]["main_guild_id"]["description"]["en-US"],
                          description_localizations=GUILD_PTB["commands"]["ptb_init"]["options"]["main_guild_id"]["description"]
                      )):
        try:
            guild_lang = "en-US"

            if not ctx.author.guild_permissions.manage_guild and ctx.author.id != ctx.guild.owner_id:
                error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["no_permissions"].get(
                    guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["no_permissions"]["en-US"]
                )
                await ctx.respond(error_msg, ephemeral=True)
                return

            await ctx.defer()

            try:
                main_guild_id_int = int(main_guild_id)
            except ValueError:
                error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["error"].get(
                    guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["error"]["en-US"]
                ).format(error="Invalid guild ID format")
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            main_guild = self.bot.get_guild(main_guild_id_int)
            if not main_guild:
                error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["main_guild_not_found"].get(
                    guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["main_guild_not_found"]["en-US"]
                ).format(guild_id=main_guild_id)
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            if main_guild_id_int in self.guild_settings:
                guild_lang = self.guild_settings[main_guild_id_int].get("guild_lang", "en-US")

            if main_guild_id_int not in self.guild_settings:
                await self.load_guild_settings()
            
            if (main_guild_id_int not in self.guild_settings or 
                not self.guild_settings[main_guild_id_int]["initialized"]):
                error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["main_guild_not_initialized"].get(
                    guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["main_guild_not_initialized"]["en-US"]
                ).format(guild_id=main_guild_id)
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            if self.guild_settings[main_guild_id_int].get("ptb_guild_id"):
                error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["main_guild_already_has_ptb"].get(
                    guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["main_guild_already_has_ptb"]["en-US"]
                ).format(guild_id=main_guild_id)
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            for existing_main_guild_id, settings in self.ptb_settings.items():
                if settings["ptb_guild_id"] == ctx.guild.id:
                    error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["ptb_already_configured"].get(
                        guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["ptb_already_configured"]["en-US"]
                    ).format(main_guild_id=existing_main_guild_id)
                    await ctx.followup.send(error_msg, ephemeral=True)
                    return

            success = await self._setup_ptb_structure(main_guild_id_int, ctx.guild)
            
            if success:
                await self.bot.run_db_query(
                    "UPDATE guild_settings SET guild_ptb = %s WHERE guild_id = %s",
                    (ctx.guild.id, main_guild_id_int),
                    commit=True
                )

                if main_guild_id_int not in self.guild_settings:
                    self.guild_settings[main_guild_id_int] = {
                        "ptb_guild_id": None,
                        "guild_lang": "en-US",
                        "initialized": True
                    }
                self.guild_settings[main_guild_id_int]["ptb_guild_id"] = ctx.guild.id
                
                success_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["success"].get(
                    guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["success"]["en-US"]
                ).format(ptb_name=ctx.guild.name, main_guild_name=main_guild.name)
                
                await ctx.followup.send(success_msg, ephemeral=True)
                logging.info(f"[GuildPTB] PTB configured via slash command by {ctx.author} - PTB: {ctx.guild.id}, Main: {main_guild_id_int}")
            else:
                error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["error"].get(
                    guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["error"]["en-US"]
                ).format(error="PTB structure setup failed")
                
                await ctx.followup.send(error_msg, ephemeral=True)
                
        except Exception as e:
            error_msg = GUILD_PTB["commands"]["ptb_init"]["messages"]["error"].get(
                guild_lang, GUILD_PTB["commands"]["ptb_init"]["messages"]["error"]["en-US"]
            ).format(error=str(e))
            
            if ctx.response.is_done():
                await ctx.followup.send(error_msg, ephemeral=True)
            else:
                await ctx.respond(error_msg, ephemeral=True)
            
            logging.error(f"[GuildPTB] Error in ptb_init command: {e}", exc_info=True)
    
    async def audit_ptb_security(self, main_guild_id: int) -> Dict:
        audit_report = {
            "main_guild_id": main_guild_id,
            "status": "unknown",
            "issues": [],
            "recommendations": []
        }
        
        try:
            if main_guild_id not in self.guild_settings:
                audit_report["status"] = "no_ptb"
                audit_report["issues"].append("No PTB configured for this guild")
                return audit_report
            
            ptb_guild_id = self.guild_settings[main_guild_id].get("ptb_guild_id")
            if not ptb_guild_id:
                audit_report["status"] = "no_ptb"
                audit_report["issues"].append("PTB guild ID not found in settings")
                return audit_report

            ownership_ok = await self._verify_ptb_ownership(main_guild_id, ptb_guild_id)
            if not ownership_ok:
                audit_report["status"] = "security_issue"
                audit_report["issues"].append("PTB ownership verification failed")
                audit_report["recommendations"].append("Re-initialize PTB or check bot permissions")
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
                audit_report["issues"].append("Bot lacks administrator permissions in PTB")
            
            if not main_bot_member or not main_bot_member.guild_permissions.administrator:
                audit_report["issues"].append("Bot lacks administrator permissions in main guild")

            expected_roles = [f"G{i}" for i in range(1, 13)]
            existing_roles = [r.name for r in ptb_guild.roles if r.name in expected_roles]
            missing_roles = set(expected_roles) - set(existing_roles)
            
            if missing_roles:
                audit_report["issues"].append(f"Missing PTB roles: {', '.join(missing_roles)}")

            expected_channels = [f"G{i}" for i in range(1, 13)] + ["infos"]
            existing_channels = [c.name for c in ptb_guild.channels if c.name in expected_channels]
            missing_channels = set(expected_channels) - set(existing_channels)
            
            if missing_channels:
                audit_report["issues"].append(f"Missing PTB channels: {', '.join(missing_channels)}")

            if not audit_report["issues"]:
                audit_report["status"] = "secure"
            elif len(audit_report["issues"]) <= 2:
                audit_report["status"] = "minor_issues"
                audit_report["recommendations"].append("Address minor configuration issues")
            else:
                audit_report["status"] = "major_issues"
                audit_report["recommendations"].append("Consider re-initializing PTB")
            
            audit_report["ptb_guild_id"] = ptb_guild_id
            audit_report["ptb_guild_name"] = ptb_guild.name
            audit_report["member_count"] = ptb_guild.member_count
            
        except Exception as e:
            audit_report["status"] = "error"
            audit_report["issues"].append(f"Audit failed: {str(e)}")
            logging.error(f"[GuildPTB] Error during security audit: {e}", exc_info=True)
        
        return audit_report


def setup(bot):
    bot.add_cog(GuildPTB(bot))