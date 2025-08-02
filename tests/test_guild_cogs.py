"""
Tests for refactored guild cogs.
"""

import pytest
import discord
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta

# Import the cogs to test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cogs.guild_init import GuildInit
from cogs.guild_ptb import GuildPTB
from cogs.guild_members import GuildMembers
from cogs.guild_events import GuildEvents
from cogs.guild_attendance import GuildAttendance


class TestGuildInit:
    """Test GuildInit cog functionality."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance."""
        bot = Mock(spec=discord.Bot)
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_category_loaded = AsyncMock()
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock(return_value='en-US')
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.invalidate_guild = AsyncMock()
        bot.run_db_query = AsyncMock()
        return bot
    
    @pytest.fixture
    def guild_init_cog(self, mock_bot):
        """Create GuildInit cog instance."""
        return GuildInit(mock_bot)
    
    def test_init_with_type_hints(self, mock_bot):
        """Test that __init__ has proper type hints."""
        cog = GuildInit(mock_bot)
        assert cog.bot == mock_bot
        # Check type hint in function signature
        assert GuildInit.__init__.__annotations__.get('bot') == discord.Bot
        assert GuildInit.__init__.__annotations__.get('return') == None
    
    @pytest.mark.asyncio
    async def test_on_ready(self, guild_init_cog):
        """Test on_ready event handler."""
        with patch('asyncio.create_task') as mock_create_task:
            await guild_init_cog.on_ready()
            mock_create_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_load_guild_init_data(self, guild_init_cog, mock_bot):
        """Test guild init data loading."""
        await guild_init_cog.load_guild_init_data()
        
        # Should load required categories
        mock_bot.cache_loader.ensure_category_loaded.assert_any_call('guild_settings')
        mock_bot.cache_loader.ensure_category_loaded.assert_any_call('guild_channels')
        mock_bot.cache_loader.ensure_category_loaded.assert_any_call('guild_roles')
        assert mock_bot.cache_loader.ensure_category_loaded.call_count == 3


class TestGuildPTB:
    """Test GuildPTB cog functionality."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance."""
        bot = Mock(spec=discord.Bot)
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_category_loaded = AsyncMock()
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.get = AsyncMock(return_value={})  # Added for PTB tests
        bot.run_db_query = AsyncMock()
        return bot
    
    @pytest.fixture
    def guild_ptb_cog(self, mock_bot):
        """Create GuildPTB cog instance."""
        return GuildPTB(mock_bot)
    
    def test_init_with_type_hints(self, mock_bot):
        """Test that __init__ has proper type hints."""
        cog = GuildPTB(mock_bot)
        assert cog.bot == mock_bot
        assert GuildPTB.__init__.__annotations__.get('bot') == discord.Bot
        assert GuildPTB.__init__.__annotations__.get('return') == None
    
    @pytest.mark.asyncio
    async def test_get_guild_ptb_settings(self, guild_ptb_cog, mock_bot):
        """Test getting PTB settings from cache."""
        guild_id = 123456
        # Mock the ptb_settings cache
        mock_bot.cache.get.return_value = {
            guild_id: {
                'guild_ptb': True,
                'ptb_guild_id': 789,
                'info_channel_id': 101
            }
        }
        
        settings = await guild_ptb_cog.get_guild_ptb_settings(guild_id)
        
        assert settings['guild_ptb'] == True
        assert settings['ptb_guild_id'] == 789
        assert settings['info_channel_id'] == 101
        # Verify cache.get was called with correct parameters
        mock_bot.cache.get.assert_called_with('temporary', 'ptb_settings')


class TestGuildMembers:
    """Test GuildMembers cog functionality."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance."""
        bot = Mock(spec=discord.Bot)
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_category_loaded = AsyncMock()
        bot.cache_loader.reload_category = AsyncMock()
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.get = AsyncMock(return_value={})
        bot.cache.set = AsyncMock()
        bot.run_db_query = AsyncMock()
        return bot
    
    @pytest.fixture
    def guild_members_cog(self, mock_bot):
        """Create GuildMembers cog instance."""
        return GuildMembers(mock_bot)
    
    def test_init_with_type_hints(self, mock_bot):
        """Test that __init__ has proper type hints."""
        cog = GuildMembers(mock_bot)
        assert cog.bot == mock_bot
        assert GuildMembers.__init__.__annotations__.get('bot') == discord.Bot
        assert GuildMembers.__init__.__annotations__.get('return') == None
    
    def test_sanitize_string(self, guild_members_cog):
        """Test string sanitization."""
        # Test normal string
        assert guild_members_cog._sanitize_string("test") == "test"
        
        # Test dangerous characters removal
        assert guild_members_cog._sanitize_string("<script>alert('xss')</script>") == "scriptalert(xss)/script"
        
        # Test max length
        long_string = "a" * 200
        assert len(guild_members_cog._sanitize_string(long_string)) == 100
    
    def test_validate_integer(self, guild_members_cog):
        """Test integer validation."""
        # Valid cases
        assert guild_members_cog._validate_integer(5, min_val=1, max_val=10) == 5
        assert guild_members_cog._validate_integer("10", max_val=20) == 10
        
        # Invalid cases
        assert guild_members_cog._validate_integer(5, min_val=10) is None
        assert guild_members_cog._validate_integer(20, max_val=10) is None
        assert guild_members_cog._validate_integer("not a number") is None
    
    def test_validate_weapon_code(self, guild_members_cog):
        """Test weapon code validation."""
        # Valid codes
        assert guild_members_cog._validate_weapon_code("GS") == "GS"
        assert guild_members_cog._validate_weapon_code("sns") == "SNS"
        
        # Invalid codes - contains invalid characters
        assert guild_members_cog._validate_weapon_code("invalid!") is None
        # Long codes get truncated but are valid if they contain only valid characters
        assert guild_members_cog._validate_weapon_code("toolongcode123") == "TOOLONGCOD"


class TestGuildEvents:
    """Test GuildEvents cog functionality."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance."""
        bot = Mock(spec=discord.Bot)
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_category_loaded = AsyncMock()
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.invalidate_category = AsyncMock()
        bot.run_db_query = AsyncMock()
        bot.user = Mock(id=123)
        return bot
    
    @pytest.fixture
    def guild_events_cog(self, mock_bot):
        """Create GuildEvents cog instance."""
        return GuildEvents(mock_bot)
    
    def test_init_with_type_hints(self, mock_bot):
        """Test that __init__ has proper type hints."""
        cog = GuildEvents(mock_bot)
        assert cog.bot == mock_bot
        assert GuildEvents.__init__.__annotations__.get('bot') == discord.Bot
        assert GuildEvents.__init__.__annotations__.get('return') == None
    
    @pytest.mark.asyncio
    async def test_get_event_from_cache(self, guild_events_cog, mock_bot):
        """Test getting event from cache."""
        guild_id = 123
        event_id = 456
        mock_bot.cache.get_guild_data.return_value = {
            'name': 'Test Event',
            'event_date': '2024-01-01',
            'registrations': '{"presence": [1, 2], "tentative": [], "absence": [3]}'
        }
        
        event = await guild_events_cog.get_event_from_cache(guild_id, event_id)
        
        assert event['guild_id'] == guild_id
        assert event['name'] == 'Test Event'
        # registrations are stored as JSON string and parsed when needed
        assert isinstance(event['registrations'], str)
        assert '{"presence": [1, 2], "tentative": [], "absence": [3]}' in event['registrations']
    
    @pytest.mark.asyncio
    async def test_get_static_group_data(self, guild_events_cog, mock_bot):
        """Test getting static group data."""
        guild_id = 123
        group_name = "Group1"
        mock_bot.cache.get_guild_data.return_value = {
            "Group1": {"member_ids": [1, 2, 3]},
            "Group2": {"member_ids": [4, 5, 6]}
        }
        
        group_data = await guild_events_cog.get_static_group_data(guild_id, group_name)
        
        assert group_data == {"member_ids": [1, 2, 3]}
        mock_bot.cache_loader.ensure_category_loaded.assert_called_with('static_groups')


class TestGuildAttendance:
    """Test GuildAttendance cog functionality."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance."""
        bot = Mock(spec=discord.Bot)
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_category_loaded = AsyncMock()
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.get = AsyncMock()
        bot.cache.set = AsyncMock()
        bot.run_db_query = AsyncMock()
        return bot
    
    @pytest.fixture
    def guild_attendance_cog(self, mock_bot):
        """Create GuildAttendance cog instance."""
        return GuildAttendance(mock_bot)
    
    def test_init_with_type_hints(self, mock_bot):
        """Test that __init__ has proper type hints."""
        cog = GuildAttendance(mock_bot)
        assert cog.bot == mock_bot
        assert GuildAttendance.__init__.__annotations__.get('bot') == discord.Bot
        assert GuildAttendance.__init__.__annotations__.get('return') == None
    
    @pytest.mark.asyncio
    async def test_get_guild_settings(self, guild_attendance_cog, mock_bot):
        """Test getting guild settings."""
        guild_id = 123
        mock_bot.cache.get_guild_data.side_effect = [
            'en-US',  # guild_lang
            1,        # premium
            {'events_channel': 456, 'notifications_channel': 789},  # channels_data
            {'members': 101}  # roles_data
        ]
        
        settings = await guild_attendance_cog.get_guild_settings(guild_id)
        
        assert settings['guild_lang'] == 'en-US'
        assert settings['premium'] == 1
        assert settings['events_channel'] == 456
        assert settings['notifications_channel'] == 789
        assert settings['members_role'] == 101
    
    def test_was_recently_checked(self, guild_attendance_cog):
        """Test recent check detection."""
        # Event with no actual presence
        event1 = {'actual_presence': []}
        assert not guild_attendance_cog._was_recently_checked(event1, datetime.now())
        
        # Event with actual presence
        event2 = {'actual_presence': [1, 2, 3]}
        assert guild_attendance_cog._was_recently_checked(event2, datetime.now())


class TestSetupFunctions:
    """Test setup functions for all cogs."""
    
    def test_guild_init_setup(self):
        """Test GuildInit setup function."""
        mock_bot = Mock(spec=discord.Bot)
        mock_bot.add_cog = Mock()
        
        from cogs.guild_init import setup
        setup(mock_bot)
        
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], GuildInit)
    
    def test_guild_ptb_setup(self):
        """Test GuildPTB setup function."""
        mock_bot = Mock(spec=discord.Bot)
        mock_bot.add_cog = Mock()
        
        from cogs.guild_ptb import setup
        setup(mock_bot)
        
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], GuildPTB)
    
    def test_guild_members_setup(self):
        """Test GuildMembers setup function."""
        mock_bot = Mock(spec=discord.Bot)
        mock_bot.add_cog = Mock()
        
        from cogs.guild_members import setup
        setup(mock_bot)
        
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], GuildMembers)
    
    def test_guild_events_setup(self):
        """Test GuildEvents setup function."""
        mock_bot = Mock(spec=discord.Bot)
        mock_bot.add_cog = Mock()
        
        from cogs.guild_events import setup
        setup(mock_bot)
        
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], GuildEvents)
    
    def test_guild_attendance_setup(self):
        """Test GuildAttendance setup function."""
        mock_bot = Mock(spec=discord.Bot)
        mock_bot.add_cog = Mock()
        
        from cogs.guild_attendance import setup
        setup(mock_bot)
        
        mock_bot.add_cog.assert_called_once()
        assert isinstance(mock_bot.add_cog.call_args[0][0], GuildAttendance)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])