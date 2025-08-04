#!/usr/bin/env python3
"""
Script pour mettre à jour automatiquement les imports dans tous les cogs
"""

import os
import re
import sys

# Forcer l'encodage UTF-8 pour Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def update_cog_imports(file_path):
    """Met à jour les imports d'un fichier cog."""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Mappings des anciens imports vers les nouveaux
    import_mappings = {
        r'from functions import': 'from ..core.functions import',
        r'from translation import': 'from ..core.translation import',
        r'from rate_limiter import': 'from ..core.rate_limiter import',
        r'from reliability import': 'from ..core.reliability import',
        r'from performance_profiler import': 'from ..core.performance_profiler import',
        r'import functions': 'from ..core import functions',
        r'import translation': 'from ..core import translation',
        r'import rate_limiter': 'from ..core import rate_limiter',
        r'import reliability': 'from ..core import reliability',
        r'import performance_profiler': 'from ..core import performance_profiler',
    }
    
    # Appliquer les remplacements
    modified = False
    for old_pattern, new_import in import_mappings.items():
        if re.search(old_pattern, content):
            content = re.sub(old_pattern, new_import, content)
            modified = True
            print(f"  ✓ Mis à jour: {old_pattern} -> {new_import}")
    
    if modified:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ {os.path.basename(file_path)} mis à jour")
    else:
        print(f"⏭️  {os.path.basename(file_path)} - aucune modification nécessaire")
    
    return modified

def main():
    """Parcourir tous les cogs et mettre à jour leurs imports."""
    cogs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app', 'cogs')
    
    if not os.path.exists(cogs_dir):
        print("❌ Erreur: Le répertoire app/cogs n'existe pas!")
        return
    
    print(f"🔍 Analyse des cogs dans {cogs_dir}")
    print("-" * 60)
    
    updated_count = 0
    total_count = 0
    
    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py') and not filename.startswith('__'):
            total_count += 1
            file_path = os.path.join(cogs_dir, filename)
            print(f"\n📄 Traitement de {filename}:")
            
            if update_cog_imports(file_path):
                updated_count += 1
    
    print("\n" + "=" * 60)
    print(f"📊 Résumé: {updated_count}/{total_count} fichiers mis à jour")

if __name__ == "__main__":
    main()