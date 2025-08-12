#!/usr/bin/env python3
"""
Script pour supprimer les fonctions load_*_data() devenues inutiles.

Ces fonctions ne font plus que wait_for_initial_load(), donc on peut :
1. Supprimer la fonction
2. Appeler directement wait_for_initial_load() dans on_ready()
"""

import re
from pathlib import Path

def optimize_cog_file(file_path: Path) -> bool:
    """Optimise un fichier cog en supprimant les fonctions inutiles."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # 1. Trouver les fonctions load_*_data qui ne font que wait_for_initial_load
    useless_pattern = r'async def (load_\w+_data)\(self\) -> None:.*?await self\.bot\.cache_loader\.wait_for_initial_load\(\).*?logging\.debug\(.*?\)'
    
    def replace_useless_function(match):
        func_name = match.group(1)
        return f'# {func_name}() removed - data loaded centrally at startup'
    
    content = re.sub(useless_pattern, replace_useless_function, content, flags=re.DOTALL)
    
    # 2. Optimiser les on_ready() qui appellent ces fonctions
    on_ready_patterns = [
        # Pattern pour asyncio.create_task(self.load_*_data())
        (r'asyncio\.create_task\(self\.load_\w+_data\(\)\)', 
         'asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())'),
        
        # Mettre à jour les logs dans on_ready()
        (r'logging\.debug\(\"\[.*?\] Cache loading tasks started.*?\"\)', 
         'logging.debug("[{}] Waiting for initial cache load")'.format(file_path.stem.title())),
    ]
    
    for pattern, replacement in on_ready_patterns:
        content = re.sub(pattern, replacement, content)
    
    if content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    
    return False

def main():
    """Fonction principale."""
    cogs_dir = Path('app/cogs')
    print("Suppression des fonctions load_*_data() inutiles...")
    
    modified_count = 0
    for py_file in cogs_dir.glob('*.py'):
        if py_file.name == '__init__.py':
            continue
            
        if optimize_cog_file(py_file):
            print(f"  OK {py_file.name} optimise")
            modified_count += 1
        else:
            print(f"  -> {py_file.name} deja optimise")
    
    print(f"\nOptimisation terminee !")
    print(f"{modified_count} fichiers modifies")
    print("Les fonctions inutiles ont ete supprimees et on_ready() optimises")

if __name__ == "__main__":
    main()