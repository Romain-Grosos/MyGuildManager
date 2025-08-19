# Guide de contribution

Merci de votre intérêt pour MyGuildManager ! Les contributions sont les bienvenues.  
Ce document décrit les règles à suivre pour contribuer efficacement.

---

## 💡 Comment contribuer ?

Vous pouvez contribuer de plusieurs manières :

- Signaler un bug
- Proposer une amélioration ou une nouvelle fonctionnalité
- Soumettre une correction ou une amélioration du code
- Améliorer la documentation
- Ajouter ou améliorer les tests

Avant toute contribution, merci de **créer une issue** pour décrire :
- Le problème rencontré
- L'idée de fonctionnalité
- La modification que vous souhaitez apporter

Cela permet d'en discuter ensemble avant que vous ne commenciez à coder.

---

## 🛠️ Mise en place de l'environnement

### 1. Fork et clone
```bash
# Forkez ce dépôt sur GitHub
# Puis clonez votre fork
git clone https://github.com/VOTRE-USERNAME/discord-bot-mgm.git
cd discord-bot-mgm
```

### 2. Configuration de l'environnement
```bash
# Créer un environnement virtuel (recommandé)
python -m venv venv

# Activer l'environnement
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Copier la configuration
cp .env.example app/.env
# Éditer app/.env avec vos paramètres
```

### 3. Créer une branche
```bash
git checkout -b feature/nom-de-votre-fonctionnalite
# ou
git checkout -b fix/description-du-bug
```

---

## 📁 Structure du projet

Consultez `docs/STRUCTURE.md` pour comprendre l'organisation du projet :

- **`app/`** - Code source principal
- **`app/core/`** - Modules utilitaires partagés
- **`app/cogs/`** - Extensions Discord (commandes)
- **`tests/`** - Tests unitaires
- **`docs/`** - Documentation

---

## ✅ Standards de code

### Conventions Python
- **PEP 8** - Style de code Python standard
- **Type hints** - Obligatoires pour toutes les fonctions publiques
- **Docstrings** - En anglais pour toutes les méthodes publiques

### Imports
```python
# Ordre des imports
import asyncio  # 1. Standard library
from typing import Dict, Optional

import discord  # 2. Third-party
from discord.ext import commands

from ..core.logger import ComponentLogger  # 3. Imports locaux
from ..core.functions import get_user_message
from ..core.translation import translations as global_translations
```

### Exemple de fonction bien documentée
```python
async def process_member_data(
    self, 
    guild_id: int, 
    member_id: int, 
    data: Dict[str, Any]
) -> Optional[MemberProfile]:
    """
    Process guild member data and return a member profile.
    
    Args:
        guild_id: Discord server ID
        member_id: Discord member ID
        data: Raw member data from database or API
        
    Returns:
        MemberProfile instance if successful, None otherwise
        
    Raises:
        DBQueryError: If database operation fails
    """
```

### Gestion du cache
```python
# ❌ JAMAIS
self.cache = {}  # Cache local interdit

# ✅ TOUJOURS
await self.bot.cache_loader.ensure_guild_settings_loaded()
settings = await self.bot.cache.get_guild_data(guild_id, 'settings')
```

### Logging enterprise-grade
```python
# ✅ ComponentLogger centralisé - OBLIGATOIRE
from ..core.logger import ComponentLogger
_logger = ComponentLogger("module_name")

# ✅ Événements structurés avec paramètres
_logger.info("user_authenticated", user_id=123, guild_id=456)
_logger.warning("cache_miss", key="guild_settings", guild_id=789)
_logger.error("database_error", query_type="SELECT", error=str(e))

# ❌ INTERDITS - Anciens patterns
import logging  # Plus utilisé
logging.info(f"User {user_id} logged in")  # Supprimé partout
```

### Translation system centralisé
```python
# ✅ Fonctions centralisées - OBLIGATOIRES
message = await get_user_message(ctx, bot.translations, "error.not_found", username="John")
message = await get_guild_message(self.bot, guild_id, bot.translations, "announcements.new_member")
locale = await get_effective_locale(self.bot, guild_id, user_id)

# ❌ INTERDITS - Accès direct
locale = ctx.locale or "en-US"  # Plus autorisé
guild_lang = await self.bot.cache.get_guild_data(guild_id, 'guild_lang')  # Direct interdit
```

---

## 🧪 Tests

### Exécuter les tests
```bash
# Tests simples
make test
# ou
python -m pytest tests/

# Tests avec couverture
make test-coverage
# ou  
python tests/run_tests_with_coverage.py

# Test d'un module spécifique
python -m pytest tests/test_cache.py

# Linting et validation
make lint          # Vérifications flake8
make typecheck     # Validation types mypy
make format        # Formatage code black
```

### Écrire des tests
- Ajoutez des tests pour toute nouvelle fonctionnalité
- Visez au moins 80% de couverture pour les nouveaux modules
- Utilisez les fixtures de `tests/conftest.py`

---

## 📝 Format des commits

### Structure
```
TYPE(SCOPE): Description courte en français

Description détaillée optionnelle
- Point spécifique 1
- Point spécifique 2

Co-Authored-By: Votre Nom <votre@email.com>
```

### Types de commits
- **FEAT** - Nouvelle fonctionnalité
- **FIX** - Correction de bug
- **PERF** - Amélioration des performances
- **REFACTOR** - Refactoring du code
- **TEST** - Ajout ou modification de tests
- **DOCS** - Documentation
- **STYLE** - Formatage, pas de changement de code
- **CHORE** - Maintenance, dépendances

### Exemples
```bash
git commit -m "FEAT(epic-items): ajout système de cache pour les items T2"
git commit -m "FIX(cache): correction fuite mémoire dans le cache loader"
git commit -m "DOCS(readme): mise à jour instructions d'installation"
```

---

## 🔄 Pull Request

### Avant de créer une PR
1. **Testez votre code** : `make test` ou `make test-coverage`
2. **Validez le code** : `make lint && make typecheck`
3. **Formatez** : `make format`
4. **Nettoyez** : `make clean`
5. **Documentez** vos changements

### Template de PR
```markdown
## Description
Brève description des changements

## Type de changement
- [ ] Bug fix
- [ ] Nouvelle fonctionnalité
- [ ] Amélioration performance
- [ ] Refactoring
- [ ] Documentation

## Tests
- [ ] Les tests existants passent
- [ ] J'ai ajouté des tests pour mes changements
- [ ] La couverture de code est maintenue ou améliorée

## Checklist
- [ ] Mon code suit les conventions du projet
- [ ] J'utilise ComponentLogger (pas `import logging`)
- [ ] J'utilise les fonctions de traduction centralisées
- [ ] Je respecte l'interdiction de cache local dans les cogs
- [ ] J'ai mis à jour la documentation si nécessaire
- [ ] J'ai testé mes changements localement
- [ ] Les imports sont correctement organisés
- [ ] `make lint && make typecheck` passe sans erreur
```

---

## 🚨 Règles importantes

### Architecture enterprise-grade
- **ComponentLogger obligatoire** : Plus jamais `import logging`
- **Traductions centralisées** : Utiliser `get_user_message()`, `get_guild_message()`
- **Cache centralisé uniquement** : Interdiction totale de cache local dans cogs
- **Imports relatifs** : Structure `from ..core import` respectée
- **Async/await** : Toujours `await` pour `sanitize_kwargs()` et fonctions translation

### Sécurité
- **JAMAIS** de secrets ou tokens dans le code
- **JAMAIS** de requêtes SQL non paramétrées
- **TOUJOURS** valider les entrées utilisateur
- **PII masking** : Respecter `PRODUCTION=True` mode

### Performance
- **Cache first** : Vérifier le cache avant la base de données
- **Libérer les ressources** : Fermer drivers, connexions
- **Timeouts appropriés** : Ne pas bloquer indéfiniment (DB timeout 15s max)
- **Observabilité** : Événements structurés pour monitoring

### Discord API
- Utiliser `@discord_resilient` pour les appels API
- Gérer les rate limits Discord
- Logging approprié des erreurs avec ComponentLogger

---

## 📜 Licence des contributions

En soumettant une contribution, vous acceptez que votre code soit intégré au projet sous la **licence Apache 2.0**.

> Vous confirmez également que vous êtes l'auteur de votre contribution ou autorisé à la soumettre, et que vous ne violez aucun droit de tiers.

---

## 🤝 Code de conduite

- Soyez respectueux et professionnel
- Accueillez les nouveaux contributeurs
- Acceptez les critiques constructives
- Focalisez-vous sur ce qui est le mieux pour le projet

---

## 📞 Besoin d'aide ?

- Créez une issue avec le tag `question`
- Consultez la documentation dans `docs/`
- Regardez les issues et PRs existantes

---

Merci pour votre contribution ! 🎉