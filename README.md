# MyGuildManager

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)
[![Discord](https://img.shields.io/badge/Discord-Bot-5865F2.svg)](https://discord.com/developers/docs)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen.svg)]()
[![Observability](https://img.shields.io/badge/Observability-Enterprise%20Grade-gold.svg)]()
[![Performance](https://img.shields.io/badge/Performance-100%2F100-success.svg)]()
[![SLO](https://img.shields.io/badge/SLO-Availability%20%7C%20Performance-blue.svg)]()

**MyGuildManager** est un bot Discord open source avancé, développé en Python avec [Pycord](https://docs.pycord.dev/), spécialement conçu pour automatiser la gestion complexe des guildes dans les jeux en ligne.

Initialement optimisé pour **Throne and Liberty**, son architecture modulaire permet une extension facile vers d'autres MMORPGs.

---

## 🚀 Objectif & Enterprise-Grade Architecture

Automatiser **jusqu'à 95% des tâches administratives** des guildes Discord avec une architecture **enterprise-grade** :

### 🎯 **Production Ready** (Août 2025)
- 📊 **Observabilité complète** - Correlation ID UUID8 + logs structurés JSON schema v1.0
- 🎯 **Alerting intelligent** - Performance (fast%/slow%) + health monitoring temps réel
- 📈 **SLO tracking** - Availability & Performance avec seuils configurables  
- 🔒 **Production security** - PII masking automatique + secrets management
- 💾 **Memory debugging** - tracemalloc + SIGUSR1/SIGBREAK cross-platform

### ⚡ **Performance Exceptionnelle** 
- **Score startup** : 100/100 (A+ Excellent) + observabilité complète
- **Database async pur** : Migration asyncmy pour performances natives
- **Cache intelligent** : O(1) percentiles + deque rate limiter optimisé haute charge
- **Bounded operations** : Shutdown garanti + aiohttp connector closure
- **Watchdog robuste** : Heartbeat mechanism anti-deadlock avec alerting

---

## ✨ Fonctionnalités principales

### 🎮 Gestion de guilde
- **Initialisation automatique** - Configuration complète en une commande
- **Gestion des rôles** - Attribution automatique selon le statut en jeu
- **Système d'absence** - Forums dédiés avec notifications intelligentes
- **Events & Attendance** - Planification avec suivi DKP automatisé

### 💎 Fonctionnalités avancées
- **Epic Items Scraper** - Import automatique des objets depuis questlog.gg
- **Loot Wishlist** - Système de souhaits avec autocomplétion et conflits
- **Static Groups** - Organisation des groupes PvP avec équilibrage
- **Recruitment** - Candidatures automatisées avec validation diplomatique
- **Diplomacy** - Gestion des diplomates automatisée avec validation

### 🔧 Architecture Enterprise & Observabilité
- **Correlation ID tracking** - Traçage UUID8 complet logs ↔ métriques avec collision detection
- **Structured logging** - JSON schema v1.0 + PII masking production automatique
- **Performance alerting** - Fast% chute/slow% spike intelligent avec cooldown anti-spam
- **SLO monitoring** - Availability & Performance tracking temps réel avec thresholds
- **Health monitoring** - Cache, reconnections, watchdog, memory proactif
- **Production hardening** - Bounded shutdown + cross-platform signals + tracemalloc
- **Cache optimisé** - O(1) percentiles + lazy dirty flag + TTL intelligent
- **Rate limiting** - deque O(1) + cleanup adaptatif haute charge
- **Circuit breakers** - Protection pannes services externes avec reliability system

---

## 🏗️ Architecture

```
app/                    # 🎯 Code applicatif principal
├── bot.py             # Point d'entrée et orchestration
├── cache.py           # Système de cache global TTL
├── db.py              # Couche d'abstraction async MySQL/MariaDB (asyncmy)
├── scheduler.py       # Planificateur de tâches cron
├── core/              # 🔧 Modules utilitaires partagés
│   ├── translation.py # Système multilingue
│   ├── reliability.py # Gestion de la résilience
│   └── rate_limiter.py # Protection anti-spam
└── cogs/              # 📦 Extensions Discord modulaires
    ├── epic_items_scraper.py
    ├── loot_wishlist.py
    └── [10+ autres modules]
```

**Architecture highlights :**
- 🏎️ Cache-first avec TTL intelligent
- 🔄 Imports relatifs pour la portabilité
- 🛡️ Séparation stricte des responsabilités
- 📈 Scalabilité horizontale prête

---

## 🚀 Installation rapide

### Prérequis
- **Python 3.10+**
- **MariaDB/MySQL 10.2+**
- **Discord Bot Token**

### 1. Installation
```bash
# Cloner le projet
git clone https://github.com/Romain-Grosos/discord-bot-mgm.git
cd discord-bot-mgm

# Installer les dépendances
pip install -r requirements.txt
# ou
make install
```

### 2. Configuration
```bash
# Copier la configuration
cp .env.example app/.env

# Éditer app/.env
nano app/.env
```

**Variables essentielles :**
```env
BOT_TOKEN=your_discord_bot_token_here
DB_HOST=localhost
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=discord_bot_mgm

# 🎯 NOUVEAU - Configuration observabilité enterprise
PRODUCTION=False                    # True pour PII masking automatique
LOG_FORMAT_JSON=True               # Logs JSON structurés schema v1.0
ALERT_FAST_PERCENT_MIN=60          # Seuil alerte fast% chute
ALERT_SLOW_PERCENT_MAX=10          # Seuil alerte slow% spike
SLO_P95_TARGET_MS=2000            # Target SLO P95 performance
TRACEMALLOC_ENABLED=False         # Memory debugging avancé
COLD_START_SECONDS=300            # Période chauffe sans fausses alertes
```

### 3. Base de données
```bash
# Créer la base de données
mysql -u root -p -e "CREATE DATABASE discord_bot_mgm;"

# Importer le schéma
mysql -u your_user -p discord_bot_mgm < sql/schema/schema_structure.sql
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

---

## 📦 Technologies & Stack

| Composant | Technologie | Version | Usage |
|-----------|-------------|---------|-------|
| **Runtime** | Python | 3.10+ | Langage principal |
| **Discord API** | Pycord | 2.6.1 | Interactions Discord |
| **Database** | MariaDB | 10.2+ | Persistance des données |
| **Web Scraping** | Selenium + BeautifulSoup | 4.25.0 + 4.12.3 | Import données jeu |
| **HTTP Client** | aiohttp | 3.10.10 | Requêtes async hardened |
| **Timezone** | pytz | 2024.2 | Gestion fuseaux horaires |
| **Testing** | pytest + pytest-cov | 8.3.3 | Tests et couverture |
| **🎯 Observability** | Structured Logging | JSON v1.0 | Logs enterprise + PII masking |
| **🎯 Correlation** | UUID | Python stdlib | Traçage requests + collision detect |
| **🎯 Memory Debug** | tracemalloc | Python stdlib | Debugging SIGUSR1/SIGBREAK |
| **🎯 Performance** | psutil | Latest | Monitoring ressources + alerting |

---

## 📊 Statut du projet

### 🎯 Version actuelle : **v2.0.0-Enterprise** (Août 2025)

| Module | Statut | Couverture Tests | Notes Enterprise |
|--------|--------|------------------|------------------|
| **Core Bot + Observability** | ✅ Production | 95% | Enterprise-grade ready |
| **Cache System Optimized** | ✅ Production | 95% | O(1) + TTL intelligence |
| **Epic Items** | ✅ Production | 80% | Scraping questlog.gg optimisé |
| **Loot Wishlist** | ✅ Production | 85% | Autocomplétion + collision detect |
| **Guild Management** | ✅ Production | 85% | Multi-serveurs + SLO monitoring |
| **🎯 Correlation Tracking** | ✅ Production | 90% | UUID8 logs ↔ métriques |
| **🎯 Performance Alerting** | ✅ Production | 85% | Fast%/slow% intelligent |
| **🎯 Health Monitoring** | ✅ Production | 80% | SLO availability/performance |

### 📈 Métriques Enterprise
- **15 cogs** fonctionnels + observabilité complète
- **1500+ lignes** de tests avec enterprise coverage
- **Multi-serveurs** supporté avec correlation tracking
- **5 langues** disponibles + structured logging
- **Score performance** : 100/100 (A+ Excellent)
- **SLO tracking** : Availability & Performance temps réel
- **Memory debugging** : tracemalloc + cross-platform signals

---

## 🛠️ Développement

### Tests
```bash
# Tests simples
python -m pytest tests/

# Avec couverture
python tests/run_tests_with_coverage.py

# Tests continus
make test
```

### Structure des contributions
```bash
# Mise à jour des imports
python scripts/update_cog_imports.py

# Nettoyage
make clean

# Documentation
# Voir docs/STRUCTURE.md et docs/COVERAGE.md
```

---

## 📋 Feuille de route Enterprise

### ✅ **ACCOMPLI : Observabilité Enterprise-Grade** (Août 2025)
- ✅ **Correlation ID tracking** - UUID8 complet logs ↔ métriques
- ✅ **Structured JSON logging** - Schema v1.0 + PII masking production
- ✅ **Performance alerting** - Fast%/slow% intelligent avec cooldown  
- ✅ **SLO monitoring** - Availability & Performance temps réel
- ✅ **Health monitoring** - Cache, reconnections, watchdog proactif
- ✅ **Production hardening** - Bounded shutdown + cross-platform signals

### 🎯 Court terme (Q4 2025) - Post-Observability
- [ ] **Export Prometheus** - Métriques enterprise vers endpoint `/metrics`  
- [ ] **Dashboard Grafana** - Visualisation SLO + correlation analytics
- [ ] **Alerting externe** - Webhooks/Slack basés sur health monitoring
- [ ] **OpenTelemetry traces** - Distributed tracing avec correlation ID
- [ ] **Documentation enterprise** - Runbooks observability production

### 🚀 Moyen terme (2026) - Enterprise Ready
- [ ] **API REST monitoring** - Endpoints métriques + health checks
- [ ] **Multi-instance support** - Redis shared state avec correlation
- [ ] **Advanced analytics** - Correlation patterns + performance insights  
- [ ] **Dashboard web premium** - Configuration + observability intégrée
- [ ] **Support multi-jeux** - Extension WoW/FFXIV avec observability

### 🌟 Long terme (2026+) - Enterprise SaaS
- [ ] **SaaS hébergé premium** - Observability-as-a-Service intégrée
- [ ] **Marketplace plugins** - Ecosystem avec observability standards
- [ ] **Advanced ML analytics** - Pattern detection sur correlation data
- [ ] **Enterprise integrations** - Datadog, New Relic, PagerDuty native

---

## 🤝 Contribuer

Les contributions sont **fortement encouragées** ! 

📖 **Guide complet :** [`CONTRIBUTING.md`](CONTRIBUTING.md)

### Démarrage rapide
1. Fork le projet
2. Créer une branche : `git checkout -b feature/amazing-feature`
3. Coder selon les standards du projet
4. Tester : `python -m pytest tests/`
5. Commiter : `git commit -m "FEAT(scope): description"`
6. Push : `git push origin feature/amazing-feature`
7. Ouvrir une Pull Request

### 💡 Idées de contributions Enterprise
- 🐛 **Corrections de bugs** - Avec correlation ID pour debugging
- ✨ **Nouvelles fonctionnalités** - Intégrant observability by design
- 📊 **Métriques additionnelles** - Enrichissement SLO monitoring  
- 🎯 **Alerting amélioré** - Nouveaux triggers health monitoring
- 📚 **Documentation enterprise** - Runbooks, dashboards, alerting
- 🧪 **Tests observability** - Coverage correlation + performance
- 🌍 **Traductions + structured logs** - Multilangue avec JSON schema

---

## 📞 Support & Communauté

- 🐛 **Bugs** : [Issues GitHub](https://github.com/votre-username/discord-bot-mgm/issues)
- 💡 **Suggestions** : [Discussions GitHub](https://github.com/votre-username/discord-bot-mgm/discussions)
- 📖 **Documentation** : [`docs/`](docs/)
- 🏗️ **Architecture** : [`docs/STRUCTURE.md`](docs/STRUCTURE.md)

---

## 📜 Licence

Ce projet est sous licence **Apache 2.0** - voir [`LICENSE`](LICENSE) pour les détails.

```
Copyright 2025 MyGuildManager Contributors

Licensed under the Apache License, Version 2.0
```

---

## 🙏 Remerciements

- 🌟 **Contributeurs** - Merci à tous ceux qui font évoluer le projet
- 🎮 **Communauté T&L** - Les testeurs des premières guildes  
- 🐍 **Pycord Team** - Pour leur excellente librairie Discord
- 🛠️ **Open Source** - L'écosystème qui rend tout cela possible

---

<div align="center">

**MyGuildManager** - *Conçu par des passionnés, pour des passionnés*

*Que votre guilde soit casual ou hardcore, automatisez l'administration et concentrez-vous sur l'essentiel : le jeu !*

[⭐ Star le projet](https://github.com/votre-username/discord-bot-mgm) • [🐛 Signaler un bug](https://github.com/votre-username/discord-bot-mgm/issues) • [💡 Proposer une feature](https://github.com/votre-username/discord-bot-mgm/discussions)

</div>