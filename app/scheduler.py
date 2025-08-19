"""
Task Scheduler Module - Enterprise-grade automated task orchestration.

This module provides a robust scheduling system for Discord bot operations with:
- Time-based task execution with timezone awareness (Europe/Paris)
- Parallel task processing with semaphore-based concurrency control
- Comprehensive metrics tracking and health monitoring
- JSON structured logging with correlation tracking
- Idempotent task execution with duplicate prevention
- Graceful shutdown with timeout-bounded cleanup
- Performance monitoring with high-resolution timers
- Anti-spam logging for bot readiness issues
- Immutable schedule constants for safety

Schedule Overview:
- Epic Items: Daily at 03:30
- Contracts: Daily at 06:30
- Roster Updates: 4x daily at 05:00, 11:00, 17:00, 23:00
- Event Creation: Daily at 12:00
- Event Reminders: Daily at 13:00, 18:00
- Event Deletion: Daily at 23:30, 04:30
- Event Closure: Every 5 minutes
- Attendance Check: Every 5 minutes
- Wishlist Updates: Daily at 09:00, 22:00

Performance Features:
- Lock-based task isolation prevents concurrent execution
- Canonical slot system prevents missed or duplicate executions
- Metrics include success/failure counts, average duration, last error
- Health status exposes active locks and execution history
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, Optional, Any, Callable, Awaitable
from zoneinfo import ZoneInfo

from discord.ext import tasks

from .core.logger import ComponentLogger

# #################################################################################### #
#                            Scheduler Configuration
# #################################################################################### #
TIMEZONE = ZoneInfo("Europe/Paris")

# #################################################################################### #
#                            Schedule Constants
# #################################################################################### #
ROSTER_SLOTS = frozenset({"05:00", "11:00", "17:00", "23:00"})
REMINDER_SLOTS = frozenset({"13:00", "18:00"})
WISHLIST_SLOTS = frozenset({"09:00", "22:00"})
EVENTS_DELETE_SLOTS = frozenset({"23:30", "04:30"})

TASK_COG_MAPPING = {
    "contracts": "Contract",
    "roster": "GuildMembers",
    "events_create": "GuildEvents",
    "events_reminder": "GuildEvents",
    "events_delete": "GuildEvents",
    "events_close": "GuildEvents",
    "attendance_check": "GuildAttendance",
    "epic_items_scraping": "EpicItemsScraper",
    "wishlist_update": "LootWishlist",
}

# #################################################################################### #
#                            Task Scheduler Core System
# #################################################################################### #
class TaskScheduler:
    """Core task scheduler for automated bot operations."""

    def __init__(self, bot):
        """
        Initialize task scheduler with locks, metrics and bot instance.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self._logger = ComponentLogger("scheduler")
        self._task_locks: Dict[str, asyncio.Lock] = {
            "contracts": asyncio.Lock(),
            "roster": asyncio.Lock(),
            "events_create": asyncio.Lock(),
            "events_reminder": asyncio.Lock(),
            "events_delete": asyncio.Lock(),
            "events_close": asyncio.Lock(),
            "attendance_check": asyncio.Lock(),
            "epic_items_scraping": asyncio.Lock(),
            "wishlist_update": asyncio.Lock(),
        }
        self._last_execution: Dict[str, str] = {}
        self._task_metrics: Dict[str, Dict[str, Any]] = {
            task: {
                "success": 0,
                "failures": 0,
                "total_time": 0,
                "last_duration_ms": 0,
                "last_error": None,
                "skipped_no_cog": 0,
                "skipped_not_ready": 0,
            }
            for task in self._task_locks.keys()
        }
        self._last_not_ready_log = 0.0
        self._scheduler_running = False
        self._watchdog_alert_triggered = False
        self._watchdog_threshold_seconds = 300
        self._task_start_times: Dict[str, float] = {}
        self._stuck_tasks: set = set()
        self._logger.info("scheduler_initialized", tasks_count=len(self._task_locks)
        )

    def _should_execute(self, task_key: str, slot: str) -> bool:
        """
        Check if task should execute based on canonical slot.

        Args:
            task_key: Unique identifier for the task
            slot: Canonical slot identifier (YYYYMMDD-HHMM or similar)

        Returns:
            True if task should execute, False otherwise
        """
        if self._last_execution.get(task_key) == slot:
            self._logger.debug("duplicate_slot_skipped", task=task_key, slot=slot)
            return False
        self._last_execution[task_key] = slot
        return True

    async def _execute_with_monitoring(
        self, task_name: str, coroutine: Callable[..., Awaitable[Any]], *args, **kwargs
    ):
        """
        Execute task with performance monitoring and error handling.

        Args:
            task_name: Name of the task for logging and metrics
            coroutine: Coroutine function to execute
            *args: Arguments for the coroutine
            **kwargs: Keyword arguments for the coroutine
        """
        if task_name not in self._task_metrics:
            self._task_metrics[task_name] = {
                "success": 0,
                "failures": 0,
                "total_time": 0,
                "last_duration_ms": 0,
                "last_error": None,
                "skipped_no_cog": 0,
                "skipped_not_ready": 0,
            }

        start_time = time.perf_counter()

        self._task_start_times[task_name] = time.monotonic()
        
        try:
            self._logger.info("task_started", task=task_name)

            try:
                await asyncio.wait_for(
                    coroutine(*args, **kwargs),
                    timeout=self._watchdog_threshold_seconds
                )
            except asyncio.TimeoutError:
                self._stuck_tasks.add(task_name)
                self._watchdog_alert_triggered = True
                self._logger.critical("watchdog_alert",
                    task=task_name,
                    timeout_seconds=self._watchdog_threshold_seconds,
                    action="task_killed"
                )
                raise

            execution_time = int((time.perf_counter() - start_time) * 1000)

            self._stuck_tasks.discard(task_name)
            self._task_metrics[task_name]["success"] += 1
            self._task_metrics[task_name]["total_time"] += execution_time
            self._task_metrics[task_name]["last_duration_ms"] = execution_time
            self._task_metrics[task_name]["last_error"] = None

            self._logger.info("task_finished", task=task_name, duration_ms=execution_time
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            execution_time = int((time.perf_counter() - start_time) * 1000)
            self._task_metrics[task_name]["failures"] += 1
            self._task_metrics[task_name]["last_duration_ms"] = execution_time
            self._task_metrics[task_name]["last_error"] = {
                "type": type(e).__name__,
                "message": str(e),
                "timestamp": datetime.now(TIMEZONE).isoformat(),
            }

            if isinstance(e, asyncio.TimeoutError):
                self._stuck_tasks.add(task_name)
            
            self._logger.error("task_failed",
                task=task_name,
                duration_ms=execution_time,
                error_type=type(e).__name__,
                error_msg=str(e),
                is_timeout=isinstance(e, asyncio.TimeoutError),
                watchdog_triggered=self._watchdog_alert_triggered
            )
        finally:
            self._task_start_times.pop(task_name, None)

    async def _safe_get_cog(self, cog_name: str) -> Optional[Any]:
        """
        Safely get cog with error handling.

        Args:
            cog_name: Name of the cog to retrieve

        Returns:
            Cog instance or None if not found (typed as Any to avoid attribute access issues)
        """
        cog = self.bot.get_cog(cog_name)
        if not cog:
            self._logger.warning("cog_not_found", cog=cog_name)
            for task_name, mapped_cog in TASK_COG_MAPPING.items():
                if mapped_cog == cog_name:
                    self._task_metrics[task_name]["skipped_no_cog"] += 1
        return cog

    # #################################################################################### #
    #                            Scheduled Task Execution
    # #################################################################################### #
    async def execute_scheduled_tasks(self):
        """
        Execute all scheduled tasks based on current time.

        This method runs all time-based scheduled tasks including:
        - Epic items scraping
        - Contract cleanup
        - Roster updates
        - Event management
        - Attendance checks
        - Wishlist updates
        """
        if not self.bot.is_ready():
            now = time.perf_counter()
            if now - self._last_not_ready_log > 300:
                self._logger.warning("bot_still_not_ready",
                    message="Bot not ready for 5+ minutes",
                )
                self._last_not_ready_log = now

            for task_name in self._task_metrics.keys():
                self._task_metrics[task_name]["skipped_not_ready"] += 1
            return

        now_dt = datetime.now(TIMEZONE)
        now_str = now_dt.strftime("%H:%M")
        slot_exact = now_dt.strftime("%Y%m%d-%H%M")
        slot_5min = f"{now_dt.strftime('%Y%m%d-%H')}-{now_dt.minute//5}"

        if now_str == "03:30" and self._should_execute(
            "epic_items_scraping", slot_exact
        ):
            if self._task_locks["epic_items_scraping"].locked():
                self._logger.warning("lock_skipped", task="epic_items_scraping")
            else:
                async with self._task_locks["epic_items_scraping"]:
                    self._logger.info("task_triggered", task="epic_items_scraping")
                    epic_items_cog = await self._safe_get_cog("EpicItemsScraper")
                    if epic_items_cog:
                        await self._execute_with_monitoring(
                            "epic_items_scraping", epic_items_cog.scrape_epic_items
                        )

        if now_str == "06:30" and self._should_execute("contracts", slot_exact):
            if self._task_locks["contracts"].locked():
                self._logger.warning("lock_skipped", task="contracts")
            else:
                async with self._task_locks["contracts"]:
                    self._logger.info("task_triggered", task="contracts")
                    contracts = await self._safe_get_cog("Contract")
                    if contracts:
                        await self._execute_with_monitoring(
                            "contracts", contracts.contract_delete_cron
                        )

        if now_str in ROSTER_SLOTS and self._should_execute("roster", slot_exact):
            if self._task_locks["roster"].locked():
                self._logger.warning("lock_skipped", task="roster")
            else:
                async with self._task_locks["roster"]:
                    self._logger.info("task_triggered", task="roster")
                    guild_members_cog = await self._safe_get_cog("GuildMembers")
                    if guild_members_cog:
                        await self._execute_with_monitoring(
                            "roster",
                            self._process_roster_updates_parallel,
                            guild_members_cog,
                        )

        if now_str == "12:00" and self._should_execute("events_create", slot_exact):
            if self._task_locks["events_create"].locked():
                self._logger.warning("lock_skipped", task="events_create")
            else:
                async with self._task_locks["events_create"]:
                    self._logger.info("task_triggered", task="events_create")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            "events_create",
                            events_cog.create_events_for_all_premium_guilds,
                        )

        if now_str in REMINDER_SLOTS and self._should_execute(
            "events_reminder", slot_exact
        ):
            if self._task_locks["events_reminder"].locked():
                self._logger.warning("lock_skipped", task="events_reminder")
            else:
                async with self._task_locks["events_reminder"]:
                    self._logger.info("task_triggered", task="events_reminder")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            "events_reminder", events_cog.event_reminder_cron
                        )

        if now_str in EVENTS_DELETE_SLOTS and self._should_execute(
            "events_delete", slot_exact
        ):
            if self._task_locks["events_delete"].locked():
                self._logger.warning("lock_skipped", task="events_delete")
            else:
                async with self._task_locks["events_delete"]:
                    self._logger.info("task_triggered", task="events_delete")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            "events_delete", events_cog.event_delete_cron
                        )

        if now_dt.minute % 5 == 0 and self._should_execute("events_close", slot_5min):
            if self._task_locks["events_close"].locked():
                self._logger.debug("lock_skipped", task="events_close")
            else:
                async with self._task_locks["events_close"]:
                    self._logger.info("task_triggered", task="events_close")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            "events_close", events_cog.event_close_cron
                        )

        if now_dt.minute % 5 == 0 and self._should_execute(
            "attendance_check", slot_5min
        ):
            if self._task_locks["attendance_check"].locked():
                self._logger.debug("lock_skipped", task="attendance_check")
            else:
                async with self._task_locks["attendance_check"]:
                    self._logger.debug("task_triggered", task="attendance_check")
                    attendance_cog = await self._safe_get_cog("GuildAttendance")
                    if attendance_cog:
                        await self._execute_with_monitoring(
                            "attendance_check", attendance_cog.check_voice_presence
                        )

        if now_str in WISHLIST_SLOTS and self._should_execute(
            "wishlist_update", slot_exact
        ):
            if self._task_locks["wishlist_update"].locked():
                self._logger.warning("lock_skipped", task="wishlist_update")
            else:
                async with self._task_locks["wishlist_update"]:
                    self._logger.info("task_triggered", task="wishlist_update", time=now_str
                    )
                    loot_wishlist_cog = await self._safe_get_cog("LootWishlist")
                    if loot_wishlist_cog:
                        await self._execute_with_monitoring(
                            "wishlist_update",
                            self._update_all_guild_wishlists,
                            loot_wishlist_cog,
                        )

    async def _update_all_guild_wishlists(self, loot_wishlist_cog):
        """
        Update wishlist messages for all guilds in parallel.

        Args:
            loot_wishlist_cog: LootWishlist cog instance
        """
        if not self.bot.is_ready():
            self._logger.warning("bot_not_ready", task="wishlist_update")
            return

        guild_ids = [guild.id for guild in self.bot.guilds]
        if not guild_ids:
            self._logger.warning("no_guilds_found", task="wishlist_update")
            return

        semaphore = asyncio.Semaphore(5)
        successful_updates = 0
        failed_updates = 0

        async def update_guild_wishlist(guild_id):
            nonlocal successful_updates, failed_updates
            async with semaphore:
                try:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        self._logger.warning("guild_not_accessible", guild_id=guild_id
                        )
                        failed_updates += 1
                        return

                    success = await loot_wishlist_cog.update_wishlist_message(guild_id)
                    if success:
                        successful_updates += 1
                        self._logger.debug("wishlist_updated", guild_id=guild_id)
                    else:
                        failed_updates += 1
                        self._logger.debug("wishlist_update_false", guild_id=guild_id
                        )
                except Exception as e:
                    failed_updates += 1
                    self._logger.error("wishlist_update_error",
                        guild_id=guild_id,
                        error=str(e),
                    )

        tasks = [update_guild_wishlist(guild_id) for guild_id in guild_ids]
        await asyncio.gather(*tasks, return_exceptions=True)

        self._logger.info("wishlist_update_completed",
            successful=successful_updates,
            failed=failed_updates,
            guild_count=len(guild_ids),
        )

    async def _process_roster_updates_parallel(self, guild_members_cog):
        """
        Process roster updates for all guilds in parallel with rate limiting.

        Args:
            guild_members_cog: GuildMembers cog instance
        """
        guild_ids = [guild.id for guild in self.bot.guilds]
        if not guild_ids:
            self._logger.info("no_guilds_found", task="roster_update")
            return

        semaphore = asyncio.Semaphore(5)

        async def process_guild(guild_id):
            async with semaphore:
                try:
                    guild_ptb_config = await self.bot.cache.get_guild_data(
                        guild_id, "ptb_settings"
                    )
                    if (
                        guild_ptb_config
                        and guild_ptb_config.get("ptb_guild_id") == guild_id
                    ):
                        self._logger.debug("ptb_guild_skipped", guild_id=guild_id)
                        return

                    await guild_members_cog.run_maj_roster(guild_id)
                    self._logger.debug("roster_updated", guild_id=guild_id)

                    guild_events_cog = self.bot.get_cog("GuildEvents")
                    if guild_events_cog:
                        await guild_events_cog.update_static_groups_message_for_cron(
                            guild_id
                        )
                        self._logger.debug("static_groups_updated", guild_id=guild_id
                        )

                except Exception as e:
                    self._logger.error("roster_update_failed", guild_id=guild_id, error=str(e)
                    )

        await asyncio.gather(
            *[process_guild(guild_id) for guild_id in guild_ids], return_exceptions=True
        )
        self._logger.info("roster_update_completed", guild_count=len(guild_ids))

    # #################################################################################### #
    #                            Health Monitoring and Status
    # #################################################################################### #
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get scheduler health status and metrics.

        Returns:
            Dictionary containing task metrics, active locks, and last executions
        """
        enriched_metrics = {}
        for task_name, metrics in self._task_metrics.items():
            total_runs = metrics["success"] + metrics["failures"]
            avg_ms = metrics["total_time"] // total_runs if total_runs > 0 else 0

            enriched_metrics[task_name] = {
                **metrics,
                "avg_ms": avg_ms,
                "total_runs": total_runs,
                "last_run": self._last_execution.get(task_name),
            }

        return {
            "task_metrics": enriched_metrics,
            "active_locks": {
                name: lock.locked() for name, lock in self._task_locks.items()
            },
            "last_executions": self._last_execution,
            "scheduler_running": self._scheduler_running,
        }

# #################################################################################### #
#                            Global Scheduler Components
# #################################################################################### #
_scheduler_instance: Optional[TaskScheduler] = None
_scheduled_task: Optional[tasks.Loop] = None
_scheduler_logger = ComponentLogger("scheduler_global")

def setup_task_scheduler(bot):
    """
    Initialize and start the task scheduler.

    Args:
        bot: Discord bot instance

    Returns:
        TaskScheduler instance
    """
    global _scheduler_instance, _scheduled_task

    if _scheduled_task and _scheduled_task.is_running():
        _scheduler_logger.warning("scheduler_already_running")
        return _scheduler_instance

    _scheduler_instance = TaskScheduler(bot)

    @tasks.loop(minutes=1)
    async def scheduled_tasks():
        if _scheduler_instance:
            await _scheduler_instance.execute_scheduled_tasks()

    @scheduled_tasks.before_loop
    async def before_scheduled_tasks():
        _scheduler_instance._logger.debug("waiting_for_bot")
        await bot.wait_until_ready()
        _scheduler_instance._scheduler_running = True
        _scheduler_instance._logger.info("scheduler_started")

    @scheduled_tasks.after_loop
    async def after_scheduled_tasks():
        _scheduler_instance._scheduler_running = False
        if scheduled_tasks.is_being_cancelled():
            _scheduler_instance._logger.info("scheduler_stopped")
        else:
            _scheduler_instance._logger.warning("scheduler_stopped_unexpectedly")

    _scheduled_task = scheduled_tasks

    if hasattr(bot, "_background_tasks"):
        bot._scheduler_loop = scheduled_tasks

    try:
        scheduled_tasks.start()
        _scheduler_instance._logger.info("scheduler_launch_success")
    except Exception as e:
        _scheduler_instance._logger.error("scheduler_launch_failed", error=str(e))

    return _scheduler_instance

def get_scheduler_health_status() -> Dict[str, Any]:
    """
    Get current scheduler health status.

    Returns:
        Dictionary containing scheduler health status or error message
    """
    if _scheduler_instance:
        return _scheduler_instance.get_health_status()
    return {"error": "Scheduler not initialized", "scheduler_running": False}

async def stop_scheduler():
    """
    Stop the task scheduler and cancel all scheduled tasks properly.
    """
    global _scheduled_task
    if not _scheduled_task:
        if _scheduler_instance:
            _scheduler_instance._logger.debug("scheduler_not_running")
        return

    _scheduled_task.cancel()

    max_wait = 5.0
    poll_interval = 0.1
    start = time.perf_counter()

    while _scheduled_task.is_running():
        elapsed = time.perf_counter() - start
        if elapsed >= max_wait:
            if _scheduler_instance:
                _scheduler_instance._logger.warning(
                    "scheduler_stop_timeout", waited_ms=int(elapsed * 1000)
                )
            break
        await asyncio.sleep(poll_interval)

    if not _scheduled_task.is_running():
        if _scheduler_instance:
            elapsed = time.perf_counter() - start
            _scheduler_instance._logger.info(
                "scheduler_stopped_cleanly", waited_ms=int(elapsed * 1000)
            )
