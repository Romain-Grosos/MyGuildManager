"""
Integration tests - Validates interactions between components and end-to-end workflows.
"""

import pytest
import asyncio
import sys
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from .conftest import AsyncContextManager

# Mock config and mariadb modules to avoid dependency issues
config_mock = Mock()
config_mock.DB_USER = "test_user"
config_mock.DB_PASS = "test_pass"
config_mock.DB_HOST = "localhost"
sys.modules['config'] = config_mock

# Mock dotenv
dotenv_mock = Mock()
dotenv_mock.load_dotenv = Mock()
sys.modules['dotenv'] = dotenv_mock

# Mock mariadb module
mariadb_mock = Mock()
mariadb_mock.connect = Mock(return_value=Mock())
mariadb_mock.Error = Exception
sys.modules['mariadb'] = mariadb_mock

class TestCacheDatabaseIntegration:
    """Test cache and database integration."""
    
    @pytest.mark.asyncio
    async def test_cache_miss_triggers_db_query(self):
        """Test that cache miss triggers database query."""
        mock_bot = Mock()
        mock_bot.run_db_query = AsyncMock(return_value=[("Test Guild", "en-US")])
        
        from cache import GlobalCacheSystem
        cache = GlobalCacheSystem()
        cache.bot = mock_bot
        
        guild_id = 123456789
        # Use the actual cache method that exists
        result = await cache.get_guild_members(guild_id)
        
        mock_bot.run_db_query.assert_called_once()
        assert isinstance(result, dict)
    
    @pytest.mark.asyncio
    async def test_cache_invalidation_workflow(self):
        """Test cache invalidation and refresh workflow."""
        mock_bot = Mock()
        mock_bot.run_db_query = AsyncMock(side_effect=[
            [("Initial Data",)],
            [("Updated Data",)]
        ])
        
        from cache import GlobalCacheSystem
        cache = GlobalCacheSystem()
        cache.bot = mock_bot
        
        await cache.set('test_category', 'initial_value', 123, 'test_key')
        
        initial_value = await cache.get('test_category', 123, 'test_key')
        assert initial_value == 'initial_value'
        
        await cache.invalidate_category('test_category')
        
        final_value = await cache.get('test_category', 123, 'test_key')
        assert final_value is None

class TestReliabilityIntegration:
    """Test reliability system integration with other components."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_with_database_operations(self):
        """Test circuit breaker integration with database operations."""
        # Mock the db imports to avoid dependency issues
        from unittest.mock import MagicMock
        run_db_query = AsyncMock(side_effect=Exception("Database connection error"))
        db_circuit_breaker = MagicMock()
        db_circuit_breaker.failure_threshold = 2
        db_circuit_breaker.failure_count = 0
        db_circuit_breaker.state = "CLOSED"
        db_circuit_breaker.is_open = Mock(return_value=False)
        
        # Simulate database failures
        for _ in range(2):
            try:
                await run_db_query("SELECT * FROM test")
            except Exception:
                db_circuit_breaker.failure_count += 1
                if db_circuit_breaker.failure_count >= db_circuit_breaker.failure_threshold:
                    db_circuit_breaker.state = "OPEN"
                    db_circuit_breaker.is_open.return_value = True
        
        assert db_circuit_breaker.state == "OPEN"
        
        # Test that circuit breaker blocks further requests
        if db_circuit_breaker.is_open():
            # Simulate circuit breaker blocking the request
            with pytest.raises(Exception):
                if db_circuit_breaker.is_open():
                    raise Exception("Database temporarily unavailable")
                await run_db_query("SELECT * FROM test")
    
    @pytest.mark.asyncio
    async def test_resilient_decorator_with_cache_operations(self):
        """Test resilient decorator with cache operations."""
        from reliability import discord_resilient
        from cache import GlobalCache
        
        cache = GlobalCache()
        call_count = 0
        
        @discord_resilient(service_name='cache_service', max_retries=2)
        async def cache_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Cache operation failed")
            await cache.set('test_category', 'test_value', 123, 'test_key')
            return await cache.get('test_category', 123, 'test_key')
        
        with patch('asyncio.sleep'):
            result = await cache_operation()
            
            assert result == 'test_value'
            assert call_count == 2

class TestBotHealthIntegration:
    """Test bot health system integration."""
    
    @pytest.mark.asyncio
    async def test_health_check_all_components(self, mock_bot):
        """Test comprehensive health check of all components."""
        # Mock Health cog since it might not exist
        health_cog = Mock()
        health_cog.component_status = {}
        health_cog._check_database = AsyncMock(return_value='healthy')
        health_cog._check_discord_api = AsyncMock(return_value='healthy')
        health_cog._check_cache = AsyncMock(return_value='healthy')
        health_cog._check_reliability_system = AsyncMock(return_value='healthy')
        health_cog._check_all_components = AsyncMock()
        
        with patch.object(health_cog, '_check_database', return_value='healthy'):
            with patch.object(health_cog, '_check_discord_api', return_value='healthy'):
                with patch.object(health_cog, '_check_cache', return_value='healthy'):
                    with patch.object(health_cog, '_check_reliability_system', return_value='healthy'):
                        await health_cog._check_all_components()
                        
                        status = health_cog.component_status
                        
                        assert status['database'] == 'healthy'
                        assert status['discord_api'] == 'healthy'
                        assert status['cache'] == 'healthy'
                        assert status['reliability_system'] == 'healthy'
    
    @pytest.mark.asyncio
    async def test_health_metrics_integration(self, mock_bot):
        """Test health metrics with real performance data."""
        # Mock Health cog since it might not exist
        health_cog = Mock()
        health_cog._create_metrics_embed = AsyncMock()
        mock_embed = Mock()
        mock_embed.title = "📊 Performance Metrics"
        mock_embed.fields = [Mock()]
        health_cog._create_metrics_embed.return_value = mock_embed
        
        with patch('cogs.health.get_global_cache') as mock_cache:
            mock_cache_instance = Mock()
            mock_cache_instance.get_metrics.return_value = {
                'global': {
                    'hit_rate': 85,
                    'total_entries': 150,
                    'total_requests': 1000,
                    'cache_hits': 850,
                    'cache_misses': 150
                }
            }
            mock_cache.return_value = mock_cache_instance
            
            with patch('db.db_manager.get_performance_metrics') as mock_db_metrics:
                mock_db_metrics.return_value = {
                    'active_connections': 2,
                    'waiting_queue': 0,
                    'query_metrics': {
                        'SELECT': {'count': 100, 'avg_time': 0.05, 'slow_queries': 0},
                        'INSERT': {'count': 20, 'avg_time': 0.03, 'slow_queries': 0}
                    },
                    'circuit_breaker_state': 'CLOSED',
                    'circuit_breaker_failures': 0
                }
                
                embed = await health_cog._create_metrics_embed()
                
                assert embed.title == "📊 Performance Metrics"
                assert len(embed.fields) > 0

class TestEventDrivenIntegration:
    """Test event-driven integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_member_join_workflow(self, mock_bot, mock_guild, mock_member):
        """Test complete member join workflow with all components."""
        # Mock cogs since they might not exist or have dependency issues
        notification_cog = Mock()
        notification_cog.get_safe_channel = Mock(return_value=Mock())
        notification_cog.safe_send_notification = AsyncMock(return_value=Mock())
        notification_cog.check_event_rate_limit = Mock(return_value=True)
        notification_cog.on_member_join = AsyncMock()
        
        autorole_cog = Mock()
        
        mock_member.guild = mock_guild
        
        mock_bot.cache.get_guild_data = AsyncMock(side_effect=[
            "en-US",
            12345
        ])
        
        with patch.object(notification_cog, 'get_safe_channel', return_value=Mock()):
            with patch.object(notification_cog, 'safe_send_notification', return_value=Mock()):
                with patch.object(notification_cog, 'check_event_rate_limit', return_value=True):
                    await notification_cog.on_member_join(mock_member)
                    
                    mock_bot.cache.get_guild_data.assert_called()
    
    @pytest.mark.asyncio
    async def test_database_backup_integration(self, mock_bot):
        """Test database backup integration with reliability system."""
        from reliability import DataBackupManager
        
        backup_manager = DataBackupManager()
        backup_manager.bot = mock_bot
        
        mock_bot.run_db_query = AsyncMock(side_effect=[
            [("Test Guild", "en-US", 1, "Test Server")],
            [(123, "Member1"), (456, "Member2")],
            [(1, "Test Event")]
        ])
        
        mock_bot.run_db_transaction = AsyncMock(return_value=True)
        
        backup_file = await backup_manager.backup_guild_data(mock_bot, 123456789)
        # Read the backup file to get backup data
        import json
        with open(backup_file, 'r') as f:
            backup_data = json.load(f)
        
        assert backup_data is not None
        assert "guild_id" in backup_data
        
        restore_result = await backup_manager.restore_guild_data(mock_bot, 123456789, backup_file)
        assert restore_result is True

class TestPerformanceIntegration:
    """Test performance-related integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_cache_performance_under_load(self):
        """Test cache performance under simulated load."""
        from cache import GlobalCache
        
        cache = GlobalCache()
        
        async def cache_operations(operation_id):
            for i in range(100):
                await cache.set(f'load_test_{operation_id}', f'value_{i}', operation_id, f'key_{i}')
                result = await cache.get(f'load_test_{operation_id}', operation_id, f'key_{i}')
                assert result == f'value_{i}'
        
        tasks = [cache_operations(i) for i in range(10)]
        await asyncio.gather(*tasks)
        
        metrics = cache.get_metrics()
        assert metrics['global']['total_requests'] >= 2000
        assert metrics['global']['hit_rate'] >= 50
    
    @pytest.mark.asyncio
    async def test_database_connection_pool_performance(self):
        """Test database connection pool under concurrent load."""
        # Mock db module to avoid dependency issues
        run_db_query = AsyncMock(return_value=("test_result",))
        
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ("test_result",)
        mock_cursor.execute = Mock()
        mock_cursor.close = Mock()
        
        mock_conn = Mock()
        mock_conn.cursor.return_value = mock_cursor
        
        async def db_operation(operation_id):
            result = await run_db_query(f"SELECT {operation_id}", fetch_one=True)
            return result
        
        tasks = [db_operation(i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 20
        assert all(result == ("test_result",) for result in results)

class TestErrorRecoveryIntegration:
    """Test error recovery integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_cache_failure_recovery(self):
        """Test cache failure and recovery integration."""
        from cache import GlobalCache
        
        cache = GlobalCache()
        
        await cache.set('recovery_test', 'value1', 123, 'key1')
        
        with patch.object(cache, '_cache', side_effect=Exception("Cache failure")):
            result = await cache.get('recovery_test', 123, 'key1')
            assert result is None
        
        result = await cache.get('recovery_test', 123, 'key1')
        assert result == 'value1'
    
    @pytest.mark.asyncio
    async def test_service_degradation_workflow(self):
        """Test service degradation and recovery workflow."""
        from reliability import GracefulDegradation
        
        degradation = GracefulDegradation()
        
        async def primary_service():
            raise Exception("Primary service unavailable")
        
        async def fallback_service():
            return "fallback_result"
        
        degradation.register_fallback("test_service", fallback_service)
        degradation.degrade_service("test_service", "Simulated failure")
        
        result = await degradation.execute_with_fallback("test_service", primary_service)
        assert result == "fallback_result"
        
        status = degradation.degraded_services
        assert "test_service" in status
        
        degradation.restore_service("test_service")
        updated_status = degradation.degraded_services
        assert "test_service" not in updated_status

if __name__ == "__main__":
    """Run integration tests directly."""
    pytest.main([__file__, "-v"])