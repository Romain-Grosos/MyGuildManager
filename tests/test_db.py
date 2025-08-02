"""
Database system tests - Validates DB operations, transactions, and resilience.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Mock config and mariadb modules to avoid dependency issues
import sys
from unittest.mock import Mock as MockModule

config_mock = MockModule()
config_mock.DB_USER = "test_user"
config_mock.DB_PASS = "test_pass"
config_mock.DB_HOST = "localhost"
config_mock.DB_PORT = 3306
config_mock.DB_NAME = "test_db"
config_mock.DB_POOL_SIZE = 5
config_mock.DB_TIMEOUT = 30
config_mock.DB_CIRCUIT_BREAKER_THRESHOLD = 3
sys.modules['config'] = config_mock

# Mock mariadb module with proper exception hierarchy
mariadb_mock = MockModule()
mariadb_mock.connect = Mock(return_value=Mock())

class MariaDBError(Exception):
    pass

class MariaDBDataError(MariaDBError):
    pass

class MariaDBIntegrityError(MariaDBError):
    pass

class MariaDBOperationalError(MariaDBError):
    pass

class MariaDBPoolError(MariaDBError):
    pass

class MariaDBProgrammingError(MariaDBError):
    pass

mariadb_mock.Error = MariaDBError
mariadb_mock.DataError = MariaDBDataError
mariadb_mock.IntegrityError = MariaDBIntegrityError
mariadb_mock.OperationalError = MariaDBOperationalError
mariadb_mock.PoolError = MariaDBPoolError
mariadb_mock.ProgrammingError = MariaDBProgrammingError
sys.modules['mariadb'] = mariadb_mock

from db import (
    CircuitBreaker, DatabaseManager, run_db_query, run_db_transaction,
    DBQueryError, db_circuit_breaker, db_manager
)

class TestCircuitBreaker:
    """Test CircuitBreaker functionality."""
    
    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initial state."""
        cb = CircuitBreaker(failure_threshold=3, timeout=60)
        
        assert cb.failure_threshold == 3
        assert cb.timeout == 60
        assert cb.failure_count == 0
        assert cb.state == "CLOSED"
        assert not cb.is_open()
    
    def test_circuit_breaker_failure_recording(self):
        """Test failure recording and state transitions."""
        cb = CircuitBreaker(failure_threshold=2, timeout=1)
        
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == "CLOSED"
        
        cb.record_failure()
        assert cb.failure_count == 2
        assert cb.state == "OPEN"
        assert cb.is_open()
    
    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery mechanism."""
        cb = CircuitBreaker(failure_threshold=1, timeout=1)
        
        cb.record_failure()
        assert cb.state == "OPEN"
        
        time.sleep(1.1)
        assert not cb.is_open()
        
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

class TestDatabaseManager:
    """Test DatabaseManager functionality."""
    
    @pytest.fixture
    def db_manager_instance(self):
        """Create DatabaseManager instance for testing."""
        return DatabaseManager()
    
    def test_database_manager_initialization(self, db_manager_instance):
        """Test database manager initialization."""
        assert db_manager_instance.active_connections == 0
        assert db_manager_instance.waiting_queue == 0
        assert isinstance(db_manager_instance.query_metrics, dict)
        assert db_manager_instance.slow_query_threshold == 2.0
    
    def test_query_metrics_logging(self, db_manager_instance):
        """Test query metrics collection."""
        db_manager_instance.log_query_metrics("SELECT * FROM test", 0.5)
        db_manager_instance.log_query_metrics("SELECT * FROM test", 1.5)
        db_manager_instance.log_query_metrics("INSERT INTO test VALUES (1)", 0.3)
        
        metrics = db_manager_instance.query_metrics
        
        assert "SELECT" in metrics
        assert "INSERT" in metrics
        assert metrics["SELECT"]["count"] == 2
        assert metrics["INSERT"]["count"] == 1
        assert metrics["SELECT"]["avg_time"] == 1.0
    
    def test_slow_query_detection(self, db_manager_instance):
        """Test slow query detection and logging."""
        with patch('logging.warning') as mock_warning:
            db_manager_instance.log_query_metrics("SELECT * FROM slow_table", 3.5)
            
            mock_warning.assert_called_once()
            assert "Slow query detected" in mock_warning.call_args[0][0]
    
    def test_performance_metrics(self, db_manager_instance):
        """Test performance metrics collection."""
        db_manager_instance.log_query_metrics("SELECT * FROM test", 0.5)
        
        metrics = db_manager_instance.get_performance_metrics()
        
        assert "active_connections" in metrics
        assert "waiting_queue" in metrics
        assert "query_metrics" in metrics
        assert "circuit_breaker_state" in metrics
        assert "circuit_breaker_failures" in metrics

class TestDatabaseOperations:
    """Test database query operations."""
    
    @pytest.mark.asyncio
    async def test_successful_query(self):
        """Test successful database query execution."""
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ("test_result",)
        mock_cursor.execute = Mock()
        mock_cursor.close = Mock()
        
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = Mock()
        
        with patch('db.db_manager.get_connection_with_timeout') as mock_context:
            mock_context.return_value.__aenter__.return_value = mock_conn
            mock_context.return_value.__aexit__.return_value = None
            
            result = await run_db_query("SELECT * FROM test", fetch_one=True)
            
            assert result == ("test_result",)
            mock_cursor.execute.assert_called_once_with("SELECT * FROM test", ())
            mock_cursor.fetchone.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_query(self):
        """Test circuit breaker blocking queries when open."""
        with patch('db.db_circuit_breaker.is_open', return_value=True):
            with pytest.raises(DBQueryError, match="Database temporarily unavailable"):
                await run_db_query("SELECT * FROM test")
    
    @pytest.mark.asyncio
    async def test_query_retry_on_timeout(self):
        """Test query retry mechanism on timeout."""
        call_count = 0
        
        def mock_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise asyncio.TimeoutError()
            return "success"
        
        with patch('db.db_circuit_breaker.is_open', return_value=False):
            with patch('asyncio.wait_for', side_effect=mock_wait_for):
                with patch('asyncio.sleep'):
                    result = await run_db_query("SELECT * FROM test")
                    
                    assert result == "success"
                    assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_transaction_success(self):
        """Test successful database transaction."""
        mock_cursor = Mock()
        mock_cursor.execute = Mock()
        mock_cursor.close = Mock()
        
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.commit = Mock()
        mock_conn.rollback = Mock()
        mock_conn.autocommit = True
        
        queries = [
            ("INSERT INTO test VALUES (%s)", (1,)),
            ("UPDATE test SET value = %s WHERE id = %s", ("new_value", 1))
        ]
        
        with patch('db.db_manager.get_connection_with_timeout') as mock_context:
            mock_context.return_value.__aenter__.return_value = mock_conn
            mock_context.return_value.__aexit__.return_value = None
            
            result = await run_db_transaction(queries)
            
            assert result is True
            assert mock_cursor.execute.call_count == 2
            mock_conn.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self):
        """Test transaction rollback on error."""
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = [None, Exception("Database error")]
        mock_cursor.close = Mock()
        
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.rollback = Mock()
        mock_conn.autocommit = True
        
        queries = [
            ("INSERT INTO test VALUES (%s)", (1,)),
            ("INVALID SQL", ())
        ]
        
        with patch('db.db_manager.get_connection_with_timeout') as mock_context:
            mock_context.return_value.__aenter__.return_value = mock_conn
            mock_context.return_value.__aexit__.return_value = None
            
            with pytest.raises(Exception):
                await run_db_transaction(queries)
            
            assert mock_conn.rollback.called
    
    @pytest.mark.asyncio
    async def test_query_metrics_integration(self):
        """Test query metrics integration with actual queries."""
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ("test_result",)
        mock_cursor.execute = Mock()
        mock_cursor.close = Mock()
        
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        
        with patch('db.db_manager.get_connection_with_timeout') as mock_context:
            mock_context.return_value.__aenter__.return_value = mock_conn
            mock_context.return_value.__aexit__.return_value = None
            
            with patch.object(db_manager, 'log_query_metrics') as mock_metrics:
                await run_db_query("SELECT * FROM test", fetch_one=True)
                
                mock_metrics.assert_called_once()
                args = mock_metrics.call_args[0]
                assert args[0] == "SELECT * FROM test"
                assert isinstance(args[1], float)

class TestDatabaseIntegration:
    """Test database integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_database_health_check(self):
        """Test database connectivity health check."""
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (1,)
        mock_cursor.execute = Mock()
        mock_cursor.close = Mock()
        
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        
        with patch('db.db_manager.get_connection_with_timeout') as mock_context:
            mock_context.return_value.__aenter__.return_value = mock_conn
            mock_context.return_value.__aexit__.return_value = None
            
            result = await run_db_query("SELECT 1", fetch_one=True)
            
            assert result == (1,)
            mock_cursor.execute.assert_called_once_with("SELECT 1", ())
    
    @pytest.mark.asyncio
    async def test_connection_pool_exhaustion_handling(self):
        """Test handling of connection pool exhaustion."""
        import mariadb
        
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = mariadb.PoolError("Pool exhausted")
        mock_cursor.close = Mock()
        
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        
        # Mock the database manager's method instead
        with patch('db.db_manager') as mock_db_manager:
            mock_db_manager.get_connection_with_timeout = AsyncMock()
            mock_db_manager.get_connection_with_timeout.return_value.__aenter__.return_value = mock_conn
            mock_db_manager.get_connection_with_timeout.return_value.__aexit__.return_value = None
            
            with patch('asyncio.sleep'):
                with pytest.raises(Exception):  # Pool exhaustion error
                    await run_db_query("SELECT * FROM test", fetch_one=True)

if __name__ == "__main__":
    """Run database tests directly."""
    pytest.main([__file__, "-v"])