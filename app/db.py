import asyncio
import contextlib
import logging
import sys
import time
from typing import Optional, Any

import mariadb

import config

# #################################################################################### #
#                            Database Pool Initialization
# #################################################################################### #
pool_connection = None

def initialize_db_pool() -> bool:
    """
    Initialize MariaDB connection pool with configuration settings.
    
    Returns:
        True if pool initialization succeeded, False otherwise
    """
    global pool_connection
    try:
        pool_connection = mariadb.connect(
            user=config.DB_USER,
            password=config.DB_PASS,
            host=config.DB_HOST,
            port=config.DB_PORT,
            database=config.DB_NAME,
            pool_name="secure_pool",
            pool_size=config.DB_POOL_SIZE,
            connect_timeout=config.DB_TIMEOUT
        )
        logging.info(f"[DBManager] DB pool initialized (size: {config.DB_POOL_SIZE}, timeout: {config.DB_TIMEOUT}s)")
        return True
    except mariadb.Error as e:
        logging.critical(f"[DBManager] Failed to initialize DB pool: {type(e).__name__}")
        return False

if not initialize_db_pool():
    sys.exit(1)

# #################################################################################### #
#                            Query Logging Utilities
# #################################################################################### #
def safe_log_query(query: str, params: tuple):
    """
    Log query execution safely without exposing sensitive data.
    
    Args:
        query: SQL query string
        params: Query parameters tuple
    """
    safe_query = query[:100] + "..." if len(query) > 100 else query
    param_count = len(params) if params else 0
    logging.debug(f"[DBManager] Executing query (params: {param_count}): {safe_query}")

def safe_log_error(error: Exception, query: str):
    """
    Log query errors safely without exposing sensitive data.
    
    Args:
        error: Exception that occurred
        query: SQL query that failed
    """
    safe_query = query[:50] + "..." if len(query) > 50 else query
    logging.error(f"[DBManager] Query failed: {type(error).__name__} | Query: {safe_query}")

# #################################################################################### #
#                            Circuit Breaker Pattern
# #################################################################################### #
class CircuitBreaker:
    """Circuit breaker to prevent cascading failures when database is unavailable."""
    
    def __init__(self, failure_threshold: int | None = None, timeout: int = 60):
        """
        Initialize circuit breaker with failure threshold and timeout.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Timeout in seconds before attempting to close circuit
        """
        self.failure_threshold = failure_threshold or config.DB_CIRCUIT_BREAKER_THRESHOLD
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state = "CLOSED"
    
    def is_open(self) -> bool:
        """
        Check if circuit breaker is open (blocking requests).
        
        Returns:
            True if circuit breaker is open, False otherwise
        """
        if self.state == "OPEN":
            if self.last_failure_time and time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
                logging.info("[DBManager] Circuit breaker entering HALF_OPEN state")
                return False
            return True
        return False
    
    def record_success(self):
        """
        Record successful operation, potentially closing the breaker.
        """
        if self.state == "HALF_OPEN":
            logging.info("[DBManager] Circuit breaker CLOSED - DB recovered")
        self.failure_count = 0
        self.state = "CLOSED"
    
    def record_failure(self):
        """
        Record failed operation, potentially opening the breaker.
        """
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logging.warning(f"[DBManager] Circuit breaker OPEN - DB temporarily unavailable (failures: {self.failure_count})")

# #################################################################################### #
#                            Database Connection Manager
# #################################################################################### #
class DatabaseManager:
    """Manages database connections with proper pooling and timeout handling."""
    
    def __init__(self):
        """
        Initialize database manager with connection pooling and metrics.
        """
        self.active_connections = 0
        self.max_active_connections = config.DB_POOL_SIZE
        self.connection_semaphore = asyncio.Semaphore(config.DB_POOL_SIZE)
        self.waiting_queue = 0
        self.query_metrics = {}
        self.slow_query_threshold = 2.0
    
    @contextlib.asynccontextmanager
    async def get_connection_with_timeout(self):
        """
        Get database connection with timeout and proper resource management.
        
        Yields:
            Database connection from the pool
            
        Raises:
            asyncio.TimeoutError: If connection acquisition times out
        """
        self.waiting_queue += 1
        
        try:
            await asyncio.wait_for(
                self.connection_semaphore.acquire(),
                timeout=config.DB_TIMEOUT
            )
            
            if self.waiting_queue > config.DB_POOL_SIZE * 1.5 and self.waiting_queue % 10 == 0:
                logging.warning(f"[DBManager] High queue: {self.waiting_queue - 1} waiting, {self.active_connections} active")
            
            conn = None
            try:
                self.active_connections += 1
                conn = await asyncio.wait_for(
                    asyncio.to_thread(self._get_connection), 
                    timeout=config.DB_TIMEOUT
                )
                yield conn
            finally:
                self.active_connections -= 1
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
        finally:
            self.waiting_queue -= 1
            try:
                self.connection_semaphore.release()
            except ValueError:
                pass
    
    def _get_connection(self):
        """
        Get connection from pool.
        
        Returns:
            MariaDB connection from the pool
        """
        return mariadb.connect(pool_name="secure_pool")
    
    def log_query_metrics(self, query: str, execution_time: float):
        """
        Log query execution metrics and detect slow queries.
        
        Args:
            query: SQL query that was executed
            execution_time: Query execution time in seconds
        """
        query_type = query.strip().split()[0].upper()
        
        if query_type not in self.query_metrics:
            self.query_metrics[query_type] = {
                'count': 0,
                'total_time': 0,
                'avg_time': 0,
                'slow_queries': 0
            }
        
        metrics = self.query_metrics[query_type]
        metrics['count'] += 1
        metrics['total_time'] += execution_time
        metrics['avg_time'] = metrics['total_time'] / metrics['count']
        
        if execution_time > self.slow_query_threshold:
            metrics['slow_queries'] += 1
            safe_query = query[:100] + "..." if len(query) > 100 else query
            logging.warning(f"[DBManager] Slow query detected ({execution_time:.2f}s): {safe_query}")
    
    def get_performance_metrics(self) -> dict:
        """
        Get database performance metrics.
        
        Returns:
            Dictionary containing performance metrics
        """
        return {
            'active_connections': self.active_connections,
            'waiting_queue': self.waiting_queue,
            'query_metrics': self.query_metrics.copy(),
            'circuit_breaker_state': db_circuit_breaker.state,
            'circuit_breaker_failures': db_circuit_breaker.failure_count
        }

# #################################################################################### #
#                            Global Database Components
# #################################################################################### #
db_circuit_breaker = CircuitBreaker()
db_manager = DatabaseManager()

class DBQueryError(Exception):
    """
    Custom exception for database query errors.
    """
    pass

# #################################################################################### #
#                            Main Database Query Function
# #################################################################################### #
async def run_db_query(query: str, params: tuple = (), commit: bool = False, fetch_one: bool = False, fetch_all: bool = False) -> Optional[Any]:
    """
    Execute database query with resilience patterns and proper error handling.
    
    Args:
        query: SQL query string
        params: Query parameters tuple (default: empty)
        commit: Whether to commit the transaction (default: False)
        fetch_one: Whether to fetch one row (default: False)
        fetch_all: Whether to fetch all rows (default: False)
        
    Returns:
        Query result or None depending on fetch parameters
        
    Raises:
        DBQueryError: If query execution fails
    """
    
    if db_circuit_breaker.is_open():
        logging.warning("[DBManager] Database circuit breaker is open - query blocked")
        raise DBQueryError("Database temporarily unavailable (circuit breaker open)")
    
    safe_log_query(query, params)
    
    async def _execute():
        start_time = time.time()
        async with db_manager.get_connection_with_timeout() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                
                result = None
                if commit:
                    conn.commit()
                elif fetch_one:
                    result = cursor.fetchone()
                elif fetch_all:
                    result = cursor.fetchall()
                
                execution_time = time.time() - start_time
                db_manager.log_query_metrics(query, execution_time)
                db_circuit_breaker.record_success()
                return result
                
            except (mariadb.DataError, mariadb.IntegrityError) as e:
                safe_log_error(e, query)
                db_circuit_breaker.record_failure()
                raise DBQueryError(f"Database constraint error: {type(e).__name__}")
            except mariadb.OperationalError as e:
                safe_log_error(e, query)
                db_circuit_breaker.record_failure()
                raise DBQueryError("Database connection error")
            except mariadb.PoolError as e:
                safe_log_error(e, query)
                db_circuit_breaker.record_failure()
                raise DBQueryError("Connection pool exhausted - too many concurrent requests")
            except mariadb.ProgrammingError as e:
                safe_log_error(e, query)
                raise DBQueryError(f"Database query error: {type(e).__name__}")
            finally:
                cursor.close()

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            return await asyncio.wait_for(_execute(), timeout=config.DB_TIMEOUT)
        except asyncio.TimeoutError:
            logging.warning(f"[DBManager] Query timeout (attempt {attempt+1}/{max_attempts})")
            if attempt == max_attempts - 1:
                db_circuit_breaker.record_failure()
                raise DBQueryError("Query timeout after multiple attempts")
            await asyncio.sleep(0.5 * (attempt + 1))
        except DBQueryError as e:
            error_msg = str(e).lower()
            if "pool exhausted" in error_msg or "too many concurrent" in error_msg:
                if attempt == max_attempts - 1:
                    raise
                wait_time = min(2.0 * (attempt + 1), 5.0)
                logging.warning(f"[DBManager] Pool exhausted, retrying in {wait_time}s (attempt {attempt+1}/{max_attempts})")
                await asyncio.sleep(wait_time)
                continue
            elif "temporarily unavailable" in error_msg:
                raise
            else:
                raise
        except Exception as e:
            safe_log_error(e, query)
            if attempt == max_attempts - 1:
                db_circuit_breaker.record_failure()
                raise DBQueryError(f"Unexpected database error: {type(e).__name__}")

async def run_db_transaction(queries_and_params: list, max_attempts: int = 3) -> bool:
    """Execute multiple queries in a single transaction with rollback support.
    
    Args:
        queries_and_params: List of tuples (query, params)
        max_attempts: Maximum retry attempts
        
    Returns:
        bool: True if transaction succeeded, False otherwise
        
    Raises:
        DBQueryError: If transaction fails after all attempts
    """
    if db_circuit_breaker.is_open():
        raise DBQueryError("Database temporarily unavailable (circuit breaker open)")
    
    for attempt in range(max_attempts):
        try:
            async def _execute_transaction():
                async with db_manager.get_connection_with_timeout() as conn:
                    cursor = conn.cursor()
                    try:
                        conn.autocommit = False

                        for query, params in queries_and_params:
                            safe_log_query(query, params)
                            cursor.execute(query, params)

                        conn.commit()
                        db_circuit_breaker.record_success()
                        logging.info(f"[DBManager] Transaction completed successfully ({len(queries_and_params)} queries)")
                        return True
                        
                    except Exception as e:
                        try:
                            conn.rollback()
                            logging.warning(f"[DBManager] Transaction rolled back due to error: {type(e).__name__}")
                        except Exception as rollback_error:
                            logging.error(f"[DBManager] Failed to rollback transaction: {rollback_error}")

                        if isinstance(e, (mariadb.DataError, mariadb.IntegrityError)):
                            safe_log_error(e, "TRANSACTION")
                            db_circuit_breaker.record_failure()
                            raise DBQueryError(f"Transaction constraint error: {type(e).__name__}")
                        elif isinstance(e, mariadb.OperationalError):
                            safe_log_error(e, "TRANSACTION")
                            db_circuit_breaker.record_failure()
                            raise DBQueryError(f"Transaction operational error: {type(e).__name__}")
                        else:
                            raise
                    finally:
                        conn.autocommit = True
            
            return await asyncio.wait_for(_execute_transaction(), timeout=config.DB_TIMEOUT * 2)
            
        except asyncio.TimeoutError:
            logging.warning(f"[DBManager] Transaction timeout (attempt {attempt+1}/{max_attempts})")
            if attempt == max_attempts - 1:
                db_circuit_breaker.record_failure()
                raise DBQueryError("Transaction timeout after multiple attempts")
            await asyncio.sleep(1.0 * (attempt + 1))
        except DBQueryError as e:
            error_msg = str(e).lower()
            if "constraint error" in error_msg or "operational error" in error_msg:
                raise
            elif "pool exhausted" in error_msg:
                if attempt == max_attempts - 1:
                    raise
                wait_time = min(2.0 * (attempt + 1), 5.0)
                logging.warning(f"[DBManager] Pool exhausted during transaction, retrying in {wait_time}s")
                await asyncio.sleep(wait_time)
                continue
            else:
                raise
        except Exception as e:
            safe_log_error(e, "TRANSACTION")
            if attempt == max_attempts - 1:
                db_circuit_breaker.record_failure()
                raise DBQueryError(f"Unexpected transaction error: {type(e).__name__}")
            await asyncio.sleep(0.5 * (attempt + 1))
    
    return False
