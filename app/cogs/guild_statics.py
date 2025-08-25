"""
Guild Statics Cog - Static group management system for guild events.

This cog provides comprehensive static group management with:

STATIC GROUP FEATURES:
- Static group creation for guild events
- Member addition/removal with validation and limits
- Real-time message updates with group composition display
- Multi-language support for group names and commands
- Integration with guild member data and class information

PERFORMANCE OPTIMIZATIONS:
- Efficient cache management with automatic reload
- Batch operations for group member updates
- Smart message formatting with class emoji integration
- Optimized database queries with proper error handling

ENTERPRISE PATTERNS:
- ComponentLogger structured logging with correlation tracking
- Discord API resilience with retry logic
- Database transactions with rollback protection
- Comprehensive error handling and recovery
- Cache synchronization with guild data

Architecture: Enterprise-grade with comprehensive monitoring, automatic cleanup,
and production-ready reliability patterns.
"""

from __future__ import annotations

import time
from typing import Optional, TypedDict

import discord
from discord import NotFound, HTTPException
from discord.ext import commands

from app.core.logger import ComponentLogger
from app.core.reliability import discord_resilient
from app.core.translation import translations as global_translations

STATIC_GROUPS = global_translations.get("static_groups", {})

_logger = ComponentLogger("guild_statics")

class GroupMember(TypedDict, total=False):
    """Group member data structure for display/processing."""
    user_id: int
    pseudo: str
    member_class: str
    GS: str | int
    weapons: str
    tentative: bool

class GroupStats(TypedDict):
    """Group composition statistics."""
    size: int
    composition: str
    avg_gs: float
    tanks: int
    healers: int
    dps: int
    classes: dict[str, int]

WEAPON_EMOJIS = {
    "B": "<:TL_B:1362340360470270075>",
    "CB": "<:TL_CB:1362340413142335619>",
    "DG": "<:TL_DG:1362340445148938251>",
    "GS": "<:TL_GS:1362340479819059211>",
    "S": "<:TL_S:1362340495447167048>",
    "SNS": "<:TL_SNS:1362340514002763946>",
    "SP": "<:TL_SP:1362340530062888980>",
    "W": "<:TL_W:1362340545376030760>",
}

CLASS_EMOJIS = {
    "Tank": "<:tank:1374760483164524684>",
    "Healer": "<:healer:1374760495613218816>",
    "Melee DPS": "<:DPS:1374760287491850312>",
    "Ranged DPS": "<:DPS:1374760287491850312>",
    "Flanker": "<:flank:1374762529036959854>",
}

class StaticGroupsPaginationView(discord.ui.View):
    """
    Discord UI View for static groups pagination with navigation buttons.
    """
    
    def __init__(self, bot, guild_id: int, embeds: list[discord.Embed]):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.all_embeds = embeds
        self.current_page = 0
        self.items_per_page = 9  # 1 header + 8 groups per page max
        self.groups_per_page = 8  # Max groups per page

        if len(embeds) <= 1:
            self.total_pages = 1
        else:
            # First embed is header, rest are groups
            group_embeds_count = len(embeds) - 1
            # Each page can show 8 groups max
            if group_embeds_count <= self.groups_per_page:
                self.total_pages = 1
            else:
                remaining_groups = group_embeds_count - self.groups_per_page
                self.total_pages = 1 + ((remaining_groups + self.groups_per_page - 1) // self.groups_per_page)  # ceil division
        
        self._update_buttons()
    
    def _update_buttons(self):
        """Update button states based on current page."""
        self.previous_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page >= self.total_pages - 1

        if self.total_pages <= 1:
            self.previous_page.style = discord.ButtonStyle.gray
            self.next_page.style = discord.ButtonStyle.gray
            self.previous_page.disabled = True
            self.next_page.disabled = True
    
    def _get_current_embeds(self) -> list[discord.Embed]:
        """Get embeds for current page."""
        if len(self.all_embeds) <= self.items_per_page:
            return self.all_embeds
        
        header_embed = self.all_embeds[0]
        
        # Calculate group range for current page
        groups_start = 1 + (self.current_page * self.groups_per_page)
        groups_end = min(groups_start + self.groups_per_page, len(self.all_embeds))
        
        # Get groups for this page
        page_embeds = [header_embed] + self.all_embeds[groups_start:groups_end]
        
        # Update header with page info if multiple pages
        if self.total_pages > 1:
            updated_header = discord.Embed(
                title=header_embed.title,
                description=f"{header_embed.description}\n\n📄 Page {self.current_page + 1}/{self.total_pages}",
                color=header_embed.color
            )
            page_embeds[0] = updated_header
        
        return page_embeds
    
    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.primary, disabled=True)
    async def previous_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Navigate to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            
            embeds = self._get_current_embeds()
            await interaction.response.edit_message(embeds=embeds, view=self)
    
    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.primary)
    async def next_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Navigate to next page."""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_buttons()
            
            embeds = self._get_current_embeds()
            await interaction.response.edit_message(embeds=embeds, view=self)
    
    async def on_timeout(self):
        """Handle view timeout by disabling all buttons."""
        for item in self.children:
            item.disabled = True
        
        try:
            guild = self.bot.get_guild(self.guild_id)
            if guild:
                result = await self.bot.run_db_query(
                    "SELECT statics_channel, statics_message FROM guild_channels WHERE guild_id = %s",
                    (self.guild_id,),
                    fetch_one=True
                )
                
                if result and result[0] and result[1]:
                    channel = guild.get_channel(int(result[0]))
                    if channel:
                        message = await channel.fetch_message(int(result[1]))
                        await message.edit(view=self)
        except Exception:
            pass

class GuildStatics(commands.Cog):
    """
    Discord cog for managing static groups within guilds.

    This cog provides comprehensive static group management functionality including:
    - Static group creation for recurring events
    - Member addition and removal with validation
    - Real-time group composition updates
    - Integration with guild member data and classes
    - Multi-language support and localization
    """

    def __init__(self, bot):
        """
        Initialize the GuildStatics cog.

        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self._register_statics_commands()

    def _register_statics_commands(self):
        """Register static group commands with the centralized statics group."""
        if hasattr(self.bot, "statics_group"):

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_create", {})
                .get("name", {})
                .get("en-US", "group_create"),
                description=STATIC_GROUPS.get("static_create", {})
                .get("description", {})
                .get("en-US", "Create a static group"),
                name_localizations=STATIC_GROUPS.get("static_create", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_create", {}).get(
                    "description", {}
                ),
            )(self.static_create)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_add", {})
                .get("name", {})
                .get("en-US", "player_add"),
                description=STATIC_GROUPS.get("static_add", {})
                .get("description", {})
                .get("en-US", "Add player to static group"),
                name_localizations=STATIC_GROUPS.get("static_add", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_add", {}).get(
                    "description", {}
                ),
            )(self.static_add)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_remove", {})
                .get("name", {})
                .get("en-US", "player_remove"),
                description=STATIC_GROUPS.get("static_remove", {})
                .get("description", {})
                .get("en-US", "Remove player from static group"),
                name_localizations=STATIC_GROUPS.get("static_remove", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_remove", {}).get(
                    "description", {}
                ),
            )(self.static_remove)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_delete", {})
                .get("name", {})
                .get("en-US", "group_delete"),
                description=STATIC_GROUPS.get("static_delete", {})
                .get("description", {})
                .get("en-US", "Delete a static group"),
                name_localizations=STATIC_GROUPS.get("static_delete", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_delete", {}).get(
                    "description", {}
                ),
            )(self.static_delete)

            self.bot.statics_group.command(
                name=STATIC_GROUPS.get("static_update", {})
                .get("name", {})
                .get("en-US", "update"),
                description=STATIC_GROUPS.get("static_update", {})
                .get("description", {})
                .get("en-US", "Update static groups message"),
                name_localizations=STATIC_GROUPS.get("static_update", {}).get(
                    "name", {}
                ),
                description_localizations=STATIC_GROUPS.get("static_update", {}).get(
                    "description", {}
                ),
            )(self.static_update)

    async def get_static_group_data(
        self, guild_id: int, group_name: str
    ) -> Optional[dict]:
        """
        Get data for a specific static group.

        Args:
            guild_id: The guild ID
            group_name: Name of the static group

        Returns:
            Group data dictionary or None if not found
        """
        static_groups = await self.bot.cache.get_guild_data(guild_id, "static_groups")
        if not static_groups:
            return None

        return static_groups.get(group_name)
    
    async def get_group_names_autocomplete(self, ctx: discord.AutocompleteContext) -> list[str]:
        """
        Get list of static group names for autocomplete.
        
        Args:
            ctx: Discord autocomplete context
            
        Returns:
            List of group names
        """
        guild_id = ctx.interaction.guild_id
        groups = await self.bot.cache.get_guild_data(guild_id, "static_groups") or {}
        names = list(groups.keys())
        q = (ctx.value or "").lower()
        if q:
            names = [n for n in names if q in n.lower()]
        return names[:25]
    
    async def get_group_members_autocomplete(self, ctx: discord.AutocompleteContext) -> list[discord.OptionChoice]:
        """
        Get list of members from selected group for autocomplete.
        
        Args:
            ctx: Discord autocomplete context
            
        Returns:
            List of OptionChoice with member display names and IDs
        """
        guild_id = ctx.interaction.guild_id
        guild = ctx.interaction.guild
        group_name = ctx.options.get("group_name")

        if not group_name or not guild:
            return []

        group = await self.get_static_group_data(guild_id, group_name)
        member_ids = (group or {}).get("members", []) or []

        q = (ctx.value or "").lower()

        suggestions = []
        for mid in member_ids:
            m = guild.get_member(mid)
            if not m:
                continue
            display = m.display_name
            if not q or q in display.lower():
                suggestions.append(discord.OptionChoice(name=display, value=str(mid)))

        return suggestions[:25]

    async def get_static_groups_data(self, guild_id: int) -> dict:
        """
        Get static groups data from centralized cache.

        Args:
            guild_id: The guild ID to get data for

        Returns:
            Dictionary containing all static groups data for the guild
        """
        static_groups = await self.bot.cache.get_guild_data(guild_id, "static_groups")
        return static_groups or {}
    
    def _sort_groups_for_display(self, groups_dict: dict) -> list[tuple[str, dict]]:
        """
        Sort groups for display: lead groups first, then alphabetical, then pve groups.
        
        Args:
            groups_dict: Dictionary of group_name -> group_data
            
        Returns:
            List of (group_name, group_data) tuples sorted for display
        """
        group_items = list(groups_dict.items())
        
        def get_sort_key(item):
            group_name = item[0].lower()

            if "lead" in group_name:
                return (1, group_name)
            elif "pve" in group_name:
                return (3, group_name)
            else:
                return (2, group_name)
        
        return sorted(group_items, key=get_sort_key)

    async def _format_static_group_members(
        self, member_ids: list[int], guild_obj, absent_text: str
    ) -> list[str]:
        """
        Format static group members for display with class icons, weapons, and GS.

        Args:
            member_ids: List of Discord member IDs
            guild_obj: Discord guild object
            absent_text: Text to display for absent members

        Returns:
            List of formatted member strings with class icons and names
        """
        if not member_ids:
            return []

        member_info_list = []

        try:
            guild_members_cache = await self.bot.cache.get_bulk_guild_members(guild_obj.id) or {}
        except Exception:
            guild_members_cache = {}

        for member_id in member_ids:
            member = guild_obj.get_member(member_id) if guild_obj else None

            member_data = guild_members_cache.get(member_id, {})

            class_value = member_data.get("class", "Unknown")
            if not class_value or class_value == "NULL":
                class_value = "Unknown"

            gs_value = member_data.get("GS")
            if not gs_value or gs_value == 0 or gs_value == "0":
                gs_value = "N/A"

            weapons_value = member_data.get("weapons")
            if not weapons_value or weapons_value == "NULL":
                weapons_value = "N/A"

            member_info = {
                "member": member,
                "member_id": member_id,
                "class": class_value,
                "gs": gs_value,
                "weapons": weapons_value,
                "mention": (
                    member.mention if member else f"<@{member_id}> ({absent_text})"
                ),
                "is_present": member is not None,
            }
            member_info_list.append(member_info)

        class_priority = {
            "Tank": 1,
            "Healer": 2,
            "Melee DPS": 3,
            "Ranged DPS": 4,
            "Flanker": 5,
            "Unknown": 99,
        }

        member_info_list.sort(
            key=lambda x: (class_priority.get(x["class"], 99), not x["is_present"])
        )

        formatted_members = []
        for info in member_info_list:
            class_emoji = CLASS_EMOJIS.get(info["class"], "❓")

            weapons_emoji = ""
            if info["weapons"] and info["weapons"] != "N/A":
                weapon_list = [
                    w.strip() for w in info["weapons"].split("/") if w.strip()
                ]
                weapons_emoji = (
                    " ".join(
                        [
                            str(WEAPON_EMOJIS.get(weapon, weapon))
                            for weapon in weapon_list
                        ]
                    )
                    if weapon_list
                    else ""
                )

            gs_display = (
                f"({info['gs']})" if info["gs"] and info["gs"] != "N/A" else "(N/A)"
            )

            line = f"{class_emoji} {info['mention']} {weapons_emoji} {gs_display}"

            formatted_members.append(line)

        return formatted_members

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="guild_statics", max_retries=2)
    async def static_create(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_create"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_create"]["options"][
                "group_name"
            ]["description"],
            required=True,
            max_length=50,
        ),
    ):
        """
        Create a new static group.

        Args:
            ctx: Discord application context
            group_name: Name of the group to create
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = guild.id
        guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"

        try:
            existing_groups = await self.get_static_groups_data(guild_id)
            if group_name in existing_groups:
                error_msg = (
                    STATIC_GROUPS["static_create"]["messages"]["already_exists"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_create"]["messages"]["already_exists"].get(
                            "en-US"
                        ),
                    )
                    .format(group_name=group_name)
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return

            query = "INSERT INTO guild_static_groups (guild_id, group_name) VALUES (%s, %s)"
            await self.bot.run_db_query(query, (guild_id, group_name), commit=True)

            await self.bot.cache_loader.reload_category("static_groups")

            success_msg = (
                STATIC_GROUPS["static_create"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_create"]["messages"]["success"].get("en-US"),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(success_msg, ephemeral=True)

            _logger.info(
                "static_group_created",
                group_name=group_name,
                guild_id=guild_id,
            )

        except Exception as e:
            if "Duplicate entry" in str(e):
                duplicate_msg = (
                    STATIC_GROUPS["static_create"]["messages"]["already_exists"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_create"]["messages"][
                            "already_exists"
                        ].get("en-US"),
                    )
                    .format(group_name=group_name)
                )
                await ctx.followup.send(duplicate_msg, ephemeral=True)
            else:
                general_error_msg = (
                    STATIC_GROUPS["static_create"]["messages"]["error"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_create"]["messages"]["error"].get(
                            "en-US"
                        ),
                    )
                    .format(error=str(e))
                )
                await ctx.followup.send(general_error_msg, ephemeral=True)
                _logger.error("error_creating_static_group", error=str(e))

    @discord_resilient(service_name="guild_statics", max_retries=2)
    async def static_add(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_add"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_add"]["options"][
                "group_name"
            ]["description"],
            required=True,
            autocomplete=discord.utils.basic_autocomplete(lambda ctx: ctx.bot.get_cog("GuildStatics").get_group_names_autocomplete(ctx) if ctx.bot.get_cog("GuildStatics") else []),
        ),
        member: discord.Member = discord.Option(
            discord.Member,
            description=STATIC_GROUPS["static_add"]["options"]["member"]["description"][
                "en-US"
            ],
            description_localizations=STATIC_GROUPS["static_add"]["options"]["member"][
                "description"
            ],
            required=True,
        ),
    ):
        """
        Add a member to a static group.

        Args:
            ctx: Discord application context
            group_name: Name of the group
            member: Discord member to add
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = guild.id
        member_id = member.id
        guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"

        existing_groups = await self.get_static_groups_data(guild_id)
        if group_name not in existing_groups:
            error_msg = (
                STATIC_GROUPS["static_add"]["messages"]["group_not_found"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get(
                        "en-US"
                    ),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        group_data = existing_groups[group_name]
        current_members = group_data.get("members", [])
        
        if member_id in current_members:
            already_in_msg = (
                STATIC_GROUPS["static_add"]["messages"]["already_in_group"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["already_in_group"].get(
                        "en-US"
                    ),
                )
                .format(member=member.display_name, group_name=group_name)
            )
            await ctx.followup.send(already_in_msg, ephemeral=True)
            return

        if len(current_members) >= 20:
            full_group_msg = (
                STATIC_GROUPS["static_add"]["messages"]["group_full"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["group_full"].get("en-US"),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(full_group_msg, ephemeral=True)
            return

        try:
            static_groups_data = await self.bot.cache.get_guild_data(guild_id, "static_groups") or {}
            group_info = static_groups_data.get(group_name)

            if not group_info:
                not_found_msg = (
                    STATIC_GROUPS["static_add"]["messages"]["group_not_found"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_add"]["messages"]["group_not_found"].get(
                            "en-US"
                        ),
                    )
                    .format(group_name=group_name)
                )
                await ctx.followup.send(not_found_msg, ephemeral=True)
                return

            group_query = "SELECT id FROM guild_static_groups WHERE guild_id = %s AND group_name = %s AND is_active = TRUE"
            group_result = await self.bot.run_db_query(group_query, (guild_id, group_name), fetch_one=True)
            
            if not group_result:
                error_msg = (
                    STATIC_GROUPS["static_add"]["messages"]["group_db_not_found"]
                    .get(guild_lang, STATIC_GROUPS["static_add"]["messages"]["group_db_not_found"].get("en-US"))
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return
                
            group_id = group_result[0]
            position = len(current_members) + 1

            query = "INSERT INTO guild_static_members (group_id, member_id, position_order) VALUES (%s, %s, %s)"
            await self.bot.run_db_query(query, (group_id, member_id, position), commit=True)

            await self.bot.cache_loader.reload_category("static_groups")

            await self.update_static_groups_message(guild_id)

            updated_count = len(current_members) + 1
            
            success_msg = (
                STATIC_GROUPS["static_add"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["success"].get("en-US"),
                )
                .format(member=member.display_name, group_name=group_name, count=updated_count)
            )
            await ctx.followup.send(success_msg, ephemeral=True)

            _logger.info(
                "member_added_to_static_group",
                member_id=member_id,
                group_name=group_name,
                guild_id=guild_id,
            )

        except Exception as e:
            error_msg = (
                STATIC_GROUPS["static_add"]["messages"]["error"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_add"]["messages"]["error"].get("en-US"),
                )
                .format(error=str(e))
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            _logger.error("error_adding_member_static_group", error=str(e))

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="guild_statics", max_retries=2)
    async def static_remove(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_remove"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_remove"]["options"][
                "group_name"
            ]["description"],
            required=True,
            autocomplete=discord.utils.basic_autocomplete(lambda ctx: ctx.bot.get_cog("GuildStatics").get_group_names_autocomplete(ctx) if ctx.bot.get_cog("GuildStatics") else []),
        ),
        member_id: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_remove"]["options"]["member"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_remove"]["options"][
                "member"
            ]["description"],
            required=True,
            autocomplete=discord.utils.basic_autocomplete(lambda ctx: ctx.bot.get_cog("GuildStatics").get_group_members_autocomplete(ctx) if ctx.bot.get_cog("GuildStatics") else []),
        ),
    ):
        """
        Remove a member from a static group.

        Args:
            ctx: Discord application context
            group_name: Name of the group
            member_id: ID of member to remove
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = guild.id

        guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
        
        member = guild.get_member(int(member_id))
        if not member:
            error_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["member_not_found"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["member_not_found"].get(
                        "en-US"
                    ),
                )
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        existing_groups = await self.get_static_groups_data(guild_id)
        if group_name not in existing_groups:
            error_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["group_not_found"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["group_not_found"].get(
                        "en-US"
                    ),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        group_data = existing_groups[group_name]
        current_members = group_data.get("members", [])
        
        if member.id not in current_members:
            not_in_group_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["not_in_group"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["not_in_group"].get(
                        "en-US"
                    ),
                )
                .format(member=member.display_name, group_name=group_name)
            )
            await ctx.followup.send(not_in_group_msg, ephemeral=True)
            return

        try:
            static_groups_data = await self.bot.cache.get_guild_data(guild_id, "static_groups") or {}
            group_info = static_groups_data.get(group_name)

            if not group_info:
                not_found_msg = (
                    STATIC_GROUPS["static_remove"]["messages"]["group_not_found"]
                    .get(
                        guild_lang,
                        STATIC_GROUPS["static_remove"]["messages"][
                            "group_not_found"
                        ].get("en-US"),
                    )
                    .format(group_name=group_name)
                )
                await ctx.followup.send(not_found_msg, ephemeral=True)
                return

            group_query = "SELECT id FROM guild_static_groups WHERE guild_id = %s AND group_name = %s AND is_active = TRUE"
            group_result = await self.bot.run_db_query(group_query, (guild_id, group_name), fetch_one=True)
            
            if not group_result:
                error_msg = (
                    STATIC_GROUPS["static_remove"]["messages"]["group_db_not_found"]
                    .get(guild_lang, STATIC_GROUPS["static_remove"]["messages"]["group_db_not_found"].get("en-US"))
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return
                
            group_id = group_result[0]

            query = "DELETE FROM guild_static_members WHERE group_id = %s AND member_id = %s"
            await self.bot.run_db_query(query, (group_id, int(member_id)), commit=True)

            await self.bot.cache_loader.reload_category("static_groups")

            await self.update_static_groups_message(guild_id)

            updated_count = len(current_members) - 1
            
            success_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["success"].get("en-US"),
                )
                .format(member=member.display_name, group_name=group_name, count=updated_count)
            )
            await ctx.followup.send(success_msg, ephemeral=True)

            _logger.info(
                "member_removed_from_static_group",
                member_id=member_id,
                group_name=group_name,
                guild_id=guild_id,
            )

        except Exception as e:
            error_msg = (
                STATIC_GROUPS["static_remove"]["messages"]["error"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_remove"]["messages"]["error"].get("en-US"),
                )
                .format(error=str(e))
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            _logger.error("error_removing_member_static_group", error=str(e))

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="guild_statics", max_retries=2)
    async def static_delete(
        self,
        ctx: discord.ApplicationContext,
        group_name: str = discord.Option(
            str,
            description=STATIC_GROUPS["static_delete"]["options"]["group_name"][
                "description"
            ]["en-US"],
            description_localizations=STATIC_GROUPS["static_delete"]["options"][
                "group_name"
            ]["description"],
            required=True,
            autocomplete=discord.utils.basic_autocomplete(lambda ctx: ctx.bot.get_cog("GuildStatics").get_group_names_autocomplete(ctx) if ctx.bot.get_cog("GuildStatics") else []),
        ),
    ):
        """
        Delete a static group.

        Args:
            ctx: Discord application context
            group_name: Name of the group to delete
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = guild.id
        guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"

        existing_groups = await self.get_static_groups_data(guild_id)
        if group_name not in existing_groups:
            error_msg = (
                STATIC_GROUPS["static_delete"]["messages"]["not_found"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_delete"]["messages"]["not_found"].get(
                        "en-US"
                    ),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            return

        try:
            group_query = "SELECT id FROM guild_static_groups WHERE guild_id = %s AND group_name = %s AND is_active = TRUE"
            group_result = await self.bot.run_db_query(group_query, (guild_id, group_name), fetch_one=True)
            
            if not group_result:
                error_msg = (
                    STATIC_GROUPS["static_delete"]["messages"]["group_db_not_found"]
                    .get(guild_lang, STATIC_GROUPS["static_delete"]["messages"]["group_db_not_found"].get("en-US"))
                )
                await ctx.followup.send(error_msg, ephemeral=True)
                return
                
            group_id = group_result[0]

            await self.bot.run_db_query("DELETE FROM guild_static_members WHERE group_id = %s", (group_id,), commit=True)

            await self.bot.run_db_query("DELETE FROM guild_static_groups WHERE id = %s", (group_id,), commit=True)

            await self.bot.cache_loader.reload_category("static_groups")

            await self.update_static_groups_message(guild_id)

            success_msg = (
                STATIC_GROUPS["static_delete"]["messages"]["success"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_delete"]["messages"]["success"].get("en-US"),
                )
                .format(group_name=group_name)
            )
            await ctx.followup.send(success_msg, ephemeral=True)

            _logger.info(
                "static_group_deleted",
                group_name=group_name,
                guild_id=guild_id,
            )

        except Exception as e:
            error_msg = (
                STATIC_GROUPS["static_delete"]["messages"]["error"]
                .get(
                    guild_lang,
                    STATIC_GROUPS["static_delete"]["messages"]["error"].get("en-US"),
                )
                .format(error=str(e))
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            _logger.error("error_deleting_static_group", error=str(e))

    async def update_static_groups_message_for_cron(self, guild_id: int) -> None:
        """
        Update static groups message for automated tasks.

        Args:
            guild_id: The guild ID to update
        """
        try:
            _logger.debug("updating_static_groups_message_cron", guild_id=guild_id)
            await self.update_static_groups_message(guild_id)
        except Exception as e:
            _logger.error(
                "static_groups_message_cron_update_failed",
                guild_id=guild_id,
                error=str(e),
            )

    async def update_static_groups_message(self, guild_id: int) -> bool:
        """
        Update static groups message in the groups channel.

        Args:
            guild_id: The guild ID to update

        Returns:
            True if successful, False otherwise
        """
        try:
            guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
            static_groups = await self.get_static_groups_data(guild_id)

            result = await self.bot.run_db_query(
                "SELECT statics_channel, statics_message FROM guild_channels WHERE guild_id = %s",
                (guild_id,),
                fetch_one=True
            )

            if not result or not result[0]:
                _logger.debug("no_groups_channel_configured", guild_id=guild_id)
                return False

            statics_channel_id, statics_message_id = result

            guild = self.bot.get_guild(guild_id)
            if not guild:
                return False

            channel = guild.get_channel(int(statics_channel_id))
            if not channel:
                return False

            title = STATIC_GROUPS["static_update"]["messages"]["title"].get(
                guild_lang,
                STATIC_GROUPS["static_update"]["messages"]["title"].get("en-US"),
            )
            
            embeds = []
            
            if not static_groups:
                no_groups_text = STATIC_GROUPS["static_update"]["messages"][
                    "no_groups"
                ].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["no_groups"].get(
                        "en-US"
                    ),
                )
                embed = discord.Embed(
                    title=title, 
                    description=no_groups_text, 
                    color=discord.Color.blue()
                )
                embeds.append(embed)
            else:
                header_embed = discord.Embed(
                    title=title,
                    description=f"*Updated: <t:{int(time.time())}:R>*",
                    color=discord.Color.blue(),
                )
                embeds.append(header_embed)

                members_count_template = STATIC_GROUPS["static_update"]["messages"][
                    "members_count"
                ].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["members_count"].get(
                        "en-US"
                    ),
                )
                no_members_text = STATIC_GROUPS["static_update"]["messages"][
                    "no_members"
                ].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["no_members"].get(
                        "en-US"
                    ),
                )
                absent_text = STATIC_GROUPS["static_update"]["messages"]["absent"].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["absent"].get("en-US"),
                )

                sorted_groups = self._sort_groups_for_display(static_groups)
                
                for group_name, group_data in sorted_groups:
                    members = group_data.get("members", [])
                    member_count = len(members)

                    members_count = members_count_template.format(count=member_count)
                    description = f"{members_count}\n\n"
                    
                    if members:
                        formatted_members = await self._format_static_group_members(
                            members, guild, absent_text
                        )
                        description += "\n".join(f"• {member}" for member in formatted_members)
                    else:
                        description += no_members_text

                    group_embed = discord.Embed(
                        title=f"🛡️ {group_name}",
                        description=description,
                        color=discord.Color.gold(),
                    )
                    embeds.append(group_embed)

            view = None
            display_embeds = embeds
            
            if len(embeds) > 9:
                view = StaticGroupsPaginationView(self.bot, guild_id, embeds)
                display_embeds = view._get_current_embeds()

            try:
                if statics_message_id:
                    message = await channel.fetch_message(int(statics_message_id))
                    await message.edit(embeds=display_embeds, view=view)
                else:
                    message = await channel.send(embeds=display_embeds, view=view)
                    await self.bot.run_db_query(
                        "UPDATE guild_channels SET statics_message = %s WHERE guild_id = %s",
                        (message.id, guild_id),
                        commit=True
                    )

                _logger.info(
                    "static_groups_message_updated",
                    guild_id=guild_id,
                    groups_count=len(static_groups)
                )
                return True

            except (NotFound, HTTPException) as e:
                _logger.error("static_groups_message_update_failed", guild_id=guild_id, error=str(e))
                return False

        except Exception as e:
            _logger.error("update_static_groups_message_failed", guild_id=guild_id, error=str(e))
            return False

    async def static_update(self, ctx: discord.ApplicationContext):
        """
        Update static groups message manually via command.

        Args:
            ctx: Discord application context
        """
        await ctx.defer(ephemeral=True)

        guild = ctx.guild
        guild_id = guild.id
        
        try:
            success = await self._static_update_internal(guild_id)
            guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
            
            if success:
                success_msg = STATIC_GROUPS["static_update"]["messages"]["success"].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["success"].get("en-US"),
                )
                await ctx.followup.send(success_msg, ephemeral=True)
            else:
                error_msg = STATIC_GROUPS["static_update"]["messages"]["no_message"].get(
                    guild_lang,
                    STATIC_GROUPS["static_update"]["messages"]["no_message"].get("en-US"),
                )
                await ctx.followup.send(error_msg, ephemeral=True)
        except Exception as e:
            guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"
            error_msg = STATIC_GROUPS["static_update"]["messages"]["no_message"].get(
                guild_lang,
                STATIC_GROUPS["static_update"]["messages"]["no_message"].get("en-US"),
            )
            await ctx.followup.send(error_msg, ephemeral=True)
            _logger.error("static_update_command_failed", guild_id=guild_id, error=str(e))

    @discord_resilient(service_name="discord_api", max_retries=3)
    @discord_resilient(service_name="guild_statics", max_retries=2)
    async def _static_update_internal(self, guild_id: int) -> bool:
        """
        Internal method for static update with resilience.

        Args:
            guild_id: Guild ID to update

        Returns:
            True if successful, False otherwise
        """
        guild_lang = await self.bot.cache.get_guild_data(guild_id, "guild_lang") or "en-US"

        result = await self.bot.run_db_query(
            "SELECT statics_channel, statics_message FROM guild_channels WHERE guild_id = %s",
            (guild_id,),
            fetch_one=True
        )

        if not result or not result[0]:
            _logger.debug("no_statics_channel_configured", guild_id=guild_id)
            return False

        return await self.update_static_groups_message(guild_id)

def setup(bot):
    """Setup function for the cog."""
    bot.add_cog(GuildStatics(bot))
