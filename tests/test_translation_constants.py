"""
Tests for translation constants usage in cogs.
"""

import pytest
from unittest.mock import Mock, patch
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTranslationConstants:
    """Test that cogs use translation constants correctly."""
    
    def test_guild_init_constants(self):
        """Test GuildInit uses correct translation constants."""
        from cogs.guild_init import APP_INITIALIZE_DATA, APP_MODIFICATION_DATA, APP_RESET_DATA
        from translation import translations as global_translations
        
        # These should be loaded from global_translations
        assert APP_INITIALIZE_DATA == global_translations.get("commands", {}).get("app_initialize", {})
        assert APP_MODIFICATION_DATA == global_translations.get("commands", {}).get("app_modify", {})
        assert APP_RESET_DATA == global_translations.get("commands", {}).get("app_reset", {})
    
    def test_guild_ptb_constants(self):
        """Test GuildPTB uses correct translation constants."""
        from cogs.guild_ptb import GUILD_PTB
        from translation import translations as global_translations
        
        assert GUILD_PTB == global_translations.get("guild_ptb", {})
    
    def test_guild_members_constants(self):
        """Test GuildMembers uses correct translation constants."""
        from cogs.guild_members import GUILD_MEMBERS, CONFIG_ROSTER_DATA
        from translation import translations as global_translations
        
        assert GUILD_MEMBERS == global_translations.get("guild_members", {})
        assert CONFIG_ROSTER_DATA == global_translations.get("commands", {}).get("config_roster", {})
    
    def test_guild_events_constants(self):
        """Test GuildEvents uses correct translation constants."""
        from cogs.guild_events import GUILD_EVENTS
        from translation import translations as global_translations
        
        assert GUILD_EVENTS == global_translations.get("guild_events", {})
    
    def test_guild_attendance_constants(self):
        """Test GuildAttendance uses correct translation constants."""
        from cogs.guild_attendance import GUILD_EVENTS, GUILD_ATTENDANCE
        from translation import translations as global_translations
        
        assert GUILD_EVENTS == global_translations.get("guild_events", {})
        assert GUILD_ATTENDANCE == global_translations.get("guild_attendance", {})
    
    def test_llm_constants(self):
        """Test LLMInteraction uses correct translation constants."""
        from cogs.llm import LLM_DATA
        from translation import translations as global_translations
        
        assert LLM_DATA == global_translations.get("llm", {})
        
    def test_constants_not_empty(self):
        """Test that translation constants are loaded (not empty dicts)."""
        # This is a basic sanity check - in a real environment, translations should be loaded
        from translation import translations as global_translations
        
        # At minimum, global_translations should be a dict
        assert isinstance(global_translations, dict)


class TestTranslationAccess:
    """Test translation access patterns in cogs."""
    
    @patch('cogs.guild_init.get_user_message')
    def test_guild_init_translation_access(self, mock_get_user_message):
        """Test that GuildInit accesses translations correctly."""
        from cogs.guild_init import GuildInit, APP_INITIALIZE_DATA
        import discord
        
        mock_bot = Mock(spec=discord.Bot)
        mock_bot.cache_loader = Mock()
        mock_bot.cache_loader.ensure_category_loaded = Mock()
        mock_bot.cache = Mock()
        
        cog = GuildInit(mock_bot)
        
        # The cog should use the constant, not self.translations
        assert hasattr(cog, 'bot')
        assert not hasattr(cog, 'translations')  # Should not have this attribute anymore
    
    def test_core_translation_access(self):
        """Test that Core cog doesn't use self.translations."""
        from cogs.core import Core
        import discord
        
        mock_bot = Mock(spec=discord.Bot)
        mock_bot.synced = False
        
        cog = Core(mock_bot)
        
        # The cog should not have translations attribute
        assert hasattr(cog, 'bot')
        assert not hasattr(cog, 'translations')


class TestTranslationFallbacks:
    """Test translation fallback behavior."""
    
    def test_empty_translation_dict_handling(self):
        """Test handling when translation dicts are empty."""
        # Mock empty translations
        with patch('cogs.guild_init.APP_INITIALIZE_DATA', {}):
            from cogs.guild_init import GuildInit
            import discord
            
            mock_bot = Mock(spec=discord.Bot)
            mock_bot.cache_loader = Mock()
            mock_bot.cache = Mock()
            
            # Should not raise error even with empty translations
            cog = GuildInit(mock_bot)
            assert cog.bot == mock_bot
    
    def test_missing_translation_key_handling(self):
        """Test behavior when translation keys are missing."""
        # This would be caught at runtime in get_user_message function
        # Here we just test that the constants can be accessed
        from cogs.guild_members import GUILD_MEMBERS
        
        # Should return empty dict if key doesn't exist
        missing_key = GUILD_MEMBERS.get("nonexistent_key", {})
        assert missing_key == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])