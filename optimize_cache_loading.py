#!/usr/bin/env python3
"""
Script de migration pour optimiser le chargement des caches.

Ce script remplace les appels individuels ensure_category_loaded() 
par un simple wait_for_initial_load() dans tous les cogs.
"""

import os
import re
from pathlib import Path

def optimize_cog_file(file_path: Path) -> bool:
    """
    Optimise un fichier cog en remplaçant les load_*_data() methods.
    
    Args:
        file_path: Chemin vers le fichier cog
        
    Returns:
        bool: True si des modifications ont été apportées
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # Pattern pour détecter les méthodes load_*_data
    load_method_pattern = r'async def load_\w+_data\(self\) -> None:(.*?)(?=\n    async def|\n    def|\nclass|\n\n|\Z)'
    
    def replace_load_method(match):
        method_content = match.group(1)
        method_name = match.group(0).split('(')[0].split()[-1]
        
        # Extraire le nom du cog depuis le nom de la méthode
        cog_name = method_name.replace('load_', '').replace('_data', '').title()
        if cog_name == 'Guild_members':
            cog_name = 'GuildMembers'
        elif cog_name == 'Guild_events':
            cog_name = 'GuildEvents'
        elif cog_name == 'Guild_attendance':
            cog_name = 'GuildAttendance'
        elif cog_name == 'Guild_ptb':
            cog_name = 'GuildPTB'
        elif cog_name == 'Guild_init':
            cog_name = 'GuildInit'
        elif cog_name == 'Profile_setup':
            cog_name = 'ProfileSetup'
        elif cog_name == 'Dynamic_voice':
            cog_name = 'DynamicVoice'
        
        # Nouvelle implémentation optimisée
        new_method = f'''async def {method_name}(self) -> None:
        """
        Wait for centralized cache load to complete.
        
        This method now simply waits for the initial load to finish
        rather than loading data itself, avoiding duplicate DB queries.
        
        Returns:
            None
        """
        logging.debug("[{cog_name}] Waiting for initial cache load")
        
        # Simply wait for the centralized load to complete
        await self.bot.cache_loader.wait_for_initial_load()
        
        logging.debug("[{cog_name}] Cache ready - data available")'''
        
        return new_method
    
    # Remplacer toutes les méthodes load_*_data
    content = re.sub(load_method_pattern, replace_load_method, content, flags=re.DOTALL)
    
    # Sauvegarder si des changements ont été apportés
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    
    return False

def main():
    """Fonction principale de migration."""
    cogs_dir = Path('app/cogs')
    
    if not cogs_dir.exists():
        print("ERR: Repertoire app/cogs non trouve")
        return
    
    print("Optimisation du chargement des caches...")
    
    # Traiter tous les fichiers .py dans le répertoire cogs
    modified_count = 0
    for py_file in cogs_dir.glob('*.py'):
        if py_file.name == '__init__.py':
            continue
            
        print(f"Traitement de {py_file.name}...")
        
        try:
            if optimize_cog_file(py_file):
                print(f"  OK {py_file.name} optimise")
                modified_count += 1
            else:
                print(f"  -> {py_file.name} deja optimise")
        except Exception as e:
            print(f"  ERR {py_file.name}: {e}")
    
    print(f"\nOptimisation terminee !")
    print(f"{modified_count} fichiers modifies")
    print(f"Le chargement des caches sera maintenant centralise et optimise")

if __name__ == "__main__":
    main()