"""
Pytest configuration and fixtures for Discord Bot tests - Simplified approach.
"""

import pytest
import asyncio
import sys
import os
import json
from unittest.mock import Mock, AsyncMock, patch, mock_open

# Set environment variables immediately before any imports
env_vars = {
    'DISCORD_TOKEN': 'MTE0ODk5Mjc4NjU1MTI0Njg0OC5G2dKr2.fake_discord_token_for_testing_with_sufficient_length_12345',
    'OPENAI_API_KEY': 'sk-fake-openai-api-key-for-testing-with-sufficient-length-123456789',
    'DATABASE_URL': 'sqlite:///:memory:',
    'REDIS_URL': 'redis://localhost:6379',
    'LOG_LEVEL': 'DEBUG',
    'ENVIRONMENT': 'test',
    'DB_USER': 'test_user',
    'DB_PASS': 'test_password',
    'DB_HOST': 'localhost',
    'DB_PORT': '3306',
    'DB_NAME': 'test_database',
    'MAX_MEMORY_MB': '1024',
    'MAX_CPU_PERCENT': '90',
    'MAX_RECONNECT_ATTEMPTS': '5',
    'RATE_LIMIT_PER_MINUTE': '100',
    'DB_POOL_SIZE': '25',
    'DB_TIMEOUT': '30',
    'DB_CIRCUIT_BREAKER_THRESHOLD': '5',
    'TRANSLATION_FILE': 'translation.json',
    'MAX_TRANSLATION_FILE_SIZE': '1048576',
    'DEBUG': 'False'
}

# Set environment variables immediately
for key, value in env_vars.items():
    os.environ[key] = value

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock discord.Bot to point to commands.Bot for compatibility
import discord
from discord.ext import commands

discord.Bot = commands.Bot

# Mock db module and its exceptions
class MockDBQueryError(Exception):
    """Mock DB Query Error for testing."""
    pass

# Add db module mock before any imports that might need it
import types
db_module = types.ModuleType('db')
db_module.DBQueryError = MockDBQueryError
sys.modules['db'] = db_module

# Mock pytz module for profile_setup.py
class MockTimezone:
    """Mock timezone class."""
    def __init__(self, name):
        self.zone = name
    
    def localize(self, dt):
        return dt
    
    def normalize(self, dt):
        return dt

pytz_module = types.ModuleType('pytz')
pytz_module.timezone = lambda name: MockTimezone(name)
pytz_module.UTC = MockTimezone('UTC')
sys.modules['pytz'] = pytz_module

# Mock discord.slash_command and other py-cord specific decorators
def mock_slash_command(*args, **kwargs):
    """Mock slash command decorator."""
    def decorator(func):
        func.slash_command_kwargs = kwargs
        # Add error handler attribute
        func.error = lambda error_func: error_func
        return func
    return decorator

def mock_bridge_command(*args, **kwargs):
    """Mock bridge command decorator."""
    def decorator(func):
        func.bridge_command_kwargs = kwargs
        # Add error handler attribute
        func.error = lambda error_func: error_func
        return func
    return decorator

discord.slash_command = mock_slash_command
discord.bridge_command = mock_bridge_command
commands.bridge_command = mock_bridge_command
commands.slash_command = mock_slash_command

# Mock discord.Option and other py-cord specific classes
class MockOption:
    """Mock Discord Option class."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
    
    def __call__(self, func):
        return func

class MockOptionChoice:
    """Mock Discord OptionChoice class."""
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

discord.Option = MockOption
discord.OptionChoice = MockOptionChoice

# Mock additional Discord classes commonly used in cogs
class MockApplicationContext:
    """Mock Discord ApplicationContext."""
    def __init__(self):
        self.guild = Mock()
        self.guild.id = 123456789
        self.user = Mock()
        self.user.id = 987654321
        self.author = self.user
        self.channel = Mock()
        self.channel.id = 555666777
        
    async def defer(self, ephemeral=False):
        pass
        
    async def respond(self, content=None, **kwargs):
        return Mock()
        
    async def followup(self, content=None, **kwargs):
        return Mock()

class MockInteraction:
    """Mock Discord Interaction."""
    def __init__(self):
        self.guild = Mock()
        self.guild.id = 123456789
        self.user = Mock()
        self.user.id = 987654321
        self.channel = Mock()
        self.response = Mock()
        self.response.send_message = AsyncMock()
        
discord.ApplicationContext = MockApplicationContext
discord.Interaction = MockInteraction

# Mock additional py-cord specific attributes
class MockPermissions:
    """Mock Discord Permissions."""
    VALID_FLAGS = {
        'create_instant_invite', 'kick_members', 'ban_members', 'administrator',
        'manage_channels', 'manage_guild', 'add_reactions', 'view_audit_log',
        'priority_speaker', 'stream', 'read_messages', 'view_channel',
        'send_messages', 'send_tts_messages', 'manage_messages', 'embed_links',
        'attach_files', 'read_message_history', 'mention_everyone', 'external_emojis',
        'view_guild_insights', 'connect', 'speak', 'mute_members', 'deafen_members',
        'move_members', 'use_voice_activation', 'change_nickname', 'manage_nicknames',
        'manage_roles', 'manage_permissions', 'manage_webhooks', 'manage_emojis',
        'manage_emojis_and_stickers', 'use_application_commands', 'request_to_speak',
        'manage_events', 'manage_threads', 'create_public_threads', 'create_private_threads',
        'external_stickers', 'send_messages_in_threads', 'use_embedded_activities',
        'moderate_members'
    }
    
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
            
discord.Permissions = MockPermissions

# Create a flexible mock translation structure that responds to any key
class FlexibleDict(dict):
    """A dictionary that returns a flexible structure for any missing key."""
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            # Return a completely flexible structure that handles all common patterns
            result = FlexibleDict()
            # Pre-populate with all common translation patterns used in cogs
            common_fields = [
                'name', 'description', 'title', 'message', 'options', 'commands', 'choices',
                'name_localizations', 'description_localizations', 'value', 'footer',
                'members_count', 'dm_message', 'value_comment', 'not_positive', 'not_registered',
                'updated', 'event_recap', 'invitation', 'success', 'error', 'warning',
                'info', 'help', 'usage', 'example', 'note', 'tip', 'required', 'optional'
            ]
            
            for field in common_fields:
                if field in ['options', 'commands', 'choices', 'event_recap', 'invitation']:
                    result[field] = FlexibleDict()
                elif field in ['name_localizations', 'description_localizations']:
                    result[field] = FlexibleDict({'en-US': f'{key}'})
                else:
                    result[field] = FlexibleDict({'en-US': f'{key} {field}'})
                    
            # Direct locale access
            result['en-US'] = f'{key}'
            result['fr-FR'] = f'{key} fr'
            
            self[key] = result
            return result
    
    def get(self, key, default=None):
        try:
            return self[key]
        except:
            # Always return FlexibleDict for missing keys, ignoring the default
            return FlexibleDict()
    
    def values(self):
        """Return flexible values that support iteration."""
        vals = list(super().values())
        if not vals:  # If no values, create a mock structure for iteration
            vals = [FlexibleDict({
                'name_localizations': FlexibleDict({'en-US': 'mock'}),
                'value': 'mock'
            })]
        return vals

# Use FlexibleDict for all translations - this will handle any structure dynamically
mock_translations = FlexibleDict()

# Create a fake translation file with actual content for testing
import tempfile

# Add comprehensive base translations to the FlexibleDict
base_translations = {
    'commands': {
        'app_initialize': {'name': {'en-US': 'Initialize'}, 'description': {'en-US': 'Initialize guild'}},
        'app_modify': {'name': {'en-US': 'Modify'}, 'description': {'en-US': 'Modify guild'}},
        'app_reset': {'name': {'en-US': 'Reset'}, 'description': {'en-US': 'Reset guild'}},
        'config_roster': {'name': {'en-US': 'Config Roster'}, 'description': {'en-US': 'Configure roster'}}
    },
    'guild_init': {
        'name': {'en-US': 'guild-init'},
        'description': {'en-US': 'Guild initialization commands'},
        'options': {
            'config_mode': {
                'description': {'en-US': 'Configuration mode'},
                'choices': {
                    'minimal': {'name_localizations': {'en-US': 'Minimal'}, 'value': 'minimal'},
                    'complete': {'name_localizations': {'en-US': 'Complete'}, 'value': 'complete'}
                }
            }
        },
        'role_names': {},
        'channel_names': {}
    },
    'guild_ptb': {
        'name': {'en-US': 'guild-ptb'},
        'description': {'en-US': 'PTB server management'},
        'sync': {'en-US': 'Synchronization'},
        'commands': {
            'ptb_init': {
                'name': {'en-US': 'ptb-init'}, 
                'description': {'en-US': 'Initialize PTB server'},
                'options': {
                    'main_guild_id': {
                        'description': {'en-US': 'Main guild ID to link PTB server'}
                    }
                }
            }
        },
        'event_recap': {
            'title': {'en-US': 'Event Recap {event_id}'},
            'description': {'en-US': 'Event summary'},
            'footer': {'en-US': 'PTB Event System'},
            'members_count': {'en-US': 'Members: {count}'}
        },
        'invitation': {'dm_message': {'en-US': 'Join the PTB server: {invite_url}'}}
    },
    'guild_members': {
        'name': {'en-US': 'guild-members'}, 
        'description': {'en-US': 'Member management'}, 
        'profile': {'en-US': 'Profile'},
        'gs': {
            'name': {'en-US': 'gs'},
            'description': {'en-US': 'Update your gear score'},
            'value_comment': {'en-US': 'Your gear score value'},
            'not_positive': {'en-US': 'Gear score must be positive'},
            'not_registered': {'en-US': 'You are not registered'},
            'updated': {'en-US': '{username} updated gear score to {value}'}
        },
        'weapons': {
            'name': {'en-US': 'weapons'},
            'description': {'en-US': 'Update your weapons'},
            'value_comment': {'en-US': 'Your weapon codes (e.g., GS, SNS)'},
            'updated': {'en-US': 'Weapons updated'}
        },
        'username': {
            'name': {'en-US': 'username'},
            'description': {'en-US': 'Update username'},
            'value_comment': {'en-US': 'Your in-game username'},
            'updated': {'en-US': 'Username updated'}
        },
        'character_class': {
            'name': {'en-US': 'class'},
            'description': {'en-US': 'Update character class'},
            'value_comment': {'en-US': 'Your character class'},
            'updated': {'en-US': 'Class updated'}
        },
        'build': {
            'name': {'en-US': 'build'},
            'description': {'en-US': 'Update build URL'},
            'value_comment': {'en-US': 'Build URL (questlog.gg or maxroll.gg)'},
            'updated': {'en-US': 'Build updated'}
        }
    },
    'guild_events': {'name': {'en-US': 'guild-events'}, 'description': {'en-US': 'Event management'}, 'event': {'en-US': 'Event'}},
    'guild_attendance': {'name': {'en-US': 'guild-attendance'}, 'description': {'en-US': 'Attendance tracking'}, 'attendance': {'en-US': 'Attendance'}},
    'llm': {'name': {'en-US': 'llm'}, 'description': {'en-US': 'AI interactions'}, 'chat': {'en-US': 'Chat'}},
    'core': {'name': {'en-US': 'core'}, 'description': {'en-US': 'Core functions'}, 'initialize': {'en-US': 'Initialize'}},
    'health': {'name': {'en-US': 'health'}, 'description': {'en-US': 'Health monitoring'}, 'status': {'en-US': 'Status'}},
    'absence': {'name': {'en-US': 'absence'}, 'description': {'en-US': 'Absence management'}},
    'autorole': {'name': {'en-US': 'autorole'}, 'description': {'en-US': 'Automatic role assignment'}},
    'notification': {'name': {'en-US': 'notification'}, 'description': {'en-US': 'Notification management'}},
    'contract': {'name': {'en-US': 'contract'}, 'description': {'en-US': 'Contract management'}},
    'dynamic_voice': {'name': {'en-US': 'dynamic-voice'}, 'description': {'en-US': 'Dynamic voice channels'}},
    'profile_setup': {'name': {'en-US': 'profile-setup'}, 'description': {'en-US': 'Profile setup'}},
    'static_groups': {
        'channel': {
            'name': {'en-US': 'static-groups'},
            'placeholder': {
                'title': {'en-US': 'Static Groups'},
                'description': {'en-US': 'Static group management'}
            }
        }
    }
}

# Convert all nested dicts to FlexibleDict and update mock_translations
def make_flexible(obj):
    """Convert nested dict structures to FlexibleDict recursively."""
    if isinstance(obj, dict):
        result = FlexibleDict()
        for k, v in obj.items():
            result[k] = make_flexible(v)
        return result
    return obj

flexible_base = make_flexible(base_translations)
mock_translations.update(flexible_base)

# Mock the translation module directly in sys.modules BEFORE any imports
import types
translation_module = types.ModuleType('translation')
translation_module.translations = mock_translations
translation_module.load_translations = lambda: None
sys.modules['translation'] = translation_module

temp_translation_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
json.dump(base_translations, temp_translation_file)
temp_translation_file.close()
os.environ['TRANSLATION_FILE'] = temp_translation_file.name

@pytest.fixture(scope="session", autouse=True)
def mock_translation_loading():
    """Mock translation loading during module import."""
    # Mock the entire translation loading process
    with patch('translation.load_translations') as mock_load:
        with patch('translation.translations', mock_translations):
            mock_load.return_value = None  # load_translations returns nothing
            yield

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def mock_bot():
    """Create mock Discord bot instance."""
    bot = Mock(spec=discord.Bot)
    bot.user = Mock(id=123456789)
    bot.guilds = []
    bot.latency = 0.05
    bot.synced = False
    
    # Cache system
    bot.cache = Mock()
    bot.cache.get_guild_data = AsyncMock()
    bot.cache.set_guild_data = AsyncMock()
    bot.cache.get_user_data = AsyncMock()
    bot.cache.set_user_data = AsyncMock()
    bot.cache.get = AsyncMock()
    bot.cache.set = AsyncMock()
    bot.cache.delete = AsyncMock()
    bot.cache.invalidate_guild = AsyncMock()
    bot.cache.invalidate_category = AsyncMock()
    bot.cache._cache = {}
    bot.cache._hot_keys = set()
    bot.cache.set_static_data = AsyncMock()
    
    # Cache loader
    bot.cache_loader = Mock()
    bot.cache_loader.ensure_category_loaded = AsyncMock()
    bot.cache_loader.reload_category = AsyncMock()
    
    # Database
    bot.run_db_query = AsyncMock()
    
    # Discord API methods
    bot.fetch_user = AsyncMock()
    bot.fetch_guild = AsyncMock()
    bot.sync_commands = AsyncMock()
    bot.add_cog = Mock()
    bot.get_cog = Mock()
    bot.loop = Mock()
    
    # Additional systems
    bot.reliability_system = Mock()
    bot.reliability_system.backup_manager = Mock()
    bot.reliability_system.get_system_status = Mock(return_value={
        'circuit_breakers': {},
        'degraded_services': [],
        'failure_counts': {},
        'backup_count': 5
    })
    
    bot.profiler = Mock()
    bot.profiler.get_summary_stats = Mock(return_value={
        'total_functions_profiled': 10,
        'total_calls': 100,
        'total_time_ms': 50.0,
        'avg_call_time_ms': 0.5,
        'slow_calls_count': 1,
        'very_slow_calls_count': 0,
        'total_errors': 0,
        'error_rate': 0.0,
        'functions_with_errors': 0,
        'active_calls_count': 0
    })
    bot.profiler.get_function_stats = Mock(return_value=[])
    bot.profiler.get_slow_calls = Mock(return_value=[])
    bot.profiler.get_active_calls = Mock(return_value=[])
    bot.profiler.get_recommendations = Mock(return_value=[])
    bot.profiler.reset_stats = Mock()
    
    return bot

@pytest.fixture
def mock_guild():
    """Create mock Discord guild."""
    guild = Mock(spec=discord.Guild)
    guild.id = 123456789
    guild.name = "Test Guild"
    guild.me = Mock()
    guild.me.edit = AsyncMock()
    guild.members = []
    
    return guild

@pytest.fixture
def mock_member():
    """Create mock Discord member."""
    member = Mock(spec=discord.Member)
    member.id = 987654321
    member.name = "TestUser"
    member.display_name = "Test User"
    member.nick = "TestNick"
    member.edit = AsyncMock()
    member.guild = Mock()
    member.guild.id = 123456789
    
    return member

@pytest.fixture
def mock_user():
    """Create mock Discord user."""
    user = Mock(spec=discord.User)
    user.id = 987654321
    user.name = "TestUser"
    user.display_name = "Test User"
    
    return user

@pytest.fixture
def mock_channel():
    """Create mock Discord channel."""
    channel = Mock(spec=discord.TextChannel)
    channel.id = 555666777
    channel.name = "test-channel"
    channel.send = AsyncMock()
    
    return channel

class AsyncContextManager:
    """Helper for mocking async context managers."""
    def __init__(self, return_value=None):
        self.return_value = return_value
    
    async def __aenter__(self):
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass