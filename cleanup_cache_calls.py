#!/usr/bin/env python3
"""
Script pour nettoyer les appels ensure_category_loaded restants.

Remplace les appels ensure_category_loaded('guild_settings') par des commentaires
puisque les données sont maintenant chargées centralement au démarrage.
"""

import os
import re
from pathlib import Path

def cleanup_cog_file(file_path: Path) -> bool:
    """
    Nettoie un fichier cog en remplaçant les appels ensure_category_loaded.
    
    Args:
        file_path: Chemin vers le fichier cog
        
    Returns:
        bool: True si des modifications ont été apportées
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Remplacer les appels ensure_category_loaded par des commentaires
    patterns = [
        r'await self\.bot\.cache_loader\.ensure_category_loaded\([\'"]guild_settings[\'"]\)',
        r'await self\.bot\.cache_loader\.ensure_category_loaded\([\'"]guild_roles[\'"]\)',
        r'await self\.bot\.cache_loader\.ensure_category_loaded\([\'"]guild_channels[\'"]\)',
    ]
    
    for pattern in patterns:
        content = re.sub(
            pattern,
            '# Data already loaded centrally at startup',
            content
        )
    
    # Sauvegarder si des changements ont été apportés
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    
    return False

def main():
    """Fonction principale de nettoyage."""
    cogs_dir = Path('app/cogs')
    
    if not cogs_dir.exists():
        print("ERR: Repertoire app/cogs non trouve")
        return
    
    print("Nettoyage des appels ensure_category_loaded...")
    
    # Traiter tous les fichiers .py dans le répertoire cogs
    modified_count = 0
    for py_file in cogs_dir.glob('*.py'):
        if py_file.name == '__init__.py':
            continue
            
        print(f"Nettoyage de {py_file.name}...")
        
        try:
            if cleanup_cog_file(py_file):
                print(f"  OK {py_file.name} nettoye")
                modified_count += 1
            else:
                print(f"  -> {py_file.name} deja propre")
        except Exception as e:
            print(f"  ERR {py_file.name}: {e}")
    
    print(f"\nNettoyage termine !")
    print(f"{modified_count} fichiers modifies")
    print("Les appels redondants ont ete remplaces par des commentaires")

if __name__ == "__main__":
    main()