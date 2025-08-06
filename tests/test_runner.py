#!/usr/bin/env python3
"""
Test Runner - Point d'entrée unique pour tous les tests du Discord Bot MGM

Usage:
    python tests/test_runner.py                    # Tous les tests avec coverage
    python tests/test_runner.py --unit             # Tests unitaires seulement
    python tests/test_runner.py --integration      # Tests d'intégration seulement
    python tests/test_runner.py --cog absence      # Tests d'un cog spécifique
    python tests/test_runner.py --core             # Tests des modules core
    python tests/test_runner.py --fast             # Tests rapides seulement
    python tests/test_runner.py --coverage-only    # Génère le rapport de coverage
    python tests/test_runner.py --html             # Ouvre le rapport HTML
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import List, Optional

# Configuration des couleurs pour la console
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'  
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def colored(text: str, color: str) -> str:
    """Applique une couleur au texte si supporté par le terminal."""
    if os.name == 'nt' and not os.getenv('FORCE_COLOR'):
        return text  # Pas de couleurs sur Windows par défaut
    return f"{color}{text}{Colors.END}"

def setup_logging():
    """Configure le système de logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

class TestRunner:
    """Gestionnaire principal pour l'exécution des tests."""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.tests_dir = Path(__file__).parent
        self.logger = logging.getLogger(__name__)
        
    def check_dependencies(self) -> bool:
        """Vérifie que toutes les dépendances sont installées."""
        required_packages = [
            'pytest',
            'pytest_asyncio', 
            'pytest_cov',
            'coverage'
        ]
        
        missing = []
        for package in required_packages:
            try:
                __import__(package.replace('-', '_'))
                self.logger.info(f"OK {package} trouve")
            except ImportError:
                missing.append(package)
                
        if missing:
            self.logger.error(f"Paquets manquants: {', '.join(missing)}")
            self.logger.error("Installez avec: pip install -r tests/requirements_test.txt")
            return False
            
        return True
    
    def get_test_files(self, filter_type: Optional[str] = None, 
                      cog_name: Optional[str] = None,
                      core_only: bool = False) -> List[str]:
        """Obtient la liste des fichiers de test à exécuter."""
        test_files = []
        
        if filter_type == "unit":
            test_files.extend([
                "tests/core/",
                "tests/cogs/", 
                "tests/utils/"
            ])
        elif filter_type == "integration":
            test_files.extend([
                "tests/integration/"
            ])
        elif cog_name:
            cog_test = f"tests/cogs/test_{cog_name}.py"
            if Path(cog_test).exists():
                test_files.append(cog_test)
            else:
                self.logger.warning(f"Test pour le cog '{cog_name}' non trouvé: {cog_test}")
        elif core_only:
            test_files.extend([
                "tests/core/"
            ])
        else:
            # Tous les tests par défaut
            test_files.extend([
                "tests/core/",
                "tests/cogs/",
                "tests/utils/",
                "tests/integration/"
            ])
            
        return test_files
    
    def build_pytest_command(self, test_files: List[str], 
                            coverage: bool = True,
                            fast: bool = False,
                            verbose: bool = True) -> List[str]:
        """Construit la commande pytest."""
        cmd = [sys.executable, "-m", "pytest"]
        
        # Ajouter les fichiers de test
        cmd.extend(test_files)
        
        # Options de base
        if verbose:
            cmd.append("-v")
        
        cmd.append("--tb=short")
        
        # Marqueurs pour les tests rapides
        if fast:
            cmd.extend(["-m", "not slow"])
            
        # Configuration de coverage
        if coverage:
            cmd.extend([
                "--cov=app",
                "--cov=run_bot.py", 
                "--cov-report=html:htmlcov",
                "--cov-report=term-missing:skip-covered",
                "--cov-report=xml",
                "--cov-config=tests/.coveragerc"
            ])
            
        # Support asyncio
        cmd.extend([
            "--asyncio-mode=auto",
            "--disable-warnings"
        ])
        
        return cmd
    
    def run_tests(self, cmd: List[str]) -> tuple[bool, float, str, str]:
        """Exécute les tests et retourne les résultats."""
        start_time = time.time()
        
        self.logger.info(f"Execution: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=600  # 10 minutes max
            )
            
            execution_time = time.time() - start_time
            success = result.returncode == 0
            
            return success, execution_time, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            self.logger.error("Tests interrompus (timeout de 10 minutes)")
            return False, time.time() - start_time, "", "Timeout expired"
        except Exception as e:
            self.logger.error(f"Erreur lors de l'execution: {e}")
            return False, time.time() - start_time, "", str(e)
    
    def display_results(self, success: bool, execution_time: float,
                       stdout: str, stderr: str):
        """Affiche les résultats des tests."""
        print("\n" + "="*80)
        
        if success:
            print(colored("TESTS REUSSIS", Colors.GREEN + Colors.BOLD))
        else:
            print(colored("TESTS ECHOUES", Colors.RED + Colors.BOLD))
            
        print(f"Temps d'execution: {execution_time:.2f}s")
        print("="*80)
        
        if stdout:
            print("\nSORTIE DES TESTS:")
            print("-" * 40)
            print(stdout)
            
        if stderr:
            print("\nERREURS/AVERTISSEMENTS:")
            print("-" * 40)
            print(stderr)
    
    def generate_coverage_summary(self) -> bool:
        """Génère un résumé du coverage."""
        try:
            cmd = [sys.executable, "-m", "coverage", "report", "--format=text"]
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=self.project_root
            )
            
            if result.returncode == 0:
                print("\nRESUME DU COVERAGE:")
                print("="*50) 
                print(result.stdout)
                return True
            else:
                self.logger.warning("Impossible de generer le resume de coverage")
                return False
                
        except Exception as e:
            self.logger.error(f"Erreur generation coverage: {e}")
            return False
    
    def open_html_report(self) -> bool:
        """Ouvre le rapport HTML de coverage."""
        html_file = self.project_root / "htmlcov" / "index.html"
        
        if html_file.exists():
            try:
                webbrowser.open(f"file://{html_file.absolute()}")
                self.logger.info(f"Rapport HTML ouvert: {html_file}")
                return True
            except Exception as e:
                self.logger.error(f"Impossible d'ouvrir le rapport HTML: {e}")
                return False
        else:
            self.logger.warning("Rapport HTML non trouve. Executez d'abord les tests avec --coverage.")
            return False
    
    def validate_environment(self) -> bool:
        """Valide l'environnement avant l'exécution des tests."""
        # Vérifier la structure des tests
        required_dirs = ['core', 'cogs', 'integration', 'utils']
        for dir_name in required_dirs:
            test_dir = self.tests_dir / dir_name
            if not test_dir.exists():
                self.logger.warning(f"Repertoire de tests manquant: {test_dir}")
                
        # Vérifier les fichiers de configuration
        config_files = ['.coveragerc', 'pyproject.toml', 'conftest.py']
        for config_file in config_files:
            config_path = self.tests_dir / config_file
            if not config_path.exists():
                self.logger.warning(f"Fichier de configuration manquant: {config_path}")
                
        return True

def main():
    """Fonction principale."""
    parser = argparse.ArgumentParser(
        description="Test Runner pour Discord Bot MGM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  python tests/test_runner.py                     # Tous les tests avec coverage
  python tests/test_runner.py --unit              # Tests unitaires seulement  
  python tests/test_runner.py --integration       # Tests d'intégration seulement
  python tests/test_runner.py --cog absence       # Tests pour le cog 'absence'
  python tests/test_runner.py --core              # Tests des modules core seulement
  python tests/test_runner.py --fast              # Tests rapides (sans les lents)
  python tests/test_runner.py --no-coverage       # Sans rapport de coverage
  python tests/test_runner.py --html              # Ouvre le rapport HTML existant
        """
    )
    
    # Options principales
    parser.add_argument('--unit', action='store_true',
                       help='Exécuter uniquement les tests unitaires')
    parser.add_argument('--integration', action='store_true', 
                       help='Exécuter uniquement les tests d\'intégration')
    parser.add_argument('--cog', type=str,
                       help='Exécuter les tests pour un cog spécifique')
    parser.add_argument('--core', action='store_true',
                       help='Exécuter uniquement les tests des modules core')
    parser.add_argument('--fast', action='store_true',
                       help='Exécuter uniquement les tests rapides (sans marker slow)')
    
    # Options de coverage
    parser.add_argument('--no-coverage', action='store_true',
                       help='Désactiver le rapport de coverage')
    parser.add_argument('--coverage-only', action='store_true',
                       help='Générer uniquement le rapport de coverage (sans tests)')
    parser.add_argument('--html', action='store_true',
                       help='Ouvrir le rapport HTML de coverage')
    
    # Options de sortie
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Mode silencieux (moins de verbosité)')
    parser.add_argument('--debug', action='store_true',
                       help='Mode debug (plus de verbosité)')
    
    args = parser.parse_args()
    
    # Configuration du logging
    setup_logging()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    
    runner = TestRunner()
    
    print(colored("TEST DISCORD BOT MGM - TEST RUNNER", Colors.CYAN + Colors.BOLD))
    print(colored("="*50, Colors.CYAN))
    
    # Cas spéciaux
    if args.html:
        runner.open_html_report()
        return 0
        
    if args.coverage_only:
        runner.generate_coverage_summary()
        return 0
    
    # Validation de l'environnement
    if not runner.check_dependencies():
        return 1
        
    runner.validate_environment()
    
    # Déterminer les tests à exécuter
    filter_type = None
    if args.unit:
        filter_type = "unit"
    elif args.integration:
        filter_type = "integration"
        
    test_files = runner.get_test_files(
        filter_type=filter_type,
        cog_name=args.cog,
        core_only=args.core
    )
    
    if not test_files:
        runner.logger.error("Aucun fichier de test trouve")
        return 1
    
    # Construire et exécuter la commande pytest
    cmd = runner.build_pytest_command(
        test_files=test_files,
        coverage=not args.no_coverage,
        fast=args.fast,
        verbose=not args.quiet
    )
    
    success, exec_time, stdout, stderr = runner.run_tests(cmd)
    
    # Afficher les résultats
    runner.display_results(success, exec_time, stdout, stderr)
    
    # Générer le résumé de coverage si activé
    if not args.no_coverage and success:
        runner.generate_coverage_summary()
        
        # Informations sur les rapports générés
        print(f"\nRapports disponibles:")
        print(f"   HTML: htmlcov/index.html")
        print(f"   XML:  coverage.xml") 
        print(f"   Utilisation: python tests/test_runner.py --html")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())