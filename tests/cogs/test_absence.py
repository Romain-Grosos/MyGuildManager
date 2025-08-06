"""
Tests for cogs.absence module - Absence Manager Cog functionality.
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
class TestAbsenceManager:
    """Test the AbsenceManager cog functionality."""

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
        
        # Mock absence group for command registration
        bot.absence_group = Mock()
        bot.absence_group.command = Mock()
        
        return bot

    @pytest.fixture
    def absence_manager(self, mock_bot):
        """Create AbsenceManager instance with mocked dependencies."""
        with patch('core.translation.translations', {
            'absence_system': {
                'absence_add': {
                    'name': {'en-US': 'absence_add'},
                    'description': {'en-US': 'Mark a member as absent.'}
                },
                'return': {
                    'name': {'en-US': 'return'},
                    'description': {'en-US': 'Signal your return from absence.'}
                }
            }
        }):
            from app.cogs.absence import AbsenceManager
            return AbsenceManager(mock_bot)

    @pytest.fixture
    def mock_guild(self):
        """Create a mock Discord guild."""
        guild = Mock()
        guild.id = 123456789
        guild.name = "Test Guild"
        guild.get_role = Mock()
        return guild

    @pytest.fixture
    def mock_member(self, mock_guild):
        """Create a mock Discord member."""
        member = Mock()
        member.id = 987654321
        member.name = "TestUser"
        member.display_name = "Test User"
        member.guild = mock_guild
        member.add_roles = AsyncMock()
        member.remove_roles = AsyncMock()
        member.send = AsyncMock()
        return member

    @pytest.fixture
    def mock_ctx(self, mock_bot, mock_guild, mock_member):
        """Create a mock Discord application context."""
        ctx = Mock()
        ctx.bot = mock_bot
        ctx.guild = mock_guild
        ctx.author = mock_member
        ctx.user = mock_member
        ctx.respond = AsyncMock()
        ctx.followup = AsyncMock()
        ctx.defer = AsyncMock()
        return ctx

    def test_absence_manager_initialization(self, absence_manager, mock_bot):
        """Test AbsenceManager initialization."""
        assert absence_manager.bot == mock_bot
        
        # Verify command registration was attempted
        mock_bot.absence_group.command.assert_called()

    def test_command_registration(self, mock_bot):
        """Test that commands are properly registered with the absence group."""
        with patch('core.translation.translations', {
            'absence_system': {
                'absence_add': {
                    'name': {'en-US': 'absence_add', 'fr-FR': 'ajout_absence'},
                    'description': {'en-US': 'Mark a member as absent.', 'fr-FR': 'Marquer un membre comme absent.'}
                },
                'return': {
                    'name': {'en-US': 'return', 'fr-FR': 'retour'},
                    'description': {'en-US': 'Signal your return from absence.', 'fr-FR': 'Signaler votre retour d\'absence.'}
                }
            }
        }):
            from app.cogs.absence import AbsenceManager
            absence_manager = AbsenceManager(mock_bot)
            
            # Verify commands were registered with correct parameters
            assert mock_bot.absence_group.command.call_count == 2
            
            # Check that both commands were registered
            calls = mock_bot.absence_group.command.call_args_list
            registered_names = [call[1]['name'] for call in calls]
            assert 'absence_add' in registered_names
            assert 'return' in registered_names

    @pytest.mark.asyncio
    async def test_on_ready_event(self, absence_manager):
        """Test on_ready event handler.""" 
        with patch('asyncio.create_task') as mock_create_task:
            await absence_manager.on_ready()
            
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_guild_roles_success(self, absence_manager, mock_guild):
        """Test successful guild roles retrieval."""
        # Mock role data
        absence_manager.bot.cache.get_guild_data.return_value = {
            'members': 111,
            'absent_members': 222
        }
        
        # Mock roles
        member_role = Mock()
        member_role.id = 111
        absent_role = Mock()
        absent_role.id = 222
        
        mock_guild.get_role.side_effect = lambda role_id: {
            111: member_role,
            222: absent_role
        }.get(role_id)
        
        member_role_result, absent_role_result = await absence_manager._get_guild_roles(mock_guild)
        
        assert member_role_result == member_role
        assert absent_role_result == absent_role
        absence_manager.bot.cache.get_guild_data.assert_called_once_with(mock_guild.id, 'roles')

    @pytest.mark.asyncio
    async def test_get_guild_roles_no_data(self, absence_manager, mock_guild):
        """Test guild roles retrieval with no cached data."""
        absence_manager.bot.cache.get_guild_data.return_value = None
        
        member_role, absent_role = await absence_manager._get_guild_roles(mock_guild)
        
        assert member_role is None
        assert absent_role is None

    @pytest.mark.asyncio
    async def test_get_guild_roles_missing_roles(self, absence_manager, mock_guild):
        """Test guild roles retrieval with missing roles.""" 
        absence_manager.bot.cache.get_guild_data.return_value = {
            'members': 111,
            'absent_members': 222
        }
        
        # Mock roles as None (deleted/missing)
        mock_guild.get_role.return_value = None
        
        with patch('logging.warning') as mock_warning:
            member_role, absent_role = await absence_manager._get_guild_roles(mock_guild)
            
        assert member_role is None
        assert absent_role is None
        mock_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_absence_channels(self, absence_manager):
        """Test loading of absence channels data."""
        await absence_manager.load_absence_channels()
        
        # Verify required categories are loaded
        absence_manager.bot.cache_loader.ensure_category_loaded.assert_any_call('guild_channels')
        absence_manager.bot.cache_loader.ensure_category_loaded.assert_any_call('guild_roles')

    @pytest.mark.asyncio
    async def test_absence_add_command_success(self, absence_manager, mock_ctx):
        """Test successful absence addition."""
        # Mock target member
        target_member = Mock()
        target_member.id = 555666777
        target_member.display_name = "Target User"
        target_member.add_roles = AsyncMock()
        target_member.remove_roles = AsyncMock()
        
        # Mock roles
        member_role = Mock()
        absent_role = Mock()
        
        with patch.object(absence_manager, '_get_guild_roles', return_value=(member_role, absent_role)), \
             patch('core.functions.get_user_message', return_value="Member marked as absent"), \
             patch.object(absence_manager, '_notify_absence', return_value=True):
            
            await absence_manager.absence_add(mock_ctx, target_member, "Vacation")
            
            # Verify role changes
            target_member.remove_roles.assert_called_once_with(member_role)
            target_member.add_roles.assert_called_once_with(absent_role)
            
            # Verify response
            mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_absence_add_no_roles(self, absence_manager, mock_ctx):
        """Test absence addition when roles are not configured."""
        target_member = Mock()
        
        with patch.object(absence_manager, '_get_guild_roles', return_value=(None, None)), \
             patch('core.functions.get_user_message', return_value="Roles not configured"):
            
            await absence_manager.absence_add(mock_ctx, target_member, "Vacation")
            
            # Should respond with error message
            mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_absence_remove_command_success(self, absence_manager, mock_ctx):
        """Test successful absence removal."""
        # Mock roles
        member_role = Mock()
        absent_role = Mock()
        
        # Mock database query result
        absence_manager.bot.run_db_query.return_value = [
            {'id': 1, 'user_id': mock_ctx.author.id, 'reason': 'Vacation'}
        ]
        
        with patch.object(absence_manager, '_get_guild_roles', return_value=(member_role, absent_role)), \
             patch('core.functions.get_user_message', return_value="Welcome back!"), \
             patch.object(absence_manager, '_notify_return', return_value=True):
            
            await absence_manager.absence_remove(mock_ctx)
            
            # Verify role changes
            mock_ctx.author.add_roles.assert_called_once_with(member_role)
            mock_ctx.author.remove_roles.assert_called_once_with(absent_role)
            
            # Verify database update
            absence_manager.bot.run_db_query.assert_called()
            
            # Verify response
            mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_absence_remove_not_absent(self, absence_manager, mock_ctx):
        """Test absence removal when user is not marked absent."""
        absence_manager.bot.run_db_query.return_value = []  # No absence record
        
        with patch('core.functions.get_user_message', return_value="You are not marked as absent"):
            await absence_manager.absence_remove(mock_ctx)
            
            mock_ctx.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_absence_success(self, absence_manager, mock_ctx):
        """Test absence notification."""
        target_member = Mock()
        target_member.display_name = "Test User"
        reason = "Vacation"
        
        # Mock channel data
        absence_manager.bot.cache.get_guild_data.return_value = {'absence_notifications': 123456789}
        
        # Mock channel
        mock_channel = Mock()
        mock_channel.send = AsyncMock()
        absence_manager.bot.get_channel = Mock(return_value=mock_channel)
        
        with patch('core.functions.get_guild_message', return_value="User is now absent"):
            result = await absence_manager._notify_absence(mock_ctx.guild, target_member, reason, mock_ctx.author)
            
            assert result is True
            mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_absence_no_channel(self, absence_manager, mock_ctx):
        """Test absence notification with no notification channel configured."""
        target_member = Mock()
        
        # No channel data
        absence_manager.bot.cache.get_guild_data.return_value = None
        
        with patch('logging.debug') as mock_debug:
            result = await absence_manager._notify_absence(mock_ctx.guild, target_member, "reason", mock_ctx.author)
            
            assert result is False
            mock_debug.assert_called()

    @pytest.mark.asyncio
    async def test_notify_return_success(self, absence_manager, mock_ctx):
        """Test return notification."""
        member = mock_ctx.author
        
        # Mock channel data
        absence_manager.bot.cache.get_guild_data.return_value = {'absence_notifications': 123456789}
        
        # Mock channel
        mock_channel = Mock()
        mock_channel.send = AsyncMock()
        absence_manager.bot.get_channel = Mock(return_value=mock_channel)
        
        with patch('core.functions.get_guild_message', return_value="User has returned"):
            result = await absence_manager._notify_return(mock_ctx.guild, member)
            
            assert result is True
            mock_channel.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_handling_in_commands(self, absence_manager, mock_ctx):
        """Test error handling in absence commands.""" 
        target_member = Mock()
        
        # Simulate database error
        absence_manager.bot.run_db_query.side_effect = Exception("Database error")
        
        with patch('logging.error') as mock_error, \
             patch('core.functions.get_user_message', return_value="An error occurred"):
            
            await absence_manager.absence_add(mock_ctx, target_member, "Vacation")
            
            mock_error.assert_called()
            mock_ctx.respond.assert_called()

    @pytest.mark.asyncio
    async def test_get_absence_list(self, absence_manager, mock_ctx):
        """Test retrieving list of absent members."""
        # Mock database response
        absence_manager.bot.run_db_query.return_value = [
            {'user_id': 111, 'reason': 'Vacation', 'since': '2024-01-01'},
            {'user_id': 222, 'reason': 'Medical', 'since': '2024-01-02'}
        ]
        
        absent_list = await absence_manager._get_absence_list(mock_ctx.guild.id)
        
        assert len(absent_list) == 2
        assert absent_list[0]['user_id'] == 111
        assert absent_list[1]['user_id'] == 222

    @pytest.mark.asyncio
    async def test_clean_expired_absences(self, absence_manager):
        """Test cleaning up expired absences."""
        guild_id = 123456789
        
        # Mock expired absences
        absence_manager.bot.run_db_query.return_value = [
            {'id': 1, 'user_id': 111},
            {'id': 2, 'user_id': 222}
        ]
        
        await absence_manager._clean_expired_absences(guild_id)
        
        # Verify cleanup queries were made
        absence_manager.bot.run_db_query.assert_called()


@pytest.mark.cog
@pytest.mark.integration
@pytest.mark.asyncio
class TestAbsenceManagerIntegration:
    """Integration tests for AbsenceManager with other systems."""

    @pytest.fixture
    def integrated_bot(self):
        """Create a more realistic bot mock for integration testing."""
        bot = Mock()
        
        # Cache system
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        bot.cache.set_guild_data = AsyncMock()
        
        # Cache loader
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_category_loaded = AsyncMock()
        
        # Database
        bot.run_db_query = AsyncMock()
        
        # Channel and role retrieval
        bot.get_channel = Mock()
        
        # Command group
        bot.absence_group = Mock()
        bot.absence_group.command = Mock()
        
        return bot

    @pytest.mark.asyncio
    async def test_full_absence_workflow(self, integrated_bot):
        """Test complete absence workflow from add to return."""
        with patch('core.translation.translations', {
            'absence_system': {
                'absence_add': {
                    'name': {'en-US': 'absence_add'},
                    'description': {'en-US': 'Mark a member as absent.'}
                },
                'return': {
                    'name': {'en-US': 'return'},
                    'description': {'en-US': 'Signal your return from absence.'}
                }
            }
        }):
            from app.cogs.absence import AbsenceManager
            absence_manager = AbsenceManager(integrated_bot)
            
            # Create mock objects
            guild = Mock()
            guild.id = 123456789
            
            member = Mock()
            member.id = 987654321
            member.display_name = "Test User"
            member.add_roles = AsyncMock()
            member.remove_roles = AsyncMock()
            
            ctx = Mock()
            ctx.guild = guild
            ctx.author = member
            ctx.respond = AsyncMock()
            ctx.defer = AsyncMock()
            
            # Mock roles
            member_role = Mock()
            absent_role = Mock()
            
            # Mock successful role retrieval
            integrated_bot.cache.get_guild_data.return_value = {
                'members': 111,
                'absent_members': 222
            }
            
            guild.get_role.side_effect = lambda role_id: {
                111: member_role,
                222: absent_role
            }.get(role_id)
            
            # Mock database operations
            integrated_bot.run_db_query.side_effect = [
                None,  # For absence add
                [{'id': 1, 'user_id': member.id, 'reason': 'Test'}],  # For absence check
                None   # For absence removal
            ]
            
            # Mock translation functions
            with patch('core.functions.get_user_message', side_effect=[
                "Member marked as absent",
                "Welcome back!"
            ]) as mock_get_user_message, \
                 patch.object(absence_manager, '_notify_absence', return_value=True), \
                 patch.object(absence_manager, '_notify_return', return_value=True):
                
                # Test absence addition
                await absence_manager.absence_add(ctx, member, "Testing")
                
                # Verify role changes for absence
                member.remove_roles.assert_called_with(member_role)
                member.add_roles.assert_called_with(absent_role)
                
                # Reset mocks for return test
                member.add_roles.reset_mock()
                member.remove_roles.reset_mock()
                
                # Test absence removal  
                await absence_manager.absence_remove(ctx)
                
                # Verify role changes for return
                member.add_roles.assert_called_with(member_role)
                member.remove_roles.assert_called_with(absent_role)
                
                # Verify both operations responded to user
                assert ctx.respond.call_count == 2

    @pytest.mark.asyncio
    async def test_absence_with_translation_system(self, integrated_bot):
        """Test absence manager integration with translation system."""
        translations = {
            'absence_system': {
                'absence_add': {
                    'name': {'en-US': 'absence_add', 'fr-FR': 'ajout_absence'},
                    'description': {'en-US': 'Mark absent', 'fr-FR': 'Marquer absent'}
                },
                'success_added': {'en-US': 'Member marked absent', 'fr-FR': 'Membre marqué absent'},
                'error_no_roles': {'en-US': 'Roles not configured', 'fr-FR': 'Rôles non configurés'}
            }
        }
        
        with patch('core.translation.translations', translations):
            from app.cogs.absence import AbsenceManager
            absence_manager = AbsenceManager(integrated_bot)
            
            # Verify that translations are being used for command registration
            integrated_bot.absence_group.command.assert_called()
            
            # Check that localized names and descriptions are passed
            calls = integrated_bot.absence_group.command.call_args_list
            for call in calls:
                assert 'name_localizations' in call[1]
                assert 'description_localizations' in call[1]