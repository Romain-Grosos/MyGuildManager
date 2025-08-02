# 🧪 Tests - Discord Bot MGM

## 📋 Structure

```
tests/
├── __init__.py              # Package initialization
├── conftest.py             # Pytest configuration and fixtures
├── test_cache.py           # Cache system tests
├── test_db.py              # Database system tests  
├── test_reliability.py     # Reliability system tests
├── test_integration.py     # Integration tests
├── run_tests.py           # Test runner script
└── README.md              # This file
```

## 🚀 Quick Start

### Install Dependencies
```bash
pip install pytest pytest-asyncio
```

### Run All Tests
```bash
python tests/run_tests.py
```

### Run Specific Test Suite
```bash
python tests/run_tests.py --type cache
python tests/run_tests.py --type db
python tests/run_tests.py --type reliability
python tests/run_tests.py --type integration
```

### Quick Validation
```bash
python tests/run_tests.py --type quick
```

## 📊 Test Coverage

### Cache System Tests (`test_cache.py`)
- ✅ Cache entry creation and expiration
- ✅ Hot key detection mechanism
- ✅ Basic set/get operations
- ✅ TTL functionality
- ✅ Category invalidation
- ✅ Guild-specific operations
- ✅ Bulk operations
- ✅ Metrics collection
- ✅ Predictive caching

### Database Tests (`test_db.py`)
- ✅ Circuit breaker functionality
- ✅ Connection pool management
- ✅ Query execution and retry
- ✅ Transaction management
- ✅ Performance metrics
- ✅ Error handling
- ✅ Pool exhaustion scenarios

### Reliability Tests (`test_reliability.py`)
- ✅ Service circuit breakers
- ✅ Retry mechanisms with backoff
- ✅ Graceful degradation
- ✅ Backup and recovery
- ✅ Resilient decorator
- ✅ End-to-end reliability flow

### Integration Tests (`test_integration.py`)
- ✅ Cache-Database integration
- ✅ Reliability system integration
- ✅ Health monitoring integration
- ✅ Event-driven workflows
- ✅ Performance under load
- ✅ Error recovery scenarios

## 🎯 Test Commands

### Basic Usage
```bash
# Run all tests
python tests/run_tests.py

# Verbose output
python tests/run_tests.py --verbose

# With coverage report
python tests/run_tests.py --coverage

# Quick validation only
python tests/run_tests.py --quick-check
```

### Advanced Usage
```bash
# Run specific test file directly
python -m pytest tests/test_cache.py -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=html

# Run specific test method
python -m pytest tests/test_cache.py::TestGlobalCache::test_basic_set_get -v
```

## 📈 Performance Benchmarks

### Expected Results
- **Cache Operations**: <1ms per operation
- **Database Queries**: <100ms per query
- **Circuit Breaker**: <1ms overhead
- **Retry Mechanisms**: 3 attempts with exponential backoff

### Load Testing
```bash
# Test with simulated load
python tests/run_tests.py --type integration --verbose
```

## 🔧 Pre-Deployment Checklist

Run these tests before any deployment:

```bash
# 1. Quick validation
python tests/run_tests.py --type quick

# 2. Full test suite
python tests/run_tests.py --verbose

# 3. Integration tests
python tests/run_tests.py --type integration

# 4. Coverage report
python tests/run_tests.py --coverage
```

## 🐛 Troubleshooting

### Common Issues

**Import Errors**
```bash
# Add project root to Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python tests/run_tests.py
```

**Missing Dependencies**
```bash
pip install pytest pytest-asyncio
```

**Database Connection Issues**
- Ensure database is running
- Check connection configuration
- Verify credentials

### Debug Mode
```bash
# Run with maximum verbosity
python -m pytest tests/ -v -s --tb=long
```

## 📋 Test Development Guidelines

### Adding New Tests
1. Create test file in `tests/` directory
2. Follow naming convention: `test_*.py`
3. Use appropriate fixtures from `conftest.py`
4. Add to `run_tests.py` if needed

### Test Structure
```python
class TestComponentName:
    \"\"\"Test specific component functionality.\"\"\"
    
    @pytest.fixture
    def component_instance(self):
        \"\"\"Create component instance for testing.\"\"\"
        return Component()
    
    @pytest.mark.asyncio
    async def test_specific_functionality(self, component_instance):
        \"\"\"Test specific functionality with clear description.\"\"\"
        # Arrange
        # Act  
        # Assert
```

### Best Practices
- Use descriptive test names
- Test both success and failure scenarios
- Mock external dependencies
- Test edge cases and error conditions
- Maintain test independence
- Use appropriate assertions

## 📊 CI/CD Integration

### GitHub Actions Example
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
        run: pip install pytest pytest-asyncio
      - name: Run tests
        run: python tests/run_tests.py --coverage
```

## 🎯 Metrics and Reporting

### Coverage Reports
- HTML report: `htmlcov/index.html`
- Terminal summary included in test output
- Target: >90% coverage for critical components

### Performance Metrics
- Execution time per test suite
- Memory usage monitoring
- Database query performance
- Cache hit/miss ratios