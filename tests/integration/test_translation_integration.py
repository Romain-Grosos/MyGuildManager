"""
Integration tests for the translation system with other bot components.
"""

import json
import pytest
import tempfile
import os
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

# Import test utilities
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.integration
@pytest.mark.translation
@pytest.mark.asyncio
class TestTranslationSystemIntegration:
    """Test integration of translation system with bot components."""

    @pytest.fixture
    def sample_translations_file(self):
        """Create a temporary translations file."""
        translations = {
            "commands": {
                "guild_init": {
                    "name": {"en-US": "guild-init", "fr-FR": "init-guilde"},
                    "description": {"en-US": "Initialize guild", "fr-FR": "Initialiser la guilde"}
                }
            },
            "guild_members": {
                "gs": {
                    "name": {"en-US": "gs", "fr-FR": "gs"},
                    "description": {"en-US": "Update gear score", "fr-FR": "Mettre à jour le score d'équipement"},
                    "success": {"en-US": "Gear score updated to {value}", "fr-FR": "Score d'équipement mis à jour à {value}"},
                    "error_invalid": {"en-US": "Invalid gear score", "fr-FR": "Score d'équipement invalide"}
                }
            },
            "absence": {
                "marked_absent": {"en-US": "Member {username} marked absent", "fr-FR": "Membre {username} marqué absent"},
                "returned": {"en-US": "Member {username} returned", "fr-FR": "Membre {username} de retour"}
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(translations, f, indent=2)
            temp_file_path = f.name
            
        yield temp_file_path
        
        # Cleanup
        os.unlink(temp_file_path)

    @pytest.fixture
    def mock_bot_with_cache(self):
        """Create a bot mock with cache system for locale resolution."""
        bot = Mock()
        
        # Cache system
        bot.cache = Mock()
        bot.cache.get_guild_member_data = AsyncMock()
        bot.cache.get_user_setup_data = AsyncMock()
        bot.cache.get_guild_data = AsyncMock()
        
        # Cache loader
        bot.cache_loader = Mock()
        bot.cache_loader.ensure_guild_settings_loaded = AsyncMock()
        bot.cache_loader.ensure_user_setup_loaded = AsyncMock()
        
        # Translation data
        bot.translations = {
            'global': {
                'supported_locales': ['en-US', 'fr-FR', 'es-ES']
            }
        }
        
        return bot

    @pytest.fixture
    def mock_ctx_with_bot(self, mock_bot_with_cache):
        """Create a context with bot integration."""
        ctx = Mock()
        ctx.bot = mock_bot_with_cache
        ctx.guild = Mock()
        ctx.guild.id = 123456789
        ctx.author = Mock()
        ctx.author.id = 987654321
        ctx.locale = 'en-US'
        return ctx

    async def test_translation_loading_and_usage_integration(self, sample_translations_file):
        """Test complete translation loading and usage workflow."""
        with patch('config.TRANSLATION_FILE', sample_translations_file), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
            
            # Clear module cache
            modules_to_clear = [name for name in sys.modules.keys() 
                               if name.startswith('core.translation')]
            for module in modules_to_clear:
                del sys.modules[module]
                
            # Import and load translations
            from core import translation
            from core.functions import get_user_message
            
            # Test basic translation retrieval
            assert translation.translations is not None
            assert "commands" in translation.translations
            assert "guild_members" in translation.translations
            
            # Test message retrieval
            ctx = Mock()
            ctx.locale = 'en-US'
            
            message = await get_user_message(
                ctx, translation.translations, 'guild_members.gs.success', value=2500
            )
            
            assert message == "Gear score updated to 2500"
            
            # Test French translation
            ctx.locale = 'fr-FR'
            message_fr = await get_user_message(
                ctx, translation.translations, 'guild_members.gs.success', value=2500
            )
            
            assert message_fr == "Score d'équipement mis à jour à 2500"

    async def test_effective_locale_resolution_integration(self, mock_ctx_with_bot, sample_translations_file):
        """Test effective locale resolution with cache integration."""
        with patch('config.TRANSLATION_FILE', sample_translations_file), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
            
            from core.functions import get_user_message, get_effective_locale
            
            # Clear translation module cache
            modules_to_clear = [name for name in sys.modules.keys() 
                               if name.startswith('core.translation')]
            for module in modules_to_clear:
                del sys.modules[module]
                
            from core import translation
            
            # Test member preference override
            mock_ctx_with_bot.bot.cache.get_guild_member_data.return_value = {
                'language': 'fr-FR'
            }
            
            effective_locale = await get_effective_locale(
                mock_ctx_with_bot.bot, 
                mock_ctx_with_bot.guild.id,
                mock_ctx_with_bot.author.id
            )
            
            assert effective_locale == 'fr-FR'
            
            # Test message with effective locale
            message = await get_user_message(
                mock_ctx_with_bot, translation.translations, 
                'absence.marked_absent', username='TestUser'
            )
            
            # Should use French due to effective locale
            assert message == "Membre TestUser marqué absent"

    async def test_guild_message_integration(self, mock_bot_with_cache, sample_translations_file):
        """Test guild message functionality with cache integration."""
        with patch('config.TRANSLATION_FILE', sample_translations_file), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
            
            from core.functions import get_guild_message
            
            # Clear translation module cache
            modules_to_clear = [name for name in sys.modules.keys() 
                               if name.startswith('core.translation')]
            for module in modules_to_clear:
                del sys.modules[module]
                
            from core import translation
            
            # Mock guild language preference
            mock_bot_with_cache.cache.get_guild_data.return_value = 'fr-FR'
            
            message = await get_guild_message(
                mock_bot_with_cache, 123456789, translation.translations,
                'absence.returned', username='TestUser'
            )
            
            assert message == "Membre TestUser de retour"
            
            # Verify cache was queried
            mock_bot_with_cache.cache.get_guild_data.assert_called()

    async def test_cog_command_translation_integration(self, mock_ctx_with_bot, sample_translations_file):
        """Test cog command integration with translation system."""
        with patch('config.TRANSLATION_FILE', sample_translations_file), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
            
            # Clear translation module cache
            modules_to_clear = [name for name in sys.modules.keys() 
                               if name.startswith('core.translation')]
            for module in modules_to_clear:
                del sys.modules[module]
            
            # Mock bot with command groups
            mock_ctx_with_bot.bot.member_group = Mock()
            mock_ctx_with_bot.bot.member_group.command = Mock()
            
            # Test guild members cog with translations
            with patch('core.translation.translations') as mock_translations:
                mock_translations.get.return_value = {
                    'gs': {
                        'name': {'en-US': 'gs', 'fr-FR': 'gs'},
                        'description': {'en-US': 'Update gear score', 'fr-FR': 'Mettre à jour GS'}
                    }
                }
                
                from app.cogs.guild_members import GuildMembers
                guild_members = GuildMembers(mock_ctx_with_bot.bot)
                
                # Verify command registration with translations
                mock_ctx_with_bot.bot.member_group.command.assert_called()
                
                # Check that localization data was passed
                calls = mock_ctx_with_bot.bot.member_group.command.call_args_list
                for call in calls:
                    if 'name_localizations' in call[1]:
                        assert call[1]['name_localizations'] is not None

    @pytest.mark.slow
    async def test_translation_system_performance_under_load(self, sample_translations_file):
        """Test translation system performance with many concurrent requests."""
        import asyncio
        import time
        
        with patch('config.TRANSLATION_FILE', sample_translations_file), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
            
            from core.functions import get_user_message
            
            # Clear translation module cache
            modules_to_clear = [name for name in sys.modules.keys() 
                               if name.startswith('core.translation')]
            for module in modules_to_clear:
                del sys.modules[module]
                
            from core import translation
            
            async def get_translation_task(locale):
                ctx = Mock()
                ctx.locale = locale
                return await get_user_message(
                    ctx, translation.translations, 
                    'guild_members.gs.success', value=2500
                )
            
            # Create many concurrent translation requests
            start_time = time.time()
            
            tasks = []
            locales = ['en-US', 'fr-FR'] * 50  # 100 requests
            for locale in locales:
                tasks.append(get_translation_task(locale))
            
            results = await asyncio.gather(*tasks)
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Verify all translations completed
            assert len(results) == 100
            
            # Verify correct translations
            en_results = [r for i, r in enumerate(results) if locales[i] == 'en-US']
            fr_results = [r for i, r in enumerate(results) if locales[i] == 'fr-FR']
            
            assert all(r == "Gear score updated to 2500" for r in en_results)
            assert all(r == "Score d'équipement mis à jour à 2500" for r in fr_results)
            
            # Performance should be reasonable (adjust threshold as needed)
            assert execution_time < 2.0  # Should complete within 2 seconds

    async def test_translation_fallback_chain_integration(self, mock_ctx_with_bot, sample_translations_file):
        """Test complete translation fallback chain integration."""
        with patch('config.TRANSLATION_FILE', sample_translations_file), \
             patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
            
            from core.functions import get_user_message
            
            # Clear translation module cache
            modules_to_clear = [name for name in sys.modules.keys() 
                               if name.startswith('core.translation')]
            for module in modules_to_clear:
                del sys.modules[module]
                
            from core import translation
            
            # Test fallback chain: member -> user -> guild -> system default
            
            # 1. No member preference
            mock_ctx_with_bot.bot.cache.get_guild_member_data.return_value = None
            
            # 2. No user preference  
            mock_ctx_with_bot.bot.cache.get_user_setup_data.return_value = None
            
            # 3. Guild preference set to French
            mock_ctx_with_bot.bot.cache.get_guild_data.return_value = 'fr-FR'
            
            # Should use guild preference (French)
            message = await get_user_message(
                mock_ctx_with_bot, translation.translations,
                'guild_members.gs.error_invalid'
            )
            
            assert message == "Score d'équipement invalide"
            
            # 4. Test final fallback to en-US when no guild preference
            mock_ctx_with_bot.bot.cache.get_guild_data.return_value = None
            
            message_fallback = await get_user_message(
                mock_ctx_with_bot, translation.translations,
                'guild_members.gs.error_invalid'
            )
            
            assert message_fallback == "Invalid gear score"

    async def test_translation_error_handling_integration(self, mock_ctx_with_bot):
        """Test translation system error handling in integrated environment."""
        from core.functions import get_user_message
        
        # Test with invalid translation structure
        invalid_translations = {
            'malformed': 'not_a_dict'  # Should be dict with locales
        }
        
        with patch('logging.error') as mock_error:
            message = await get_user_message(
                mock_ctx_with_bot, invalid_translations, 'malformed'
            )
            
        assert message == ""  # Should return empty string on error
        mock_error.assert_called()
        
        # Test with missing key
        valid_translations = {
            'existing': {
                'en-US': 'Existing message'
            }
        }
        
        message_missing = await get_user_message(
            mock_ctx_with_bot, valid_translations, 'nonexistent.key'
        )
        
        assert message_missing == ""  # Should return empty for missing keys


@pytest.mark.integration 
@pytest.mark.asyncio
class TestBotStartupIntegration:
    """Test bot startup integration with translation system."""

    async def test_bot_initialization_with_translations(self):
        """Test that bot initializes properly with translation system."""
        sample_translations = {
            "commands": {
                "help": {
                    "name": {"en-US": "help"},
                    "description": {"en-US": "Show help"}
                }
            }
        }
        
        # Create temporary translation file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sample_translations, f)
            temp_file = f.name
        
        try:
            with patch('config.TRANSLATION_FILE', temp_file), \
                 patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
                
                # Clear translation module cache
                modules_to_clear = [name for name in sys.modules.keys() 
                                   if name.startswith('core.translation')]
                for module in modules_to_clear:
                    del sys.modules[module]
                
                # Import should succeed and load translations
                from core import translation
                
                assert translation.translations is not None
                assert "commands" in translation.translations
                assert translation.translations["commands"]["help"]["name"]["en-US"] == "help"
                
        finally:
            os.unlink(temp_file)

    async def test_cog_loading_with_translation_dependencies(self):
        """Test that cogs can be loaded with translation system dependencies."""
        sample_translations = {
            "absence_system": {
                "absence_add": {
                    "name": {"en-US": "absence_add"},
                    "description": {"en-US": "Mark member absent"}
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(sample_translations, f)
            temp_file = f.name
            
        try:
            with patch('config.TRANSLATION_FILE', temp_file), \
                 patch('config.MAX_TRANSLATION_FILE_SIZE', 10 * 1024 * 1024):
                
                # Clear translation module cache
                modules_to_clear = [name for name in sys.modules.keys() 
                                   if name.startswith('core.translation')]
                for module in modules_to_clear:
                    del sys.modules[module]
                
                # Mock bot
                mock_bot = Mock()
                mock_bot.absence_group = Mock()
                mock_bot.absence_group.command = Mock()
                
                # Cog should load without errors
                from app.cogs.absence import AbsenceManager
                absence_cog = AbsenceManager(mock_bot)
                
                assert absence_cog.bot == mock_bot
                
        finally:
            os.unlink(temp_file)