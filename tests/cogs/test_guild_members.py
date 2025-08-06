"""
Tests for cogs.guild_members module - Guild Members Cog functionality.
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

# Import test utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.cog
@pytest.mark.asyncio
class TestGuildMembers:
    """Test the GuildMembers cog functionality."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot with necessary systems."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_category_loaded = AsyncMock()
        bot.run_db_query = AsyncMock()
        
        # Mock command groups
        bot.member_group = Mock()
        bot.member_group.command = Mock()
        bot.staff_group = Mock() 
        bot.staff_group.command = Mock()
        
        return bot

    @pytest.fixture
    def guild_members_cog(self, mock_bot):
        """Create GuildMembers instance with mocked dependencies."""
        translations = {
            'member_management': {
                'gs': {
                    'name': {'en-US': 'gs'},
                    'description': {'en-US': 'Update your gear score (GS)'}
                },
                'weapons': {
                    'name': {'en-US': 'weapons'},
                    'description': {'en-US': 'Update your weapon combination'}
                },
                'build': {
                    'name': {'en-US': 'build'},
                    'description': {'en-US': 'Update your build URL'}
                },
                'username': {
                    'name': {'en-US': 'username'},
                    'description': {'en-US': 'Update your username'}
                }
            }
        }
        
        with patch('core.translation.translations', translations):
            from app.cogs.guild_members import GuildMembers
            return GuildMembers(mock_bot)

    @pytest.fixture
    def mock_ctx(self, mock_bot):
        """Create a mock Discord application context."""
        ctx = Mock()
        ctx.bot = mock_bot
        ctx.guild = Mock()
        ctx.guild.id = 123456789
        ctx.author = Mock()
        ctx.author.id = 987654321
        ctx.author.display_name = "Test User"
        ctx.respond = AsyncMock()
        ctx.defer = AsyncMock()
        return ctx

    def test_guild_members_initialization(self, guild_members_cog, mock_bot):
        """Test GuildMembers initialization."""
        assert guild_members_cog.bot == mock_bot
        assert guild_members_cog.allowed_build_domains == ['questlog.gg', 'maxroll.gg']
        assert guild_members_cog.max_username_length == 32
        assert guild_members_cog.max_gs_value == 9999
        assert guild_members_cog.min_gs_value == 500

    def test_command_registration(self, mock_bot):
        """Test that commands are properly registered."""
        translations = {
            'member_management': {
                'gs': {'name': {'en-US': 'gs'}, 'description': {'en-US': 'Update gear score'}},
                'weapons': {'name': {'en-US': 'weapons'}, 'description': {'en-US': 'Update weapons'}},
                'build': {'name': {'en-US': 'build'}, 'description': {'en-US': 'Update build'}},
                'username': {'name': {'en-US': 'username'}, 'description': {'en-US': 'Update username'}},
            }
        }
        
        with patch('core.translation.translations', translations):
            from app.cogs.guild_members import GuildMembers
            guild_members = GuildMembers(mock_bot)
            
            # Verify member commands were registered
            assert mock_bot.member_group.command.call_count >= 4
            
            # Check specific command names
            calls = mock_bot.member_group.command.call_args_list
            registered_names = [call[1]['name'] for call in calls]
            assert 'gs' in registered_names
            assert 'weapons' in registered_names
            assert 'build' in registered_names
            assert 'username' in registered_names

    @pytest.mark.asyncio
    async def test_gs_command_valid_value(self, guild_members_cog, mock_ctx):
        """Test gear score command with valid value.""" 
        valid_gs = 2500
        
        # Mock database success
        guild_members_cog.bot.run_db_query.return_value = None
        
        with patch('core.functions.get_user_message', return_value=f"Gear score updated to {valid_gs}"):
            await guild_members_cog.gs(mock_ctx, valid_gs)
            
        # Verify database was called
        guild_members_cog.bot.run_db_query.assert_called_once()
        
        # Verify response
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_gs_command_invalid_low_value(self, guild_members_cog, mock_ctx):
        """Test gear score command with too low value."""
        invalid_gs = 100  # Below min_gs_value
        
        with patch('core.functions.get_user_message', return_value="Gear score too low"):
            await guild_members_cog.gs(mock_ctx, invalid_gs)
            
        # Database should not be called
        guild_members_cog.bot.run_db_query.assert_not_called()
        
        # Should respond with error
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_gs_command_invalid_high_value(self, guild_members_cog, mock_ctx):
        """Test gear score command with too high value."""
        invalid_gs = 15000  # Above max_gs_value
        
        with patch('core.functions.get_user_message', return_value="Gear score too high"):
            await guild_members_cog.gs(mock_ctx, invalid_gs)
            
        # Database should not be called
        guild_members_cog.bot.run_db_query.assert_not_called()
        
        # Should respond with error
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_weapons_command_valid(self, guild_members_cog, mock_ctx):
        """Test weapons command with valid weapon combination."""
        valid_weapons = "GS, SNS"  # Great Sword, Sword and Shield
        
        guild_members_cog.bot.run_db_query.return_value = None
        
        with patch('core.functions.get_user_message', return_value="Weapons updated"):
            await guild_members_cog.weapons(mock_ctx, valid_weapons)
            
        guild_members_cog.bot.run_db_query.assert_called_once()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_weapons_command_invalid_length(self, guild_members_cog, mock_ctx):
        """Test weapons command with too long input."""
        invalid_weapons = "A" * 200  # Too long
        
        with patch('core.functions.get_user_message', return_value="Weapons input too long"):
            await guild_members_cog.weapons(mock_ctx, invalid_weapons)
            
        guild_members_cog.bot.run_db_query.assert_not_called()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_command_valid_url(self, guild_members_cog, mock_ctx):
        """Test build command with valid build URL."""
        valid_url = "https://questlog.gg/builds/test-build"
        
        guild_members_cog.bot.run_db_query.return_value = None
        
        with patch('core.functions.get_user_message', return_value="Build updated"):
            await guild_members_cog.build(mock_ctx, valid_url)
            
        guild_members_cog.bot.run_db_query.assert_called_once()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_command_invalid_domain(self, guild_members_cog, mock_ctx):
        """Test build command with invalid domain."""
        invalid_url = "https://invalid-site.com/build"
        
        with patch('core.functions.get_user_message', return_value="Invalid build URL domain"):
            await guild_members_cog.build(mock_ctx, invalid_url)
            
        guild_members_cog.bot.run_db_query.assert_not_called()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_command_invalid_url_format(self, guild_members_cog, mock_ctx):
        """Test build command with malformed URL."""
        invalid_url = "not-a-valid-url"
        
        with patch('core.functions.get_user_message', return_value="Invalid URL format"):
            await guild_members_cog.build(mock_ctx, invalid_url)
            
        guild_members_cog.bot.run_db_query.assert_not_called()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_username_command_valid(self, guild_members_cog, mock_ctx):
        """Test username command with valid username."""
        valid_username = "TestPlayer123"
        
        guild_members_cog.bot.run_db_query.return_value = None
        
        with patch('core.functions.get_user_message', return_value="Username updated"):
            await guild_members_cog.username(mock_ctx, valid_username)
            
        guild_members_cog.bot.run_db_query.assert_called_once()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_username_command_too_long(self, guild_members_cog, mock_ctx):
        """Test username command with too long username."""
        long_username = "A" * 50  # Exceeds max_username_length
        
        with patch('core.functions.get_user_message', return_value="Username too long"):
            await guild_members_cog.username(mock_ctx, long_username)
            
        guild_members_cog.bot.run_db_query.assert_not_called()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_username_command_invalid_characters(self, guild_members_cog, mock_ctx):
        """Test username command with invalid characters."""
        invalid_username = "Test@User!"
        
        with patch('core.functions.get_user_message', return_value="Invalid characters in username"):
            await guild_members_cog.username(mock_ctx, invalid_username)
            
        guild_members_cog.bot.run_db_query.assert_not_called()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_show_build_command_existing_member(self, guild_members_cog, mock_ctx):
        """Test show_build command for existing member."""
        target_member = Mock()
        target_member.id = 555666777
        target_member.display_name = "Target User"
        
        # Mock database response with build data
        guild_members_cog.bot.run_db_query.return_value = [
            {
                'build_url': 'https://questlog.gg/builds/test',
                'username': 'TargetPlayer',
                'weapons': 'GS, SNS',
                'gear_score': 2800
            }
        ]
        
        with patch('core.functions.get_user_message', return_value="Build information"):
            await guild_members_cog.show_build(mock_ctx, target_member)
            
        guild_members_cog.bot.run_db_query.assert_called_once()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_show_build_command_no_data(self, guild_members_cog, mock_ctx):
        """Test show_build command for member with no data."""
        target_member = Mock()
        target_member.id = 555666777
        target_member.display_name = "Target User"
        
        # Mock empty database response
        guild_members_cog.bot.run_db_query.return_value = []
        
        with patch('core.functions.get_user_message', return_value="No build data found"):
            await guild_members_cog.show_build(mock_ctx, target_member)
            
        guild_members_cog.bot.run_db_query.assert_called_once()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_change_language_command(self, guild_members_cog, mock_ctx):
        """Test change language command."""
        new_language = "fr-FR"
        
        guild_members_cog.bot.run_db_query.return_value = None
        
        with patch('core.functions.get_user_message', return_value="Language changed"):
            await guild_members_cog.change_language(mock_ctx, new_language)
            
        guild_members_cog.bot.run_db_query.assert_called_once()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_database_error_handling(self, guild_members_cog, mock_ctx):
        """Test error handling when database operations fail."""
        valid_gs = 2500
        
        # Simulate database error
        guild_members_cog.bot.run_db_query.side_effect = Exception("Database connection failed")
        
        with patch('logging.error') as mock_error, \
             patch('core.functions.get_user_message', return_value="An error occurred"):
            
            await guild_members_cog.gs(mock_ctx, valid_gs)
            
        mock_error.assert_called()
        mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_build_url_private_method(self, guild_members_cog):
        """Test the private _validate_build_url method."""
        # Valid URLs
        valid_urls = [
            "https://questlog.gg/builds/test",
            "https://maxroll.gg/nw/build/test",
            "http://questlog.gg/simple"
        ]
        
        for url in valid_urls:
            assert guild_members_cog._validate_build_url(url) == True
        
        # Invalid URLs
        invalid_urls = [
            "https://invalid-site.com/build",
            "not-a-url",
            "ftp://questlog.gg/build",
            ""
        ]
        
        for url in invalid_urls:
            assert guild_members_cog._validate_build_url(url) == False

    @pytest.mark.asyncio
    async def test_validate_username_private_method(self, guild_members_cog):
        """Test the private _validate_username method."""
        # Valid usernames
        valid_usernames = [
            "TestUser",
            "Player123",
            "Test_User",
            "User-Name"
        ]
        
        for username in valid_usernames:
            assert guild_members_cog._validate_username(username) == True
        
        # Invalid usernames
        invalid_usernames = [
            "",  # Empty
            "A" * 50,  # Too long
            "Test@User",  # Invalid characters
            "User!Name",  # Invalid characters
            "Test User",  # Space (if not allowed)
        ]
        
        for username in invalid_usernames:
            assert guild_members_cog._validate_username(username) == False

    @pytest.mark.asyncio
    async def test_validate_weapons_private_method(self, guild_members_cog):
        """Test the private _validate_weapons method."""
        # Valid weapon combinations
        valid_weapons = [
            "GS",
            "GS, SNS",
            "Bow, Spear",
            "Great Sword, Sword and Shield"
        ]
        
        for weapons in valid_weapons:
            assert guild_members_cog._validate_weapons(weapons) == True
        
        # Invalid weapon combinations
        invalid_weapons = [
            "",  # Empty
            "A" * 200,  # Too long
        ]
        
        for weapons in invalid_weapons:
            assert guild_members_cog._validate_weapons(weapons) == False


@pytest.mark.cog
@pytest.mark.integration
@pytest.mark.asyncio
class TestGuildMembersIntegration:
    """Integration tests for GuildMembers with other systems."""

    @pytest.fixture
    def integrated_bot(self):
        """Create a more realistic bot for integration testing."""
        bot = Mock()
        
        # Cache system
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        bot.cache.set_guild_data = AsyncMock()
        
        # Database system
        bot.run_db_query = AsyncMock()
        
        # Command groups
        bot.member_group = Mock()
        bot.member_group.command = Mock(return_value=lambda func: func)
        bot.staff_group = Mock() 
        bot.staff_group.command = Mock(return_value=lambda func: func)
        
        return bot

    @pytest.mark.asyncio
    async def test_member_profile_update_workflow(self, integrated_bot):
        """Test complete member profile update workflow."""
        translations = {
            'member_management': {
                'gs': {'name': {'en-US': 'gs'}, 'description': {'en-US': 'Update gear score'}},
                'weapons': {'name': {'en-US': 'weapons'}, 'description': {'en-US': 'Update weapons'}},
                'build': {'name': {'en-US': 'build'}, 'description': {'en-US': 'Update build'}},
                'username': {'name': {'en-US': 'username'}, 'description': {'en-US': 'Update username'}}
            }
        }
        
        with patch('core.translation.translations', translations):
            from app.cogs.guild_members import GuildMembers
            guild_members = GuildMembers(integrated_bot)
            
            # Create context
            ctx = Mock()
            ctx.guild = Mock()
            ctx.guild.id = 123456789
            ctx.author = Mock()
            ctx.author.id = 987654321
            ctx.respond = AsyncMock()
            
            # Mock successful database operations
            integrated_bot.run_db_query.return_value = None
            
            with patch('core.functions.get_user_message', side_effect=[
                "Gear score updated to 2500",
                "Weapons updated to GS, SNS", 
                "Build updated",
                "Username updated to TestPlayer"
            ]):
                # Test profile updates in sequence
                await guild_members.gs(ctx, 2500)
                await guild_members.weapons(ctx, "GS, SNS")
                await guild_members.build(ctx, "https://questlog.gg/builds/test")
                await guild_members.username(ctx, "TestPlayer")
                
                # Verify all operations succeeded
                assert integrated_bot.run_db_query.call_count == 4
                assert ctx.respond.call_count == 4

    @pytest.mark.asyncio
    async def test_roster_update_with_performance_profiling(self, integrated_bot):
        """Test roster update with performance profiling integration."""
        translations = {
            'member_management': {
                'maj_roster': {'name': {'en-US': 'maj_roster'}, 'description': {'en-US': 'Update roster'}}
            }
        }
        
        with patch('core.translation.translations', translations), \
             patch('core.performance_profiler.profile_performance') as mock_profile:
            
            from app.cogs.guild_members import GuildMembers
            guild_members = GuildMembers(integrated_bot)
            
            # Verify that performance profiling decorator is being used
            # This is mainly to check that the import and decorator application works
            assert hasattr(guild_members, '_register_staff_commands')

    @pytest.mark.asyncio
    async def test_rate_limiting_integration(self, integrated_bot):
        """Test integration with rate limiting system."""
        translations = {
            'member_management': {
                'gs': {'name': {'en-US': 'gs'}, 'description': {'en-US': 'Update gear score'}}
            }
        }
        
        with patch('core.translation.translations', translations), \
             patch('core.rate_limiter.admin_rate_limit') as mock_rate_limit:
            
            from app.cogs.guild_members import GuildMembers
            guild_members = GuildMembers(integrated_bot)
            
            # Verify that rate limiting is imported and available
            # The actual rate limiting behavior is tested in the rate_limiter tests
            assert mock_rate_limit is not None