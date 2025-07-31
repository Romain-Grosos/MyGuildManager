#!/usr/bin/env python3
"""
Test runner with coverage metrics for Discord Bot project.
Generates comprehensive coverage reports in multiple formats.
"""

import subprocess
import sys
import os
import logging
from pathlib import Path

def setup_logging():
    """Setup logging for the test runner."""
    # Configure stdout to use UTF-8 encoding on Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

def run_tests_with_coverage():
    """Run tests with coverage analysis."""
    logger = logging.getLogger(__name__)
    
    # Ensure we're in the project directory
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    logger.info("🧪 Starting test execution with coverage analysis...")
    
    try:
        # Run pytest with coverage
        cmd = [
            sys.executable, "-m", "pytest",
            "tests/",
            "--cov=.",
            "--cov-report=html",
            "--cov-report=term-missing",
            "--cov-report=xml",
            "--cov-config=.coveragerc",
            "-v"
        ]
        
        logger.info(f"📋 Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Print stdout
        if result.stdout:
            print("\n" + "="*80)
            print("TEST OUTPUT:")
            print("="*80)
            print(result.stdout)
        
        # Print stderr if there are errors
        if result.stderr:
            print("\n" + "="*80)
            print("ERRORS/WARNINGS:")
            print("="*80)
            print(result.stderr)
        
        # Check if tests passed
        if result.returncode == 0:
            logger.info("✅ All tests passed successfully!")
            
            # Check if HTML report was generated
            html_report = project_root / "htmlcov" / "index.html"
            if html_report.exists():
                logger.info(f"📊 HTML coverage report generated: {html_report}")
                logger.info("   Open this file in your browser to view detailed coverage")
            
            # Check if XML report was generated
            xml_report = project_root / "coverage.xml"
            if xml_report.exists():
                logger.info(f"📄 XML coverage report generated: {xml_report}")
            
            return True
        else:
            logger.error(f"❌ Tests failed with return code: {result.returncode}")
            return False
            
    except FileNotFoundError:
        logger.error("❌ pytest or coverage not found. Please install with: pip install pytest pytest-cov")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error running tests: {e}")
        return False

def generate_coverage_summary():
    """Generate a summary of coverage metrics."""
    logger = logging.getLogger(__name__)
    
    try:
        # Run coverage report to get summary
        cmd = [sys.executable, "-m", "coverage", "report", "--format=text"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("\n📈 COVERAGE SUMMARY:")
            logger.info("="*50)
            print(result.stdout)
        else:
            logger.warning("⚠️  Could not generate coverage summary")
            
    except Exception as e:
        logger.warning(f"⚠️  Error generating coverage summary: {e}")

def main():
    """Main execution function."""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("🚀 Discord Bot - Test Coverage Analysis")
    logger.info("="*50)
    
    success = run_tests_with_coverage()
    
    if success:
        generate_coverage_summary()
        logger.info("\n🎯 Coverage analysis completed successfully!")
        logger.info("📂 Reports available in:")
        logger.info("   - htmlcov/index.html (HTML report)")
        logger.info("   - coverage.xml (XML report)")
        sys.exit(0)
    else:
        logger.error("\n💥 Coverage analysis failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()