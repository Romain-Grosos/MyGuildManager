# Structure du Projet MyGuildManager

**Dernière mise à jour : 18 août 2025 - Architecture Enterprise Observability**

## 🚀 ENTERPRISE-GRADE - Observabilité Production Complète

### ✅ Observabilité Exceptionnelle (Août 2025)
- **Correlation ID** : Traçage UUID8 sur toutes les requêtes avec collision detection
- **Logs structurés** : JSON schema v1.0 + PII masking automatique en production
- **Alerting intelligent** : Performance (fast%/slow%) + health monitoring temps réel  
- **SLO tracking** : Availability & Performance avec seuils configurables
- **Memory debugging** : tracemalloc + SIGUSR1/SIGBREAK cross-platform
- **Bounded shutdown** : Cleanup garanti avec timeouts + aiohttp connector closure

### ⚡ VALIDATION GUILD_EVENTS.PY (20 août 2025) - PATTERNS ENTERPRISE

**Standards enterprise-grade définis** - Refactoring complet du cog le plus critique (171KB) avec validation exhaustive des patterns à appliquer aux autres cogs :

#### ✅ **8 Standards Enterprise Validés**
1. **Transaction Consistency** : DB → UI avec rollback approprié
2. **Method Naming Accuracy** : Cohérence noms vs appels
3. **Database Operations** : `INSERT IGNORE` + `lastrowid` check robuste
4. **Type Hints Precision** : Refléter usage réel (`int | float | str`)
5. **Performance Optimization** : Élimination duplications/boucles
6. **Exception Logging** : `exc_info=True` pour debug complet
7. **Input Processing** : Parsers multi-formats sans preprocessing redondant
8. **Fallback Consistency** : États valides, jamais input invalide

#### 📋 **Checklist Migration Autres Cogs**
**Patterns obligatoires à appliquer systématiquement :**
- ✅ Ordre transactionnel : cache → DB → embed/UI
- ✅ Logging avec `exc_info=True` pour exceptions inattendues
- ✅ Type hints précis reflétant usage réel des fonctions
- ✅ Optimisations performance : une seule passe pour constructions répétées
- ✅ Fallbacks vers états valides, jamais input original invalide
- ✅ Nettoyage preprocessing redondant (laisser parsers faire le travail)
- ✅ Cohérence noms méthodes avec leurs appels
- ✅ Opérations DB robustes avec gestion duplicatas appropriée

### 🎯 Évolutions Majeures Enterprise
1. **Observabilité complète** - Correlation logs ↔ métriques avec context auto-injection
2. **Performance optimisée** - Percentiles O(1), rate limiter deque, watchdog robuste
3. **Production security** - PII masking, secrets safe, schema versioning
4. **Monitoring proactif** - SLO availability/performance + health checks intelligents

### ✅ Performance Exceptionnelle (Août 2025 + Observability + AsyncDB)
- **Score startup** : 100/100 (A+ Excellent) + observabilité complète
- **Database async pur** : Migration asyncmy pour performances natives
- **Auto-reloads éliminés** : 0 (vs 30 précédemment)
- **Démarrage ultra-rapide** : 0.01s pour chargement complet + correlation tracking
- **Stabilité parfaite** : 0 erreur, 0 warning + alerting proactif
- **Cache intelligent** : Protection automatique + health monitoring intégré

## 📁 Organisation des répertoires

```
discord-bot-mgm/
├── app/                    # 🎯 Code applicatif principal
│   ├── __init__.py        # Package principal
│   ├── bot.py             # Point d'entrée du bot + init async DB
│   ├── cache.py           # Système de cache global TTL intelligent
│   ├── cache_loader.py    # Chargeur de cache centralisé
│   ├── config.py          # Configuration robuste + validation
│   ├── db.py              # Couche async pure MySQL/MariaDB (asyncmy)
│   ├── scheduler.py       # Planificateur enterprise + observabilité
│   ├── .env               # Variables d'environnement (non versionné)
│   ├── core/              # 🔧 Modules utilitaires centraux
│   │   ├── __init__.py
│   │   ├── functions.py   # Fonctions utilitaires
│   │   ├── translation.py # Système de traduction
│   │   ├── translation.json # Fichier de traductions
│   │   ├── reliability.py # Gestion de la fiabilité
│   │   ├── rate_limiter.py # Limitation de débit
│   │   ├── performance_profiler.py # Profilage performances
│   │   ├── logger.py      # 📝 ComponentLogger centralisé - Migration 100%
│   │   ├── cache_audit.py # Monitoring cache production
│   │   └── production_cache_agent.py # Agent surveillance cache
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
├── scripts/                # 🛠️ Scripts utilitaires + Observability tools
│   ├── update_cog_imports.py
│   ├── analyze_logs.py      # Analyseur logs 48MB (optimisations cache)
│   ├── analyze_startup_performance.py  # Analyseur performance démarrage
│   ├── correlation_analyzer.py    # 🎯 NOUVEAU - Analyseur correlation ID + collision detection
│   ├── slo_dashboard.py          # 🎯 NOUVEAU - Dashboard SLO availability/performance
│   └── alert_simulator.py       # 🎯 NOUVEAU - Simulateur alertes pour tests
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

## 🚀 Patterns de Développement

### Configuration
```python
# ✅ Bon - utiliser config.py
from config import get_db_host

# ❌ Éviter - accès direct
import os
host = os.getenv("DB_HOST")
```

### Cache
```python
# ✅ Bon - utiliser le cache global
cache = get_global_cache()
data = await cache.get("guild_data", guild_id)

# ❌ Éviter - requêtes DB directes fréquentes
data = await db.query("SELECT ...")
```

### Logging
```python
# ✅ Bon - utiliser le logger centralisé
from core.logger import ComponentLogger
logger = ComponentLogger("mon_module")
logger.info("operation_completed", user_id=123)

# ❌ Éviter - logging basique
import logging
logging.info("Opération terminée")
```

### Traduction
```python
# ✅ Bon - utiliser les fonctions core
from core.functions import get_user_message
msg = get_user_message(ctx, "welcome.message", username=user.name)

# ❌ Éviter - hardcoder le texte
msg = f"Bienvenue {user.name}!"
```

## 🎓 Niveaux de Contribution

### **Niveau Débutant** - Modifier les Cogs
- Ajouter commandes dans `cogs/`
- Utiliser patterns existants
- Pas de modifications du core

### **Niveau Intermédiaire** - Étendre les Systèmes
- Ajouter catégories cache
- Nouvelles traductions
- Modifier la logique métier

### **Niveau Avancé** - Architecture Core
- Modifier `cache.py`, `reliability.py`
- Nouveaux patterns de monitoring
- Optimisations performance

## ⚠️ Points d'Attention

### Cache
- **Format de clés** : Toujours `category:type:id`
- **TTL** : Définir dans `CACHE_CATEGORIES`
- **Métriques** : Vérifier l'impact performance

### Base de Données
- **Pool** : Utiliser le pool existant
- **Timeout** : Respecter les seuils configurés
- **Circuit breaker** : Actif sur les erreurs

### Logs
- **Format JSON** : Structure obligatoire
- **PII** : Masquage automatique en production
- **Correlation ID** : Pour traçabilité

### Performance
- **Seuils** : 200ms pour requêtes simples
- **Monitoring** : Métriques automatiques
- **Alerting** : Logs structurés pour observabilité

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

### Mapping des commandes par groupe avec permissions

- **`/admin_bot`** 🔒 (Admin) : bot_initialize, bot_modify, bot_reset, discord_setup, ptb_init
- **`/absence`** 🔒 (Staff) : absence_add *(staff déclare les absences)*
- **`/member`** ✅ (Membres) : gs, weapons, build, username, show_build, change_language, **return** *(signaler retour)*
- **`/loot`** ✅ (Membres) : epic_items, add_item, remove_item, show_wishlist
- **`/staff`** 🔒 (Staff) : maj_effectifs, notify_profile, config_roster, contract, contract_delete, wishlist_admin
- **`/events`** 🔒 (Staff) : create, confirm, cancel, preview_groups
- **`/statics`** 🔒 (Staff) : group_create, player_add, player_remove, group_delete, update

### 🎯 Permissions Discord par Groupe (13 août 2025)

| Groupe | Permission Requise | Accessible aux Membres ? | Logique |
|--------|-------------------|---------------------------|---------|
| `admin_bot` | `administrator=True` | ❌ Admin uniquement | Administration bot |
| `absence` | `manage_guild=True` | ❌ Staff uniquement | **Staff déclare absences** |
| `member` | `send_messages=True` | ✅ **Tous membres** | **Membres gèrent profil + retour** |
| `loot` | `send_messages=True` | ✅ **Tous membres** | Gestion wishlist personnelle |
| `staff` | `manage_roles=True` | ❌ Staff uniquement | Modération équipe |
| `events` | `manage_events=True` | ❌ Staff uniquement | Gestion événements |
| `statics` | `manage_roles=True` | ❌ Staff uniquement | Groupes statiques |

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

## 🎯 Cache Intelligent - Architecture Révolutionnaire (13 août 2025)

### Protection Anti-Reload Automatique

```python
# cache.py - Protection intelligente
async def _is_guild_configured(self, guild_id: int) -> bool:
    """Vérifie si guilde configurée sans déclencher auto-reload"""
    # Cache TTL 30 minutes des guildes configurées
    if self._configured_guilds_cache is None:
        query = "SELECT guild_id FROM guild_settings WHERE initialized = TRUE"
        # Mise en cache pour éviter requêtes répétées
    return guild_id in self._configured_guilds_cache

# Protection avant auto-reload
if result is None and _auto_reload and self._initial_load_complete:
    if not await self._is_guild_configured(guild_id):
        logging.debug(f"[Cache] Skipping auto-reload for unconfigured guild {guild_id}")
        return None
```

## 🔐 Système Permissions Discord Hiérarchisé (13 août 2025)

### Permissions Rôles Automatiques

```python
# guild_init.py - Création rôles avec permissions
if key == "guild_master":
    permissions.update(administrator=True)  # 👑 Contrôle total
elif key == "officer":
    permissions.update(  # 🛡️ Gestion complète + modération
        manage_roles=True, ban_members=True, manage_events=True,
        mute_members=True, priority_speaker=True  # + 8 autres
    )
elif key == "guardian":
    permissions.update(  # 🔰 Gestion modérée
        manage_roles=True, kick_members=True, manage_events=True,
        mute_members=True, priority_speaker=True  # + 6 autres, pas de ban
    )
```

### Architecture Commandes Membres vs Staff

```python
# Logique métier optimisée
"/absence absence_add"  # 🔒 Staff déclare membre absent
"/member return"        # ✅ Membre signale son retour

# Accès étendu membres
"/member" + "/loot" = 11 commandes accessibles via rôles "membres"/"absents"
```

### Invalidation Automatique Cache

```python
# core.py - Invalidation après modifications guildes
after guild initialization:
    await self.bot.cache.invalidate_configured_guilds_cache()
    
after guild reset:
    await self.bot.cache.invalidate_configured_guilds_cache()
```

## 📝 Notes importantes

1. **`.env` dans app/** - Pour simplifier le déploiement, le fichier .env est dans le dossier app/
2. **Imports relatifs** - Utilisation d'imports relatifs pour la portabilité
3. **Structure modulaire** - Chaque cog est indépendant et peut être activé/désactivé
4. **Cache centralisé OBLIGATOIRE** - Toujours utiliser `self.bot.cache` et `self.bot.cache_loader`
5. **Groupes centralisés** - OBLIGATOIRE : méthode `_register_*_commands()` dans chaque cog
6. **Pas de décorateurs slash** - Suppression de tous les `@discord.slash_command()`
7. **Protection intelligente** - Auto-reload uniquement pour guildes configurées (TTL 30min)
8. **Performance maximale** - Score 100/100 en production avec 0 auto-reload
9. **Permissions hiérarchisées** - Discord roles avec permissions automatiques (Maître/Officier/Gardien)
10. **Accès membres étendu** - 11 commandes accessibles via permissions granulaires

## 📝 SYSTÈME COMPONENTLOGGER (Août 2025)

### 🎯 Migration Enterprise-Grade Complète
**Migration terminée à 100%** - Remplacement du système `logging` standard par ComponentLogger centralisé :

#### ✅ Architecture centralisée
- **Module unique** : `core/logger.py` avec classe `ComponentLogger`
- **Événements structurés** : Logging avec événements nommés (`cache_miss`, `db_error`, etc.)
- **JSON uniforme** : Output cohérent via `log_json()` dans tous les modules
- **Composants identifiés** : Chaque module a son ID unique (`bot`, `cache`, `db`, etc.)

#### ✅ Pattern standardisé dans tous les modules
```python
from core.logger import ComponentLogger
_logger = ComponentLogger("module_name")

_logger.info("event_name", param1=value1, param2=value2)
_logger.error("error_occurred", error_type=type(e).__name__, error=str(e))
```

#### ✅ Modules migrés (12/12 - 100%)
- **Racine** : bot.py, cache.py, cache_loader.py, config.py, db.py, scheduler.py
- **Core** : functions.py, translation.py, reliability.py, rate_limiter.py, performance_profiler.py, cache_audit.py
- **Total** : 326+ appels `logging.*` → événements structurés

#### ✅ Avantages obtenus
- **Cohérence** : Format JSON uniforme dans tous les logs
- **Maintenance** : Un seul point de configuration
- **Performance** : Élimination f-strings coûteuses
- **Monitoring** : Événements nommés pour alerting automatique

## 🔧 Maintenance

- Les logs sont dans `logs/discord-bot.log` au format JSON structuré
- Le cache est géré automatiquement avec TTL
- Les scripts SQL de migration doivent être numérotés chronologiquement
- Logs ComponentLogger avec événements nommés pour monitoring avancé