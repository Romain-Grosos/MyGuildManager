# Structure du Projet MyGuildManager

**Dernière mise à jour : Août 2025 - Architecture Centralisée**

## 📁 Organisation des répertoires

```
discord-bot-mgm/
├── app/                    # 🎯 Code applicatif principal
│   ├── __init__.py        # Package principal
│   ├── bot.py             # Point d'entrée du bot
│   ├── cache.py           # Système de cache global
│   ├── cache_loader.py    # Chargeur de cache centralisé
│   ├── config.py          # Configuration (chargement .env)
│   ├── db.py              # Couche base de données
│   ├── scheduler.py       # Planificateur de tâches
│   ├── .env               # Variables d'environnement (non versionné)
│   ├── core/              # 🔧 Modules utilitaires centraux
│   │   ├── __init__.py
│   │   ├── functions.py   # Fonctions utilitaires
│   │   ├── translation.py # Système de traduction
│   │   ├── translation.json # Fichier de traductions
│   │   ├── reliability.py # Gestion de la fiabilité
│   │   ├── rate_limiter.py # Limitation de débit
│   │   └── performance_profiler.py # Profilage performances
│   └── cogs/              # 📦 Extensions Discord (commandes)
│       ├── __init__.py
│       ├── absence.py
│       ├── autorole.py
│       ├── contract.py
│       ├── core.py
│       ├── dynamic_voice.py
│       ├── epic_items_scraper.py
│       ├── guild_attendance.py
│       ├── guild_events.py
│       ├── guild_init.py
│       ├── guild_members.py
│       ├── guild_ptb.py
│       ├── llm.py
│       ├── loot_wishlist.py
│       ├── notification.py
│       └── profile_setup.py
├── sql/                    # 📊 Scripts base de données
│   ├── schema/            # Schéma de base
│   │   └── schema_structure.sql
│   └── migrations/        # Scripts de migration
├── tests/                  # 🧪 Tests unitaires
│   ├── __init__.py
│   ├── conftest.py
│   └── test_*.py
├── scripts/                # 🛠️ Scripts utilitaires
│   └── update_cog_imports.py
├── docs/                   # 📚 Documentation
├── logs/                   # 📝 Fichiers de logs (non versionné)
├── run_bot.py             # 🚀 Script de lancement Python
├── run_bot.bat            # 🚀 Script de lancement Windows
├── requirements.txt       # 📦 Dépendances Python
├── Makefile              # 🎯 Commandes utiles
├── .env.example          # 📋 Template variables d'environnement
├── .gitignore
├── README.md
├── CONTRIBUTING.md
├── LICENSE
└── STRUCTURE.md          # Ce fichier

```

## 🚀 Démarrage rapide

### 1. Installation

```bash
# Cloner le projet
git clone <url-du-projet>
cd discord-bot-mgm

# Installer les dépendances
pip install -r requirements.txt
# ou
make install
```

### 2. Configuration

```bash
# Copier le fichier d'exemple
cp .env.example app/.env

# Éditer app/.env avec vos paramètres
```

### 3. Base de données

```bash
# Exécuter le script de création
mysql -u <user> -p <database> < sql/schema/schema_structure.sql
```

### 4. Lancement

```bash
# Linux/Mac
python run_bot.py
# ou
make run

# Windows
run_bot.bat
```

## 📦 Imports dans les fichiers

### Dans app/ (fichiers racine)
```python
from . import config
from .cache import get_global_cache
from .core.translation import translations
```

### Dans app/cogs/
```python
from ..core.functions import get_user_message
from ..core.translation import translations
from ..core.reliability import discord_resilient
```

### Dans app/core/
```python
from ..config import SOME_CONFIG
from ..db import run_db_query
```

## 🛠️ Commandes Make disponibles

- `make install` - Installer les dépendances
- `make run` - Lancer le bot
- `make test` - Exécuter les tests
- `make clean` - Nettoyer les fichiers temporaires
- `make update-imports` - Mettre à jour les imports des cogs

## 🎯 Architecture des Commandes Slash - CENTRALISÉE (Août 2025)

### Groupes de commandes centralisés

Le bot utilise maintenant **7 groupes centralisés** créés dans `bot.py` pour organiser les 31+ commandes slash :

```python
# Dans bot.py - Groupes centralisés
bot.admin_group     # Administration bot (5 commandes)
bot.absence_group   # Gestion absences (2 commandes)  
bot.member_group    # Profils membres (6 commandes)
bot.loot_group      # Gestion loot & wishlists (4 commandes)
bot.staff_group     # Modération & gestion (6 commandes)
bot.events_group    # Événements guildes (4 commandes)
bot.statics_group   # Groupes statiques (5 commandes)
```

### Mapping des commandes par groupe

- **`/admin_bot`** : bot_initialize, bot_modify, bot_reset, discord_setup, ptb_init
- **`/absence`** : absence_add, return  
- **`/member`** : gs, weapons, build, username, show_build, change_language
- **`/loot`** : epic_items, add_item, remove_item, show_wishlist
- **`/staff`** : maj_effectifs, notify_profile, config_roster, contract, contract_delete, wishlist_admin
- **`/events`** : create, confirm, cancel, preview_groups
- **`/statics`** : group_create, player_add, player_remove, group_delete, update

### Pattern d'implémentation dans les cogs

```python
class MyCog(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self._register_my_commands()  # OBLIGATOIRE dans __init__
    
    def _register_my_commands(self):
        """Register commands with the centralized group."""
        if hasattr(self.bot, 'my_group'):
            self.bot.my_group.command(
                name=TRANSLATIONS["command"]["name"]["en-US"],
                description=TRANSLATIONS["command"]["description"]["en-US"],
                name_localizations=TRANSLATIONS["command"]["name"],
                description_localizations=TRANSLATIONS["command"]["description"]
            )(self.my_command_function)
    
    # ❌ SUPPRIMÉ : @discord.slash_command() décorateurs
    # ✅ CONSERVÉ : @admin_rate_limit, @discord_resilient, etc.
    async def my_command_function(self, ctx: discord.ApplicationContext):
        pass
```

### Gestion d'erreurs centralisée

- **Automatique** : Tous les groupes bénéficient de la gestion d'erreurs centralisée
- **Multilingue** : Messages traduits selon `ctx.locale` avec fallback EN
- **Robuste** : 6 types d'erreurs gérés (Permissions, NotFound, HTTP, etc.)
- **Une seule fonction** dans `bot.py` pour tous les groupes

## 📝 Notes importantes

1. **`.env` dans app/** - Pour simplifier le déploiement, le fichier .env est dans le dossier app/
2. **Imports relatifs** - Utilisation d'imports relatifs pour la portabilité
3. **Structure modulaire** - Chaque cog est indépendant et peut être activé/désactivé
4. **Cache centralisé** - Toujours utiliser `self.bot.cache` et `self.bot.cache_loader`
5. **Groupes centralisés** - OBLIGATOIRE : méthode `_register_*_commands()` dans chaque cog
6. **Pas de décorateurs slash** - Suppression de tous les `@discord.slash_command()`

## 🔧 Maintenance

- Les logs sont dans `logs/discord-bot.log`
- Le cache est géré automatiquement avec TTL
- Les scripts SQL de migration doivent être numérotés chronologiquement