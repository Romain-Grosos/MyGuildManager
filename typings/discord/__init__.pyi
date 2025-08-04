"""Type stubs for py-cord (discord.py v2) to fix Pylance issues"""

from typing import Any, Optional, List, Dict, Callable, Union, Type, Coroutine
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

def slash_command(*args: Any, **kwargs: Any) -> Callable: ...
def user_command(*args: Any, **kwargs: Any) -> Callable: ...
def message_command(*args: Any, **kwargs: Any) -> Callable: ...