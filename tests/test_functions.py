"""
Tests for functions.py - Translation system utilities and message handling.
"""

import pytest
from unittest.mock import Mock, patch
from functions import sanitize_kwargs, get_nested_value, get_user_message


class TestSanitizeKwargs:
    """Test sanitize_kwargs function for safe string formatting."""
    
    def test_sanitize_valid_kwargs(self):
        """Test sanitization of valid kwargs."""
        kwargs = {
            'username': 'TestUser',
            'count': 42,
            'ratio': 3.14,
            'active': True
        }
        
        result = sanitize_kwargs(**kwargs)
        
        assert result['username'] == 'TestUser'
        assert result['count'] == '42'
        assert result['ratio'] == '3.14'
        assert result['active'] == 'True'
    
    def test_sanitize_long_strings(self):
        """Test string truncation at 200 characters."""
        long_string = 'x' * 300
        kwargs = {'long_text': long_string}
        
        result = sanitize_kwargs(**kwargs)
        
        assert len(result['long_text']) == 200
        assert result['long_text'] == 'x' * 200
    
    def test_sanitize_complex_objects(self):
        """Test handling of complex objects (converted to type name)."""
        kwargs = {
            'dict_obj': {'key': 'value'},
            'list_obj': [1, 2, 3],
            'mock_obj': Mock()
        }
        
        result = sanitize_kwargs(**kwargs)
        
        assert result['dict_obj'] == 'dict'
        assert result['list_obj'] == 'list'
        assert result['mock_obj'] == 'Mock'
    
    def test_sanitize_invalid_keys(self):
        """Test filtering of invalid key names."""
        kwargs = {
            'valid_key': 'valid',
            '123invalid': 'invalid_start',
            'invalid-key': 'invalid_dash',
            'invalid key': 'invalid_space'
        }
        
        with patch('functions.logging.warning') as mock_warning:
            result = sanitize_kwargs(**kwargs)
            
            assert 'valid_key' in result
            assert '123invalid' not in result
            assert 'invalid-key' not in result
            assert 'invalid key' not in result
            assert mock_warning.call_count == 3


class TestGetNestedValue:
    """Test get_nested_value function for safe dictionary navigation."""
    
    def test_get_simple_nested_value(self):
        """Test getting simple nested values."""
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
        data = {'existing': 'value'}
        
        with patch('functions.logging.warning') as mock_warning:
            result = get_nested_value(data, ['missing', 'key'])
            
            assert result is None
            mock_warning.assert_called_once()
    
    def test_get_nested_value_depth_limit(self):
        """Test depth protection mechanism."""
        data = {'a': {'b': {'c': {'d': {'e': {'f': 'deep'}}}}}}
        deep_keys = ['a', 'b', 'c', 'd', 'e', 'f', 'too_deep']
        
        with patch('functions.logging.warning') as mock_warning:
            result = get_nested_value(data, deep_keys, max_depth=5)
            
            assert result is None
            mock_warning.assert_called_once()
            assert "depth exceeds limit" in str(mock_warning.call_args)
    
    def test_get_nested_value_wrong_structure(self):
        """Test handling of non-dict values in path."""
        data = {
            'level1': {
                'level2': 'string_value'  # Not a dict
            }
        }
        
        with patch('functions.logging.error') as mock_error:
            result = get_nested_value(data, ['level1', 'level2', 'level3'])
            
            assert result is None
            mock_error.assert_called_once()
            assert "Unexpected structure" in str(mock_error.call_args)


class TestGetUserMessage:
    """Test get_user_message function for localized message retrieval."""
    
    @pytest.fixture
    def sample_translations(self):
        """Sample translations data for testing."""
        return {
            'simple': {
                'message': {
                    'en-US': 'Hello World',
                    'fr-FR': 'Bonjour Monde'
                }
            },
            'with_params': {
                'greeting': {
                    'en-US': 'Hello {name}!',
                    'fr-FR': 'Bonjour {name}!'
                }
            },
            'fallback_test': {
                'partial': {
                    'fr-FR': 'Seulement français'
                }
            }
        }
    
    @pytest.fixture
    def mock_ctx(self):
        """Mock Discord context."""
        ctx = Mock()
        ctx.locale = 'en-US'
        return ctx
    
    def test_get_simple_message(self, sample_translations, mock_ctx):
        """Test getting simple localized message."""
        result = get_user_message(mock_ctx, sample_translations, 'simple.message')
        assert result == 'Hello World'
    
    def test_get_message_with_parameters(self, sample_translations, mock_ctx):
        """Test message formatting with parameters."""
        result = get_user_message(
            mock_ctx, 
            sample_translations, 
            'with_params.greeting',
            name='Alice'
        )
        assert result == 'Hello Alice!'
    
    def test_get_message_fallback_to_english(self, sample_translations):
        """Test fallback to en-US when locale not available."""
        ctx = Mock()
        ctx.locale = 'es-ES'  # Spanish not available
        
        result = get_user_message(ctx, sample_translations, 'simple.message')
        assert result == 'Hello World'  # Falls back to en-US
    
    def test_get_message_no_fallback(self, sample_translations):
        """Test handling when no fallback available."""
        ctx = Mock()
        ctx.locale = 'de-DE'
        
        with patch('functions.logging.warning') as mock_warning:
            result = get_user_message(ctx, sample_translations, 'fallback_test.partial')
            
            assert result == ''
            mock_warning.assert_called_once()
    
    def test_invalid_translations_dict(self, mock_ctx):
        """Test handling of invalid translations dictionary."""
        with patch('functions.logging.error') as mock_error:
            result = get_user_message(mock_ctx, None, 'test.key')
            
            assert result == ''
            mock_error.assert_called_once()
            assert "Invalid translations dictionary" in str(mock_error.call_args)
    
    def test_invalid_key_parameter(self, sample_translations, mock_ctx):
        """Test handling of invalid key parameter."""
        with patch('functions.logging.error') as mock_error:
            result = get_user_message(mock_ctx, sample_translations, None)
            
            assert result == ''
            mock_error.assert_called_once()
            assert "Invalid key parameter" in str(mock_error.call_args)
    
    def test_key_too_long(self, sample_translations, mock_ctx):
        """Test handling of overly long keys."""
        long_key = 'a' * 150
        
        with patch('functions.logging.warning') as mock_warning:
            result = get_user_message(mock_ctx, sample_translations, long_key)
            
            assert result == ''
            mock_warning.assert_called_once()
            assert "too long" in str(mock_warning.call_args)
    
    def test_invalid_key_format(self, sample_translations, mock_ctx):
        """Test handling of invalid key format."""
        with patch('functions.logging.error') as mock_error:
            result = get_user_message(mock_ctx, sample_translations, 'invalid-key!')
            
            assert result == ''
            mock_error.assert_called_once()
            assert "Invalid key format" in str(mock_error.call_args)
    
    def test_missing_placeholder(self, sample_translations, mock_ctx):
        """Test handling of missing placeholder in formatting."""
        with patch('functions.logging.error') as mock_error:
            result = get_user_message(
                mock_ctx,
                sample_translations,
                'with_params.greeting'  # Requires {name} parameter
                # Missing name parameter
            )
            
            assert result == 'Hello {name}!'  # Returns unformatted
            mock_error.assert_called_once()
    
    def test_format_string_error(self, sample_translations, mock_ctx):
        """Test handling of format string errors."""
        bad_translations = {
            'bad_format': {
                'message': {
                    'en-US': 'Hello {name:invalid_format}'
                }
            }
        }
        
        with patch('functions.logging.error') as mock_error:
            result = get_user_message(
                mock_ctx,
                bad_translations,
                'bad_format.message',
                name='Alice'
            )
            
            assert result == 'Hello {name:invalid_format}'  # Returns unformatted
            mock_error.assert_called_once()
    
    def test_no_context_defaults_to_english(self, sample_translations):
        """Test behavior when no context is provided."""
        result = get_user_message(None, sample_translations, 'simple.message')
        assert result == 'Hello World'  # Defaults to en-US
    
    def test_non_string_message_value(self, mock_ctx):
        """Test handling of non-string message values."""
        bad_translations = {
            'bad_message': {
                'value': {
                    'en-US': 123  # Not a string
                }
            }
        }
        
        with patch('functions.logging.error') as mock_error:
            result = get_user_message(mock_ctx, bad_translations, 'bad_message.value')
            
            assert result == ''
            mock_error.assert_called_once()
            assert "not a string" in str(mock_error.call_args)
    
    def test_non_dict_final_value(self, mock_ctx):
        """Test handling when final value is not a dictionary."""
        bad_translations = {
            'bad_structure': 'should_be_dict'
        }
        
        with patch('functions.logging.error') as mock_error:
            result = get_user_message(mock_ctx, bad_translations, 'bad_structure')
            
            assert result == ''
            mock_error.assert_called_once()
            assert "not a dictionary" in str(mock_error.call_args)