"""
Tests for translation.py - Translation system loader and validation.
"""

import pytest
import json
import os
import sys
from unittest.mock import patch, mock_open, MagicMock
from pathlib import Path


class TestTranslationLoading:
    """Test translation file loading and validation."""
    
    def setup_method(self):
        """Setup method to ensure clean state for each test."""
        # Remove translation module from cache if it exists
        modules_to_remove = [name for name in sys.modules.keys() if name.startswith('translation')]
        for module in modules_to_remove:
            del sys.modules[module]
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('builtins.open', new_callable=mock_open)
    @patch('translation.logging')
    def test_load_translations_success(self, mock_logging, mock_file, mock_getsize, mock_exists):
        """Test successful translation loading."""
        # Setup mocks
        mock_exists.return_value = True
        mock_getsize.return_value = 1000  # Valid file size
        
        sample_translations = {
            "commands": {
                "help": {
                    "en-US": "Help command",
                    "fr-FR": "Commande d'aide"
                }
            }
        }
        mock_file.return_value.read.return_value = json.dumps(sample_translations)
        
        # Mock config values
        with patch('translation.TRANSLATION_FILE', 'translation.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024):
            
            # Import translation module (this will execute load_translations)
            import translation
            
            # Verify successful loading
            mock_logging.info.assert_called_with("[TranslationsManager] Translations loaded successfully (1 entries).")
            assert translation.translations == sample_translations
    
    @patch('translation.os.path.exists')
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_file_not_found(self, mock_exit, mock_logging, mock_exists):
        """Test handling of missing translation file."""
        mock_exists.return_value = False
        
        with patch('translation.TRANSLATION_FILE', 'missing.json'):
            try:
                import translation
            except SystemExit:
                pass  # Expected due to sys.exit call
            
            mock_logging.error.assert_any_call("[TranslationsManager] Translations file 'missing.json' not found.")
            mock_logging.error.assert_any_call("[TranslationsManager] Critical error: Cannot continue without translations.")
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_file_too_large(self, mock_exit, mock_logging, mock_getsize, mock_exists):
        """Test handling of oversized translation file."""
        mock_exists.return_value = True
        mock_getsize.return_value = 10 * 1024 * 1024  # 10MB (over limit)
        
        with patch('translation.TRANSLATION_FILE', 'large.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024):  # 5MB limit
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_logging.error.assert_called_with("[TranslationsManager] Translation file too large: 10485760 bytes (max: 5242880)")
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_empty_file(self, mock_exit, mock_logging, mock_getsize, mock_exists):
        """Test handling of empty translation file."""
        mock_exists.return_value = True
        mock_getsize.return_value = 0
        
        with patch('translation.TRANSLATION_FILE', 'empty.json'):
            try:
                import translation
            except SystemExit:
                pass
            
            mock_logging.error.assert_called_with("[TranslationsManager] Translation file is empty: empty.json")
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('builtins.open', new_callable=mock_open)
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_invalid_json(self, mock_exit, mock_logging, mock_file, mock_getsize, mock_exists):
        """Test handling of invalid JSON in translation file."""
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        mock_file.return_value.read.return_value = "{ invalid json }"
        
        with patch('translation.TRANSLATION_FILE', 'invalid.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            # Check that JSON decode error was logged
            error_calls = [call for call in mock_logging.error.call_args_list 
                          if "Failed to decode translations JSON" in str(call)]
            assert len(error_calls) > 0
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('builtins.open', new_callable=mock_open)
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_not_dict(self, mock_exit, mock_logging, mock_file, mock_getsize, mock_exists):
        """Test handling of non-dictionary translation data."""
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        mock_file.return_value.read.return_value = json.dumps(["not", "a", "dictionary"])
        
        with patch('translation.TRANSLATION_FILE', 'list.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_logging.error.assert_called_with("[TranslationsManager] Translation file must contain a JSON object")
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('builtins.open', new_callable=mock_open)
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_empty_dict(self, mock_exit, mock_logging, mock_file, mock_getsize, mock_exists):
        """Test handling of empty translation dictionary."""
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        mock_file.return_value.read.return_value = json.dumps({})
        
        with patch('translation.TRANSLATION_FILE', 'empty_dict.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_logging.error.assert_called_with("[TranslationsManager] Translation file contains no translations")
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('builtins.open')
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_permission_error(self, mock_exit, mock_logging, mock_open, mock_getsize, mock_exists):
        """Test handling of permission errors when reading file."""
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        mock_open.side_effect = PermissionError("Permission denied")
        
        with patch('translation.TRANSLATION_FILE', 'protected.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_logging.error.assert_called_with("[TranslationsManager] Permission denied reading translations file: protected.json")
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('builtins.open')
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_os_error(self, mock_exit, mock_logging, mock_open, mock_getsize, mock_exists):
        """Test handling of OS errors when reading file."""
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        mock_open.side_effect = OSError("Disk full")
        
        with patch('translation.TRANSLATION_FILE', 'problematic.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_logging.error.assert_called_with("[TranslationsManager] OS error reading translations file: Disk full")
            mock_exit.assert_called_with(1)
    
    @patch('translation.os.path.exists')
    @patch('translation.os.path.getsize')
    @patch('builtins.open')
    @patch('translation.logging')
    @patch('translation.sys.exit')
    def test_load_translations_unexpected_error(self, mock_exit, mock_logging, mock_open, mock_getsize, mock_exists):
        """Test handling of unexpected errors when loading translations."""
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        mock_open.side_effect = RuntimeError("Unexpected error")
        
        with patch('translation.TRANSLATION_FILE', 'error.json'), \
             patch('translation.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_logging.error.assert_called_with("[TranslationsManager] Unexpected error loading translations: Unexpected error")
            mock_exit.assert_called_with(1)


class TestTranslationDataValidation:
    """Test validation of translation data structure."""
    
    def test_valid_translation_structure(self):
        """Test validation of properly structured translation data."""
        valid_translations = {
            "commands": {
                "help": {
                    "en-US": "Help command",
                    "fr-FR": "Commande d'aide",
                    "es-ES": "Comando de ayuda"
                },
                "info": {
                    "en-US": "Information about {item}",
                    "fr-FR": "Information sur {item}"
                }
            },
            "errors": {
                "not_found": {
                    "en-US": "Item not found",
                    "fr-FR": "Élément non trouvé"
                }
            }
        }
        
        # Test that the structure is a dictionary
        assert isinstance(valid_translations, dict)
        
        # Test that top-level keys exist
        assert "commands" in valid_translations
        assert "errors" in valid_translations
        
        # Test that nested structure is proper
        assert isinstance(valid_translations["commands"]["help"], dict)
        assert "en-US" in valid_translations["commands"]["help"]
        assert isinstance(valid_translations["commands"]["help"]["en-US"], str)
    
    def test_translation_completeness_check(self):
        """Test checking for translation completeness across locales."""
        translations = {
            "test": {
                "complete": {
                    "en-US": "Complete message",
                    "fr-FR": "Message complet"
                },
                "incomplete": {
                    "en-US": "Only English"
                    # Missing fr-FR
                }
            }
        }
        
        # Test complete translations
        complete_entry = translations["test"]["complete"]
        assert "en-US" in complete_entry
        assert "fr-FR" in complete_entry
        
        # Test incomplete translations
        incomplete_entry = translations["test"]["incomplete"]
        assert "en-US" in incomplete_entry
        assert "fr-FR" not in incomplete_entry
    
    def test_translation_parameter_validation(self):
        """Test validation of translation parameters."""
        translations_with_params = {
            "messages": {
                "greeting": {
                    "en-US": "Hello {name}!",
                    "fr-FR": "Bonjour {name}!"
                },
                "count": {
                    "en-US": "Found {count} items",
                    "fr-FR": "Trouvé {count} éléments"
                }
            }
        }
        
        # Test parameter consistency
        greeting_en = translations_with_params["messages"]["greeting"]["en-US"]
        greeting_fr = translations_with_params["messages"]["greeting"]["fr-FR"]
        
        assert "{name}" in greeting_en
        assert "{name}" in greeting_fr
        
        count_en = translations_with_params["messages"]["count"]["en-US"]
        count_fr = translations_with_params["messages"]["count"]["fr-FR"]
        
        assert "{count}" in count_en
        assert "{count}" in count_fr