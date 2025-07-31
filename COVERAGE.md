# 📊 Test Coverage Guide

## Quick Start

### Run Tests with Coverage
```bash
# Simple command
python -m pytest tests/ --cov=. --cov-report=html --cov-report=term

# Or use the comprehensive script
python run_tests_with_coverage.py
```

### View Results
- **Terminal**: Coverage summary displayed after tests
- **HTML Report**: Open `htmlcov/index.html` in your browser
- **XML Report**: `coverage.xml` for CI/CD integration

## Current Coverage Status

### Overall Coverage: **28.71%**

| Module | Coverage | Key Focus Areas |
|--------|----------|----------------|
| **db.py** | 63.02% | ✅ Well tested |
| **reliability.py** | 61.21% | ✅ Good coverage |
| **cache.py** | 38.63% | ⚠️ Needs improvement |
| **Other modules** | 0.00% | 🔴 Not covered |

## Coverage Exclusions

Configured in `.coveragerc`:
- Test files themselves
- `bot.py` (entry point, hard to test in isolation)
- `performance_profiler.py` (external dependencies)
- Configuration files
- Backup/log directories

## Improving Coverage

### Priority Areas for New Tests:

1. **cache_loader.py** (0% → target 80%)
   - Test guild settings loading
   - Test error handling scenarios

2. **config.py** (0% → target 70%)
   - Test environment variable validation
   - Test configuration edge cases

3. **functions.py** (0% → target 90%)
   - Test translation functions
   - Test input sanitization

4. **scheduler.py** (0% → target 60%)
   - Test cron job scheduling
   - Test task execution flows

### Easy Wins:
- Add unit tests for utility functions
- Test error handling paths
- Test configuration validation

## Advanced Usage

### Generate Coverage Report Only
```bash
python -m coverage report --format=text
```

### Coverage with Branch Analysis
```bash
python -m pytest --cov=. --cov-branch --cov-report=html
```

### Exclude Specific Lines
Add `# pragma: no cover` to lines that shouldn't be covered.

## CI/CD Integration

The `coverage.xml` file is generated for integration with:
- GitHub Actions
- SonarQube  
- CodeCov
- Other CI/CD tools

## Goals

- **Short term**: Reach 50% overall coverage
- **Medium term**: Reach 70% overall coverage  
- **Long term**: Maintain 80%+ coverage for critical modules

---

📈 **Remember**: Coverage is a tool, not a goal. Focus on testing critical paths and edge cases!