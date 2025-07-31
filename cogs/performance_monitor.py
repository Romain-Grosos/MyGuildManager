"""
Performance Monitor Cog - Commands to monitor performance.
"""

import discord
from discord.ext import commands
import logging
from datetime import datetime

class PerformanceMonitor(commands.Cog):
    """Cog to monitor and analyze bot performance."""
    
    def __init__(self, bot):
        self.bot = bot
    
    @discord.slash_command(name="profile", description="Show performance profiling stats")
    @commands.has_permissions(administrator=True)
    async def profile_stats(self, ctx: discord.ApplicationContext, 
                           detail: str = discord.Option(
                               description="Detail level: summary, functions, slow, active",
                               choices=["summary", "functions", "slow", "active", "recommendations"],
                               default="summary"
                           )):
        """Displays performance profiling statistics."""
        await ctx.defer(ephemeral=True)
        
        if not hasattr(self.bot, 'profiler'):
            await ctx.followup.send("❌ Performance profiler not available", ephemeral=True)
            return
        
        profiler = self.bot.profiler
        
        try:
            if detail == "summary":
                embed = await self._create_summary_embed(profiler)
            elif detail == "functions":
                embed = await self._create_functions_embed(profiler)
            elif detail == "slow":
                embed = await self._create_slow_calls_embed(profiler)
            elif detail == "active":
                embed = await self._create_active_calls_embed(profiler)
            elif detail == "recommendations":
                embed = await self._create_recommendations_embed(profiler)
            else:
                embed = await self._create_summary_embed(profiler)
            
            await ctx.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logging.error(f"[PerformanceMonitor] Error in profile command: {e}", exc_info=True)
            await ctx.followup.send(f"❌ Error retrieving profile stats: {e}", ephemeral=True)
    
    async def _create_summary_embed(self, profiler) -> discord.Embed:
        """Creates the performance summary embed."""
        summary = profiler.get_summary_stats()
        
        embed = discord.Embed(
            title="📊 Performance Profile Summary",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="📈 Overview",
            value=f"Functions: {summary['total_functions_profiled']}\n"
                  f"Total Calls: {summary['total_calls']:,}\n"
                  f"Total Time: {summary['total_time_ms']:.1f}ms",
            inline=True
        )
        
        embed.add_field(
            name="⚡ Performance",
            value=f"Avg Call Time: {summary['avg_call_time_ms']:.2f}ms\n"
                  f"Slow Calls: {summary['slow_calls_count']}\n"
                  f"Very Slow: {summary['very_slow_calls_count']}",
            inline=True
        )
        
        embed.add_field(
            name="❌ Errors",
            value=f"Total Errors: {summary['total_errors']}\n"
                  f"Error Rate: {summary['error_rate']:.2f}%\n"
                  f"Functions w/ Errors: {summary['functions_with_errors']}",
            inline=True
        )
        
        embed.add_field(
            name="🔄 Active",
            value=f"Active Calls: {summary['active_calls_count']}",
            inline=True
        )
        
        return embed
    
    async def _create_functions_embed(self, profiler) -> discord.Embed:
        """Creates the function statistics embed."""
        stats = profiler.get_function_stats(10)
        
        embed = discord.Embed(
            title="🔍 Top 10 Functions by Total Time",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        
        if not stats:
            embed.description = "No function statistics available"
            return embed
        
        for i, stat in enumerate(stats[:10], 1):
            func_name = stat['function'].split('.')[-1]  # Nom court
            value = (f"Calls: {stat['calls']:,} | "
                    f"Avg: {stat['avg_time_ms']:.1f}ms | "
                    f"Max: {stat['max_time_ms']:.1f}ms\n"
                    f"Errors: {stat['errors']} ({stat['error_rate']:.1f}%)")
            
            embed.add_field(
                name=f"{i}. {func_name}",
                value=value,
                inline=False
            )
        
        return embed
    
    async def _create_slow_calls_embed(self, profiler) -> discord.Embed:
        """Creates the slow calls embed."""
        slow_calls = profiler.get_slow_calls(15)
        
        embed = discord.Embed(
            title="🐌 Recent Slow Calls",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        
        if not slow_calls:
            embed.description = "No slow calls detected recently"
            return embed
        
        description_parts = []
        for call in slow_calls[-15:]:  # 15 most recent
            func_name = call['function'].split('.')[-1]
            status = "✅" if call['success'] else "❌"
            time_str = call['timestamp'].strftime("%H:%M:%S")
            description_parts.append(
                f"`{time_str}` {status} **{func_name}** - {call['duration_ms']:.1f}ms"
            )
        
        embed.description = "\n".join(description_parts[-15:])  # Limite Discord
        return embed
    
    async def _create_active_calls_embed(self, profiler) -> discord.Embed:
        """Creates the active calls embed."""
        active_calls = profiler.get_active_calls()
        
        embed = discord.Embed(
            title="🔄 Active Function Calls",
            color=discord.Color.yellow(),
            timestamp=datetime.now()
        )
        
        if not active_calls:
            embed.description = "No active calls"
            return embed
        
        description_parts = []
        for call in active_calls[:15]:  # Limit to 15
            func_name = call['function'].split('.')[-1]
            started = call['started_at'].strftime("%H:%M:%S")
            description_parts.append(
                f"**{func_name}** - {call['duration_ms']:.1f}ms (started {started})"
            )
        
        embed.description = "\n".join(description_parts)
        return embed
    
    async def _create_recommendations_embed(self, profiler) -> discord.Embed:
        """Creates the optimization recommendations embed."""
        recommendations = profiler.get_recommendations()
        
        embed = discord.Embed(
            title="💡 Performance Recommendations",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        if not recommendations:
            embed.description = "✅ No performance issues detected!"
            return embed
        
        embed.description = "\n".join(recommendations)
        return embed
    
    @discord.slash_command(name="optimize", description="Run performance optimizations")
    @commands.has_permissions(administrator=True)
    async def optimize_performance(self, ctx: discord.ApplicationContext,
                                 action: str = discord.Option(
                                     description="Optimization action",
                                     choices=["cache-clear", "profile-reset", "preload-guild"],
                                     default="cache-clear"
                                 )):
        """Executes performance optimizations."""
        await ctx.defer(ephemeral=True)
        
        try:
            if action == "cache-clear":
                if hasattr(self.bot, 'cache'):
                    # Clear smart cache
                    cleared_count = len(self.bot.cache._cache)
                    self.bot.cache._cache.clear()
                    self.bot.cache._hot_keys.clear()
                    await ctx.followup.send(f"✅ Smart cache cleared ({cleared_count} entries)", ephemeral=True)
                else:
                    await ctx.followup.send("❌ Cache system not available", ephemeral=True)
            
            elif action == "profile-reset":
                if hasattr(self.bot, 'profiler'):
                    self.bot.profiler.reset_stats()
                    await ctx.followup.send("✅ Profiler statistics reset", ephemeral=True)
                else:
                    await ctx.followup.send("❌ Profiler not available", ephemeral=True)
            
            elif action == "preload-guild":
                if hasattr(self.bot, 'cache') and hasattr(self.bot.cache, '_preload_guild_data') and ctx.guild:
                    await self.bot.cache._preload_guild_data(ctx.guild.id)
                    await ctx.followup.send(f"✅ Preloaded data for guild {ctx.guild.name}", ephemeral=True)
                else:
                    await ctx.followup.send("❌ Smart cache not available or no guild context", ephemeral=True)
            
        except Exception as e:
            logging.error(f"[PerformanceMonitor] Error in optimize command: {e}", exc_info=True)
            await ctx.followup.send(f"❌ Error during optimization: {e}", ephemeral=True)

def setup(bot):
    """Setup function to add the PerformanceMonitor cog to the bot."""
    bot.add_cog(PerformanceMonitor(bot))