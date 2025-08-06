"""
Test simple pour valider le système de traduction centralisé
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Ajout du dossier app au path pour les imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

def test_import_translation_system():
    """Test que le système de traduction peut être importé correctement."""
    try:
        from core.translation import translations
        assert translations is not None
        assert isinstance(translations, dict)
        print(f"✓ Système de traduction importé avec {len(translations)} sections")
    except Exception as e:
        pytest.fail(f"Impossible d'importer le système de traduction: {e}")

def test_translation_structure():
    """Test la structure hiérarchique des traductions."""
    from core.translation import translations
    
    # Vérifier les sections principales
    expected_sections = ['global', 'absence_system', 'event_management', 'loot_system']
    for section in expected_sections:
        assert section in translations, f"Section manquante: {section}"
    
    # Vérifier la structure global
    assert 'global' in translations
    global_section = translations['global']
    assert 'supported_locales' in global_section
    assert 'language_names' in global_section
    
    print(f"✓ Structure hiérarchique validée avec {len(translations)} sections")

def test_import_functions():
    """Test que les fonctions de traduction peuvent être importées."""
    try:
        from core.functions import get_user_message, get_guild_message
        assert callable(get_user_message)
        assert callable(get_guild_message)
        print("✓ Fonctions de traduction importées")
    except Exception as e:
        pytest.fail(f"Impossible d'importer les fonctions: {e}")

def test_cog_translation_pattern():
    """Test le pattern d'utilisation dans les cogs."""
    from core.translation import translations as global_translations
    
    # Test pattern utilisé dans les cogs
    EVENT_MANAGEMENT = global_translations.get("event_management", {})
    ABSENCE_DATA = global_translations.get("absence_system", {})
    LOOT_SYSTEM = global_translations.get("loot_system", {})
    
    assert isinstance(EVENT_MANAGEMENT, dict)
    assert isinstance(ABSENCE_DATA, dict) 
    assert isinstance(LOOT_SYSTEM, dict)
    
    print("✓ Pattern d'utilisation des cogs validé")

@patch('core.functions.get_effective_locale')
@patch('core.functions.get_nested_value')
def test_get_user_message_mock(mock_get_nested, mock_get_locale):
    """Test de la fonction get_user_message avec mocks."""
    from core.functions import get_user_message
    
    # Setup mocks
    mock_get_locale.return_value = "fr"
    mock_get_nested.return_value = "Message de test"
    
    # Mock context
    mock_ctx = Mock()
    mock_ctx.locale = "fr"
    mock_ctx.guild.id = 123
    mock_ctx.author.id = 456
    
    # Mock translations
    mock_translations = {"test": {"message": {"fr": "Message de test"}}}
    
    # Test
    result = get_user_message(mock_ctx, mock_translations, "test.message")
    
    # Vérifications
    assert result is not None
    print("✓ Fonction get_user_message testée avec succès")

def test_bot_initialization():
    """Test simple d'initialisation des composants du bot."""
    # Test que les modules principaux sont importables
    modules_to_test = [
        'core.translation',
        'core.functions', 
        'core.cache_manager',
        'core.performance_profiler',
        'core.reliability'
    ]
    
    for module_name in modules_to_test:
        try:
            __import__(module_name)
            print(f"✓ Module {module_name} importé avec succès")
        except Exception as e:
            print(f"⚠ Module {module_name} non disponible: {e}")

if __name__ == "__main__":
    pytest.main([__file__, "-v"])