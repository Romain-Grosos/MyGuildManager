"""
Health Monitor Cog - Integrated bot health monitoring system.
"""

import discord
from discord.ext import commands, tasks
import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
import json
from scheduler import get_scheduler_health_status
from cache import get_global_cache

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


class Health(commands.Cog):
    """Cog for monitoring bot health and performance metrics."""
    
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        
        self.component_status = {
            'database': 'unknown',
            'discord_api': 'unknown',
            'memory': 'unknown',
            'cpu': 'unknown',
            'scheduler': 'unknown',
            'cache': 'unknown'
        }
        
        self.command_metrics = {}
        self.last_health_check = 0
        
        self.health_check_loop.start()
        
        logging.info("[Health] Health monitoring cog loaded")
    
    def cog_unload(self):
        """Clean up tasks when unloading cog."""
        self.health_check_loop.cancel()
    
    @tasks.loop(minutes=5)
    async def health_check_loop(self):
        """Periodically check health of all system components."""
        try:
            await self._check_all_components()
            self.last_health_check = time.time()
        except Exception as e:
            logging.error(f"[Health] Health check failed: {e}")
    
    @health_check_loop.before_loop
    async def before_health_check(self):
        """Wait for bot to be ready before starting health checks."""
        await self.bot.wait_until_ready()
    
    async def _check_all_components(self):
        """Check health status of all system components."""
        
        self.component_status['database'] = await self._check_database()
        self.component_status['discord_api'] = await self._check_discord_api()
        
        if PSUTIL_AVAILABLE:
            self.component_status['memory'] = self._check_memory()
            self.component_status['cpu'] = self._check_cpu()
        
        self.component_status['scheduler'] = self._check_scheduler()
        self.component_status['cache'] = self._check_cache()
        
        unhealthy = [name for name, status in self.component_status.items() if status == 'error']
        if unhealthy:
            logging.warning(f"[Health] Unhealthy components: {unhealthy}")
    
    async def _check_database(self) -> str:
        """Check database health and response time."""
        try:
            start_time = time.time()
            await self.bot.run_db_query("SELECT 1", fetch_one=True)
            response_time = (time.time() - start_time) * 1000
            
            if response_time > 5000:
                return 'error'
            elif response_time > 1000:
                return 'warning'
            else:
                return 'healthy'
                
        except Exception as e:
            logging.error(f"[Health] Database check failed: {e}")
            return 'error'
    
    async def _check_discord_api(self) -> str:
        """Check Discord API health and response time."""
        try:
            start_time = time.time()
            await self.bot.fetch_user(self.bot.user.id)
            response_time = (time.time() - start_time) * 1000
            
            if response_time > 10000:
                return 'error'
            elif response_time > 2000:
                return 'warning'
            else:
                return 'healthy'
                
        except discord.HTTPException as e:
            if e.status == 429:
                return 'warning'
            else:
                return 'error'
        except Exception:
            return 'error'
    
    def _check_memory(self) -> str:
        """Check memory usage status."""
        try:
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            
            if memory_mb > 2048:
                return 'error'
            elif memory_mb > 1024:
                return 'warning'
            else:
                return 'healthy'
                
        except Exception:
            return 'unknown'
    
    def _check_cpu(self) -> str:
        """Check CPU usage status."""
        try:
            process = psutil.Process()
            cpu_percent = process.cpu_percent()
            
            if cpu_percent > 80:
                return 'error'
            elif cpu_percent > 50:
                return 'warning'
            else:
                return 'healthy'
                
        except Exception:
            return 'unknown'
    
    def _check_scheduler(self) -> str:
        """Check scheduler health and task status."""
        try:
            scheduler_status = get_scheduler_health_status()
            if 'error' in scheduler_status:
                return 'error'
            
            task_metrics = scheduler_status.get('task_metrics', {})
            total_failures = sum(metrics.get('failures', 0) for metrics in task_metrics.values())
            total_tasks = sum(metrics.get('success', 0) + metrics.get('failures', 0) for metrics in task_metrics.values())
            
            if total_tasks > 0:
                failure_rate = (total_failures / total_tasks) * 100
                if failure_rate > 20:
                    return 'error'
                elif failure_rate > 10:
                    return 'warning'
            
            return 'healthy'
            
        except Exception:
            return 'unknown'
    
    def _check_cache(self) -> str:
        """Check global cache system health."""
        try:
            cache = get_global_cache()
            metrics = cache.get_metrics()
            
            global_metrics = metrics['global']
            hit_rate = global_metrics.get('hit_rate', 0)
            total_entries = global_metrics.get('total_entries', 0)
            
            if total_entries > 10000:
                return 'warning'
            elif hit_rate < 30 and global_metrics.get('total_requests', 0) > 100:
                return 'warning'
            
            return 'healthy'
            
        except Exception:
            return 'unknown'
    
    def record_command_execution(self, command_name: str, execution_time: float, success: bool = True):
        """Record command execution metrics."""
        if command_name not in self.command_metrics:
            self.command_metrics[command_name] = {'count': 0, 'total_time': 0, 'errors': 0}
        
        metrics = self.command_metrics[command_name]
        metrics['count'] += 1
        metrics['total_time'] += execution_time
        
        if not success:
            metrics['errors'] += 1
    
    @discord.slash_command(name="health", description="Display bot health status")
    @commands.has_permissions(administrator=True)
    async def health_command(self, ctx: discord.ApplicationContext):
        """Command to display health status."""
        await ctx.defer(ephemeral=True)
        
        await self._check_all_components()
        embed = await self._create_health_embed()
        
        await ctx.followup.send(embed=embed, ephemeral=True)
    
    @discord.slash_command(name="metrics", description="Display detailed performance metrics")
    @commands.has_permissions(administrator=True)
    async def metrics_command(self, ctx: discord.ApplicationContext):
        """Command to display detailed metrics."""
        await ctx.defer(ephemeral=True)
        
        embed = await self._create_metrics_embed()
        
        await ctx.followup.send(embed=embed, ephemeral=True)
    
    async def _create_health_embed(self) -> discord.Embed:
        """Create health status embed."""
        
        status_icons = {
            'healthy': '🟢',
            'warning': '🟡', 
            'error': '🔴',
            'unknown': '⚪'
        }
        
        overall_status = 'healthy'
        if 'error' in self.component_status.values():
            overall_status = 'error'
        elif 'warning' in self.component_status.values():
            overall_status = 'warning'
        
        color_map = {
            'healthy': discord.Color.green(),
            'warning': discord.Color.yellow(),
            'error': discord.Color.red(),
            'unknown': discord.Color.light_grey()
        }
        
        embed = discord.Embed(
            title=f"{status_icons[overall_status]} Bot Health Status",
            color=color_map[overall_status],
            timestamp=datetime.utcnow()
        )
        
        for component, status in self.component_status.items():
            embed.add_field(
                name=component.replace('_', ' ').title(),
                value=f"{status_icons[status]} {status}",
                inline=True
            )
        
        uptime_seconds = time.time() - self.start_time
        uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        
        embed.add_field(
            name="⏱️ Uptime",
            value=uptime_str,
            inline=True
        )
        
        embed.add_field(
            name="🤖 Bot Info",
            value=f"Latency: {self.bot.latency * 1000:.0f}ms\nGuilds: {len(self.bot.guilds)}",
            inline=True
        )
        
        embed.set_footer(text="Last check")
        
        return embed
    
    async def _create_metrics_embed(self) -> discord.Embed:
        """Create performance metrics embed."""
        
        embed = discord.Embed(
            title="📊 Performance Metrics",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        if hasattr(self.bot, 'optimizer'):
            stats = self.bot.optimizer.get_performance_stats()
            
            embed.add_field(
                name="🎯 Commands",
                value=f"Executed: {stats['commands_executed']}\nDB queries: {stats['db_queries_count']}",
                inline=True
            )
            
            embed.add_field(
                name="🌐 Discord API",
                value=f"Total calls: {stats['api_calls_total']}\nCached: {stats['api_calls_cached']}",
                inline=True
            )
            
            embed.add_field(
                name="💾 Cache",
                value=f"Hit rate: {stats['cache_hit_rate']}%\nSize: {stats['cache_size']}",
                inline=True
            )
        
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                cpu_percent = process.cpu_percent()
                
                embed.add_field(
                    name="🖥️ System",
                    value=f"CPU: {cpu_percent:.1f}%\nRAM: {memory_mb:.0f}MB",
                    inline=True
                )
            except Exception:
                pass
        
        if self.command_metrics:
            top_commands = sorted(
                self.command_metrics.items(),
                key=lambda x: x[1]['count'],
                reverse=True
            )[:5]
            
            top_commands_text = "\n".join([
                f"{cmd}: {data['count']}x"
                for cmd, data in top_commands
            ])
            
            embed.add_field(
                name="🏆 Top Commands",
                value=top_commands_text or "None",
                inline=True
            )
        
        scheduler_status = get_scheduler_health_status()
        if 'task_metrics' in scheduler_status:
            task_metrics = scheduler_status['task_metrics']
            total_success = sum(metrics.get('success', 0) for metrics in task_metrics.values())
            total_failures = sum(metrics.get('failures', 0) for metrics in task_metrics.values())
            
            embed.add_field(
                name="⏰ Scheduler",
                value=f"Success: {total_success}\nFailures: {total_failures}",
                inline=True
            )
        
        try:
            cache = get_global_cache()
            cache_metrics = cache.get_metrics()
            global_cache = cache_metrics['global']
            
            embed.add_field(
                name="🗄️ Global Cache",
                value=f"Hit rate: {global_cache['hit_rate']}%\nEntries: {global_cache['total_entries']}",
                inline=True
            )
        except Exception:
            pass
        
        return embed
    
    @discord.slash_command(name="clear-cache", description="Clear bot cache")
    @commands.has_permissions(administrator=True)
    async def clear_cache_command(self, ctx: discord.ApplicationContext):
        """Command to clear bot cache."""
        await ctx.defer(ephemeral=True)
        
        cleared_count = 0
        
        if hasattr(self.bot, 'optimizer'):
            self.bot.optimizer._member_cache.clear()
            self.bot.optimizer._channel_cache.clear()
            self.bot.optimizer._guild_cache.clear()
            self.bot.optimizer._cache_times.clear()
            cleared_count += 50  # Estimate
        
        try:
            cache = get_global_cache()
            metrics_before = cache.get_metrics()
            global_entries_before = metrics_before['global']['total_entries']
            
            for category in ['guild_data', 'user_data', 'events_data', 'roster_data', 'temporary']:
                await cache.invalidate_category(category)
            
            metrics_after = cache.get_metrics()
            global_entries_after = metrics_after['global']['total_entries']
            global_cleared = global_entries_before - global_entries_after
            cleared_count += global_cleared
            
        except Exception as e:
            logging.error(f"[Health] Error clearing global cache: {e}")
        
        await ctx.followup.send(f"✅ Cache cleared ({cleared_count} entries removed)", ephemeral=True)
        logging.info(f"[Health] Cache cleared by {ctx.author} ({cleared_count} entries)")
    
    async def get_health_status(self) -> Dict[str, str]:
        """Get current health status of all components."""
        await self._check_all_components()
        return self.component_status.copy()
    
    def get_uptime(self) -> timedelta:
        """Get bot uptime."""
        return timedelta(seconds=int(time.time() - self.start_time))


def setup(bot):
    """Setup function for the cog."""
    bot.add_cog(Health(bot))
    logging.info("[Health] Health monitoring cog setup completed")