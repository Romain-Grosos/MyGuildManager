#!/usr/bin/env python3
"""
Script de nettoyage final pour les catégories chargées centralement.

Remplace les ensure_category_loaded pour les catégories déjà chargées 
au démarrage par des commentaires.
"""

import re
from pathlib import Path

# Catégories chargées centralement au démarrage
CENTRALLY_LOADED_CATEGORIES = [
    'guild_settings',
    'guild_roles', 
    'guild_channels',
    'welcome_messages',
    'absence_messages',
    'guild_members',
    'events_data',
    'static_data',
    'static_groups',
    'user_setup',
    'weapons',
    'weapons_combinations',
    'guild_ideal_staff',
    'games_list',
    'epic_items_t2',
    'guild_ptb_settings'
]

def cleanup_remaining_calls(file_path: Path) -> bool:
    """Nettoie les appels restants pour les catégories chargées centralement."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Remplacer les appels pour les catégories chargées centralement
    for category in CENTRALLY_LOADED_CATEGORIES:
        pattern = rf'await self\.bot\.cache_loader\.ensure_category_loaded\([\'\"]{category}[\'\"]\)'
        replacement = f'# {category} already loaded centrally at startup'
        content = re.sub(pattern, replacement, content)
    
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    
    return False

def main():
    """Fonction principale."""
    cogs_dir = Path('app/cogs')
    print("Nettoyage final des appels ensure_category_loaded...")
    
    modified_count = 0
    for py_file in cogs_dir.glob('*.py'):
        if py_file.name == '__init__.py':
            continue
            
        if cleanup_remaining_calls(py_file):
            print(f"  OK {py_file.name} optimise")
            modified_count += 1
        else:
            print(f"  -> {py_file.name} deja propre")
    
    print(f"\nNettoyage final termine !")
    print(f"{modified_count} fichiers modifies")

if __name__ == "__main__":
    main()