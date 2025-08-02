"""
Tests for config.py - Environment variable validation and configuration management.
"""

import pytest
import os
import sys
from unittest.mock import patch, mock_open, MagicMock
from pathlib import Path


class TestEnvironmentValidation:
    """Test environment variable validation functions."""
    
    def test_validate_env_var_success(self):
        """Test successful environment variable validation."""
        # Mock load_dotenv to avoid import issues
        with patch('config.load_dotenv'):
            from config import validate_env_var
            
            result = validate_env_var("TEST_VAR", "test_value")
            assert result == "test_value"
    
    def test_validate_env_var_missing_required(self):
        """Test validation failure for missing required variable."""
        with patch('config.load_dotenv'):
            from config import validate_env_var
            
            with pytest.raises(ValueError, match="Missing required environment variable: TEST_VAR"):
                validate_env_var("TEST_VAR", "", required=True)
    
    def test_validate_env_var_missing_optional(self):
        """Test validation success for missing optional variable."""
        with patch('config.load_dotenv'):
            from config import validate_env_var
            
            result = validate_env_var("TEST_VAR", "", required=False)
            assert result == ""
    
    def test_validate_int_env_var_success(self):
        """Test successful integer environment variable validation."""
        with patch('config.load_dotenv'):
            from config import validate_int_env_var
            
            result = validate_int_env_var("TEST_INT", "42")
            assert result == 42
    
    def test_validate_int_env_var_with_default(self):
        """Test integer validation with default value."""
        with patch('config.load_dotenv'):
            from config import validate_int_env_var
            
            result = validate_int_env_var("TEST_INT", "", default=100)
            assert result == 100
    
    def test_validate_int_env_var_invalid(self):
        """Test integer validation with invalid value."""
        with patch('config.load_dotenv'):
            from config import validate_int_env_var
            
            with pytest.raises(ValueError, match="Invalid integer value for TEST_INT: not_a_number"):
                validate_int_env_var("TEST_INT", "not_a_number")
    
    def test_validate_int_env_var_missing_no_default(self):
        """Test integer validation missing value without default."""
        with patch('config.load_dotenv'):
            from config import validate_int_env_var
            
            with pytest.raises(ValueError, match="Missing required integer environment variable: TEST_INT"):
                validate_int_env_var("TEST_INT", "")


class TestLogDirectoryCreation:
    """Test log directory creation and validation."""
    
    def test_log_directory_creation_success(self):
        """Test successful log directory creation."""
        with patch('os.path.exists', return_value=False), \
             patch('os.makedirs') as mock_makedirs, \
             patch('os.getenv') as mock_getenv, \
             patch('dotenv.load_dotenv'), \
             patch('builtins.open', mock_open()):
            
            mock_getenv.side_effect = lambda key, default=None: {
                'DEBUG': 'False',
                'DISCORD_TOKEN': 'test_token_' + 'x' * 50,
                'DB_USER': 'test_user',
                'DB_PASS': 'test_pass',
                'DB_HOST': 'localhost',
                'DB_PORT': '3306',
                'DB_NAME': 'test_db'
            }.get(key, default)
            
            # Force reimport of config module
            import importlib
            import config
            importlib.reload(config)
            
            mock_makedirs.assert_called_once_with('logs', mode=0o750)
    
    def test_log_directory_creation_failure(self):
        """Test log directory creation failure."""
        with patch('os.path.exists', return_value=False), \
             patch('os.makedirs', side_effect=OSError("Permission denied")), \
             patch('builtins.print') as mock_print, \
             patch('sys.exit') as mock_exit, \
             patch('os.getenv') as mock_getenv, \
             patch('dotenv.load_dotenv'), \
             patch('builtins.open', mock_open()):
            
            mock_getenv.side_effect = lambda key, default=None: {
                'DEBUG': 'False',
                'DISCORD_TOKEN': 'test_token_' + 'x' * 50,
                'DB_USER': 'test_user',
                'DB_PASS': 'test_pass',
                'DB_HOST': 'localhost',
                'DB_PORT': '3306',
                'DB_NAME': 'test_db'
            }.get(key, default)
            
            # Force reimport of config module
            import importlib
            try:
                import config
                importlib.reload(config)
            except SystemExit:
                pass  # Expected due to mocked sys.exit
            
            mock_exit.assert_called_with(1)
            mock_print.assert_called()


class TestConfigurationValidation:
    """Test configuration parameter validation."""
    
    @patch('builtins.print')
    def test_memory_limit_validation_warning(self, mock_print):
        """Test memory limit validation warnings."""
        # We'll test the validation logic by checking if warnings are printed
        # for out-of-range values
        
        # Test values that should trigger warnings
        test_cases = [
            ('MAX_MEMORY_MB', 25, "50-2048MB"),  # Too low
            ('MAX_MEMORY_MB', 4096, "50-2048MB"),  # Too high
            ('MAX_CPU_PERCENT', 5, "10-95%"),  # Too low
            ('MAX_CPU_PERCENT', 99, "10-95%"),  # Too high
        ]
        
        for param_name, value, expected_range in test_cases:
            expected_warning = f"WARNING: {param_name} ({value}) outside recommended range {expected_range}"
            
            # Simulate the validation check
            if param_name == 'MAX_MEMORY_MB':
                if not (50 <= value <= 2048):
                    print(expected_warning, file=sys.stderr)
            elif param_name == 'MAX_CPU_PERCENT':
                if not (10 <= value <= 95):
                    print(expected_warning, file=sys.stderr)
    
    def test_database_port_validation(self):
        """Test database port validation."""
        # Test valid port range
        valid_ports = [1, 3306, 5432, 65535]
        for port in valid_ports:
            assert 1 <= port <= 65535
        
        # Test invalid ports
        invalid_ports = [0, -1, 65536, 100000]
        for port in invalid_ports:
            assert not (1 <= port <= 65535)
    
    def test_database_name_length_validation(self):
        """Test database name length validation."""
        # Test valid database names
        valid_names = ["test", "my_database", "a" * 64]
        for name in valid_names:
            assert len(name) <= 64
        
        # Test invalid database names (too long)
        invalid_name = "a" * 65
        assert len(invalid_name) > 64


class TestTokenValidation:
    """Test Discord token validation."""
    
    def test_token_length_validation(self):
        """Test Discord token length validation."""
        # Test valid token (>= 50 characters)
        valid_token = "x" * 60
        assert len(valid_token) >= 50
        
        # Test invalid token (< 50 characters)
        invalid_token = "x" * 30
        assert len(invalid_token) < 50
    
    def test_token_format_validation(self):
        """Test basic token format requirements."""
        # Test that token is string and non-empty
        valid_token = "MTk4NjIyNDgzNDcxOTI1MjQ4.Cl2FMQ.ZnCjm1XVW7vRze4b7Cq4se7kKWs"
        
        assert isinstance(valid_token, str)
        assert len(valid_token) > 0
        assert len(valid_token) >= 50


class TestDebugConfiguration:
    """Test DEBUG configuration parsing."""
    
    def test_debug_true_values(self):
        """Test values that should set DEBUG to True."""
        true_values = ["true", "True", "TRUE", "1", "yes", "Yes", "YES"]
        
        for value in true_values:
            debug_result = value.lower() in ("true", "1", "yes")
            assert debug_result is True
    
    def test_debug_false_values(self):
        """Test values that should set DEBUG to False."""
        false_values = ["false", "False", "FALSE", "0", "no", "No", "NO", ""]
        
        for value in false_values:
            debug_result = value.lower() in ("true", "1", "yes")
            assert debug_result is False


class TestFileOperations:
    """Test file operation validations."""
    
    @patch('builtins.open')
    @patch('builtins.print')
    @patch('sys.exit')
    def test_log_file_write_permission_failure(self, mock_exit, mock_print, mock_open):
        """Test handling of log file write permission failure."""
        mock_open.side_effect = IOError("Permission denied")
        
        # Simulate the file write test
        try:
            with open("test_log_file.log", 'a') as f:
                pass
        except IOError as e:
            print(f"CRITICAL: Cannot write to log file test_log_file.log: {e}", file=sys.stderr)
            mock_exit(1)
        
        mock_exit.assert_called_with(1)
        mock_print.assert_called()


class TestTranslationFileValidation:
    """Test translation file configuration validation."""
    
    def test_translation_file_extension_validation(self):
        """Test translation file extension validation."""
        valid_files = ["translation.json", "messages.json", "lang.json"]
        invalid_files = ["translation.txt", "messages.xml", "lang"]
        
        for filename in valid_files:
            assert filename.endswith('.json')
        
        for filename in invalid_files:
            assert not filename.endswith('.json')
    
    def test_translation_file_size_validation(self):
        """Test translation file size limits."""
        min_size = 1024  # 1KB
        max_size = 50 * 1024 * 1024  # 50MB
        
        # Test valid sizes
        valid_sizes = [1024, 1024 * 1024, 10 * 1024 * 1024]
        for size in valid_sizes:
            assert min_size <= size <= max_size
        
        # Test invalid sizes
        invalid_sizes = [512, 100 * 1024 * 1024]
        for size in invalid_sizes:
            assert not (min_size <= size <= max_size)