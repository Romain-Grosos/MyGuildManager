"""
Tests for core.translation module - Translation system and loading.
"""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock

# Import test utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.core
@pytest.mark.translation
class TestTranslationLoading:
    """Test translation file loading and validation."""

    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Reset translation module state before each test."""
        # Clear any cached modules
        modules_to_clear = [name for name in sys.modules.keys() 
                           if name.startswith('core.translation')]
        for module in modules_to_clear:
            del sys.modules[module]

    def test_load_translations_success(self):
        """Test successful translation loading."""
        sample_translations = {
            "commands": {
                "help": {
                    "en-US": "Help command",
                    "fr-FR": "Commande d'aide"
                }
            },
            "errors": {
                "not_found": {
                    "en-US": "Not found",
                    "fr-FR": "Introuvable"
                }
            }
        }

        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=1024), \
             patch('builtins.open', mock_open(read_data=json.dumps(sample_translations))), \
             patch('config.TRANSLATION_FILE', 'translation.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.info') as mock_info:

            # Import and test the module
            from core import translation
            
            # Verify successful loading
            assert translation.translations == sample_translations
            mock_info.assert_called_with("[TranslationsManager] Translations loaded successfully (2 entries).")

    def test_load_translations_file_not_found(self):
        """Test handling of missing translation file."""
        with patch('os.path.exists', return_value=False), \
             patch('config.TRANSLATION_FILE', 'missing_file.json'), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call("[TranslationsManager] Translations file 'missing_file.json' not found.")

    def test_load_translations_file_too_large(self):
        """Test handling of oversized translation file."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=10 * 1024 * 1024), \
             patch('config.TRANSLATION_FILE', 'large_file.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call("[TranslationsManager] Translation file too large: 10485760 bytes (max: 5242880)")

    def test_load_translations_empty_file(self):
        """Test handling of empty translation file."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=0), \
             patch('config.TRANSLATION_FILE', 'empty_file.json'), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call("[TranslationsManager] Translation file is empty: empty_file.json")

    def test_load_translations_invalid_json(self):
        """Test handling of malformed JSON."""
        invalid_json = '{"invalid": json, missing quotes}'

        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', mock_open(read_data=invalid_json)), \
             patch('config.TRANSLATION_FILE', 'invalid.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        # Verify that JSON decode error was logged
        mock_error.assert_any_call(
            pytest.StringMatching(r".*Failed to decode translations JSON.*")
        )

    def test_load_translations_not_dict(self):
        """Test handling of non-dictionary JSON structure."""
        invalid_structure = '["this", "is", "not", "a", "dictionary"]'

        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', mock_open(read_data=invalid_structure)), \
             patch('config.TRANSLATION_FILE', 'invalid_structure.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call("[TranslationsManager] Translation file must contain a JSON object")

    def test_load_translations_empty_dict(self):
        """Test handling of empty dictionary."""
        empty_dict = '{}'

        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=2), \
             patch('builtins.open', mock_open(read_data=empty_dict)), \
             patch('config.TRANSLATION_FILE', 'empty_dict.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call("[TranslationsManager] Translation file contains no translations")

    def test_load_translations_permission_error(self):
        """Test handling of permission denied errors."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', side_effect=PermissionError("Access denied")), \
             patch('config.TRANSLATION_FILE', 'protected_file.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call("[TranslationsManager] Permission denied reading translations file: protected_file.json")

    def test_load_translations_os_error(self):
        """Test handling of OS errors."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', side_effect=OSError("Disk error")), \
             patch('config.TRANSLATION_FILE', 'corrupted_file.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call(
            pytest.StringMatching(r".*OS error reading translations file.*")
        )

    def test_load_translations_unexpected_error(self):
        """Test handling of unexpected errors."""
        with patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=100), \
             patch('builtins.open', side_effect=RuntimeError("Unexpected error")), \
             patch('config.TRANSLATION_FILE', 'error_file.json'), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 5 * 1024 * 1024), \
             patch('logging.error') as mock_error, \
             pytest.raises(SystemExit) as exc_info:

            from core import translation

        assert exc_info.value.code == 1
        mock_error.assert_any_call(
            pytest.StringMatching(r".*Unexpected error loading translations.*")
        )

@pytest.mark.core 
@pytest.mark.translation
@pytest.mark.integration
class TestTranslationIntegration:
    """Test translation system integration with real files."""

    def test_load_real_translation_file_structure(self):
        """Test loading with realistic translation file structure."""
        realistic_translations = {
            "commands": {
                "guild_init": {
                    "name": {"en-US": "guild-init", "fr-FR": "init-guilde"},
                    "description": {"en-US": "Initialize guild", "fr-FR": "Initialiser la guilde"}
                },
                "help": {
                    "name": {"en-US": "help", "fr-FR": "aide"},
                    "description": {"en-US": "Show help", "fr-FR": "Afficher l'aide"}
                }
            },
            "errors": {
                "permission_denied": {
                    "en-US": "Permission denied",
                    "fr-FR": "Permission refusée"
                },
                "user_not_found": {
                    "en-US": "User not found",
                    "fr-FR": "Utilisateur introuvable"
                }
            },
            "guild_init": {
                "success": {
                    "en-US": "Guild initialized successfully",
                    "fr-FR": "Guilde initialisée avec succès"
                }
            }
        }

        # Create a temporary file with the translations
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(realistic_translations, f, indent=2)
            temp_file_path = f.name

        try:
            with patch('config.TRANSLATION_FILE', temp_file_path), \
                 patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024), \
                 patch('logging.info') as mock_info:

                # Clear module cache
                modules_to_clear = [name for name in sys.modules.keys() 
                                   if name.startswith('core.translation')]
                for module in modules_to_clear:
                    del sys.modules[module]

                from core import translation
                
                # Verify structure
                assert translation.translations == realistic_translations
                assert "commands" in translation.translations
                assert "guild_init" in translation.translations["commands"]
                assert "en-US" in translation.translations["commands"]["guild_init"]["name"]
                
                mock_info.assert_called_with("[TranslationsManager] Translations loaded successfully (3 entries).")

        finally:
            # Clean up temporary file
            os.unlink(temp_file_path)