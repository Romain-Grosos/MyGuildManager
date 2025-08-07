# MyGuildManager

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org)
[![Discord](https://img.shields.io/badge/Discord-Bot-5865F2.svg)](https://discord.com/developers/docs)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange.svg)]()

**MyGuildManager** est un bot Discord open source avancé, développé en Python avec [Pycord](https://docs.pycord.dev/), spécialement conçu pour automatiser la gestion complexe des guildes dans les jeux en ligne.

Initialement optimisé pour **Throne and Liberty**, son architecture modulaire permet une extension facile vers d'autres MMORPGs.

---

## 🚀 Objectif

Automatiser **jusqu'à 95% des tâches administratives** des guildes Discord tout en offrant :
- ⚡ **Performance** - Cache intelligent et optimisations mémoire
- 🛡️ **Fiabilité** - Système de récupération automatique et circuit breakers
- 🌍 **Multilingue** - Support EN/FR/ES/DE/IT avec fallback automatique
- 📊 **Analytics** - Métriques de performance et monitoring intégré

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

### 🔧 Techniques
- **Cache centralisé** - Système TTL avec maintenance automatique
- **Rate limiting** - Protection anti-spam multiniveau
- **Profiling** - Monitoring des performances en temps réel  
- **Circuit breakers** - Protection contre les pannes de services externes

---

## 🏗️ Architecture

```
app/                    # 🎯 Code applicatif principal
├── bot.py             # Point d'entrée et orchestration
├── cache.py           # Système de cache global TTL
├── db.py              # Couche d'abstraction MariaDB
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
| **HTTP Client** | aiohttp | 3.10.10 | Requêtes async |
| **Timezone** | pytz | 2024.2 | Gestion fuseaux horaires |
| **Testing** | pytest + pytest-cov | 8.3.3 | Tests et couverture |

---

## 📊 Statut du projet

### 🎯 Version actuelle : **v1.2.0-Stable**

| Module | Statut | Couverture Tests | Notes |
|--------|--------|------------------|-------|
| **Core Bot** | ✅ Stable | 85% | Production ready |
| **Cache System** | ✅ Stable | 90% | Optimisé performance |
| **Epic Items** | ✅ Stable | 75% | Scraping questlog.gg |
| **Loot Wishlist** | ✅ Stable | 80% | Autocomplétion avancée |
| **Guild Management** | ✅ Stable | 70% | Multi-serveurs |
| **PTB Integration** | 🔄 Beta | 60% | En amélioration |

### 📈 Métriques
- **15 cogs** fonctionnels
- **1200+ lignes** de tests
- **Multi-serveurs** supporté
- **5 langues** disponibles

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

## 📋 Feuille de route

### 🎯 Court terme (Q4 2025)
- [ ] Stabilisation et optimisations des fonctionnalités existantes
- [ ] Amélioration couverture de tests (objectif 80%+)
- [ ] Documentation utilisateur complète
- [ ] Système de guildes premium (fonctionnalités avancées)

### 🚀 Moyen terme (2026)
- [ ] Dashboard web pour la configuration des guildes premium
- [ ] API REST pour intégrations externes
- [ ] Support multi-jeux (extension WoW, Final Fantasy XIV)
- [ ] Intégrations tierces (Twitch pour les streams de guilde)

### 🌟 Long terme (2026+)
- [ ] Marketplace de plugins communautaires
- [ ] SaaS hébergé pour guildes premium
- [ ] Analytics avancés et tableaux de bord
- [ ] Intégration écosystème gaming étendu

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

### 💡 Idées de contributions
- 🐛 Corrections de bugs
- ✨ Nouvelles fonctionnalités
- 📚 Amélioration documentation
- 🧪 Tests additionnels
- 🌍 Traductions supplémentaires

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