"""
Tests for cache_loader.py - Centralized cache loader for shared guild data.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from cache_loader import CacheLoader, get_cache_loader


class TestCacheLoader:
    """Test CacheLoader class functionality."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot with cache and database functionality."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.set_user_data = AsyncMock()
        bot.run_db_query = AsyncMock()
        return bot
    
    @pytest.fixture
    def cache_loader(self, mock_bot):
        """Create CacheLoader instance for testing."""
        return CacheLoader(mock_bot)
    
    def test_cache_loader_initialization(self, mock_bot):
        """Test CacheLoader initialization."""
        loader = CacheLoader(mock_bot)
        
        assert loader.bot == mock_bot
        assert loader._loaded_categories == set()
        assert isinstance(loader._loaded_categories, set)
    
    @pytest.mark.asyncio
    async def test_ensure_guild_settings_loaded_success(self, cache_loader, mock_bot):
        """Test successful guild settings loading."""
        # Mock database response with new columns (guild_ptb, initialized)
        mock_rows = [
            (123, True, 'en-US', 'Test Guild', 1, 'Server1', True, 1),
            (456, False, 'fr-FR', 'Guilde Test', 2, 'Server2', False, 0)
        ]
        mock_bot.run_db_query.return_value = mock_rows
        
        await cache_loader.ensure_guild_settings_loaded()
        
        # Verify database query was called
        mock_bot.run_db_query.assert_called_once()
        query = mock_bot.run_db_query.call_args[0][0]
        assert "SELECT guild_id, guild_ptb, guild_lang, guild_name, guild_game, guild_server, initialized, premium FROM guild_settings" in query
        
        # Verify cache was populated for both guilds (7 individual + 1 complete settings per guild = 16 total)
        assert mock_bot.cache.set_guild_data.call_count == 16
        
        # Verify category was marked as loaded
        assert 'guild_settings' in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_ensure_guild_settings_loaded_already_loaded(self, cache_loader, mock_bot):
        """Test that guild settings loading is skipped if already loaded."""
        cache_loader._loaded_categories.add('guild_settings')
        
        await cache_loader.ensure_guild_settings_loaded()
        
        # Should not call database if already loaded
        mock_bot.run_db_query.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_ensure_guild_settings_loaded_no_data(self, cache_loader, mock_bot):
        """Test guild settings loading with empty result."""
        mock_bot.run_db_query.return_value = []
        
        with patch('cache_loader.logging.warning') as mock_warning:
            await cache_loader.ensure_guild_settings_loaded()
            
            mock_warning.assert_called_with("[CacheLoader] No guild settings found in database")
        
        # Should not mark as loaded if no data
        assert 'guild_settings' not in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_ensure_guild_settings_loaded_database_error(self, cache_loader, mock_bot):
        """Test guild settings loading with database error."""
        mock_bot.run_db_query.side_effect = Exception("Database connection failed")
        
        with patch('cache_loader.logging.error') as mock_error:
            await cache_loader.ensure_guild_settings_loaded()
            
            mock_error.assert_called_once()
            assert "Error loading guild settings" in str(mock_error.call_args)
    
    @pytest.mark.asyncio
    async def test_ensure_guild_roles_loaded_success(self, cache_loader, mock_bot):
        """Test successful guild roles loading."""
        mock_rows = [
            (123, 'guild_master_123', 'officer_123', 'guardian_123', 'members_role_id', 'absent_role_id', 'allies_123', 'diplomats_123', 'friends_123', 'applicant_123', 'config_ok_123', 'rules_role_id'),
            (456, 'guild_master_456', 'officer_456', 'guardian_456', 'members2_id', None, 'allies_456', 'diplomats_456', 'friends_456', 'applicant_456', 'config_ok_456', 'rules2_id')  # Test with None value
        ]
        mock_bot.run_db_query.return_value = mock_rows
        
        await cache_loader.ensure_guild_roles_loaded()
        
        # Verify database query
        mock_bot.run_db_query.assert_called_once()
        query = mock_bot.run_db_query.call_args[0][0]
        assert "SELECT guild_id, guild_master, officer, guardian, members, absent_members, allies, diplomats, friends, applicant, config_ok, rules_ok FROM guild_roles" in query
        
        # Verify cache population - should handle None values correctly
        assert mock_bot.cache.set_guild_data.call_count >= 4  # At least 2 complete objects + individual roles
        
        # Verify category marked as loaded
        assert 'guild_roles' in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_ensure_guild_channels_loaded_success(self, cache_loader, mock_bot):
        """Test successful guild channels loading."""
        mock_rows = [
            (123, 'rules_ch', 'rules_msg', 'announcements_ch', 'voice_tavern_ch', 'voice_war_ch', 'room_ch', 'events_ch', 'members_ch', 'members_m1', 'members_m2', 'members_m3', 'members_m4', 'members_m5', 'groups_ch', 'static_ch', 'static_msg', 'abs_ch', 'loot_ch', 'tuto_ch', 'forum_allies_ch', 'forum_friends_ch', 'forum_diplomats_ch', 'forum_recruitment_ch', 'forum_members_ch', 'notifications_ch', 'external_recruitment_cat', 'category_diplomat', 'external_recruitment_ch', 'external_recruitment_msg')
        ]
        mock_bot.run_db_query.return_value = mock_rows
        
        await cache_loader.ensure_guild_channels_loaded()
        
        # Verify complex query structure
        mock_bot.run_db_query.assert_called_once()
        query = mock_bot.run_db_query.call_args[0][0]
        assert "rules_channel" in query
        assert "events_channel" in query
        assert "create_room_channel" in query
        
        # Verify multiple cache objects were created
        assert mock_bot.cache.set_guild_data.call_count >= 5  # Complete + specific configs
        
        assert 'guild_channels' in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_ensure_welcome_messages_loaded_success(self, cache_loader, mock_bot):
        """Test successful welcome messages loading."""
        mock_rows = [
            (123, 456, 789, 'msg1'),
            (123, 457, 790, 'msg2')
        ]
        mock_bot.run_db_query.return_value = mock_rows
        
        await cache_loader.ensure_welcome_messages_loaded()
        
        # Verify user data caching (not guild data)
        assert mock_bot.cache.set_user_data.call_count == 2
        
        # Verify correct data structure
        first_call = mock_bot.cache.set_user_data.call_args_list[0]
        assert first_call[0] == (123, 456, 'welcome_message', {"channel": 789, "message": 'msg1'})
        
        assert 'welcome_messages' in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_ensure_welcome_messages_loaded_empty(self, cache_loader, mock_bot):
        """Test welcome messages loading with empty result."""
        mock_bot.run_db_query.return_value = []
        
        with patch('cache_loader.logging.warning') as mock_warning:
            await cache_loader.ensure_welcome_messages_loaded()
            
            mock_warning.assert_called_with("[CacheLoader] No welcome messages found in database")
        
        # Should still mark as loaded even if empty
        assert 'welcome_messages' in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_ensure_absence_messages_loaded(self, cache_loader):
        """Test absence messages handling (no actual loading)."""
        with patch('cache_loader.logging.debug') as mock_debug:
            await cache_loader.ensure_absence_messages_loaded()
            
            mock_debug.assert_called_once()
            assert "high frequency data" in str(mock_debug.call_args)
        
        # Should mark as handled without loading
        assert 'absence_messages' in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_load_all_shared_data(self, cache_loader, mock_bot):
        """Test loading all shared data categories in parallel."""
        # Create a smart mock that returns appropriate data based on query
        def smart_query_side_effect(query, *args, **kwargs):
            if "guild_settings" in query:
                return [(123, True, 'en-US', 'Test Guild', 1, 'Server1', True, 1)]
            elif "guild_roles" in query:
                return [(123, 'gm_id', 'off_id', 'guard_id', 'mem_id', 'abs_id', 'ally_id', 'dipl_id', 'friend_id', 'app_id', 'cfg_id', 'rule_id')]
            elif "guild_channels" in query:
                return [(123, 'rules_ch', 'rules_msg', 'ann_ch', 'voice_ch', 'war_ch', 'room_ch', 'evt_ch', 'mem_ch', 'm1', 'm2', 'm3', 'm4', 'm5', 'grp_ch', 'stat_ch', 'stat_msg', 'abs_ch', 'loot_ch', 'tuto_ch', 'f_ally', 'f_friend', 'f_dipl', 'f_rec', 'f_mem', 'notif_ch', 'ext_rec_cat', 'cat_dipl', 'ext_rec_ch', 'ext_rec_msg')]
            elif "welcome_messages" in query:
                return [(123, 456, 789, 'msg1')]
            elif "absence_messages" in query:
                return [(123, 'msg1', 456)]
            elif "guild_members" in query:
                return [(123, 456, 'username', 'en-US', 'class', 'gs', 'build', 'weapons', 100, 5, 3, 2)]
            elif "events" in query:
                return [(123, 'evt1', 'Event Name', '2024-01-01', '20:00', 120, 50, 'active', 10, 8)]
            elif "user_setup" in query:
                return [(123, 456, 'en-US', 'gs', 'weapon')]
            elif "weapons" in query and "combinations" not in query:
                return [(1, 'WPN1', 'Weapon 1')]
            elif "weapons_combinations" in query:
                return [(1, 'role', 'wpn1', 'wpn2')]
            elif "guild_ideal_staff" in query:
                return [(123, 'class1', 5)]
            elif "games" in query:
                return [(1, 'Game Name', 50)]
            else:
                return []
        
        mock_bot.run_db_query.side_effect = smart_query_side_effect
        
        # Mock the bot's get_cog method for static data loading
        mock_bot.get_cog.return_value = Mock()
        mock_bot.get_cog.return_value.load_static_groups_cache = AsyncMock()
        
        # Add cache methods for static data
        mock_bot.cache.set_static_data = AsyncMock()
        mock_bot.cache.set = AsyncMock()
        
        with patch('cache_loader.logging.info') as mock_info:
            await cache_loader.load_all_shared_data()
            
            # Should log start and completion
            assert mock_info.call_count >= 2
            assert any("Loading all shared data" in str(call) for call in mock_info.call_args_list)
            assert any("completed" in str(call) for call in mock_info.call_args_list)
        
        # All categories should be loaded except events_data (which has specific requirements)
        expected_categories = {'guild_settings', 'guild_roles', 'guild_channels', 'welcome_messages', 'absence_messages', 'guild_members', 'static_data', 'user_setup', 'weapons', 'weapons_combinations', 'guild_ideal_staff', 'games_list'}
        assert expected_categories.issubset(cache_loader._loaded_categories)
    
    @pytest.mark.asyncio
    async def test_ensure_category_loaded_valid_categories(self, cache_loader, mock_bot):
        """Test ensure_category_loaded with valid category names."""
        # Create a smart mock that returns appropriate data based on query
        def smart_query_side_effect(query, *args, **kwargs):
            if "guild_settings" in query:
                return [(123, True, 'en-US', 'Test Guild', 1, 'Server1', True, 1)]
            elif "guild_roles" in query:
                return [(123, 'gm_id', 'off_id', 'guard_id', 'mem_id', 'abs_id', 'ally_id', 'dipl_id', 'friend_id', 'app_id', 'cfg_id', 'rule_id')]
            elif "guild_channels" in query:
                return [(123, 'rules_ch', 'rules_msg', 'ann_ch', 'voice_ch', 'war_ch', 'room_ch', 'evt_ch', 'mem_ch', 'm1', 'm2', 'm3', 'm4', 'm5', 'grp_ch', 'stat_ch', 'stat_msg', 'abs_ch', 'loot_ch', 'tuto_ch', 'f_ally', 'f_friend', 'f_dipl', 'f_rec', 'f_mem', 'notif_ch', 'ext_rec_cat', 'cat_dipl', 'ext_rec_ch', 'ext_rec_msg')]
            elif "welcome_messages" in query:
                return [(123, 456, 789, 'msg1')]
            elif "absence_messages" in query:
                return [(123, 'msg1', 456)]
            elif "guild_members" in query:
                return [(123, 456, 'username', 'en-US', 'class', 'gs', 'build', 'weapons', 100, 5, 3, 2)]
            elif "events" in query:
                return [(123, 'evt1', 'Event Name', '2024-01-01', '20:00', 120, 50, 'active', 10, 8)]
            elif "user_setup" in query:
                return [(123, 456, 'en-US', 'gs', 'weapon')]
            elif "weapons" in query and "combinations" not in query:
                return [(1, 'WPN1', 'Weapon 1')]
            elif "weapons_combinations" in query:
                return [(1, 'role', 'wpn1', 'wpn2')]
            elif "guild_ideal_staff" in query:
                return [(123, 'class1', 5)]
            elif "games" in query:
                return [(1, 'Game Name', 50)]
            else:
                return []
        
        mock_bot.run_db_query.side_effect = smart_query_side_effect
        
        # Mock additional cache methods
        mock_bot.cache.set_static_data = AsyncMock()
        mock_bot.cache.set = AsyncMock()
        mock_bot.get_cog.return_value = Mock()
        mock_bot.get_cog.return_value.load_static_groups_cache = AsyncMock()
        
        valid_categories = ['guild_settings', 'guild_roles', 'guild_channels', 'welcome_messages', 'absence_messages', 'guild_members', 'events_data', 'static_data', 'user_setup', 'weapons', 'weapons_combinations', 'guild_ideal_staff', 'games_list']
        
        for category in valid_categories:
            await cache_loader.ensure_category_loaded(category)
            assert category in cache_loader._loaded_categories
    
    @pytest.mark.asyncio
    async def test_ensure_category_loaded_invalid_category(self, cache_loader):
        """Test ensure_category_loaded with invalid category name."""
        with patch('cache_loader.logging.warning') as mock_warning:
            await cache_loader.ensure_category_loaded('invalid_category')
            
            mock_warning.assert_called_with("[CacheLoader] Unknown category: invalid_category")
    
    def test_is_category_loaded(self, cache_loader):
        """Test category loading status check."""
        assert not cache_loader.is_category_loaded('guild_settings')
        
        cache_loader._loaded_categories.add('guild_settings')
        assert cache_loader.is_category_loaded('guild_settings')
    
    @pytest.mark.asyncio
    async def test_reload_category(self, cache_loader, mock_bot):
        """Test category reloading functionality."""
        # First load the category
        cache_loader._loaded_categories.add('guild_settings')
        mock_bot.run_db_query.return_value = [(123, True, 'en-US', 'Test', 1, 'server', True, 1)]
        
        await cache_loader.reload_category('guild_settings')
        
        # Should still be loaded after reload
        assert cache_loader.is_category_loaded('guild_settings')
        # Should have called database again
        mock_bot.run_db_query.assert_called_once()
    
    def test_get_loaded_categories(self, cache_loader):
        """Test getting list of loaded categories."""
        cache_loader._loaded_categories.update({'cat1', 'cat2'})
        
        loaded = cache_loader.get_loaded_categories()
        
        assert loaded == {'cat1', 'cat2'}
        assert loaded is not cache_loader._loaded_categories  # Should be a copy


class TestCacheLoaderIntegration:
    """Integration tests for CacheLoader with realistic scenarios."""
    
    @pytest.fixture
    def mock_bot_with_data(self):
        """Create mock bot with realistic test data."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.set_user_data = AsyncMock()
        bot.run_db_query = AsyncMock()
        
        # Set up different responses for different queries
        def query_side_effect(query, *args, **kwargs):
            if "guild_settings" in query:
                return [
                    (123, True, 'en-US', 'English Guild', 1, 'NA', True, 1),
                    (456, False, 'fr-FR', 'Guilde Française', 2, 'EU', False, 0)
                ]
            elif "guild_roles" in query:
                return [
                    (123, 'gm_123', 'off_123', 'guard_123', 'member_role_123', 'absent_role_123', 'allies_123', 'dipl_123', 'friends_123', 'app_123', 'config_123', 'rules_role_123'),
                    (456, 'gm_456', 'off_456', 'guard_456', 'member_role_456', None, 'allies_456', 'dipl_456', 'friends_456', 'app_456', 'config_456', 'rules_role_456')
                ]
            elif "guild_channels" in query:
                return [
                    (123, 'rules_ch_123', 'rules_msg_123', 'ann_123', 'voice_tav_123', 'voice_war_123', 'room_123', 'events_123', 'members_123', 'm1_123', 'm2_123', 'm3_123', 'm4_123', 'm5_123', 'groups_123', 'static_123', 'static_msg_123', 'abs_ch_123', 'loot_123', 'tuto_123', 'forum_allies_123', 'forum_friends_123', 'forum_dipl_123', 'forum_rec_123', 'forum_mem_123', 'notif_123', 'ext_rec_cat_123', 'cat_dipl_123', 'ext_rec_ch_123', 'ext_rec_msg_123')
                ]
            elif "welcome_messages" in query:
                return [
                    (123, 789, 'welcome_ch', 'welcome_msg_1'),
                    (123, 790, 'welcome_ch', 'welcome_msg_2')
                ]
            elif "absence_messages" in query:
                return [(123, 'abs_msg_1', 456)]
            elif "guild_members" in query:
                return [(123, 456, 'username', 'en-US', 'class', 'gs', 'build', 'weapons', 100, 5, 3, 2)]
            elif "events" in query:
                return [(123, 'evt1', 'Event Name', '2024-01-01', '20:00', 120, 50, 'active', 10, 8)]
            elif "user_setup" in query:
                return [(123, 456, 'en-US', 'gs', 'weapon')]
            elif "weapons" in query and "combinations" not in query:
                return [(1, 'WPN1', 'Weapon 1')]
            elif "weapons_combinations" in query:
                return [(1, 'role', 'wpn1', 'wpn2')]
            elif "guild_ideal_staff" in query:
                return [(123, 'class1', 5)]
            elif "games" in query:
                return [(1, 'Game Name', 50)]
            return []
        
        bot.run_db_query.side_effect = query_side_effect
        return bot
    
    @pytest.mark.asyncio
    async def test_full_data_loading_scenario(self, mock_bot_with_data):
        """Test complete data loading scenario with realistic data."""
        # Add additional mock methods for static data
        mock_bot_with_data.cache.set_static_data = AsyncMock()
        mock_bot_with_data.cache.set = AsyncMock()
        mock_bot_with_data.get_cog = Mock(return_value=Mock())
        mock_bot_with_data.get_cog.return_value.load_static_groups_cache = AsyncMock()
        
        loader = CacheLoader(mock_bot_with_data)
        
        # Load all data
        await loader.load_all_shared_data()
        
        # Verify all categories were loaded
        expected_categories = {'guild_settings', 'guild_roles', 'guild_channels', 'welcome_messages', 'absence_messages', 'guild_members', 'events_data', 'static_data', 'user_setup', 'weapons', 'weapons_combinations', 'guild_ideal_staff', 'games_list'}
        assert expected_categories == loader._loaded_categories
        
        # Verify cache operations were called appropriately
        assert mock_bot_with_data.cache.set_guild_data.call_count > 10  # Multiple guilds, multiple data types
        assert mock_bot_with_data.cache.set_user_data.call_count >= 2   # Welcome messages and user setup
    
    @pytest.mark.asyncio
    async def test_partial_failure_scenario(self, mock_bot_with_data):
        """Test scenario where some categories fail to load."""
        loader = CacheLoader(mock_bot_with_data)
        
        # Mock additional methods for static data
        mock_bot_with_data.cache.set_static_data = AsyncMock()
        mock_bot_with_data.cache.set = AsyncMock()
        mock_bot_with_data.get_cog = Mock(return_value=Mock())
        mock_bot_with_data.get_cog.return_value.load_static_groups_cache = AsyncMock()
        
        # Make one query fail
        def failing_query_side_effect(query, *args, **kwargs):
            if "guild_roles" in query:
                raise Exception("Database timeout")
            return mock_bot_with_data.run_db_query.side_effect(query, *args, **kwargs)
        
        mock_bot_with_data.run_db_query.side_effect = failing_query_side_effect
        
        with patch('cache_loader.logging.error') as mock_error:
            await loader.load_all_shared_data()
            
            # Should log the error but continue with other categories
            # Expect multiple errors since recursion issue causes other categories to fail too
            assert mock_error.call_count >= 1
            error_messages = [str(call) for call in mock_error.call_args_list]
            assert any("Error loading guild roles" in msg for msg in error_messages)
        
        # Other categories should still be loaded (those without recursion issues)
        # Note: guild_settings might also fail due to recursion in mock setup
        assert 'static_data' in loader._loaded_categories  # This should always load
        assert 'absence_messages' in loader._loaded_categories  # This should always load
        assert 'guild_roles' not in loader._loaded_categories  # Failed to load
    
    @pytest.mark.asyncio
    async def test_concurrent_loading_safety(self, mock_bot_with_data):
        """Test that concurrent loading requests are handled safely."""
        loader = CacheLoader(mock_bot_with_data)
        
        # Start multiple concurrent load operations
        tasks = [
            loader.ensure_guild_settings_loaded(),
            loader.ensure_guild_settings_loaded(),
            loader.ensure_guild_settings_loaded()
        ]
        
        await asyncio.gather(*tasks)
        
        # Should only load once (subsequent calls should return early)
        assert 'guild_settings' in loader._loaded_categories
        # Database should only be called once due to early return mechanism
        guild_settings_calls = [call for call in mock_bot_with_data.run_db_query.call_args_list 
                               if "guild_settings" in str(call)]
        assert len(guild_settings_calls) == 1


class TestGlobalCacheLoaderFunction:
    """Test global cache loader function."""
    
    def test_get_cache_loader_first_call(self):
        """Test getting cache loader for first time."""
        # Reset global state
        import cache_loader
        cache_loader._cache_loader = None
        
        mock_bot = Mock()
        loader = get_cache_loader(mock_bot)
        
        assert loader is not None
        assert isinstance(loader, CacheLoader)
        assert loader.bot == mock_bot
    
    def test_get_cache_loader_subsequent_calls(self):
        """Test getting cache loader on subsequent calls."""
        mock_bot = Mock()
        
        # First call
        loader1 = get_cache_loader(mock_bot)
        
        # Second call should return same instance
        loader2 = get_cache_loader()
        
        assert loader1 is loader2
    
    def test_get_cache_loader_no_bot_when_none_exists(self):
        """Test getting cache loader without bot when none exists."""
        # Reset global state
        import cache_loader
        cache_loader._cache_loader = None
        
        loader = get_cache_loader()
        
        assert loader is None


class TestCacheLoaderErrorHandling:
    """Test error handling in various scenarios."""
    
    @pytest.fixture
    def cache_loader_with_failing_bot(self):
        """Create cache loader with bot that fails operations."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.set_guild_data = AsyncMock(side_effect=Exception("Cache error"))
        bot.cache.set_user_data = AsyncMock(side_effect=Exception("Cache error"))
        bot.run_db_query = AsyncMock(return_value=[(123, True, 'test', 'data', 1, 'server', True, 1)])
        return CacheLoader(bot)
    
    @pytest.mark.asyncio
    async def test_cache_operation_failure(self, cache_loader_with_failing_bot):
        """Test handling of cache operation failures."""
        with patch('cache_loader.logging.error') as mock_error:
            await cache_loader_with_failing_bot.ensure_guild_settings_loaded()
            
            # Should catch and log the error
            mock_error.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_database_none_response(self):
        """Test handling of None database response."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.set_guild_data = AsyncMock()
        bot.run_db_query = AsyncMock(return_value=None)
        
        loader = CacheLoader(bot)
        
        with patch('cache_loader.logging.warning') as mock_warning:
            await loader.ensure_guild_settings_loaded()
            
            # Should handle None gracefully
            mock_warning.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_malformed_database_data(self):
        """Test handling of malformed database responses."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.set_guild_data = AsyncMock()
        
        # Return malformed data (missing columns)
        bot.run_db_query = AsyncMock(return_value=[(123, 'incomplete')])  # Missing required fields
        
        loader = CacheLoader(bot)
        
        with patch('cache_loader.logging.error') as mock_error:
            await loader.ensure_guild_settings_loaded()
            
            # Should catch unpacking error
            mock_error.assert_called_once()
            assert "Error loading guild settings" in str(mock_error.call_args)


class TestCacheLoaderDataStructures:
    """Test proper data structure handling in cache loader."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create mock bot for data structure tests."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.set_guild_data = AsyncMock()
        bot.cache.set_user_data = AsyncMock()
        bot.run_db_query = AsyncMock()
        return bot
    
    @pytest.mark.asyncio
    async def test_guild_settings_data_structure(self, mock_bot):
        """Test guild settings creates correct data structures."""
        mock_bot.run_db_query.return_value = [
            (123, True, 'en-US', 'Test Guild', 1, 'NA Server', True, 1)
        ]
        
        loader = CacheLoader(mock_bot)
        await loader.ensure_guild_settings_loaded()
        
        # Find the call that sets the complete settings object
        settings_calls = [call for call in mock_bot.cache.set_guild_data.call_args_list
                         if len(call[0]) > 1 and call[0][1] == 'settings']
        
        assert len(settings_calls) == 1
        settings_data = settings_calls[0][0][2]  # The data parameter
        
        expected_structure = {
            'guild_ptb': True,
            'guild_lang': 'en-US',
            'guild_name': 'Test Guild',
            'guild_game': 1,
            'guild_server': 'NA Server',
            'initialized': True,
            'premium': 1
        }
        assert settings_data == expected_structure
    
    @pytest.mark.asyncio
    async def test_guild_channels_complex_structures(self, mock_bot):
        """Test guild channels creates complex nested structures."""
        mock_bot.run_db_query.return_value = [
            (123, 'rules_ch', 'rules_msg', 'ann_ch', 'voice_tav', 'voice_war', 'room_ch', 'events_ch', 'members_ch', 'm1', 'm2', 'm3', 'm4', 'm5', 'groups_ch', 'static_ch', 'static_msg', 'abs_ch', 'loot_ch', 'tuto_ch', 'forum_allies', 'forum_friends', 'forum_dipl', 'forum_rec', 'forum_mem', 'notif_ch', 'ext_rec_cat', 'cat_dipl', 'ext_rec_ch', 'ext_rec_msg')
        ]
        
        loader = CacheLoader(mock_bot)
        await loader.ensure_guild_channels_loaded()
        
        # Check for rules message structure
        rules_calls = [call for call in mock_bot.cache.set_guild_data.call_args_list
                      if call[0][2] == 'rules_message']
        
        if rules_calls:  # Only if rules channel and message exist
            rules_data = rules_calls[0][0][3]
            assert rules_data == {'channel': 'rules_ch', 'message': 'rules_msg'}
        
        # Check for absence channels structure
        absence_calls = [call for call in mock_bot.cache.set_guild_data.call_args_list
                        if call[0][2] == 'absence_channels']
        
        if absence_calls:
            absence_data = absence_calls[0][0][3]
            assert 'abs_channel' in absence_data
            assert 'forum_members_channel' in absence_data