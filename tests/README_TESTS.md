# 🧪 Discord Bot MGM - Suite de Tests Moderne

**Suite de tests complète et professionnelle pour le Discord Bot MGM avec coverage automatique et architecture moderne.**

## 📋 Table des Matières

- [🚀 Démarrage Rapide](#-démarrage-rapide)
- [🏗️ Architecture des Tests](#️-architecture-des-tests)
- [🔧 Installation](#-installation) 
- [💻 Utilisation](#-utilisation)
- [📊 Coverage et Rapports](#-coverage-et-rapports)
- [🎯 Types de Tests](#-types-de-tests)
- [📝 Écrire de Nouveaux Tests](#-écrire-de-nouveaux-tests)
- [🔍 Dépannage](#-dépannage)
- [⚙️ Configuration Avancée](#️-configuration-avancée)

## 🚀 Démarrage Rapide

### Installation des Dépendances
```bash
pip install -r tests/requirements_test.txt
```

### Exécuter Tous les Tests avec Coverage
```bash
python tests/test_runner.py
```

### Ouvrir le Rapport HTML
```bash
python tests/test_runner.py --html
```

## 🏗️ Architecture des Tests

```
tests/
├── 📁 core/                        # Tests des modules core/
│   ├── test_translation.py         # Système de traduction
│   ├── test_functions.py           # Fonctions utilitaires
│   ├── test_rate_limiter.py        # Rate limiting
│   └── test_*.py                   # Autres modules core
├── 📁 cogs/                        # Tests des cogs Discord
│   ├── test_absence.py             # Gestion des absences  
│   ├── test_guild_members.py       # Gestion des membres
│   ├── test_guild_events.py        # Événements de guilde
│   └── test_*.py                   # Autres cogs
├── 📁 integration/                 # Tests d'intégration
│   ├── test_translation_integration.py  # Intégration traduction
│   ├── test_bot_startup.py         # Démarrage du bot
│   └── test_*.py                   # Autres intégrations
├── 📁 utils/                       # Tests utilitaires
│   ├── test_config.py              # Configuration
│   └── test_*.py                   # Autres utilitaires
├── 🔧 conftest.py                  # Configuration pytest globale
├── 🚀 test_runner.py               # Point d'entrée unique
├── 📋 requirements_test.txt        # Dépendances tests
├── ⚙️ pyproject.toml               # Configuration moderne
├── 📊 .coveragerc                  # Configuration coverage
└── 📚 README_TESTS.md              # Cette documentation
```

## 🔧 Installation

### 1. Prérequis
- Python 3.9+
- Accès au projet Discord Bot MGM
- Dépendances du bot installées

### 2. Installation des Dépendances de Test
```bash
# Installation des dépendances de test
pip install -r tests/requirements_test.txt

# Vérification de l'installation
python tests/test_runner.py --help
```

### 3. Vérification de l'Environnement
```bash
# Test rapide de validation
python tests/test_runner.py --fast
```

## 💻 Utilisation

### Commands Principales

```bash
# 🔥 EXÉCUTION COMPLÈTE
python tests/test_runner.py                    # Tous les tests + coverage

# 🎯 TESTS SPÉCIFIQUES
python tests/test_runner.py --unit             # Tests unitaires seulement
python tests/test_runner.py --integration      # Tests d'intégration seulement
python tests/test_runner.py --core             # Modules core/ seulement
python tests/test_runner.py --cog absence      # Cog spécifique

# ⚡ TESTS RAPIDES
python tests/test_runner.py --fast             # Tests rapides (sans marker slow)
python tests/test_runner.py --unit --fast      # Tests unitaires rapides

# 📊 COVERAGE
python tests/test_runner.py --no-coverage      # Sans rapport coverage
python tests/test_runner.py --coverage-only    # Générer rapport seulement
python tests/test_runner.py --html             # Ouvrir rapport HTML

# 🔍 MODES DE SORTIE
python tests/test_runner.py --quiet            # Mode silencieux
python tests/test_runner.py --debug            # Mode debug détaillé
```

### Exemples d'Usage Courants

```bash
# Développement quotidien - tests rapides
python tests/test_runner.py --unit --fast

# Avant commit - suite complète
python tests/test_runner.py

# Debug d'un problème spécifique
python tests/test_runner.py --cog guild_members --debug

# Vérifier la couverture d'un module
python tests/test_runner.py --core --html

# Tests d'intégration avant déploiement
python tests/test_runner.py --integration
```

## 📊 Coverage et Rapports

### Types de Rapports Générés

1. **Rapport Terminal** - Résumé dans la console
2. **Rapport HTML** - Détaillé avec navigation (`htmlcov/index.html`)
3. **Rapport XML** - Pour outils CI/CD (`coverage.xml`)

### Métriques de Coverage

- **Objectif Global**: >80% de couverture
- **Modules Core**: >90% de couverture
- **Cogs Principaux**: >75% de couverture
- **Tests d'Intégration**: >70% de couverture

### Interprétation des Rapports

```bash
# Génération et ouverture du rapport HTML
python tests/test_runner.py --html

# Structure du rapport:
htmlcov/
├── index.html          # Page principale avec résumé
├── app_*.html          # Coverage par fichier
└── status.json         # Données JSON pour outils
```

## 🎯 Types de Tests

### 1. Tests Unitaires (`tests/core/`, `tests/cogs/`)
- **Objectif**: Tester des fonctions/méthodes isolées
- **Marqueurs**: `@pytest.mark.unit`, `@pytest.mark.core`, `@pytest.mark.cog`
- **Exemple**:
```python
@pytest.mark.unit
@pytest.mark.core
def test_sanitize_kwargs():
    from core.functions import sanitize_kwargs
    result = sanitize_kwargs(username="test", level=42)
    assert result == {"username": "test", "level": "42"}
```

### 2. Tests d'Intégration (`tests/integration/`)
- **Objectif**: Tester l'interaction entre composants
- **Marqueurs**: `@pytest.mark.integration`
- **Exemple**:
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_translation_with_cache():
    # Test intégration système traduction + cache
    pass
```

### 3. Tests de Performance (`@pytest.mark.slow`)
- **Objectif**: Tester les performances sous charge
- **Marqueurs**: `@pytest.mark.slow`, `@pytest.mark.performance`

### 4. Tests de Robustesse
- **Objectif**: Tester la gestion d'erreurs et cas limites
- **Marqueurs**: `@pytest.mark.reliability`

## 📝 Écrire de Nouveaux Tests

### Structure Type d'un Test

```python
"""
Tests pour [module] - [Description courte].
"""

import pytest
from unittest.mock import Mock, AsyncMock
from pathlib import Path
import sys

# Configuration du chemin
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

@pytest.mark.[category]  # unit, integration, cog, core
@pytest.mark.asyncio    # Si fonctions async
class Test[ComponentName]:
    """Test [Component] functionality."""
    
    @pytest.fixture
    def mock_component(self):
        """Create mock component for testing."""
        return Mock()
    
    async def test_[specific_functionality](self, mock_component):
        """Test [specific functionality] with clear description."""
        # Arrange
        expected_result = "expected"
        
        # Act
        result = await component_function(mock_component)
        
        # Assert
        assert result == expected_result
```

### Bonnes Pratiques

1. **Noms de Tests Descriptifs**
   ```python
   def test_gs_command_with_valid_value()    # ✅ Bon
   def test_gs()                             # ❌ Mauvais
   ```

2. **Utilisation des Fixtures**
   ```python
   @pytest.fixture
   def mock_bot(self):
       bot = Mock()
       bot.cache = Mock()
       return bot
   ```

3. **Marqueurs Appropriés**
   ```python
   @pytest.mark.unit      # Test unitaire
   @pytest.mark.cog       # Test de cog
   @pytest.mark.slow      # Test lent (>1s)
   @pytest.mark.asyncio   # Test asynchrone
   ```

4. **Assertions Claires**
   ```python
   assert result.status == "success"
   assert len(results) == 3
   assert "error" not in response.content
   ```

### Ajouter un Nouveau Cog

1. **Créer le fichier de test**:
   ```bash
   touch tests/cogs/test_[nom_du_cog].py
   ```

2. **Structure de base**:
   ```python
   @pytest.mark.cog
   @pytest.mark.asyncio
   class Test[NomDuCog]:
       @pytest.fixture
       def [nom_du_cog]_cog(self, mock_bot):
           from app.cogs.[nom_du_cog] import [NomDuCog]
           return [NomDuCog](mock_bot)
   ```

3. **Ajouter les tests de commandes**:
   ```python
   async def test_[commande]_success(self, [nom_du_cog]_cog, mock_ctx):
       await [nom_du_cog]_cog.[commande](mock_ctx, "param")
       mock_ctx.respond.assert_called_once()
   ```

## 🔍 Dépannage

### Problèmes Courants

#### 1. **Erreurs d'Import**
```bash
# Symptôme
ImportError: No module named 'app'

# Solution
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python tests/test_runner.py
```

#### 2. **Tests qui Échouent de Façon Intermittente**
```bash
# Analyser les tests avec plus de verbosité
python tests/test_runner.py --debug

# Isoler un test spécifique
python -m pytest tests/core/test_translation.py::TestTranslationLoading::test_load_translations_success -v
```

#### 3. **Problèmes de Coverage**
```bash
# Vérifier la configuration coverage
cat tests/.coveragerc

# Régénérer complètement le coverage
rm -rf htmlcov coverage.xml
python tests/test_runner.py
```

#### 4. **Tests Lents**
```bash
# Identifier les tests lents
python tests/test_runner.py --debug | grep "slow"

# Exécuter sans les tests lents
python tests/test_runner.py --fast
```

### Debugging Avancé

```bash
# Mode debug complet avec traces
python -m pytest tests/ -v -s --tb=long

# Tests avec profiling
python -m pytest tests/ --profile-svg

# Tests avec coverage détaillé par branche
python tests/test_runner.py --debug
```

## ⚙️ Configuration Avancée

### Variables d'Environnement

```bash
# Configuration pour les tests
export ENVIRONMENT=test
export LOG_LEVEL=DEBUG
export DATABASE_URL=sqlite:///:memory:
export DISCORD_TOKEN=test_token_for_testing
```

### Configuration pytest Personnalisée

Modifier `tests/pyproject.toml`:

```toml
[tool.pytest.ini_options]
# Ajouter des marqueurs personnalisés
markers = [
    "slow: Tests lents (>1s)",
    "database: Tests nécessitant une DB",
    "custom: Tests personnalisés"
]

# Modifier la couverture cible
fail_under = 85
```

### Hooks Personnalisés

Ajouter dans `tests/conftest.py`:

```python
def pytest_configure(config):
    """Configuration personnalisée pytest."""
    config.addinivalue_line("markers", "custom: Description du marqueur")

def pytest_runtest_setup(item):
    """Exécuté avant chaque test."""
    pass
```

### Intégration CI/CD

#### GitHub Actions
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: pip install -r tests/requirements_test.txt
      - name: Run tests with coverage
        run: python tests/test_runner.py
      - name: Upload coverage
        uses: codecov/codecov-action@v1
        with:
          file: coverage.xml
```

### Optimisation des Performances

1. **Tests Parallèles**:
   ```bash
   pip install pytest-xdist
   python -m pytest tests/ -n auto
   ```

2. **Cache des Dépendances**:
   ```python
   # Dans conftest.py
   @pytest.fixture(scope="session")
   def cached_translations():
       # Cache global pour les traductions
   ```

3. **Mock Optimisé**:
   ```python
   # Utiliser des mocks réutilisables
   @pytest.fixture(scope="session")
   def global_mock_bot():
       return create_extensive_bot_mock()
   ```

---

## 📚 Ressources Supplémentaires

- **Documentation Pytest**: https://docs.pytest.org/
- **Coverage.py**: https://coverage.readthedocs.io/
- **Discord.py Testing**: https://discordpy.readthedocs.io/en/stable/testing.html

## 🤝 Contribution

1. **Ajout de Tests**: Suivre les conventions décrites dans ce guide
2. **Modification des Tests**: Maintenir la couverture >80%
3. **Nouveaux Marqueurs**: Documenter dans `pyproject.toml`
4. **Performance**: Marquer les tests lents avec `@pytest.mark.slow`

---

**📞 Support**: En cas de problème, vérifier d'abord la section [Dépannage](#-dépannage) ou analyser les logs avec `--debug`.

**⚡ Conseil**: Utilisez `python tests/test_runner.py --fast` pour les développements rapides et la suite complète avant les commits importants.