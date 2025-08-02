"""
Test runner script - Executes all tests with comprehensive reporting.
"""

import os
import sys
import subprocess
import time
import argparse
from pathlib import Path

def run_command(command, description):
    """Execute command and return results."""
    print(f"\n{'='*60}")
    print(f"TEST: {description}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
            executable='cmd.exe' if os.name == 'nt' else None
        )
        
        execution_time = time.time() - start_time
        
        print(f"Execution time: {execution_time:.2f}s")
        print(f"Exit code: {result.returncode}")
        
        if result.stdout:
            print(f"\nOutput:")
            print(result.stdout)
        
        if result.stderr:
            print(f"\nErrors:")
            print(result.stderr)
        
        return result.returncode == 0, execution_time
    
    except Exception as e:
        print(f"FAILED to execute command: {e}")
        return False, 0

def check_dependencies():
    """Check if required dependencies are installed."""
    print("Checking test dependencies...")
    
    try:
        import pytest
        print(f"OK - pytest {pytest.__version__} found")
    except ImportError:
        print("ERROR - pytest not found. Install with: pip install pytest pytest-asyncio")
        return False
    
    try:
        import pytest_asyncio
        print(f"OK - pytest-asyncio found")
    except ImportError:
        print("ERROR - pytest-asyncio not found. Install with: pip install pytest-asyncio")
        return False
    
    return True

def run_test_suite(test_type="all", verbose=False, coverage=False):
    """Run specific test suite or all tests."""
    
    if not check_dependencies():
        return False
    
    tests_dir = Path(__file__).parent
    project_root = tests_dir.parent
    
    print(f"\nTests directory: {tests_dir}")
    print(f"Project root: {project_root}")
    
    base_command = f"python -m pytest"
    
    if verbose:
        base_command += " -v -s"
    
    if coverage:
        base_command += f" --cov={project_root} --cov-report=html --cov-report=term"
    
    test_suites = {
        "cache": {
            "file": "test_cache.py",
            "description": "Cache System Tests"
        },
        "db": {
            "file": "test_db.py", 
            "description": "Database System Tests"
        },
        "reliability": {
            "file": "test_reliability.py",
            "description": "Reliability System Tests"
        },
        "integration": {
            "file": "test_integration.py",
            "description": "Integration Tests"
        }
    }
    
    results = {}
    total_time = 0
    
    if test_type == "all":
        for suite_name, suite_info in test_suites.items():
            command = f"{base_command} {tests_dir}/{suite_info['file']}"
            success, exec_time = run_command(command, suite_info['description'])
            results[suite_name] = success
            total_time += exec_time
    elif test_type in test_suites:
        suite_info = test_suites[test_type]
        command = f"{base_command} {tests_dir}/{suite_info['file']}"
        success, exec_time = run_command(command, suite_info['description'])
        results[test_type] = success
        total_time += exec_time
    else:
        print(f"ERROR - Unknown test type: {test_type}")
        print(f"Available types: {', '.join(test_suites.keys())}, all")
        return False
    
    print(f"\n{'='*60}")
    print("TEST RESULTS SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, success in results.items():
        status = "PASSED" if success else "FAILED"
        print(f"{test_name:15} {status}")
    
    print(f"\nOverall: {passed}/{total} test suites passed")
    print(f"Total execution time: {total_time:.2f}s")
    
    if passed == total:
        print("\nAll tests passed successfully!")
        return True
    else:
        print(f"\n{total - passed} test suite(s) failed")
        return False

def run_quick_validation():
    """Run quick validation checks before full tests."""
    print("Running quick validation checks...")
    
    print("\nTesting direct imports...")
    
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    try:
        import cache
        print("OK - Cache module import: SUCCESS")
    except Exception as e:
        print(f"ERROR - Cache module import: FAILED - {e}")
        return False
    
    try:
        import pytest
        print(f"OK - pytest {pytest.__version__}: SUCCESS")
    except Exception as e:
        print(f"ERROR - pytest: FAILED - {e}")
        return False
    
    try:
        import pytest_asyncio
        print("OK - pytest-asyncio: SUCCESS")
    except Exception as e:
        print(f"ERROR - pytest-asyncio: FAILED - {e}")
        return False
    
    print("SUCCESS - Quick validation: All checks passed")
    return True

def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(description="Discord Bot Test Runner")
    parser.add_argument(
        "--type", 
        choices=["all", "cache", "db", "reliability", "integration", "quick"],
        default="all",
        help="Type of tests to run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--coverage", "-c",
        action="store_true", 
        help="Generate coverage report"
    )
    parser.add_argument(
        "--quick-check",
        action="store_true",
        help="Run quick validation before tests"
    )
    
    args = parser.parse_args()
    
    print("Discord Bot MGM - Test Suite")
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    
    if args.quick_check or args.type == "quick":
        if not run_quick_validation():
            print("ERROR - Quick validation failed. Fix import issues before running full tests.")
            return 1
        
        if args.type == "quick":
            return 0
    
    success = run_test_suite(
        test_type=args.type,
        verbose=args.verbose,
        coverage=args.coverage
    )
    
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)