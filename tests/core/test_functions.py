"""
Tests for core.functions module - Translation utilities and locale management.
"""

import pytest
import logging
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

# Import test utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.core
@pytest.mark.translation
class TestSanitizeKwargs:
    """Test the sanitize_kwargs function."""

    def test_sanitize_valid_kwargs(self):
        """Test sanitization of valid keyword arguments."""
        from core.functions import sanitize_kwargs
        
        kwargs = {
            'username': 'john_doe',
            'level': 42,
            'score': 99.5,
            'is_admin': True
        }
        
        result = sanitize_kwargs(**kwargs)
        
        assert result == {
            'username': 'john_doe',
            'level': '42',
            'score': '99.5', 
            'is_admin': 'True'
        }

    def test_sanitize_long_string_truncation(self):
        """Test truncation of long string values."""
        from core.functions import sanitize_kwargs
        
        long_string = 'x' * 300
        kwargs = {'long_value': long_string}
        
        result = sanitize_kwargs(**kwargs)
        
        assert len(result['long_value']) == 200
        assert result['long_value'] == 'x' * 200

    def test_sanitize_invalid_key_names(self):
        """Test filtering of invalid key names."""
        from core.functions import sanitize_kwargs
        
        with patch('logging.warning') as mock_warning:
            kwargs = {
                'valid_key': 'value',
                '123invalid': 'should_be_filtered',
                'key-with-dash': 'should_be_filtered',
                'key with space': 'should_be_filtered',
                '': 'empty_key'
            }
            
            result = sanitize_kwargs(**kwargs)
            
            # Only valid key should remain
            assert result == {'valid_key': 'value'}
            
            # Check that warnings were logged for invalid keys
            assert mock_warning.call_count == 4

    def test_sanitize_complex_objects(self):
        """Test handling of complex objects (lists, dicts, custom objects)."""
        from core.functions import sanitize_kwargs
        
        class CustomObject:
            pass
        
        kwargs = {
            'list_value': [1, 2, 3],
            'dict_value': {'key': 'value'},
            'custom_obj': CustomObject()
        }
        
        result = sanitize_kwargs(**kwargs)
        
        assert result['list_value'] == 'list'
        assert result['dict_value'] == 'dict'
        assert result['custom_obj'] == 'CustomObject'

    def test_sanitize_none_and_special_values(self):
        """Test handling of None and other special values."""
        from core.functions import sanitize_kwargs
        
        kwargs = {
            'none_value': None,
            'zero_value': 0,
            'empty_string': '',
            'false_value': False
        }
        
        result = sanitize_kwargs(**kwargs)
        
        assert result == {
            'none_value': 'NoneType',
            'zero_value': '0',
            'empty_string': '',
            'false_value': 'False'
        }


@pytest.mark.core
@pytest.mark.translation  
class TestGetNestedValue:
    """Test the get_nested_value function."""

    def test_get_nested_value_success(self):
        """Test successful nested value retrieval."""
        from core.functions import get_nested_value
        
        data = {
            'level1': {
                'level2': {
                    'level3': 'target_value'
                }
            }
        }
        
        result = get_nested_value(data, ['level1', 'level2', 'level3'])
        assert result == 'target_value'

    def test_get_nested_value_not_found(self):
        """Test handling of missing keys."""
        from core.functions import get_nested_value
        
        data = {
            'level1': {
                'level2': {}
            }
        }
        
        with patch('logging.warning') as mock_warning:
            result = get_nested_value(data, ['level1', 'level2', 'missing'])
            
        assert result is None
        mock_warning.assert_called_once()

    def test_get_nested_value_depth_limit(self):
        """Test depth protection mechanism."""
        from core.functions import get_nested_value
        
        data = {'a': {'b': {'c': {'d': {'e': {'f': 'deep_value'}}}}}}
        keys = ['a', 'b', 'c', 'd', 'e', 'f']  # 6 levels
        
        with patch('logging.warning') as mock_warning:
            result = get_nested_value(data, keys, max_depth=5)
            
        assert result is None
        mock_warning.assert_called_with("[Translation] Key depth exceeds limit: a.b.c.d.e.f")

    def test_get_nested_value_wrong_structure(self):
        """Test handling of wrong data structure."""
        from core.functions import get_nested_value
        
        data = {
            'level1': 'not_a_dict'
        }
        
        with patch('logging.error') as mock_error:
            result = get_nested_value(data, ['level1', 'level2'])
            
        assert result is None
        mock_error.assert_called_once()

    def test_get_nested_value_empty_keys(self):
        """Test handling of empty keys list."""
        from core.functions import get_nested_value
        
        data = {'key': 'value'}
        result = get_nested_value(data, [])
        
        assert result == data


@pytest.mark.core
@pytest.mark.translation
@pytest.mark.asyncio
class TestGetEffectiveLocale:
    """Test the get_effective_locale function."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot with cache system."""
        bot = Mock()
        bot.cache_loader = AsyncMock()
        bot.cache_loader.ensure_guild_settings_loaded = AsyncMock()
        bot.cache_loader.ensure_user_setup_loaded = AsyncMock()
        
        bot.cache = Mock()
        bot.cache.get_guild_member_data = AsyncMock()
        bot.cache.get_user_setup_data = AsyncMock()
        bot.cache.get_guild_data = AsyncMock()
        
        bot.translations = {
            'global': {
                'supported_locales': ['en-US', 'fr-FR', 'es-ES', 'de-DE']
            }
        }
        
        return bot

    async def test_get_effective_locale_member_preference(self, mock_bot):
        """Test locale resolution with member preference."""
        from core.functions import get_effective_locale
        
        # Mock member data with language preference
        mock_bot.cache.get_guild_member_data.return_value = {
            'language': 'fr-FR'
        }
        
        result = await get_effective_locale(mock_bot, 123456789, 987654321)
        
        assert result == 'fr-FR'
        mock_bot.cache.get_guild_member_data.assert_called_once_with(123456789, 987654321)

    async def test_get_effective_locale_en_conversion(self, mock_bot):
        """Test conversion of 'en' to 'en-US'."""
        from core.functions import get_effective_locale
        
        mock_bot.cache.get_guild_member_data.return_value = {
            'language': 'en'
        }
        
        result = await get_effective_locale(mock_bot, 123456789, 987654321)
        
        assert result == 'en-US'

    async def test_get_effective_locale_user_setup_fallback(self, mock_bot):
        """Test fallback to user setup locale."""
        from core.functions import get_effective_locale
        
        # No member language
        mock_bot.cache.get_guild_member_data.return_value = None
        
        # User setup with locale
        mock_bot.cache.get_user_setup_data.return_value = {
            'locale': 'es-ES'
        }
        
        result = await get_effective_locale(mock_bot, 123456789, 987654321)
        
        assert result == 'es-ES'
        mock_bot.cache.get_user_setup_data.assert_called_once_with(123456789, 987654321)

    async def test_get_effective_locale_guild_fallback(self, mock_bot):
        """Test fallback to guild language."""
        from core.functions import get_effective_locale
        
        # No member or user preference
        mock_bot.cache.get_guild_member_data.return_value = None
        mock_bot.cache.get_user_setup_data.return_value = None
        
        # Guild has default language
        mock_bot.cache.get_guild_data.return_value = 'de-DE'
        
        result = await get_effective_locale(mock_bot, 123456789, 987654321)
        
        assert result == 'de-DE'
        mock_bot.cache.get_guild_data.assert_called_once_with(123456789, 'guild_lang')

    async def test_get_effective_locale_system_fallback(self, mock_bot):
        """Test final fallback to en-US."""
        from core.functions import get_effective_locale
        
        # No preferences at any level
        mock_bot.cache.get_guild_member_data.return_value = None
        mock_bot.cache.get_user_setup_data.return_value = None
        mock_bot.cache.get_guild_data.return_value = None
        
        result = await get_effective_locale(mock_bot, 123456789, 987654321)
        
        assert result == 'en-US'

    async def test_get_effective_locale_error_handling(self, mock_bot):
        """Test error handling in locale resolution."""
        from core.functions import get_effective_locale
        
        # Simulate cache error
        mock_bot.cache_loader.ensure_guild_settings_loaded.side_effect = Exception("Cache error")
        
        with patch('logging.error') as mock_error:
            result = await get_effective_locale(mock_bot, 123456789, 987654321)
            
        assert result == 'en-US'  # Fallback
        mock_error.assert_called_once()


@pytest.mark.core
@pytest.mark.translation
@pytest.mark.asyncio
class TestGetUserMessage:
    """Test the get_user_message function."""

    @pytest.fixture
    def sample_translations(self):
        """Sample translation data for testing."""
        return {
            'commands': {
                'help': {
                    'en-US': 'Help message',
                    'fr-FR': 'Message d\'aide'
                },
                'greet': {
                    'en-US': 'Hello {username}!',
                    'fr-FR': 'Bonjour {username}!'
                }
            },
            'errors': {
                'not_found': {
                    'en-US': 'Not found',
                    'fr-FR': 'Introuvable'
                }
            }
        }

    @pytest.fixture
    def mock_ctx(self):
        """Create a mock Discord context."""
        ctx = Mock()
        ctx.locale = 'en-US'
        ctx.bot = Mock()
        ctx.guild = Mock()
        ctx.guild.id = 123456789
        ctx.author = Mock() 
        ctx.author.id = 987654321
        return ctx

    async def test_get_user_message_success(self, sample_translations, mock_ctx):
        """Test successful message retrieval."""
        from core.functions import get_user_message
        
        result = await get_user_message(mock_ctx, sample_translations, 'commands.help')
        
        assert result == 'Help message'

    async def test_get_user_message_with_formatting(self, sample_translations, mock_ctx):
        """Test message with parameter formatting.""" 
        from core.functions import get_user_message
        
        result = await get_user_message(
            mock_ctx, sample_translations, 'commands.greet', username='Alice'
        )
        
        assert result == 'Hello Alice!'

    async def test_get_user_message_locale_fallback(self, sample_translations, mock_ctx):
        """Test fallback to en-US when preferred locale not available."""
        from core.functions import get_user_message
        
        # Set unsupported locale
        mock_ctx.locale = 'ja-JP'
        
        result = await get_user_message(mock_ctx, sample_translations, 'commands.help')
        
        assert result == 'Help message'  # Falls back to en-US

    async def test_get_user_message_invalid_translations(self, mock_ctx):
        """Test handling of invalid translations parameter."""
        from core.functions import get_user_message
        
        with patch('logging.error') as mock_error:
            result = await get_user_message(mock_ctx, None, 'commands.help')
            
        assert result == ""
        mock_error.assert_called_with("[Translation] Invalid translations dictionary")

    async def test_get_user_message_invalid_key(self, sample_translations, mock_ctx):
        """Test handling of invalid key parameter."""
        from core.functions import get_user_message
        
        with patch('logging.error') as mock_error:
            # Test with None key
            result1 = await get_user_message(mock_ctx, sample_translations, None)
            # Test with non-string key
            result2 = await get_user_message(mock_ctx, sample_translations, 123)
            
        assert result1 == ""
        assert result2 == ""
        assert mock_error.call_count == 2

    async def test_get_user_message_key_too_long(self, sample_translations, mock_ctx):
        """Test handling of excessively long keys."""
        from core.functions import get_user_message
        
        long_key = 'a' * 150  # Exceeds 100 char limit
        
        with patch('logging.warning') as mock_warning:
            result = await get_user_message(mock_ctx, sample_translations, long_key)
            
        assert result == ""
        mock_warning.assert_called_once()

    async def test_get_user_message_invalid_key_format(self, sample_translations, mock_ctx):
        """Test handling of invalid key format."""
        from core.functions import get_user_message
        
        invalid_keys = [
            'invalid-key-with-dash',
            'invalid key with spaces',
            'invalid@key!with#symbols'
        ]
        
        with patch('logging.error') as mock_error:
            for key in invalid_keys:
                result = await get_user_message(mock_ctx, sample_translations, key)
                assert result == ""
                
        assert mock_error.call_count == len(invalid_keys)

    async def test_get_user_message_missing_key(self, sample_translations, mock_ctx):
        """Test handling of missing translation key.""" 
        from core.functions import get_user_message
        
        result = await get_user_message(mock_ctx, sample_translations, 'nonexistent.key')
        
        assert result == ""

    async def test_get_user_message_formatting_error(self, sample_translations, mock_ctx):
        """Test handling of string formatting errors."""
        from core.functions import get_user_message
        
        with patch('logging.error') as mock_error:
            # Missing required parameter
            result = await get_user_message(mock_ctx, sample_translations, 'commands.greet')
            
        # Should return unformatted message on error
        assert result == 'Hello {username}!'
        mock_error.assert_called_once()

    async def test_get_user_message_no_context(self, sample_translations):
        """Test message retrieval without context."""
        from core.functions import get_user_message
        
        result = await get_user_message(None, sample_translations, 'commands.help')
        
        assert result == 'Help message'

    async def test_get_user_message_effective_locale_integration(self, sample_translations):
        """Test integration with effective locale system."""
        from core.functions import get_user_message
        
        # Create context with full bot integration
        ctx = Mock()
        ctx.bot = Mock()
        ctx.guild = Mock()
        ctx.guild.id = 123456789
        ctx.author = Mock()
        ctx.author.id = 987654321
        
        with patch('core.functions.get_effective_locale', return_value='fr-FR') as mock_locale:
            result = await get_user_message(ctx, sample_translations, 'commands.help')
            
        assert result == 'Message d\'aide'  # French version
        mock_locale.assert_called_once_with(ctx.bot, ctx.guild.id, ctx.author.id)


@pytest.mark.core
@pytest.mark.translation
@pytest.mark.asyncio
class TestGetGuildMessage:
    """Test the get_guild_message function."""

    @pytest.fixture
    def sample_translations(self):
        """Sample translation data for testing."""
        return {
            'guild': {
                'welcome': {
                    'en-US': 'Welcome to the server!',
                    'fr-FR': 'Bienvenue sur le serveur!'
                },
                'event_notification': {
                    'en-US': 'Event {event_name} starts in {time} minutes',
                    'fr-FR': 'L\'événement {event_name} commence dans {time} minutes'
                }
            }
        }

    @pytest.fixture  
    def mock_bot(self):
        """Create a mock bot for guild message testing."""
        bot = Mock()
        bot.cache = Mock()
        bot.cache.get_guild_data = AsyncMock()
        return bot

    async def test_get_guild_message_success(self, sample_translations, mock_bot):
        """Test successful guild message retrieval."""
        from core.functions import get_guild_message
        
        # Mock guild language
        mock_bot.cache.get_guild_data.return_value = 'en-US'
        
        result = await get_guild_message(
            mock_bot, 123456789, sample_translations, 'guild.welcome'
        )
        
        assert result == 'Welcome to the server!'
        mock_bot.cache.get_guild_data.assert_called_once()

    async def test_get_guild_message_with_formatting(self, sample_translations, mock_bot):
        """Test guild message with parameter formatting."""
        from core.functions import get_guild_message
        
        mock_bot.cache.get_guild_data.return_value = 'fr-FR'
        
        result = await get_guild_message(
            mock_bot, 123456789, sample_translations, 'guild.event_notification',
            event_name='Raid Night', time=30
        )
        
        assert result == 'L\'événement Raid Night commence dans 30 minutes'

    async def test_get_guild_message_cache_error(self, sample_translations, mock_bot):
        """Test handling of cache errors in guild message retrieval."""
        from core.functions import get_guild_message
        
        # Simulate cache error
        mock_bot.cache.get_guild_data.side_effect = Exception("Cache error")
        
        with patch('logging.error'):
            result = await get_guild_message(
                mock_bot, 123456789, sample_translations, 'guild.welcome'
            )
            
        # Should fallback to en-US
        assert result == 'Welcome to the server!'

    async def test_get_guild_message_invalid_params(self, sample_translations):
        """Test guild message with invalid parameters."""
        from core.functions import get_guild_message
        
        with patch('logging.error') as mock_error:
            # Invalid bot parameter
            result1 = await get_guild_message(None, 123456789, sample_translations, 'guild.welcome')
            # Invalid guild_id
            result2 = await get_guild_message(Mock(), None, sample_translations, 'guild.welcome')
            
        assert result1 == ""
        assert result2 == ""
        assert mock_error.call_count == 2