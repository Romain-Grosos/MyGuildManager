import logging
import asyncio
import time
from datetime import datetime
from typing import Dict, Set, Optional
import discord
import pytz
from discord.ext import tasks

# #################################################################################### #
#                            Scheduler Configuration
# #################################################################################### #
TIMEZONE = pytz.timezone("Europe/Paris")

# #################################################################################### #
#                            Task Scheduler Core System
# #################################################################################### #
class TaskScheduler:
    """Core task scheduler for automated bot operations."""
    
    def __init__(self, bot):
        self.bot = bot
        self._task_locks: Dict[str, asyncio.Lock] = {
            'contracts': asyncio.Lock(),
            'roster': asyncio.Lock(),
            'events_create': asyncio.Lock(),
            'events_reminder': asyncio.Lock(),
            'events_delete': asyncio.Lock(),
            'events_close': asyncio.Lock(),
            'attendance_check': asyncio.Lock(),
            'epic_items_scraping': asyncio.Lock(),
            'wishlist_update': asyncio.Lock()
        }
        self._last_execution: Dict[str, str] = {}
        self._task_metrics: Dict[str, Dict[str, int]] = {
            task: {'success': 0, 'failures': 0, 'total_time': 0} 
            for task in self._task_locks.keys()
        }
        
        logging.info("[Scheduler] Task scheduler initialized")

    def _should_execute(self, task_key: str, current_time: str) -> bool:
        """Check if task should execute based on last execution time."""
        if self._last_execution.get(task_key) == current_time:
            return False
        self._last_execution[task_key] = current_time
        return True
    
    async def _execute_with_monitoring(self, task_name: str, coroutine, *args, **kwargs):
        """Execute task with performance monitoring and error handling."""
        if task_name not in self._task_metrics:
            self._task_metrics[task_name] = {'success': 0, 'failures': 0, 'total_time': 0}
        
        start_time = time.time()
        try:
            await coroutine(*args, **kwargs)
            self._task_metrics[task_name]['success'] += 1
            execution_time = int((time.time() - start_time) * 1000)
            self._task_metrics[task_name]['total_time'] += execution_time
            logging.info(f"[Scheduler] {task_name} completed successfully in {execution_time}ms")
        except Exception as e:
            self._task_metrics[task_name]['failures'] += 1
            execution_time = int((time.time() - start_time) * 1000)
            logging.exception(f"[Scheduler] {task_name} failed after {execution_time}ms: {e}")
    
    async def _safe_get_cog(self, cog_name: str) -> Optional[object]:
        """Safely get cog with error handling."""
        cog = self.bot.get_cog(cog_name)
        if not cog:
            logging.warning(f"[Scheduler] {cog_name} cog not found, skipping related tasks")
        return cog

# #################################################################################### #
#                            Scheduled Task Execution
# #################################################################################### #
    async def execute_scheduled_tasks(self):
        """Execute all scheduled tasks based on current time."""
        now = datetime.now(TIMEZONE).strftime("%H:%M")
        now_time = datetime.now(TIMEZONE)

        if now == "03:30" and self._should_execute('epic_items_scraping', now):
            if self._task_locks['epic_items_scraping'].locked():
                logging.warning("[Scheduler] Epic items scraping already running, skipping")
            else:
                async with self._task_locks['epic_items_scraping']:
                    logging.info("[Scheduler] Automatic Epic T2 items scraping triggered")
                    epic_items_cog = await self._safe_get_cog("EpicItemsScraper")
                    if epic_items_cog:
                        await self._execute_with_monitoring(
                            'epic_items_scraping',
                            epic_items_cog.scrape_epic_items
                        )

        if now == "06:30" and self._should_execute('contracts', now):
            if self._task_locks['contracts'].locked():
                logging.warning("[Scheduler] Contract deletion already running, skipping")
            else:
                async with self._task_locks['contracts']:
                    logging.info("[Scheduler] Automatic deletion of contracts")
                    contracts = await self._safe_get_cog("Contract")
                    if contracts:
                        await self._execute_with_monitoring(
                            'contracts', 
                            contracts.contract_delete_cron
                        )

        if now in {"05:00", "11:00", "17:00", "23:00"} and self._should_execute('roster', now):
            if self._task_locks['roster'].locked():
                logging.warning("[Scheduler] Roster update already running, skipping")
            else:
                async with self._task_locks['roster']:
                    logging.info("[Scheduler] Launching roster update for all guilds")
                    guild_members_cog = await self._safe_get_cog("GuildMembers")
                    if guild_members_cog:
                        await self._execute_with_monitoring(
                            'roster',
                            self._process_roster_updates_parallel,
                            guild_members_cog
                        )

        if now == "12:00" and self._should_execute('events_create', now):
            if self._task_locks['events_create'].locked():
                logging.warning("[Scheduler] Event creation already running, skipping")
            else:
                async with self._task_locks['events_create']:
                    logging.info("[Scheduler] Automatic event creation triggered")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_create',
                            events_cog.create_events_for_all_premium_guilds
                        )

        if now in ["13:00", "18:00"] and self._should_execute('events_reminder', now):
            if self._task_locks['events_reminder'].locked():
                logging.warning("[Scheduler] Event reminder already running, skipping")
            else:
                async with self._task_locks['events_reminder']:
                    logging.info("[Scheduler] Automatic registration reminder triggered")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_reminder',
                            events_cog.event_reminder_cron
                        )

        if now in ["23:30", "04:30"] and self._should_execute('events_delete', now):
            if self._task_locks['events_delete'].locked():
                logging.warning("[Scheduler] Event deletion already running, skipping")
            else:
                async with self._task_locks['events_delete']:
                    logging.info("[Scheduler] Automatic deletion of finished events")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_delete',
                            events_cog.event_delete_cron
                        )

        if now_time.minute % 5 == 0 and self._should_execute('events_close', f"{now}:{now_time.minute//5}"):
            if self._task_locks['events_close'].locked():
                logging.debug("[Scheduler] Event closure already running, skipping")
            else:
                async with self._task_locks['events_close']:
                    logging.info("[Scheduler] Automatic closure of confirmed events")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_close',
                            events_cog.event_close_cron
                        )

        if now_time.minute % 5 == 0 and self._should_execute('attendance_check', f"{now}:{now_time.minute//5}"):
            if self._task_locks['attendance_check'].locked():
                logging.debug("[Scheduler] Attendance check already running, skipping")
            else:
                async with self._task_locks['attendance_check']:
                    logging.debug("[Scheduler] Automatic voice presence check")
                    attendance_cog = await self._safe_get_cog("GuildAttendance")
                    if attendance_cog:
                        await self._execute_with_monitoring(
                            'attendance_check',
                            attendance_cog.check_voice_presence
                        )

        if now in ["09:00", "22:00"] and self._should_execute('wishlist_update', now):
            if self._task_locks['wishlist_update'].locked():
                logging.warning("[Scheduler] Wishlist update already running, skipping")
            else:
                async with self._task_locks['wishlist_update']:
                    logging.info(f"[Scheduler] Automatic wishlist update triggered at {now}")
                    loot_wishlist_cog = await self._safe_get_cog("LootWishlist")
                    if loot_wishlist_cog:
                        await self._execute_with_monitoring(
                            'wishlist_update',
                            self._update_all_guild_wishlists,
                            loot_wishlist_cog
                        )

    async def _update_all_guild_wishlists(self, loot_wishlist_cog):
        """Update wishlist messages for all guilds in parallel."""
        guild_ids = [guild.id for guild in self.bot.guilds]
        if not guild_ids:
            logging.info("[Scheduler] No guilds found for wishlist update")
            return
        
        semaphore = asyncio.Semaphore(3)
        successful_updates = 0
        failed_updates = 0
        
        async def update_guild_wishlist(guild_id):
            nonlocal successful_updates, failed_updates
            async with semaphore:
                try:
                    success = await loot_wishlist_cog.update_wishlist_message(guild_id)
                    if success:
                        successful_updates += 1
                        logging.debug(f"[Scheduler] Wishlist updated for guild {guild_id}")
                    else:
                        failed_updates += 1
                        logging.debug(f"[Scheduler] Wishlist update failed for guild {guild_id}")
                except Exception as e:
                    failed_updates += 1
                    logging.error(f"[Scheduler] Error updating wishlist for guild {guild_id}: {e}")

        tasks = [update_guild_wishlist(guild_id) for guild_id in guild_ids]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logging.info(f"[Scheduler] Wishlist update completed: {successful_updates} successful, {failed_updates} failed")

    async def _process_roster_updates_parallel(self, guild_members_cog):
        """Process roster updates for all guilds in parallel with rate limiting."""
        guild_ids = [guild.id for guild in self.bot.guilds]
        if not guild_ids:
            logging.info("[Scheduler] No guilds found for roster update")
            return

        semaphore = asyncio.Semaphore(5)
        
        async def process_guild(guild_id):
            async with semaphore:
                try:
                    await guild_members_cog.run_maj_roster(guild_id)
                    logging.debug(f"[Scheduler] Roster updated for guild {guild_id}")
                    
                    guild_events_cog = self.bot.get_cog("GuildEvents")
                    if guild_events_cog:
                        await guild_events_cog.update_static_groups_message_for_cron(guild_id)
                        logging.debug(f"[Scheduler] Static groups updated for guild {guild_id}")
                    
                except Exception as e:
                    logging.error(f"[Scheduler] Roster update failed for guild {guild_id}: {e}")
                await asyncio.sleep(0.5)
        
        await asyncio.gather(*[process_guild(guild_id) for guild_id in guild_ids], return_exceptions=True)
        logging.info(f"[Scheduler] Roster update completed for {len(guild_ids)} guilds")

# #################################################################################### #
#                            Health Monitoring and Status
# #################################################################################### #
    def get_health_status(self) -> dict:
        """Get scheduler health status and metrics."""
        return {
            'task_metrics': self._task_metrics,
            'active_locks': {name: lock.locked() for name, lock in self._task_locks.items()},
            'last_executions': self._last_execution
        }

# #################################################################################### #
#                            Global Scheduler Components
# #################################################################################### #
_scheduler_instance = None
_scheduled_task = None

def setup_task_scheduler(bot):
    """Initialize and start the task scheduler."""
    global _scheduler_instance, _scheduled_task
    
    _scheduler_instance = TaskScheduler(bot)
    
    @tasks.loop(minutes=1)
    async def scheduled_tasks():
        await _scheduler_instance.execute_scheduled_tasks()
    
    @scheduled_tasks.before_loop
    async def before_scheduled_tasks():
        logging.debug("[Scheduler] Waiting for bot to be ready...")
        await bot.wait_until_ready()
        logging.debug("[Scheduler] Bot is ready, starting scheduler")
    
    @scheduled_tasks.after_loop
    async def after_scheduled_tasks():
        if scheduled_tasks.is_being_cancelled():
            logging.info("[Scheduler] Scheduled tasks stopped")
        else:
            logging.warning("[Scheduler] Scheduled tasks stopped unexpectedly")
    
    _scheduled_task = scheduled_tasks

    if hasattr(bot, '_background_tasks'):
        bot._scheduler_loop = scheduled_tasks
    
    try:
        scheduled_tasks.start()
        logging.info("[Scheduler] Task scheduler started successfully")
    except Exception as e:
        logging.error(f"[Scheduler] Error starting task scheduler: {e}")
    
    return _scheduler_instance

def get_scheduler_health_status() -> dict:
    """Get current scheduler health status."""
    if _scheduler_instance:
        return _scheduler_instance.get_health_status()
    return {'error': 'Scheduler not initialized'}

def stop_scheduler():
    """Stop the task scheduler."""
    global _scheduled_task
    if _scheduled_task:
        _scheduled_task.cancel()
        logging.info("[Scheduler] Task scheduler stopped")