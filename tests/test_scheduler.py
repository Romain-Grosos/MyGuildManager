"""
Tests for scheduler.py - Task scheduler for automated bot operations.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
try:
    import pytz
except ImportError:
    pytz = None
from scheduler import TaskScheduler, setup_task_scheduler, get_scheduler_health_status, stop_scheduler


class TestTaskScheduler:
    """Test TaskScheduler class functionality."""
    
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot for testing."""
        bot = Mock()
        bot.get_cog = Mock()
        bot.wait_until_ready = AsyncMock()
        return bot
    
    @pytest.fixture
    def scheduler(self, mock_bot):
        """Create TaskScheduler instance for testing."""
        return TaskScheduler(mock_bot)
    
    def test_scheduler_initialization(self, mock_bot):
        """Test TaskScheduler initialization."""
        scheduler = TaskScheduler(mock_bot)
        
        assert scheduler.bot == mock_bot
        assert isinstance(scheduler._task_locks, dict)
        assert isinstance(scheduler._last_execution, dict)
        assert isinstance(scheduler._task_metrics, dict)
        
        # Verify all expected task locks exist
        expected_locks = ['contracts', 'roster', 'events_create', 'events_reminder', 
                         'events_delete', 'events_close', 'attendance_check']
        for lock_name in expected_locks:
            assert lock_name in scheduler._task_locks
            assert isinstance(scheduler._task_locks[lock_name], asyncio.Lock)
        
        # Verify metrics structure
        for task_name in expected_locks:
            assert task_name in scheduler._task_metrics
            assert 'success' in scheduler._task_metrics[task_name]
            assert 'failures' in scheduler._task_metrics[task_name]
            assert 'total_time' in scheduler._task_metrics[task_name]
    
    def test_should_execute_first_time(self, scheduler):
        """Test should_execute returns True for first execution."""
        result = scheduler._should_execute('test_task', '12:00')
        assert result is True
        assert scheduler._last_execution['test_task'] == '12:00'
    
    def test_should_execute_same_time(self, scheduler):
        """Test should_execute returns False for same time."""
        scheduler._should_execute('test_task', '12:00')
        result = scheduler._should_execute('test_task', '12:00')
        assert result is False
    
    def test_should_execute_different_time(self, scheduler):
        """Test should_execute returns True for different time."""
        scheduler._should_execute('test_task', '12:00')
        result = scheduler._should_execute('test_task', '12:01')
        assert result is True
        assert scheduler._last_execution['test_task'] == '12:01'
    
    @pytest.mark.asyncio
    async def test_execute_with_monitoring_success(self, scheduler):
        """Test successful task execution with monitoring."""
        async def mock_task():
            await asyncio.sleep(0.01)  # Simulate work
            return "success"
        
        with patch('scheduler.logging.info') as mock_info:
            await scheduler._execute_with_monitoring('test_task', mock_task)
            
            # Verify success metrics
            assert scheduler._task_metrics['test_task']['success'] == 1
            assert scheduler._task_metrics['test_task']['failures'] == 0
            assert scheduler._task_metrics['test_task']['total_time'] > 0
            
            # Verify logging
            mock_info.assert_called_once()
            assert "completed successfully" in str(mock_info.call_args)
    
    @pytest.mark.asyncio
    async def test_execute_with_monitoring_failure(self, scheduler):
        """Test failed task execution with monitoring."""
        async def failing_task():
            raise Exception("Task failed")
        
        with patch('scheduler.logging.exception') as mock_exception:
            await scheduler._execute_with_monitoring('test_task', failing_task)
            
            # Verify failure metrics
            assert scheduler._task_metrics['test_task']['success'] == 0
            assert scheduler._task_metrics['test_task']['failures'] == 1
            
            # Verify logging
            mock_exception.assert_called_once()
            assert "failed after" in str(mock_exception.call_args)
    
    @pytest.mark.asyncio
    async def test_safe_get_cog_exists(self, scheduler, mock_bot):
        """Test getting existing cog."""
        mock_cog = Mock()
        mock_bot.get_cog.return_value = mock_cog
        
        result = await scheduler._safe_get_cog("TestCog")
        
        assert result == mock_cog
        mock_bot.get_cog.assert_called_once_with("TestCog")
    
    @pytest.mark.asyncio
    async def test_safe_get_cog_not_exists(self, scheduler, mock_bot):
        """Test getting non-existent cog."""
        mock_bot.get_cog.return_value = None
        
        with patch('scheduler.logging.warning') as mock_warning:
            result = await scheduler._safe_get_cog("NonExistentCog")
            
            assert result is None
            mock_warning.assert_called_once()
            assert "cog not found" in str(mock_warning.call_args)
    
    def test_get_health_status(self, scheduler):
        """Test health status reporting."""
        # Set some test data
        scheduler._last_execution['test_task'] = '12:00'
        scheduler._task_metrics['contracts']['success'] = 5
        scheduler._task_metrics['contracts']['failures'] = 1
        
        status = scheduler.get_health_status()
        
        assert 'task_metrics' in status
        assert 'active_locks' in status
        assert 'last_executions' in status
        
        assert status['task_metrics']['contracts']['success'] == 5
        assert status['task_metrics']['contracts']['failures'] == 1
        assert status['last_executions']['test_task'] == '12:00'
        
        # Verify lock status structure
        for lock_name in scheduler._task_locks.keys():
            assert lock_name in status['active_locks']
            assert isinstance(status['active_locks'][lock_name], bool)


class TestScheduledTaskExecution:
    """Test scheduled task execution logic."""
    
    @pytest.fixture
    def scheduler_with_mocks(self):
        """Create scheduler with mocked dependencies."""
        bot = Mock()
        bot.get_cog = Mock()
        scheduler = TaskScheduler(bot)
        
        # Mock all cogs
        mock_cogs = {
            'Contract': Mock(),
            'GuildMembers': Mock(),
            'GuildEvents': Mock(),
            'GuildAttendance': Mock()
        }
        
        for cog_name, cog_mock in mock_cogs.items():
            # Add async methods to cog mocks
            if cog_name == 'Contract':
                cog_mock.contract_delete_cron = AsyncMock()
            elif cog_name == 'GuildMembers':
                cog_mock.run_maj_roster = AsyncMock()
            elif cog_name == 'GuildEvents':
                cog_mock.create_events_for_all_premium_guilds = AsyncMock()
                cog_mock.event_reminder_cron = AsyncMock()
                cog_mock.event_delete_cron = AsyncMock()
                cog_mock.event_close_cron = AsyncMock()
                cog_mock.update_static_groups_message_for_cron = AsyncMock()
            elif cog_name == 'GuildAttendance':
                cog_mock.check_voice_presence = AsyncMock()
        
        bot.get_cog.side_effect = lambda name: mock_cogs.get(name)
        
        return scheduler, mock_cogs
    
    @pytest.mark.asyncio
    async def test_contract_deletion_task(self, scheduler_with_mocks):
        """Test contract deletion scheduled task."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "06:30"
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify contract deletion was called
            mock_cogs['Contract'].contract_delete_cron.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_roster_update_task(self, scheduler_with_mocks):
        """Test roster update scheduled task."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "05:00"
            mock_datetime.now.return_value = mock_now
            
            # Mock the parallel processing method
            scheduler._process_roster_updates_parallel = AsyncMock()
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify roster update was called
            scheduler._process_roster_updates_parallel.assert_called_once_with(mock_cogs['GuildMembers'])
    
    @pytest.mark.asyncio
    async def test_event_creation_task(self, scheduler_with_mocks):
        """Test event creation scheduled task."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "12:00"
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify event creation was called
            mock_cogs['GuildEvents'].create_events_for_all_premium_guilds.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_event_reminder_task(self, scheduler_with_mocks):
        """Test event reminder scheduled task."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "13:00"
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify event reminder was called
            mock_cogs['GuildEvents'].event_reminder_cron.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_event_deletion_task(self, scheduler_with_mocks):
        """Test event deletion scheduled task."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "23:30"
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify event deletion was called
            mock_cogs['GuildEvents'].event_delete_cron.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_event_closure_task(self, scheduler_with_mocks):
        """Test event closure scheduled task (every 5 minutes)."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "14:00"
            mock_now.minute = 0  # Divisible by 5
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify event closure was called
            mock_cogs['GuildEvents'].event_close_cron.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_attendance_check_task(self, scheduler_with_mocks):
        """Test attendance check scheduled task (every 5 minutes)."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "10:05"
            mock_now.minute = 5  # Divisible by 5
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify attendance check was called
            mock_cogs['GuildAttendance'].check_voice_presence.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_task_execution_with_locked_task(self, scheduler_with_mocks):
        """Test task execution when lock is already held."""
        scheduler, mock_cogs = scheduler_with_mocks
        
        # Acquire lock manually
        await scheduler._task_locks['contracts'].acquire()
        
        try:
            with patch('scheduler.datetime') as mock_datetime, \
                 patch('scheduler.logging.warning') as mock_warning:
                mock_now = Mock()
                mock_now.strftime.return_value = "06:30"
                mock_datetime.now.return_value = mock_now
                
                await scheduler.execute_scheduled_tasks()
                
                # Verify warning was logged and task was skipped
                mock_warning.assert_called_once()
                assert "already running" in str(mock_warning.call_args)
                mock_cogs['Contract'].contract_delete_cron.assert_not_called()
        finally:
            scheduler._task_locks['contracts'].release()
    
    @pytest.mark.asyncio
    async def test_task_execution_with_missing_cog(self, scheduler_with_mocks):
        """Test task execution when cog is missing."""
        scheduler, mock_cogs = scheduler_with_mocks
        scheduler.bot.get_cog.return_value = None  # No cog available
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "06:30"
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Should complete without error, no cog methods called


class TestRosterUpdateParallel:
    """Test parallel roster update functionality."""
    
    @pytest.fixture
    def scheduler_with_roster_mocks(self):
        """Create scheduler with roster-specific mocks."""
        bot = Mock()
        scheduler = TaskScheduler(bot)
        
        # Mock guild members cog
        mock_guild_members = Mock()
        mock_guild_members.run_maj_roster = AsyncMock()
        
        # Mock guild events cog
        mock_guild_events = Mock()
        mock_guild_events.update_static_groups_message_for_cron = AsyncMock()
        
        # Mock guilds in bot
        mock_guild1 = Mock()
        mock_guild1.id = 123
        mock_guild2 = Mock()
        mock_guild2.id = 456
        mock_guild3 = Mock()
        mock_guild3.id = 789
        bot.guilds = [mock_guild1, mock_guild2, mock_guild3]
        
        bot.get_cog.side_effect = lambda name: {
            'GuildEvents': mock_guild_events
        }.get(name)
        
        return scheduler, mock_guild_members, mock_guild_events
    
    @pytest.mark.asyncio
    async def test_roster_update_parallel_success(self, scheduler_with_roster_mocks):
        """Test successful parallel roster updates."""
        scheduler, mock_guild_members, mock_guild_events = scheduler_with_roster_mocks
        
        with patch('scheduler.logging.info') as mock_info:
            await scheduler._process_roster_updates_parallel(mock_guild_members)
            
            # Verify all guilds were processed
            assert mock_guild_members.run_maj_roster.call_count == 3
            assert mock_guild_events.update_static_groups_message_for_cron.call_count == 3
            
            # Verify completion logging
            mock_info.assert_called_once()
            assert "completed for 3 guilds" in str(mock_info.call_args)
    
    @pytest.mark.asyncio
    async def test_roster_update_parallel_no_guilds(self, scheduler_with_roster_mocks):
        """Test roster update with no guilds."""
        scheduler, mock_guild_members, mock_guild_events = scheduler_with_roster_mocks
        scheduler.bot.guilds = []  # No guilds
        
        with patch('scheduler.logging.info') as mock_info:
            await scheduler._process_roster_updates_parallel(mock_guild_members)
            
            mock_info.assert_called_once_with("[Scheduler] No guilds found for roster update")
            mock_guild_members.run_maj_roster.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_roster_update_parallel_with_failures(self, scheduler_with_roster_mocks):
        """Test roster update with some failures."""
        scheduler, mock_guild_members, mock_guild_events = scheduler_with_roster_mocks
        
        # Make one guild fail
        async def failing_roster_update(guild_id):
            if guild_id == 456:
                raise Exception("Database error")
        
        mock_guild_members.run_maj_roster.side_effect = failing_roster_update
        
        with patch('scheduler.logging.error') as mock_error, \
             patch('scheduler.logging.info') as mock_info:
            
            await scheduler._process_roster_updates_parallel(mock_guild_members)
            
            # Should log error for failed guild
            mock_error.assert_called_once()
            assert "failed for guild 456" in str(mock_error.call_args)
            
            # Should still complete overall process
            mock_info.assert_called_once()
            assert "completed for 3 guilds" in str(mock_info.call_args)


class TestGlobalSchedulerFunctions:
    """Test global scheduler setup and management functions."""
    
    def teardown_method(self):
        """Clean up global state after each test."""
        import scheduler
        if scheduler._scheduled_task:
            scheduler._scheduled_task.cancel()
        scheduler._scheduler_instance = None
        scheduler._scheduled_task = None
    
    def test_setup_task_scheduler(self):
        """Test task scheduler setup."""
        mock_bot = Mock()
        mock_bot.wait_until_ready = AsyncMock()
        
        with patch('scheduler.tasks.loop') as mock_loop:
            mock_task = Mock()
            mock_task.start = Mock()
            mock_task.before_loop = Mock()
            mock_task.after_loop = Mock()
            mock_loop.return_value = mock_task
            
            scheduler_instance = setup_task_scheduler(mock_bot)
            
            assert scheduler_instance is not None
            assert isinstance(scheduler_instance, TaskScheduler)
            mock_task.start.assert_called_once()
    
    def test_setup_task_scheduler_error(self):
        """Test task scheduler setup with error."""
        mock_bot = Mock()
        
        with patch('scheduler.tasks.loop') as mock_loop, \
             patch('scheduler.logging.error') as mock_error:
            mock_task = Mock()
            mock_task.start.side_effect = Exception("Start failed")
            mock_task.before_loop = Mock()
            mock_task.after_loop = Mock()
            mock_loop.return_value = mock_task
            
            scheduler_instance = setup_task_scheduler(mock_bot)
            
            assert scheduler_instance is not None
            mock_error.assert_called_once()
            assert "Error starting task scheduler" in str(mock_error.call_args)
    
    def test_get_scheduler_health_status_with_instance(self):
        """Test getting health status when scheduler exists."""
        import scheduler
        mock_scheduler = Mock()
        mock_scheduler.get_health_status.return_value = {'status': 'healthy'}
        scheduler._scheduler_instance = mock_scheduler
        
        status = get_scheduler_health_status()
        
        assert status == {'status': 'healthy'}
        mock_scheduler.get_health_status.assert_called_once()
    
    def test_get_scheduler_health_status_no_instance(self):
        """Test getting health status when scheduler doesn't exist."""
        import scheduler
        scheduler._scheduler_instance = None
        
        status = get_scheduler_health_status()
        
        assert status == {'error': 'Scheduler not initialized'}
    
    def test_stop_scheduler(self):
        """Test stopping the scheduler."""
        import scheduler
        mock_task = Mock()
        mock_task.cancel = Mock()
        scheduler._scheduled_task = mock_task
        
        with patch('scheduler.logging.info') as mock_info:
            stop_scheduler()
            
            mock_task.cancel.assert_called_once()
            mock_info.assert_called_once_with("[Scheduler] Task scheduler stopped")
    
    def test_stop_scheduler_no_task(self):
        """Test stopping scheduler when no task exists."""
        import scheduler
        scheduler._scheduled_task = None
        
        # Should not raise an error
        stop_scheduler()


class TestSchedulerIntegration:
    """Integration tests for scheduler functionality."""
    
    @pytest.mark.asyncio
    async def test_multiple_time_checks(self):
        """Test scheduler handles multiple different times correctly."""
        bot = Mock()
        bot.get_cog.return_value = None  # No cogs to avoid actual execution
        scheduler = TaskScheduler(bot)
        
        times_to_test = [
            "06:30",  # Contracts
            "05:00",  # Roster
            "12:00",  # Events create
            "13:00",  # Events reminder
            "23:30",  # Events delete
        ]
        
        for test_time in times_to_test:
            with patch('scheduler.datetime') as mock_datetime:
                mock_now = Mock()
                mock_now.strftime.return_value = test_time
                mock_now.minute = 0
                mock_datetime.now.return_value = mock_now
                
                # Should not raise any errors
                await scheduler.execute_scheduled_tasks()
    
    @pytest.mark.asyncio
    async def test_scheduler_timing_precision(self):
        """Test scheduler respects timing precision."""
        bot = Mock()
        scheduler = TaskScheduler(bot)
        
        # Test that minute-based tasks work correctly
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "10:05"
            mock_now.minute = 5  # Should trigger 5-minute tasks
            mock_datetime.now.return_value = mock_now
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify the execution key includes minute precision for 5-minute tasks
            assert any('10:05:1' in key for key in scheduler._last_execution.keys())
    
    @pytest.mark.asyncio
    async def test_concurrent_task_safety(self):
        """Test that concurrent executions are handled safely."""
        bot = Mock()
        scheduler = TaskScheduler(bot)
        
        # Mock a slow-running task
        mock_cog = Mock()
        mock_cog.contract_delete_cron = AsyncMock()
        
        async def slow_task():
            await asyncio.sleep(0.1)
        
        mock_cog.contract_delete_cron.side_effect = slow_task
        bot.get_cog.return_value = mock_cog
        
        with patch('scheduler.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.strftime.return_value = "06:30"
            mock_datetime.now.return_value = mock_now
            
            # Start multiple concurrent executions
            tasks = [
                scheduler.execute_scheduled_tasks(),
                scheduler.execute_scheduled_tasks(),
                scheduler.execute_scheduled_tasks()
            ]
            
            await asyncio.gather(*tasks)
            
            # Only one should have executed (others blocked by lock)
            assert mock_cog.contract_delete_cron.call_count == 1


class TestSchedulerErrorHandling:
    """Test error handling in scheduler."""
    
    @pytest.mark.asyncio
    async def test_cog_method_exception_handling(self):
        """Test handling of exceptions in cog methods."""
        bot = Mock()
        scheduler = TaskScheduler(bot)
        
        mock_cog = Mock()
        mock_cog.contract_delete_cron = AsyncMock(side_effect=Exception("Cog method failed"))
        bot.get_cog.return_value = mock_cog
        
        with patch('scheduler.datetime') as mock_datetime, \
             patch('scheduler.logging.exception') as mock_exception:
            mock_now = Mock()
            mock_now.strftime.return_value = "06:30"
            mock_datetime.now.return_value = mock_now
            
            # Should not raise exception
            await scheduler.execute_scheduled_tasks()
            
            # Should log the exception
            mock_exception.assert_called_once()
            assert "contracts failed" in str(mock_exception.call_args)
    
    @pytest.mark.asyncio
    async def test_timezone_handling(self):
        """Test scheduler handles timezone correctly."""
        if pytz is None:
            pytest.skip("pytz not available")
            
        bot = Mock()
        scheduler = TaskScheduler(bot)
        
        # Verify scheduler uses Europe/Paris timezone
        with patch('scheduler.datetime') as mock_datetime:
            mock_datetime.now.return_value.strftime.return_value = "12:00"
            
            await scheduler.execute_scheduled_tasks()
            
            # Verify timezone was used
            mock_datetime.now.assert_called_with(pytz.timezone("Europe/Paris"))