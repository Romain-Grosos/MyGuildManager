# Structure du Projet MyGuildManager

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

## 📝 Notes importantes

1. **`.env` dans app/** - Pour simplifier le déploiement, le fichier .env est dans le dossier app/
2. **Imports relatifs** - Utilisation d'imports relatifs pour la portabilité
3. **Structure modulaire** - Chaque cog est indépendant et peut être activé/désactivé
4. **Cache centralisé** - Toujours utiliser `self.bot.cache` et `self.bot.cache_loader`

## 🔧 Maintenance

- Les logs sont dans `logs/discord-bot.log`
- Le cache est géré automatiquement avec TTL
- Les scripts SQL de migration doivent être numérotés chronologiquement