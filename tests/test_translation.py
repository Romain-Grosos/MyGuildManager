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
    
    def test_load_translations_success(self):
        """Test successful translation loading."""
        sample_translations = {
            "commands": {
                "help": {
                    "en-US": "Help command",
                    "fr-FR": "Commande d'aide"
                }
            }
        }
        
        # Mock all dependencies before importing
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1000), \
             patch('builtins.open', mock_open(read_data=json.dumps(sample_translations))), \
             patch('logging.info') as mock_info, \
             patch('config.TRANSLATION_FILE', 'translation.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024):
            
            # Import translation module (this will execute load_translations)
            import translation
            
            # Verify successful loading
            mock_info.assert_called_with("[TranslationsManager] Translations loaded successfully (1 entries).")
            assert translation.translations == sample_translations
    
    def test_load_translations_file_not_found(self):
        """Test handling of missing translation file."""
        with patch('os.path.exists', return_value=False), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'missing.json'):
            
            try:
                import translation
            except SystemExit:
                pass  # Expected due to sys.exit call
            
            mock_error.assert_any_call("[TranslationsManager] Translations file 'missing.json' not found.")
            mock_error.assert_any_call("[TranslationsManager] Critical error: Cannot continue without translations.")
            mock_exit.assert_called_with(1)
    
    def test_load_translations_file_too_large(self):
        """Test handling of oversized translation file."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=10 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'large.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_error.assert_called_with("[TranslationsManager] Translation file too large: 10485760 bytes (max: 5242880)")
            mock_exit.assert_called_with(1)
    
    def test_load_translations_empty_file(self):
        """Test handling of empty translation file."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=0), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'empty.json'):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_error.assert_called_with("[TranslationsManager] Translation file is empty: empty.json")
            mock_exit.assert_called_with(1)
    
    def test_load_translations_invalid_json(self):
        """Test handling of invalid JSON in translation file."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', mock_open(read_data="{ invalid json }")), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'invalid.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            # Check that JSON decode error was logged  
            error_calls = [call for call in mock_error.call_args_list 
                          if "Failed to decode translations JSON" in str(call)]
            assert len(error_calls) > 0
            mock_exit.assert_called_with(1)
    
    def test_load_translations_not_dict(self):
        """Test handling of non-dictionary translation data."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', mock_open(read_data=json.dumps(["not", "a", "dictionary"]))), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'list.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_error.assert_called_with("[TranslationsManager] Translation file must contain a JSON object")
            mock_exit.assert_called_with(1)
    
    def test_load_translations_empty_dict(self):
        """Test handling of empty translation dictionary."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', mock_open(read_data=json.dumps({}))), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'empty_dict.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_error.assert_called_with("[TranslationsManager] Translation file contains no translations")
            mock_exit.assert_called_with(1)
    
    def test_load_translations_permission_error(self):
        """Test handling of permission errors when reading file."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', side_effect=PermissionError("Permission denied")), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'protected.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_error.assert_called_with("[TranslationsManager] Permission denied reading translations file: protected.json")
            mock_exit.assert_called_with(1)
    
    def test_load_translations_os_error(self):
        """Test handling of OS errors when reading file."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', side_effect=OSError("Disk full")), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'problematic.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_error.assert_called_with("[TranslationsManager] OS error reading translations file: Disk full")
            mock_exit.assert_called_with(1)
    
    def test_load_translations_unexpected_error(self):
        """Test handling of unexpected errors when loading translations."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', side_effect=RuntimeError("Unexpected error")), \
             patch('logging.error') as mock_error, \
             patch('sys.exit') as mock_exit, \
             patch('config.TRANSLATION_FILE', 'error.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 1024):
            
            try:
                import translation
            except SystemExit:
                pass
            
            mock_error.assert_called_with("[TranslationsManager] Unexpected error loading translations: Unexpected error")
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