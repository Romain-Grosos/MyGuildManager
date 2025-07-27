import logging
import discord
import asyncio
import time
from discord.ext import tasks, commands
from datetime import datetime
from typing import Dict, Set, Optional
import pytz

TIMEZONE = pytz.timezone("Europe/Paris")

class Cron(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._task_locks: Dict[str, asyncio.Lock] = {
            'contracts': asyncio.Lock(),
            'roster': asyncio.Lock(),
            'events_create': asyncio.Lock(),
            'events_reminder': asyncio.Lock(),
            'events_delete': asyncio.Lock(),
            'events_close': asyncio.Lock(),
            'attendance_check': asyncio.Lock()
        }
        self._last_execution: Dict[str, str] = {}
        self._task_metrics: Dict[str, Dict[str, int]] = {
            task: {'success': 0, 'failures': 0, 'total_time': 0} 
            for task in self._task_locks.keys()
        }
        
        try:
            self.scheduled_tasks.start()
            logging.info("✅ [CRON] Scheduled task started successfully!")
        except Exception as e:
            logging.error(f"❌ [CRON] Error while starting the cron: {e}")

    def _should_execute(self, task_key: str, current_time: str) -> bool:
        if self._last_execution.get(task_key) == current_time:
            return False
        self._last_execution[task_key] = current_time
        return True
    
    async def _execute_with_monitoring(self, task_name: str, coroutine, *args, **kwargs):
        start_time = time.time()
        try:
            await coroutine(*args, **kwargs)
            self._task_metrics[task_name]['success'] += 1
            execution_time = int((time.time() - start_time) * 1000)
            self._task_metrics[task_name]['total_time'] += execution_time
            logging.info(f"✅ [CRON] {task_name} completed successfully in {execution_time}ms")
        except Exception as e:
            self._task_metrics[task_name]['failures'] += 1
            execution_time = int((time.time() - start_time) * 1000)
            logging.exception(f"❌ [CRON] {task_name} failed after {execution_time}ms: {e}")
    
    async def _safe_get_cog(self, cog_name: str) -> Optional[object]:
        cog = self.bot.get_cog(cog_name)
        if not cog:
            logging.warning(f"⚠️ [CRON] {cog_name} cog not found, skipping related tasks")
        return cog
    
    @tasks.loop(minutes=1)
    async def scheduled_tasks(self):
        now = datetime.now(TIMEZONE).strftime("%H:%M")
        now_time = datetime.now(TIMEZONE)

        if now == "06:30" and self._should_execute('contracts', now):
            if self._task_locks['contracts'].locked():
                logging.warning("⚠️ [CRON] Contract deletion already running, skipping")
            else:
                async with self._task_locks['contracts']:
                    logging.info("⏰ [CRON] Automatic deletion of contracts")
                    contracts = await self._safe_get_cog("Contract")
                    if contracts:
                        await self._execute_with_monitoring(
                            'contracts', 
                            contracts.contract_delete_cron
                        )

        if now in {"05:00", "11:00", "17:00", "23:00"} and self._should_execute('roster', now):
            if self._task_locks['roster'].locked():
                logging.warning("⚠️ [CRON] Roster update already running, skipping")
            else:
                async with self._task_locks['roster']:
                    logging.info("⏰ [CRON] Launching roster update for all guilds")
                    guild_members_cog = await self._safe_get_cog("GuildMembers")
                    if guild_members_cog:
                        await self._execute_with_monitoring(
                            'roster',
                            self._process_roster_updates_parallel,
                            guild_members_cog
                        )

        if now == "12:00" and self._should_execute('events_create', now):
            if self._task_locks['events_create'].locked():
                logging.warning("⚠️ [CRON] Event creation already running, skipping")
            else:
                async with self._task_locks['events_create']:
                    logging.info("⏰ [CRON] Automatic event creation triggered")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_create',
                            events_cog.create_events_for_all_premium_guilds
                        )

        if now in ["13:00", "18:00"] and self._should_execute('events_reminder', now):
            if self._task_locks['events_reminder'].locked():
                logging.warning("⚠️ [CRON] Event reminder already running, skipping")
            else:
                async with self._task_locks['events_reminder']:
                    logging.info("⏰ [CRON] Automatic registration reminder triggered")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_reminder',
                            events_cog.event_reminder_cron
                        )

        if now in ["23:30", "04:30"] and self._should_execute('events_delete', now):
            if self._task_locks['events_delete'].locked():
                logging.warning("⚠️ [CRON] Event deletion already running, skipping")
            else:
                async with self._task_locks['events_delete']:
                    logging.info("⏰ [CRON] Automatic deletion of finished events")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_delete',
                            events_cog.event_delete_cron
                        )

        if now_time.minute % 5 == 0 and self._should_execute('events_close', f"{now}:{now_time.minute//5}"):
            if self._task_locks['events_close'].locked():
                logging.debug("⚠️ [CRON] Event closure already running, skipping")
            else:
                async with self._task_locks['events_close']:
                    logging.info("⏰ [CRON] Automatic closure of confirmed events")
                    events_cog = await self._safe_get_cog("GuildEvents")
                    if events_cog:
                        await self._execute_with_monitoring(
                            'events_close',
                            events_cog.event_close_cron
                        )

        if now_time.minute % 5 == 0 and self._should_execute('attendance_check', f"{now}:{now_time.minute//5}"):
            if self._task_locks['attendance_check'].locked():
                logging.debug("⚠️ [CRON] Attendance check already running, skipping")
            else:
                async with self._task_locks['attendance_check']:
                    logging.debug("⏰ [CRON] Automatic voice presence check")
                    attendance_cog = await self._safe_get_cog("GuildAttendance")
                    if attendance_cog:
                        await self._execute_with_monitoring(
                            'attendance_check',
                            attendance_cog.check_voice_presence
                        )

    async def _process_roster_updates_parallel(self, guild_members_cog):
        guild_ids = list(guild_members_cog.forum_channels.keys())
        if not guild_ids:
            logging.info("[CRON] No guilds found for roster update")
            return

        semaphore = asyncio.Semaphore(5)
        
        async def process_guild(guild_id):
            async with semaphore:
                try:
                    await guild_members_cog.run_maj_roster(guild_id)
                    logging.debug(f"✅ [CRON] Roster updated for guild {guild_id}")
                    
                    guild_events_cog = self.bot.get_cog("GuildEvents")
                    if guild_events_cog:
                        await guild_events_cog.update_static_groups_message_for_cron(guild_id)
                        logging.debug(f"✅ [CRON] Static groups updated for guild {guild_id}")
                    
                except Exception as e:
                    logging.error(f"❌ [CRON] Roster update failed for guild {guild_id}: {e}")
                await asyncio.sleep(0.5)
        
        await asyncio.gather(*[process_guild(guild_id) for guild_id in guild_ids], return_exceptions=True)
        logging.info(f"[CRON] Roster update completed for {len(guild_ids)} guilds")
    
    def get_health_status(self) -> dict:
        return {
            'task_metrics': self._task_metrics,
            'active_locks': {name: lock.locked() for name, lock in self._task_locks.items()},
            'last_executions': self._last_execution
        }
    
    @scheduled_tasks.before_loop
    async def before_scheduled_tasks(self):
        logging.debug("⌛ [CRON] Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        logging.debug("✅ [CRON] Bot is ready, starting cron")

    @scheduled_tasks.after_loop
    async def after_scheduled_tasks(self):
        if self.scheduled_tasks.is_being_cancelled():
            logging.info("[CRON] Scheduled tasks stopped")
        else:
            logging.warning("[CRON] Scheduled tasks stopped unexpectedly")

def setup(bot: discord.Bot):
    bot.add_cog(Cron(bot))
