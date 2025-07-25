import mariadb
import config
import logging
import sys
import asyncio
import time
import contextlib
from typing import Optional, Any

pool_connection = None

def initialize_db_pool() -> bool:
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
        logging.info(f"[DBManager] 🔗 DB pool initialized (size: {config.DB_POOL_SIZE}, timeout: {config.DB_TIMEOUT}s)")
        return True
    except mariadb.Error as e:
        logging.critical(f"[DBManager] ❌ Failed to initialize DB pool: {type(e).__name__}")
        return False

if not initialize_db_pool():
    sys.exit(1)

def safe_log_query(query: str, params: tuple):
    safe_query = query[:100] + "..." if len(query) > 100 else query
    param_count = len(params) if params else 0
    logging.debug(f"[DBManager] Executing query (params: {param_count}): {safe_query}")

def safe_log_error(error: Exception, query: str):
    safe_query = query[:50] + "..." if len(query) > 50 else query
    logging.error(f"[DBManager] Query failed: {type(error).__name__} | Query: {safe_query}")

class CircuitBreaker:
    def __init__(self, failure_threshold: int = None, timeout: int = 60):
        self.failure_threshold = failure_threshold or config.DB_CIRCUIT_BREAKER_THRESHOLD
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"
    
    def is_open(self) -> bool:
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "HALF_OPEN"
                logging.info("[DBManager] Circuit breaker entering HALF_OPEN state")
                return False
            return True
        return False
    
    def record_success(self):
        if self.state == "HALF_OPEN":
            logging.info("[DBManager] Circuit breaker CLOSED - DB recovered")
        self.failure_count = 0
        self.state = "CLOSED"
    
    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logging.warning(f"[DBManager] Circuit breaker OPEN - DB temporarily unavailable (failures: {self.failure_count})")

class DatabaseManager:
    def __init__(self):
        self.active_connections = 0
        self.max_active_connections = config.DB_POOL_SIZE
        self.connection_semaphore = asyncio.Semaphore(config.DB_POOL_SIZE)
        self.waiting_queue = 0
    
    @contextlib.asynccontextmanager
    async def get_connection_with_timeout(self):
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
        return mariadb.connect(pool_name="secure_pool")

db_circuit_breaker = CircuitBreaker()
db_manager = DatabaseManager()

class DBQueryError(Exception):
    pass

async def run_db_query(query: str, params: tuple = (), commit: bool = False,fetch_one: bool = False, fetch_all: bool = False) -> Optional[Any]:
    
    if db_circuit_breaker.is_open():
        raise DBQueryError("Database temporarily unavailable (circuit breaker open)")
    
    safe_log_query(query, params)
    
    async def _execute():
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
            if "pool exhausted" in str(e).lower():
                if attempt == max_attempts - 1:
                    raise
                logging.warning(f"[DBManager] Pool exhausted, retrying (attempt {attempt+1}/{max_attempts})")
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            else:
                raise
        except Exception as e:
            safe_log_error(e, query)
            if attempt == max_attempts - 1:
                db_circuit_breaker.record_failure()
                raise DBQueryError(f"Unexpected database error: {type(e).__name__}")
            await asyncio.sleep(0.5 * (attempt + 1))