"""
Guild Groups Creation Cog - Advanced group formation algorithms and composition optimization.

This cog handles the complex logic of creating balanced groups for events and activities:

CORE FEATURES:
- Automated group composition with role balancing (Tank/Healer/DPS)
- GS distribution optimization across groups
- Flexible group sizing with optimal splitting algorithms
- Tentative player management and backup system
- Multi-language embed formatting with rich member display

ALGORITHMS:
- Enhanced assignment algorithm with role prioritization
- Legacy assignment for compatibility
- Optimal group size calculation for any number of participants
- Class-based member distribution with shortage handling

GROUP COMPOSITION RULES:
- Ideal: 1 Tank, 2 Healers, 3 DPS per group
- Flexible: Adapts to available roles with intelligent fallbacks
- GS balancing: Distributes high/low GS evenly across groups
- Backup system: Manages tentative players as group reserves

INTEGRATION:
- Called by guild_events.py for event group formation
- Reusable by other cogs for ad-hoc group creation
- Cache-aware with roster data integration
- PTB notification support for cross-guild coordination
"""
#### TO BE TESTED
from __future__ import annotations

import math
import statistics
from typing import Optional, TypedDict

import discord
from discord.ext import commands

from app.core.logger import ComponentLogger
from app.core.performance_profiler import profile_performance
from app.core.reliability import discord_resilient
from app.core.translation import translations as global_translations

GROUP_MIN_SIZE = 4
GROUP_MAX_SIZE = 6
IDEAL_TANKS_PER_GROUP = 1
IDEAL_HEALERS_PER_GROUP = 2
IDEAL_DPS_PER_GROUP = 3

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

EVENT_MANAGEMENT = global_translations.get("event_management", {})

_logger = ComponentLogger("guild_groups_creation")

class GuildGroupsCreation(commands.Cog):
    """
    Advanced group formation system for guild events and activities.
    
    Provides intelligent algorithms for creating balanced groups with optimal
    composition, GS distribution, and role coverage.
    """
    
    def __init__(self, bot: discord.Bot) -> None:
        self.bot = bot
    
    @staticmethod
    def group_members_by_class(member_ids, roster_data):
        """
        Group members by their class for balanced team composition.

        Args:
            member_ids: List of member IDs to group
            roster_data: Dictionary containing member roster information

        Returns:
            Tuple of (classes_dict, missing_list) where classes_dict contains members grouped by class and missing_list contains members without class data
        """
        _logger.debug("building_class_buckets")
        classes = {
            c: [] for c in ("Tank", "Melee DPS", "Ranged DPS", "Healer", "Flanker")
        }
        missing = []

        for mid in member_ids:
            try:
                info = roster_data["members"][str(mid)]
            except KeyError:
                _logger.warning(
                    "member_id_not_found_in_roster",
                    member_id=mid,
                    operation="GroupsMembersByClass"
                )
                missing.append(mid)
                continue

            pseudo = info.get("pseudo", "Unknown")
            gs = info.get("GS", "N/A")
            weapons = info.get("weapons", "")
            member_class = info.get("class", "Unknown")

            weapon_parts = [c.strip() for c in (weapons or "").split("/") if c.strip()]
            emojis = " ".join([WEAPON_EMOJIS.get(c, c) for c in weapon_parts]) or "N/A"

            classes.setdefault(member_class, []).append(f"{pseudo} {emojis} - GS: {gs}")

        _logger.info(
            "buckets_built_complete",
            operation="GroupsMembersByClass",
            total_entries=sum(len(v) for v in classes.values()),
            missing_count=len(missing)
        )
        return classes, missing

    @staticmethod
    def _get_optimal_grouping(
        n: int, min_size: int = GROUP_MIN_SIZE, max_size: int = GROUP_MAX_SIZE
    ) -> "list[int]":
        """
        Calculate optimal group sizes for a given number of participants.

        Uses mathematical optimization to find the most balanced group distribution
        while respecting min/max size constraints.

        Args:
            n: Total number of participants
            min_size: Minimum allowed group size
            max_size: Maximum allowed group size

        Returns:
            List of group sizes that optimally distribute n participants
        """
        if n == 0:
            return []
        if n <= max_size:
            return [n] if n >= min_size else []

        optimal_groups = max(1, round(n / ((min_size + max_size) / 2)))

        base_size = n // optimal_groups
        remainder = n % optimal_groups

        if base_size < min_size:
            optimal_groups = n // min_size
            base_size = n // optimal_groups
            remainder = n % optimal_groups
        elif base_size > max_size:
            optimal_groups = math.ceil(n / max_size)
            base_size = n // optimal_groups
            remainder = n % optimal_groups

        group_sizes = [base_size] * optimal_groups

        for i in range(remainder):
            group_sizes[i] += 1

        valid_groups = [size for size in group_sizes if min_size <= size <= max_size]
        
        _logger.debug(
            "optimal_grouping_calculated",
            participants=n,
            groups_count=len(valid_groups),
            group_sizes=valid_groups,
            efficiency=sum(valid_groups) / n if n > 0 else 0
        )
        
        return valid_groups

    def _calculate_group_role_needs(self, group: list[dict]) -> dict[str, int]:
        """
        Calculate how many tanks and healers a group is missing for optimal composition.
        
        Args:
            group: List of member dictionaries with class information
            
        Returns:
            Dictionary with 'tanks_needed' and 'healers_needed' counts
        """
        current_tanks = sum(1 for member in group if member.get("class") == "Tank")
        current_healers = sum(1 for member in group if member.get("class") == "Healer")
        
        tanks_needed = max(0, IDEAL_TANKS_PER_GROUP - current_tanks)
        healers_needed = max(0, IDEAL_HEALERS_PER_GROUP - current_healers)
        
        return {
            "tanks_needed": tanks_needed,
            "healers_needed": healers_needed
        }

    def _get_group_composition_trace(self, group: list[dict]) -> GroupStats:
        """
        Generate detailed composition trace for debugging group formation.
        
        Args:
            group: List of member dictionaries
            
        Returns:
            GroupStats with detailed composition information
        """
        if not group:
            return GroupStats(
                size=0,
                composition="Empty",
                avg_gs=0.0,
                tanks=0,
                healers=0,
                dps=0,
                classes={}
            )

        class_counts = {}
        gs_values = []
        tanks = healers = dps = 0
        
        for member in group:
            member_class = member.get("class", "Unknown")
            class_counts[member_class] = class_counts.get(member_class, 0) + 1

            if member_class == "Tank":
                tanks += 1
            elif member_class == "Healer":
                healers += 1
            elif member_class in ["Melee DPS", "Ranged DPS", "Flanker"]:
                dps += 1

            gs = member.get("GS")
            if gs and str(gs).isdigit():
                gs_values.append(int(gs))
        
        avg_gs = statistics.mean(gs_values) if gs_values else 0.0

        composition_parts = []
        if tanks > 0:
            composition_parts.append(f"{tanks}T")
        if healers > 0:
            composition_parts.append(f"{healers}H")
        if dps > 0:
            composition_parts.append(f"{dps}D")
        
        composition = "/".join(composition_parts) or "None"
        
        return GroupStats(
            size=len(group),
            composition=composition,
            avg_gs=avg_gs,
            tanks=tanks,
            healers=healers,
            dps=dps,
            classes=class_counts
        )

    @profile_performance(threshold_ms=100.0)
    async def _assign_groups_enhanced(
        self,
        guild_id: int,
        presence_ids: list[int],
        tentative_ids: list[int],
        roster_data: dict,
        target_group_sizes: list[int]
    ) -> list[list[dict]]:
        """
        Enhanced group assignment algorithm with role balancing and GS optimization.
        
        This algorithm prioritizes:
        1. Role balance (tanks and healers first)
        2. Even GS distribution
        3. Optimal group sizes
        4. Tentative player management
        
        Args:
            guild_id: The guild ID for logging
            presence_ids: List of confirmed participant IDs
            tentative_ids: List of tentative participant IDs  
            roster_data: Complete roster information
            target_group_sizes: Desired sizes for each group
            
        Returns:
            List of groups, each containing member dictionaries
        """
        _logger.info(
            "enhanced_group_assignment_start",
            guild_id=guild_id,
            presence_count=len(presence_ids),
            tentative_count=len(tentative_ids),
            target_groups=len(target_group_sizes)
        )

        all_members = []
        members_by_role = {"Tank": [], "Healer": [], "DPS": []}
        
        for member_id in presence_ids:
            member_data = await self._get_member_data_for_groups(
                guild_id, member_id, roster_data, tentative=False
            )
            if member_data:
                all_members.append(member_data)
                role_category = self._categorize_member_role(member_data.get("class") or "Unknown")
                members_by_role[role_category].append(member_data)

        for member_id in tentative_ids:
            member_data = await self._get_member_data_for_groups(
                guild_id, member_id, roster_data, tentative=True
            )
            if member_data:
                all_members.append(member_data)

        all_members.sort(key=lambda m: int(m.get("GS", 0) or 0), reverse=True)

        groups = [[] for _ in target_group_sizes]

        self._distribute_role_members(groups, members_by_role["Tank"], "Tank")
        self._distribute_role_members(groups, members_by_role["Healer"], "Healer")

        remaining_dps = [m for m in members_by_role["DPS"] if not self._is_member_assigned(m, groups)]
        self._distribute_dps_by_gs(groups, remaining_dps, target_group_sizes)

        tentative_members = [m for m in all_members if m.get("tentative")]
        self._assign_attempts_as_backup(groups, tentative_members)
        
        _logger.info(
            "enhanced_group_assignment_complete",
            guild_id=guild_id,
            groups_created=len(groups),
            total_assigned=sum(len(group) for group in groups),
            group_stats=[self._get_group_composition_trace(group) for group in groups]
        )
        
        return groups

    def _categorize_member_role(self, member_class: str) -> str:
        """Categorize member class into Tank, Healer, or DPS."""
        if member_class == "Tank":
            return "Tank"
        elif member_class == "Healer":
            return "Healer"
        else:
            return "DPS"

    def _distribute_role_members(self, groups: list[list], members: list[dict], role: str):
        """Distribute role members evenly across groups."""
        for i, member in enumerate(members):
            target_group = i % len(groups)
            groups[target_group].append(member)
            
    def _distribute_dps_by_gs(self, groups: list[list], dps_members: list[dict], target_sizes: list[int]):
        """Distribute DPS members by alternating high/low GS for balance."""
        dps_members.sort(key=lambda m: int(m.get("GS", 0) or 0), reverse=True)

        group_index = 0
        direction = 1
        
        for member in dps_members:
            if len(groups[group_index]) < target_sizes[group_index]:
                groups[group_index].append(member)

            group_index += direction
            if group_index >= len(groups):
                group_index = len(groups) - 1
                direction = -1
            elif group_index < 0:
                group_index = 0
                direction = 1

    def _assign_attempts_as_backup(self, groups: list[list], attempts: list[dict]):
        """Assign attempt members as backup to groups that need them most."""
        for attempt in attempts:
            best_group_idx = self._find_best_group_for_attempt(groups, attempt)
            if best_group_idx is not None:
                groups[best_group_idx].append(attempt)

    def _find_best_group_for_attempt(self, groups: list[list], attempt: dict) -> Optional[int]:
        """Find the group that would benefit most from this attempt member."""
        attempt_role = self._categorize_member_role(attempt.get("class") or "Unknown")
        best_group_idx = None
        max_benefit = -1
        
        for i, group in enumerate(groups):
            needs = self._calculate_group_role_needs(group)
            benefit = 0
            
            if attempt_role == "Tank" and needs["tanks_needed"] > 0:
                benefit = 3
            elif attempt_role == "Healer" and needs["healers_needed"] > 0:
                benefit = 2
            else:
                benefit = 1
                
            if benefit > max_benefit:
                max_benefit = benefit
                best_group_idx = i
                
        return best_group_idx

    def _is_member_assigned(self, member: dict, groups: list[list]) -> bool:
        """Check if a member is already assigned to any group."""
        member_id = member.get("user_id")
        for group in groups:
            if any(m.get("user_id") == member_id for m in group):
                return True
        return False

    async def _get_member_data_for_groups(
        self, guild_id: int, member_id: int, roster_data: dict, tentative: bool = False
    ) -> Optional[dict]:
        """
        Get formatted member data for group formation.
        
        Args:
            guild_id: Guild ID for logging
            member_id: Member ID to fetch data for
            roster_data: Roster data dictionary
            tentative: Whether this member is tentative
            
        Returns:
            Formatted member dictionary or None if not found
        """
        try:
            member_info = roster_data.get("members", {}).get(str(member_id))
            if not member_info:
                _logger.warning(
                    "member_not_found_in_roster",
                    guild_id=guild_id,
                    member_id=member_id
                )
                return None
            
            return {
                "user_id": member_id,
                "pseudo": member_info.get("pseudo", "Unknown"),
                "member_class": member_info.get("class", "Unknown"),
                "class": member_info.get("class", "Unknown"),
                "GS": member_info.get("GS", "N/A"),
                "weapons": member_info.get("weapons", ""),
                "tentative": tentative
            }
            
        except Exception as e:
            _logger.error(
                "error_getting_member_data_for_groups",
                guild_id=guild_id,
                member_id=member_id,
                error=str(e)
            )
            return None

    def _assign_groups_legacy(
        self, presence_ids: "list[int]", tentative_ids: "list[int]", roster_data: dict
    ) -> "list[list[dict]]":
        """
        Legacy group assignment algorithm for backward compatibility.
        
        Simple round-robin assignment without advanced role balancing.
        
        Args:
            presence_ids: List of confirmed participant IDs
            tentative_ids: List of tentative participant IDs
            roster_data: Roster data dictionary
            
        Returns:
            List of groups with member dictionaries
        """
        _logger.debug("using_legacy_group_assignment")
        
        all_ids = presence_ids + tentative_ids
        if not all_ids:
            return []
        
        group_sizes = self._get_optimal_grouping(len(all_ids))
        if not group_sizes:
            return []
        
        groups = []
        member_idx = 0
        
        for size in group_sizes:
            group = []
            for _ in range(size):
                if member_idx < len(all_ids):
                    member_id = all_ids[member_idx]
                    member_data = roster_data.get("members", {}).get(str(member_id), {})
                    
                    group.append({
                        "user_id": member_id,
                        "pseudo": member_data.get("pseudo", f"User{member_id}"),
                        "member_class": member_data.get("class", "Unknown"),
                        "GS": member_data.get("GS", "N/A"),
                        "weapons": member_data.get("weapons", ""),
                        "tentative": member_id in tentative_ids
                    })
                    member_idx += 1
            
            if group:
                groups.append(group)
        
        _logger.info(
            "legacy_group_assignment_complete",
            groups_created=len(groups),
            total_members=member_idx
        )
        
        return groups

    @discord_resilient(service_name="group_formation", max_retries=2)
    async def create_groups_for_event(
        self, 
        guild_id: int, 
        event_id: int, 
        presence_ids: list[int],
        tentative_ids: list[int],
        roster_data: dict,
        use_enhanced_algorithm: bool = True
    ) -> list[list[dict]]:
        """
        Create balanced groups for an event based on participant lists.
        
        Main entry point for group creation from external cogs.
        
        Args:
            guild_id: The guild ID
            event_id: The event ID for logging
            presence_ids: List of confirmed participant IDs
            tentative_ids: List of tentative participant IDs
            roster_data: Complete roster data dictionary
            use_enhanced_algorithm: Whether to use enhanced algorithm (default: True)
            
        Returns:
            List of balanced groups with member information
        """
        _logger.info(
            "group_creation_requested",
            guild_id=guild_id,
            event_id=event_id,
            confirmed_participants=len(presence_ids),
            tentative_participants=len(tentative_ids),
            algorithm="enhanced" if use_enhanced_algorithm else "legacy"
        )
        
        if not presence_ids and not tentative_ids:
            _logger.info("no_participants_for_group_creation", guild_id=guild_id, event_id=event_id)
            return []

        total_participants = len(presence_ids)
        target_group_sizes = self._get_optimal_grouping(total_participants)
        
        if not target_group_sizes:
            _logger.warning(
                "no_valid_group_sizes",
                guild_id=guild_id,
                event_id=event_id,
                total_participants=total_participants
            )
            return []

        if use_enhanced_algorithm:
            groups = await self._assign_groups_enhanced(
                guild_id, presence_ids, tentative_ids, roster_data, target_group_sizes
            )
        else:
            groups = self._assign_groups_legacy(presence_ids, tentative_ids, roster_data)
        
        _logger.info(
            "group_creation_completed",
            guild_id=guild_id,
            event_id=event_id,
            groups_created=len(groups),
            algorithm_used="enhanced" if use_enhanced_algorithm else "legacy",
            group_compositions=[self._get_group_composition_trace(group).get("composition", "Unknown") for group in groups]
        )
        
        return groups

    def format_groups_embed_field(
        self, 
        groups: list[list[dict]], 
        guild_locale: str = "en-US",
        show_attempts: bool = True
    ) -> list[dict]:
        """
        Format groups data for Discord embed fields.
        
        Args:
            groups: List of groups with member data
            guild_locale: Guild language for localization
            show_attempts: Whether to include attempt members
            
        Returns:
            List of embed field dictionaries
        """
        if not groups:
            return [{
                "name": "👥 Groups",
                "value": "No groups formed yet.",
                "inline": False
            }]
        
        embed_fields = []
        
        for i, group in enumerate(groups, 1):
            confirmed_members = [m for m in group if not m.get("tentative")]
            tentative_members = [m for m in group if m.get("tentative")]
            
            lines = []

            for member in confirmed_members:
                class_emoji = CLASS_EMOJIS.get(member.get("member_class", ""), "")
                weapon_parts = [
                    c.strip()
                    for c in (member.get("weapons") or "").split("/")
                    if c.strip()
                ]
                weapons_emoji = " ".join([WEAPON_EMOJIS.get(c, c) for c in weapon_parts])
                pseudo = member.get("pseudo", "Unknown")
                gs = member.get("GS", "N/A")
                
                lines.append(f"{class_emoji} {weapons_emoji} {pseudo} ({gs})")

            if show_attempts and tentative_members:
                if confirmed_members:
                    lines.append("")
                    lines.append("**Backup:**")
                
                for member in tentative_members:
                    class_emoji = CLASS_EMOJIS.get(member.get("member_class", ""), "")
                    weapon_parts = [
                        c.strip()
                        for c in (member.get("weapons") or "").split("/")
                        if c.strip()
                    ]
                    weapons_emoji = " ".join([WEAPON_EMOJIS.get(c, c) for c in weapon_parts])
                    pseudo = member.get("pseudo", "Unknown")
                    gs = member.get("GS", "N/A")
                    
                    lines.append(f"{class_emoji} {weapons_emoji} *{pseudo}* ({gs}) 🔶")

            group_stats = self._get_group_composition_trace(confirmed_members)
            field_name = f"👥 Group {i} ({group_stats['composition']}) - Avg GS: {group_stats['avg_gs']:.0f}"
            field_value = "\n".join(lines) if lines else "Empty group"
            
            embed_fields.append({
                "name": field_name,
                "value": field_value,
                "inline": False
            })
        
        return embed_fields

def setup(bot: discord.Bot):
    """Set up the GuildGroupsCreation cog."""
    bot.add_cog(GuildGroupsCreation(bot))
