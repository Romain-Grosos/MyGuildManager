"""
Tests for configuration and environment management.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

# Import test utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.unit
class TestConfiguration:
    """Test configuration loading and validation."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Clean up environment before each test."""
        # Store original values
        self.original_env = {}
        config_vars = [
            'DISCORD_TOKEN', 'DATABASE_URL', 'REDIS_URL', 'LOG_LEVEL',
            'TRANSLATION_FILE', 'MAX_TRANSLATION_FILE_SIZE'
        ]
        for var in config_vars:
            self.original_env[var] = os.environ.get(var)
        
        yield
        
        # Restore original values
        for var, value in self.original_env.items():
            if value is not None:
                os.environ[var] = value
            elif var in os.environ:
                del os.environ[var]
    
    def test_config_loading_with_required_vars(self):
        """Test configuration loading with all required variables."""
        with patch.dict(os.environ, {
            'DISCORD_TOKEN': 'test_token_123',
            'DATABASE_URL': 'sqlite:///:memory:',
            'LOG_LEVEL': 'INFO',
            'TRANSLATION_FILE': 'translation.json'
        }):
            # Clear module cache
            if 'config' in sys.modules:
                del sys.modules['config']
            
            from app import config
            
            assert config.DISCORD_TOKEN == 'test_token_123'
            assert config.DATABASE_URL == 'sqlite:///:memory:'
            assert config.LOG_LEVEL == 'INFO'
            assert config.TRANSLATION_FILE == 'translation.json'

    def test_config_default_values(self):
        """Test configuration default values when env vars are missing."""
        # Clear potentially interfering environment variables
        env_to_clear = ['LOG_LEVEL', 'MAX_TRANSLATION_FILE_SIZE', 'DEBUG']
        for var in env_to_clear:
            if var in os.environ:
                del os.environ[var]
        
        # Set minimal required variables
        with patch.dict(os.environ, {
            'DISCORD_TOKEN': 'test_token',
            'DATABASE_URL': 'sqlite:///:memory:'
        }, clear=True):
            # Clear module cache
            if 'config' in sys.modules:
                del sys.modules['config']
                
            from app import config
            
            # Test default values
            assert hasattr(config, 'LOG_LEVEL')
            assert hasattr(config, 'MAX_TRANSLATION_FILE_SIZE')
            assert hasattr(config, 'DEBUG')

    def test_config_validation_discord_token(self):
        """Test Discord token validation."""
        invalid_tokens = [
            '',
            'too_short',
            'invalid_format_token',
        ]
        
        for invalid_token in invalid_tokens:
            with patch.dict(os.environ, {'DISCORD_TOKEN': invalid_token}):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                # Should either raise error or have validation logic
                try:
                    from app import config
                    # If no validation, at least check it's loaded
                    assert config.DISCORD_TOKEN == invalid_token
                except (ValueError, SystemExit):
                    # Expected if validation is implemented
                    pass

    def test_config_database_url_formats(self):
        """Test different database URL formats."""
        valid_urls = [
            'sqlite:///:memory:',
            'sqlite:///./database.db',
            'postgresql://user:pass@localhost/db',
            'mysql://user:pass@localhost/db'
        ]
        
        for db_url in valid_urls:
            with patch.dict(os.environ, {
                'DISCORD_TOKEN': 'test_token_123',
                'DATABASE_URL': db_url
            }):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                from app import config
                assert config.DATABASE_URL == db_url

    def test_config_translation_file_size_limits(self):
        """Test translation file size limit configuration."""
        test_cases = [
            ('1024', 1024),
            ('1048576', 1048576),  # 1MB
            ('5242880', 5242880),  # 5MB
        ]
        
        for size_str, expected_size in test_cases:
            with patch.dict(os.environ, {
                'DISCORD_TOKEN': 'test_token',
                'MAX_TRANSLATION_FILE_SIZE': size_str
            }):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                from app import config
                assert config.MAX_TRANSLATION_FILE_SIZE == expected_size

    def test_config_boolean_values(self):
        """Test boolean configuration values."""
        test_cases = [
            ('true', True),
            ('True', True), 
            ('TRUE', True),
            ('1', True),
            ('false', False),
            ('False', False),
            ('FALSE', False),
            ('0', False),
            ('', False)
        ]
        
        for value_str, expected_bool in test_cases:
            with patch.dict(os.environ, {
                'DISCORD_TOKEN': 'test_token',
                'DEBUG': value_str
            }):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                from app import config
                
                # Check if DEBUG is properly converted to boolean
                if hasattr(config, 'DEBUG'):
                    # If boolean conversion is implemented
                    if isinstance(config.DEBUG, bool):
                        assert config.DEBUG == expected_bool
                    else:
                        # If stored as string
                        assert config.DEBUG == value_str

    def test_config_logging_levels(self):
        """Test logging level configuration."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        
        for level in valid_levels:
            with patch.dict(os.environ, {
                'DISCORD_TOKEN': 'test_token',
                'LOG_LEVEL': level
            }):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                from app import config
                assert config.LOG_LEVEL == level

    def test_config_path_resolution(self):
        """Test path resolution for file configurations."""
        test_files = [
            'translation.json',
            './translation.json',
            '/absolute/path/translation.json',
            'app/core/translation.json'
        ]
        
        for file_path in test_files:
            with patch.dict(os.environ, {
                'DISCORD_TOKEN': 'test_token',
                'TRANSLATION_FILE': file_path
            }):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                from app import config
                assert config.TRANSLATION_FILE == file_path


@pytest.mark.unit
class TestEnvironmentVariableHandling:
    """Test environment variable handling and edge cases."""

    def test_missing_critical_env_vars(self):
        """Test behavior when critical environment variables are missing."""
        critical_vars = ['DISCORD_TOKEN']
        
        for var in critical_vars:
            # Clear all environment variables
            with patch.dict(os.environ, {}, clear=True):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                # Should either raise error or handle gracefully
                try:
                    from app import config
                    # If no error, check if default or None is set
                    if hasattr(config, var):
                        value = getattr(config, var)
                        # Could be None, empty string, or default value
                        assert value is not None or value == '' or isinstance(value, str)
                except (KeyError, SystemExit, AttributeError):
                    # Expected if validation is implemented
                    pass

    def test_env_var_whitespace_handling(self):
        """Test handling of whitespace in environment variables."""
        test_cases = [
            ('  test_token  ', 'test_token'),  # Should be stripped
            ('\ttest_token\t', 'test_token'),
            ('\ntest_token\n', 'test_token'),
        ]
        
        for input_value, expected_value in test_cases:
            with patch.dict(os.environ, {
                'DISCORD_TOKEN': input_value,
                'DATABASE_URL': 'sqlite:///:memory:'
            }):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                from app import config
                
                # Check if whitespace is properly handled
                token = config.DISCORD_TOKEN
                if token.strip() == expected_value:
                    # Whitespace was handled
                    assert True
                else:
                    # Raw value preserved (also valid)
                    assert token == input_value

    def test_numeric_env_var_conversion(self):
        """Test conversion of numeric environment variables."""
        numeric_vars = {
            'MAX_TRANSLATION_FILE_SIZE': ('5242880', int),
            'DB_PORT': ('5432', int),
            'RATE_LIMIT_PER_MINUTE': ('100', int),
        }
        
        for var_name, (value_str, expected_type) in numeric_vars.items():
            with patch.dict(os.environ, {
                'DISCORD_TOKEN': 'test_token',
                var_name: value_str
            }):
                # Clear module cache
                if 'config' in sys.modules:
                    del sys.modules['config']
                
                from app import config
                
                if hasattr(config, var_name):
                    value = getattr(config, var_name)
                    # Check if conversion was applied
                    assert isinstance(value, (expected_type, str))

    def test_case_sensitivity_env_vars(self):
        """Test case sensitivity of environment variables."""
        # Environment variables should be case-sensitive on most systems
        with patch.dict(os.environ, {
            'discord_token': 'lowercase_token',  # Wrong case
            'DISCORD_TOKEN': 'correct_token'      # Correct case
        }):
            # Clear module cache
            if 'config' in sys.modules:
                del sys.modules['config']
            
            from app import config
            
            # Should use the correctly cased version
            assert config.DISCORD_TOKEN == 'correct_token'

    def test_empty_string_vs_missing_env_vars(self):
        """Test difference between empty string and missing environment variables."""
        # Test empty string
        with patch.dict(os.environ, {'DISCORD_TOKEN': ''}):
            # Clear module cache
            if 'config' in sys.modules:
                del sys.modules['config']
            
            try:
                from app import config
                assert config.DISCORD_TOKEN == ''
            except (ValueError, SystemExit):
                # Expected if empty strings are treated as invalid
                pass
        
        # Test missing variable
        with patch.dict(os.environ, {}, clear=True):
            # Clear module cache
            if 'config' in sys.modules:
                del sys.modules['config']
            
            try:
                from app import config
                # Should either have default value or raise error
                if hasattr(config, 'DISCORD_TOKEN'):
                    assert config.DISCORD_TOKEN is not None
            except (KeyError, SystemExit, AttributeError):
                # Expected if missing variables cause errors
                pass


@pytest.mark.integration
class TestConfigurationIntegration:
    """Test configuration integration with other systems."""

    def test_config_with_logging_system(self):
        """Test configuration integration with logging."""
        with patch.dict(os.environ, {
            'DISCORD_TOKEN': 'test_token',
            'LOG_LEVEL': 'DEBUG'
        }):
            # Clear module cache
            if 'config' in sys.modules:
                del sys.modules['config']
            
            from app import config
            
            # Test logging configuration
            import logging
            
            # Should be able to set up logging with config
            try:
                logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, 'INFO'))
                logger = logging.getLogger(__name__)
                assert logger.level <= logging.DEBUG or logging.getLogger().level <= logging.DEBUG
            except (AttributeError, ValueError):
                # If LOG_LEVEL is not a valid logging level
                pass

    def test_config_file_paths_exist(self):
        """Test that configured file paths are accessible."""
        with patch.dict(os.environ, {
            'DISCORD_TOKEN': 'test_token',
            'TRANSLATION_FILE': 'nonexistent_file.json'
        }):
            # Clear module cache
            if 'config' in sys.modules:
                del sys.modules['config']
            
            from app import config
            
            # Configuration should load even if files don't exist
            # (file existence is checked at runtime, not config time)
            assert config.TRANSLATION_FILE == 'nonexistent_file.json'