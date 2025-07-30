"""
Reliability Monitor Cog - Commands for managing system reliability and resilience.
"""

import discord
from discord.ext import commands, tasks
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional

class ReliabilityMonitor(commands.Cog):
    """Cog for monitoring and managing system reliability."""
    
    def __init__(self, bot):
        self.bot = bot
        self.auto_backup_task.start()
        
    def cog_unload(self):
        """Cleanup when cog is unloaded."""
        self.auto_backup_task.cancel()
    
    @tasks.loop(hours=6)
    async def auto_backup_task(self):
        """Automated backup task for critical guilds."""
        if not hasattr(self.bot, 'reliability_system'):
            return
            
        try:
            for guild in self.bot.guilds:
                if len(guild.members) > 50:
                    try:
                        await self.bot.reliability_system.backup_manager.backup_guild_data(self.bot, guild.id)
                        await asyncio.sleep(10)
                    except Exception as e:
                        logging.error(f"[ReliabilityMonitor] Auto backup failed for guild {guild.id}: {e}")
        except Exception as e:
            logging.error(f"[ReliabilityMonitor] Auto backup task failed: {e}")
    
    @auto_backup_task.before_loop
    async def before_auto_backup(self):
        """Wait for bot to be ready before starting backup task."""
        await self.bot.wait_until_ready()
    
    @discord.slash_command(name="reliability", description="Show system reliability status")
    @commands.has_permissions(administrator=True)
    async def reliability_status(self, ctx: discord.ApplicationContext):
        """Display system reliability status."""
        await ctx.defer(ephemeral=True)
        
        if not hasattr(self.bot, 'reliability_system'):
            await ctx.followup.send("❌ Reliability system not available", ephemeral=True)
            return
        
        try:
            status = self.bot.reliability_system.get_system_status()
            
            embed = discord.Embed(
                title="🛡️ System Reliability Status",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            circuit_breakers = status['circuit_breakers']
            cb_status = []
            for service, cb_info in circuit_breakers.items():
                state_emoji = {"CLOSED": "🟢", "HALF_OPEN": "🟡", "OPEN": "🔴"}.get(cb_info['state'], "⚪")
                cb_status.append(f"{state_emoji} {service}: {cb_info['state']}")
            
            embed.add_field(
                name="🔌 Circuit Breakers",
                value="\n".join(cb_status) if cb_status else "No circuit breakers",
                inline=True
            )
            
            degraded_services = status['degraded_services']
            embed.add_field(
                name="⚠️ Degraded Services",
                value="\n".join(degraded_services) if degraded_services else "✅ All services operational",
                inline=True
            )
            
            failure_counts = status['failure_counts']
            if failure_counts:
                failures = [f"{service}: {count}" for service, count in failure_counts.items() if count > 0]
                embed.add_field(
                    name="📊 Recent Failures",
                    value="\n".join(failures[:5]) if failures else "✅ No recent failures",
                    inline=True
                )
            
            embed.add_field(
                name="💾 Backups",
                value=f"{status['backup_count']} available",
                inline=True
            )
            
            await ctx.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logging.error(f"[ReliabilityMonitor] Error in reliability status: {e}")
            await ctx.followup.send(f"❌ Error retrieving reliability status: {e}", ephemeral=True)
    
    @discord.slash_command(name="backup", description="Manage data backups")
    @commands.has_permissions(administrator=True)
    async def backup_management(self, ctx: discord.ApplicationContext,
                               action: str = discord.Option(
                                   description="Backup action",
                                   choices=["create", "list", "restore"],
                                   default="list"
                               ),
                               backup_file: str = discord.Option(
                                   description="Backup filename (for restore)",
                                   default=None
                               )):
        """Manage guild data backups."""
        await ctx.defer(ephemeral=True)
        
        if not hasattr(self.bot, 'reliability_system'):
            await ctx.followup.send("❌ Reliability system not available", ephemeral=True)
            return
        
        backup_manager = self.bot.reliability_system.backup_manager
        guild_id = ctx.guild.id if ctx.guild else None
        
        try:
            if action == "create":
                if not guild_id:
                    await ctx.followup.send("❌ This command requires a guild context", ephemeral=True)
                    return
                
                backup_file = await backup_manager.backup_guild_data(self.bot, guild_id)
                await ctx.followup.send(f"✅ Guild backup created: `{backup_file}`", ephemeral=True)
            
            elif action == "list":
                backups = backup_manager.list_backups(guild_id)
                
                if not backups:
                    await ctx.followup.send("📁 No backups found", ephemeral=True)
                    return
                
                embed = discord.Embed(
                    title="📁 Available Backups",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                
                recent_backups = backups[:10]
                backup_list = []
                for backup in recent_backups:
                    size_mb = backup['size'] / (1024 * 1024)
                    backup_list.append(
                        f"🗃️ `{backup['filename']}`\n"
                        f"   📅 {backup['created'].strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"   📏 {size_mb:.1f} MB"
                    )
                
                embed.description = "\n\n".join(backup_list)
                if len(backups) > 10:
                    embed.set_footer(text=f"Showing 10 of {len(backups)} backups")
                
                await ctx.followup.send(embed=embed, ephemeral=True)
            
            elif action == "restore":
                if not guild_id or not backup_file:
                    await ctx.followup.send("❌ Guild context and backup filename required for restore", ephemeral=True)
                    return
                
                full_backup_path = backup_manager.backup_dir + "/" + backup_file
                success = await backup_manager.restore_guild_data(self.bot, guild_id, full_backup_path)
                
                if success:
                    await ctx.followup.send(f"✅ Guild data restored from `{backup_file}`", ephemeral=True)
                else:
                    await ctx.followup.send(f"❌ Failed to restore from `{backup_file}`", ephemeral=True)
        
        except Exception as e:
            logging.error(f"[ReliabilityMonitor] Error in backup management: {e}")
            await ctx.followup.send(f"❌ Error during backup operation: {e}", ephemeral=True)
    
    @discord.slash_command(name="circuit-breaker", description="Manage circuit breakers")
    @commands.has_permissions(administrator=True)
    async def circuit_breaker_management(self, ctx: discord.ApplicationContext,
                                        action: str = discord.Option(
                                            description="Circuit breaker action",
                                            choices=["status", "reset", "open", "close"],
                                            default="status"
                                        ),
                                        service: str = discord.Option(
                                            description="Service name",
                                            choices=["discord_api", "database", "scheduler", "cache"],
                                            default="discord_api"
                                        )):
        """Manage circuit breakers for various services."""
        await ctx.defer(ephemeral=True)
        
        if not hasattr(self.bot, 'reliability_system'):
            await ctx.followup.send("❌ Reliability system not available", ephemeral=True)
            return
        
        try:
            circuit_breaker = self.bot.reliability_system.get_circuit_breaker(service)
            if not circuit_breaker:
                await ctx.followup.send(f"❌ Circuit breaker not found for service: {service}", ephemeral=True)
                return
            
            if action == "status":
                status = circuit_breaker.get_status()
                state_emoji = {"CLOSED": "🟢", "HALF_OPEN": "🟡", "OPEN": "🔴"}.get(status['state'], "⚪")
                
                embed = discord.Embed(
                    title=f"🔌 Circuit Breaker: {service}",
                    color=discord.Color.green() if status['state'] == "CLOSED" else discord.Color.orange(),
                    timestamp=datetime.now()
                )
                
                embed.add_field(name="State", value=f"{state_emoji} {status['state']}", inline=True)
                embed.add_field(name="Failures", value=status['failure_count'], inline=True)
                
                if status['last_failure']:
                    embed.add_field(name="Last Failure", value=status['last_failure'].strftime('%H:%M:%S'), inline=True)
                
                if status['next_retry']:
                    embed.add_field(name="Next Retry", value=status['next_retry'].strftime('%H:%M:%S'), inline=True)
                
                await ctx.followup.send(embed=embed, ephemeral=True)
            
            elif action == "reset":
                circuit_breaker.failure_count = 0
                circuit_breaker.state = "CLOSED"
                await ctx.followup.send(f"✅ Circuit breaker for {service} has been reset", ephemeral=True)
            
            elif action == "open":
                circuit_breaker.state = "OPEN"
                circuit_breaker.last_failure_time = datetime.now().timestamp()
                await ctx.followup.send(f"🔴 Circuit breaker for {service} has been opened", ephemeral=True)
            
            elif action == "close":
                circuit_breaker.state = "CLOSED"
                circuit_breaker.failure_count = 0
                await ctx.followup.send(f"🟢 Circuit breaker for {service} has been closed", ephemeral=True)
                
        except Exception as e:
            logging.error(f"[ReliabilityMonitor] Error in circuit breaker management: {e}")
            await ctx.followup.send(f"❌ Error managing circuit breaker: {e}", ephemeral=True)
    
    @discord.slash_command(name="recovery", description="Emergency recovery operations")
    @commands.has_permissions(administrator=True)
    async def emergency_recovery(self, ctx: discord.ApplicationContext,
                                operation: str = discord.Option(
                                    description="Recovery operation",
                                    choices=["clear-cache", "reset-circuit-breakers", "restart-degraded-services"],
                                    default="clear-cache"
                                )):
        """Perform emergency recovery operations."""
        await ctx.defer(ephemeral=True)
        
        if not hasattr(self.bot, 'reliability_system'):
            await ctx.followup.send("❌ Reliability system not available", ephemeral=True)
            return
        
        try:
            if operation == "clear-cache":
                if hasattr(self.bot, 'cache'):
                    cleared_count = len(self.bot.cache._cache)
                    self.bot.cache._cache.clear()
                    self.bot.cache._hot_keys.clear()
                    await ctx.followup.send(f"✅ Cache cleared ({cleared_count} entries)", ephemeral=True)
                else:
                    await ctx.followup.send("❌ Cache system not available", ephemeral=True)
            
            elif operation == "reset-circuit-breakers":
                reset_count = 0
                for cb in self.bot.reliability_system.circuit_breakers.values():
                    cb.failure_count = 0
                    cb.state = "CLOSED"
                    reset_count += 1
                
                await ctx.followup.send(f"✅ Reset {reset_count} circuit breakers", ephemeral=True)
            
            elif operation == "restart-degraded-services":
                degraded_services = list(self.bot.reliability_system.graceful_degradation.degraded_services.keys())
                
                for service in degraded_services:
                    self.bot.reliability_system.graceful_degradation.restore_service(service)
                
                if degraded_services:
                    await ctx.followup.send(f"✅ Restored {len(degraded_services)} degraded services", ephemeral=True)
                else:
                    await ctx.followup.send("ℹ️ No degraded services found", ephemeral=True)
        
        except Exception as e:
            logging.error(f"[ReliabilityMonitor] Error in emergency recovery: {e}")
            await ctx.followup.send(f"❌ Error during recovery operation: {e}", ephemeral=True)

def setup(bot):
    """Setup function to add the ReliabilityMonitor cog to the bot."""
    bot.add_cog(ReliabilityMonitor(bot))