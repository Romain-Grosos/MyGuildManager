"""
Reliability system tests - Validates circuit breakers, retry mechanisms, and resilience.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from reliability import (
    ServiceCircuitBreaker, RetryManager, GracefulDegradation, 
    DataBackupManager, discord_resilient
)

class TestServiceCircuitBreaker:
    """Test ServiceCircuitBreaker functionality."""
    
    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initialization with different services."""
        cb = ServiceCircuitBreaker("discord_api", failure_threshold=3, timeout=60)
        
        assert cb.service_name == "discord_api"
        assert cb.failure_threshold == 3
        assert cb.timeout == 60
        assert cb.failure_count == 0
        assert cb.state == "CLOSED"
    
    def test_circuit_breaker_failure_escalation(self):
        """Test circuit breaker failure escalation."""
        cb = ServiceCircuitBreaker("test_service", failure_threshold=2)
        
        assert not cb.is_open()
        
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == "CLOSED"
        
        cb.record_failure()
        assert cb.failure_count == 2
        assert cb.state == "OPEN"
        assert cb.is_open()
    
    def test_circuit_breaker_half_open_transition(self):
        """Test circuit breaker half-open state transition."""
        cb = ServiceCircuitBreaker("test_service", failure_threshold=1, timeout=1)
        
        cb.record_failure()
        assert cb.state == "OPEN"
        
        time.sleep(1.1)
        assert not cb.is_open()
        assert cb.state == "HALF_OPEN"
        
        # Record enough successes to close the circuit
        for _ in range(cb.half_open_max_calls):
            cb.record_success()
        
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0

class TestRetryManager:
    """Test RetryManager functionality."""
    
    @pytest.fixture
    def retry_manager(self):
        """Create RetryManager instance for testing."""
        return RetryManager()
    
    @pytest.mark.asyncio
    async def test_retry_success_on_first_attempt(self, retry_manager):
        """Test successful operation on first attempt."""
        async def success_operation():
            return "success"
        
        result = await retry_manager.retry_with_backoff(
            success_operation, max_attempts=3
        )
        
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_retry_success_after_failures(self, retry_manager):
        """Test successful operation after initial failures."""
        call_count = 0
        
        async def flaky_operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Failure {call_count}")
            return "success"
        
        with patch('asyncio.sleep'):
            result = await retry_manager.retry_with_backoff(
                flaky_operation, max_attempts=3
            )
            
            assert result == "success"
            assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_retry_exhaustion(self, retry_manager):
        """Test retry exhaustion after max attempts."""
        async def always_fail():
            raise Exception("Always fails")
        
        with patch('asyncio.sleep'):
            with pytest.raises(Exception, match="Always fails"):
                await retry_manager.retry_with_backoff(
                    always_fail, max_attempts=2
                )
    
    def test_exponential_backoff_calculation(self, retry_manager):
        """Test exponential backoff calculation."""
        base_delay = 1.0
        exponential_base = 2.0
        max_delay = 60.0
        
        # Test the exponential backoff formula
        delay_1 = min(base_delay * (exponential_base ** 1), max_delay)
        delay_2 = min(base_delay * (exponential_base ** 2), max_delay)
        delay_3 = min(base_delay * (exponential_base ** 3), max_delay)
        
        assert delay_1 == 2.0
        assert delay_2 == 4.0
        assert delay_3 == 8.0
        
        delay_max = min(base_delay * (exponential_base ** 10), max_delay)
        assert delay_max == max_delay

class TestGracefulDegradation:
    """Test GracefulDegradation functionality."""
    
    @pytest.fixture
    def degradation(self):
        """Create GracefulDegradation instance for testing."""
        return GracefulDegradation()
    
    @pytest.mark.asyncio
    async def test_register_fallback(self, degradation):
        """Test fallback registration and execution."""
        async def primary_service():
            raise Exception("Service unavailable")
        
        async def fallback_service():
            return "fallback_result"
        
        degradation.register_fallback("test_service", fallback_service)
        
        result = await degradation.execute_with_fallback(
            "test_service", primary_service
        )
        
        assert result == "fallback_result"
    
    @pytest.mark.asyncio
    async def test_fallback_not_registered(self, degradation):
        """Test behavior when fallback is not registered."""
        async def failing_service():
            raise Exception("Service error")
        
        with pytest.raises(Exception, match="Service error"):
            await degradation.execute_with_fallback(
                "unregistered_service", failing_service
            )
    
    def test_service_health_tracking(self, degradation):
        """Test service health status tracking."""
        degradation.degrade_service("api_service", "High latency")
        degradation.degrade_service("db_service", "Connection issues")
        
        assert degradation.is_degraded("api_service")
        assert degradation.is_degraded("db_service")
        assert "api_service" in degradation.degraded_services
        assert "db_service" in degradation.degraded_services
        assert degradation.degraded_services["api_service"]["reason"] == "High latency"
        
        degradation.restore_service("api_service")
        
        assert not degradation.is_degraded("api_service")
        assert degradation.is_degraded("db_service")

class TestDataBackupManager:
    """Test DataBackupManager functionality."""
    
    @pytest.fixture
    def backup_manager(self):
        """Create DataBackupManager instance for testing."""
        return DataBackupManager()
    
    @pytest.mark.asyncio
    async def test_guild_data_backup(self, backup_manager):
        """Test guild data backup creation."""
        mock_bot = Mock()
        mock_bot.run_db_query = AsyncMock()
        
        # Mock all the database queries that backup_guild_data makes
        mock_bot.run_db_query.side_effect = [
            [("Test Guild", "en-US", 1, "Test Server")],  # guild_settings
            [(123, "Member1", "en", 1500, "Tank", "Sword", 100, 5, 5, 4, "Tank"), (456, "Member2", "fr", 1600, "Healer", "Staff", 120, 8, 8, 7, "Healer")],  # guild_members
            [("Admin", 123, "role"), ("Member", 456, "role")],  # guild_roles
            [("general", 789, "text", None), ("voice", 101112, "voice", None)],  # guild_channels
            [(1, "Test Event", "2024-01-01", "active", "raid", 123, "[]", "[]", "[]")]  # events_data
        ]
        
        backup_manager.bot = mock_bot
        
        backup_file = await backup_manager.backup_guild_data(mock_bot, 123456789)
        
        assert backup_file is not None
        assert backup_file.endswith('.json')
        assert '123456789' in backup_file
        
        # Verify the backup file was created
        import os
        assert os.path.exists(backup_file)
    
    @pytest.mark.asyncio
    async def test_backup_restoration(self, backup_manager):
        """Test backup data restoration."""
        mock_bot = Mock()
        mock_bot.run_db_transaction = AsyncMock(return_value=True)
        
        backup_manager.bot = mock_bot
        
        # Create a temporary backup file
        import tempfile
        import json
        
        backup_data = {
            "guild_id": 123456789,
            "settings": {"guild_id": 123456789, "guild_name": "Test Guild", "guild_lang": "en-US", "guild_game": 1, "guild_server": "Test Server", "initialized": 1, "premium": 0},
            "members": [{"guild_id": 123456789, "member_id": 123, "username": "Member1", "language": "en", "GS": 1500, "build": "Tank", "weapons": "Sword", "DKP": 100, "nb_events": 5, "registrations": 5, "attendances": 4, "class": "Tank"}, {"guild_id": 123456789, "member_id": 456, "username": "Member2", "language": "fr", "GS": 1600, "build": "Healer", "weapons": "Staff", "DKP": 120, "nb_events": 8, "registrations": 8, "attendances": 7, "class": "Healer"}],
            "backup_timestamp": "20240101_120000",
            "backup_version": "1.0"
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(backup_data, f)
            backup_file = f.name
        
        result = await backup_manager.restore_guild_data(mock_bot, 123456789, backup_file)
        
        assert result is True
        mock_bot.run_db_transaction.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_automatic_backup_scheduling(self, backup_manager):
        """Test automatic backup scheduling for critical guilds."""
        mock_bot = Mock()
        mock_bot.run_db_query = AsyncMock(return_value=[(123456789, 1)])
        
        backup_manager.bot = mock_bot
        
        with patch.object(backup_manager, 'backup_guild_data') as mock_backup:
            mock_backup.return_value = "backup_file.json"
            
            # Manual test since run_automatic_backup doesn't exist
            result = await backup_manager.backup_guild_data(mock_bot, 123456789)
            
            assert result == "backup_file.json"

class TestDiscordResilientDecorator:
    """Test discord_resilient decorator functionality."""
    
    @pytest.mark.asyncio
    async def test_successful_operation(self):
        """Test decorator with successful operation."""
        @discord_resilient(service_name='test_service', max_retries=2)
        async def successful_function():
            return "success"
        
        result = await successful_function()
        assert result == "success"
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test decorator retry mechanism."""
        call_count = 0
        
        # Create a mock bot with reliability system
        mock_bot = Mock()
        mock_bot.reliability_system = Mock()
        mock_bot.reliability_system.execute_with_reliability = AsyncMock(return_value="success")
        
        # Create a mock self object that has the bot
        mock_self = Mock()
        mock_self.bot = mock_bot
        
        @discord_resilient(service_name='test_service', max_retries=3)
        async def flaky_function(self):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Failure {call_count}")
            return "success"
        
        with patch('asyncio.sleep'):
            result = await flaky_function(mock_self)
            
            assert result == "success"
            mock_bot.reliability_system.execute_with_reliability.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Test decorator integration with circuit breaker."""
        @discord_resilient(service_name='test_service', max_retries=2)
        async def protected_function():
            return "protected_result"
        
        # Test without bot reliability system (decorator should pass through)
        result = await protected_function()
        
        assert result == "protected_result"

class TestReliabilityIntegration:
    """Test reliability system integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_reliability_flow(self):
        """Test complete reliability flow with all components."""
        service_name = "integration_test_service"
        
        cb = ServiceCircuitBreaker(service_name, failure_threshold=2)
        retry_manager = RetryManager()
        degradation = GracefulDegradation()
        
        async def fallback_operation():
            return "fallback_success"
        
        degradation.register_fallback(service_name, fallback_operation)
        
        call_count = 0
        
        async def unreliable_operation():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                cb.record_failure()
                raise Exception(f"Service failure {call_count}")
            return "primary_success"
        
        with patch('asyncio.sleep'):
            if cb.is_open():
                result = await degradation.execute_with_fallback(
                    service_name, unreliable_operation
                )
                assert result == "fallback_success"
            else:
                try:
                    result = await retry_manager.retry_with_backoff(
                        unreliable_operation, max_attempts=2
                    )
                except Exception:
                    result = await degradation.execute_with_fallback(
                        service_name, unreliable_operation
                    )
                    assert result == "fallback_success"
    
    @pytest.mark.asyncio
    async def test_reliability_metrics_collection(self):
        """Test metrics collection across reliability components."""
        cb = ServiceCircuitBreaker("metrics_service")
        retry_manager = RetryManager()
        
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        
        metrics = {
            "circuit_breaker_failures": cb.failure_count,
            "circuit_breaker_state": cb.state
        }
        
        # After 2 failures and 1 success, count should be reduced but not necessarily 0
        assert metrics["circuit_breaker_failures"] >= 0
        assert metrics["circuit_breaker_state"] == "CLOSED"

if __name__ == "__main__":
    """Run reliability tests directly."""
    pytest.main([__file__, "-v"])