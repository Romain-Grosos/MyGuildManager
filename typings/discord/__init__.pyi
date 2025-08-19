"""Type stubs for py-cord (discord.py v2.6.1) to fix Pylance issues"""

from typing import Any, Optional, List, Dict, Callable, Union, Type, Coroutine, Literal
from discord.ext import commands
import discord.abc as abc
import discord.enums as enums
import discord.errors as errors
import discord.types as types
import discord.utils as utils

from discord import *

class Bot(commands.Bot):
    """
    Py-cord Bot class that extends commands.Bot with slash command support.
    This stub helps Pylance understand that discord.Bot exists in py-cord.
    """
    
    def __init__(
        self,
        *,
        command_prefix: Optional[Union[str, List[str], Callable]] = None,
        help_command: Optional[commands.HelpCommand] = ...,
        description: Optional[str] = None,
        intents: Optional[Intents] = None,
        debug_guilds: Optional[List[int]] = None,
        **options: Any
    ) -> None: ...
    
    async def sync_commands(
        self,
        *,
        commands: Optional[List[ApplicationCommand]] = None,
        method: str = "bulk_overwrite",
        force: bool = False,
        guild_ids: Optional[List[int]] = None,
        register_guild_commands: bool = True,
        check_guilds: Optional[List[int]] = None,
        delete_existing: bool = True
    ) -> None: ...
    
    def add_application_command(self, command: ApplicationCommand) -> None: ...
    def remove_application_command(self, command: Union[ApplicationCommand, str]) -> Optional[ApplicationCommand]: ...
    
    @property
    def pending_application_commands(self) -> List[ApplicationCommand]: ...

class ApplicationCommand:
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

class SlashCommand(ApplicationCommand):
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

class SlashCommandGroup(ApplicationCommand):
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

class ApplicationContext:
    """Application context for slash commands."""
    
    def __init__(self, bot: Bot, interaction: Interaction, command: ApplicationCommand) -> None: ...
    
    @property
    def bot(self) -> Bot: ...
    
    @property
    def guild(self) -> Optional[Guild]: ...
    
    @property
    def channel(self) -> Optional[abc.GuildChannel]: ...
    
    @property
    def author(self) -> Optional[Union[Member, User]]: ...
    
    @property
    def user(self) -> Optional[Union[Member, User]]: ...
    
    @property
    def voice_client(self) -> Optional[VoiceClient]: ...
    
    @property
    def interaction(self) -> Interaction: ...
    
    @property
    def command(self) -> ApplicationCommand: ...
    
    @property
    def locale(self) -> Optional[str]: ...
    
    async def respond(
        self,
        content: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        embeds: Optional[List[Embed]] = None,
        view: Optional[View] = None,
        tts: bool = False,
        ephemeral: bool = False,
        allowed_mentions: Optional[AllowedMentions] = None,
        delete_after: Optional[float] = None,
        file: Optional[File] = None,
        files: Optional[List[File]] = None
    ) -> Optional[Interaction]: ...
    
    async def send_followup(
        self,
        content: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        embeds: Optional[List[Embed]] = None,
        view: Optional[View] = None,
        tts: bool = False,
        ephemeral: bool = False,
        allowed_mentions: Optional[AllowedMentions] = None,
        file: Optional[File] = None,
        files: Optional[List[File]] = None
    ) -> Webhook: ...
    
    async def edit(
        self,
        content: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        embeds: Optional[List[Embed]] = None,
        view: Optional[View] = None,
        allowed_mentions: Optional[AllowedMentions] = None,
        delete_after: Optional[float] = None,
        file: Optional[File] = None,
        files: Optional[List[File]] = None
    ) -> Optional[Interaction]: ...
    
    async def delete(self, *, delay: Optional[float] = None) -> None: ...

def slash_command(
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    name_localizations: Optional[Dict[str, str]] = None,
    description_localizations: Optional[Dict[str, str]] = None,
    options: Optional[List[Option]] = None,
    default_member_permissions: Optional[Permissions] = None,
    dm_permission: bool = True,
    nsfw: bool = False,
    guild_ids: Optional[List[int]] = None,
    guild_only: bool = False,
    auto_sync: bool = True
) -> Callable: ...

def user_command(
    *,
    name: Optional[str] = None,
    name_localizations: Optional[Dict[str, str]] = None,
    default_member_permissions: Optional[Permissions] = None,
    dm_permission: bool = True,
    nsfw: bool = False,
    guild_ids: Optional[List[int]] = None,
    guild_only: bool = False,
    auto_sync: bool = True
) -> Callable: ...

def message_command(
    *,
    name: Optional[str] = None,
    name_localizations: Optional[Dict[str, str]] = None,
    default_member_permissions: Optional[Permissions] = None,
    dm_permission: bool = True,
    nsfw: bool = False,
    guild_ids: Optional[List[int]] = None,
    guild_only: bool = False,
    auto_sync: bool = True
) -> Callable: ...