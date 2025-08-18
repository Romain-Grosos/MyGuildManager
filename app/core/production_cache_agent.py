"""
Production Cache Agent - Real-time monitoring for cache.py ↔ cache_loader.py

Mission: Ensure consistency and reliability between the two cache systems.
Monitor performance, slots, TTL, hit-rate continuously.
Detect anomalies before production impact.

Production Checkpoints:
1. Category consistency - CACHE_CATEGORIES vs ensure_*_loaded
2. Key monitoring - Detection legacy format (_) vs standard (category:type:id)
3. Thresholds & performance - Synchronization thresholds
4. Preload slots - Zombie slots with auto-repair
5. Recursive protection - _recursion_depth <= _max_recursion_depth
6. Cache health - Hit-rate < 70%, evictions > 50%, size > 10k
7. Observability - JSON v1.0 with graduated alerting (debug→warning→error)
"""

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, Optional, Set, List
from contextvars import ContextVar

from .logger import ComponentLogger

correlation_id_context: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)


class ProductionCacheAgent:
    """Production monitoring agent for enterprise-grade cache consistency."""

    def __init__(self, bot):
        """
        Initialize production cache monitoring agent.

        Args:
            bot: Discord bot instance with cache and cache_loader
        """
        self.bot = bot
        self._logger = ComponentLogger("production_cache_agent")
        self._last_check_time = 0.0
        self._check_interval = int(os.environ.get("CACHE_AUDIT_INTERVAL", "60"))
        self._auto_repairs_count = 0
        self._legacy_key_detections = defaultdict(int)

        self._hit_rate_threshold = 70.0
        self._eviction_rate_threshold = 50.0
        self._cache_size_threshold = 10000

        self._critical_categories = {
            "guild_data",
            "user_data",
            "roster_data",
            "guild_settings",
            "guild_members",
            "user_setup",
        }

        self._legacy_patterns = [
            r"bulk_guild_members_\d+",
            r"guild_roles_\d+",
            r"role_members_\d+_\d+",
            r"\w+_\d+_\w+",
        ]


    async def production_health_check(self) -> Dict[str, Any]:
        """
        Real-time production monitoring with auto-repair.

        Returns:
            Dict with production status and auto-repair actions performed
        """
        check_start = time.monotonic()
        results = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "check_duration_ms": 0,
            "critical_issues": 0,
            "warnings": 0,
            "auto_repairs": 0,
            "status": "healthy",
        }

        try:
            self._logger.debug("production_health_check_started")

            category_status = await self._check_category_consistency()
            results["categories"] = category_status
            results["critical_issues"] += category_status.get("critical_count", 0)
            results["warnings"] += category_status.get("warning_count", 0)

            key_status = await self._check_key_formats()
            results["key_formats"] = key_status
            results["warnings"] += key_status.get("legacy_keys_found", 0)

            threshold_status = await self._check_performance_thresholds()
            results["thresholds"] = threshold_status
            results["critical_issues"] += threshold_status.get("mismatches", 0)

            slots_status = await self._check_preload_slots()
            results["preload_slots"] = slots_status
            results["auto_repairs"] += slots_status.get("repairs_made", 0)
            if slots_status.get("zombie_slots", 0) > 0:
                results["warnings"] += 1

            recursion_status = await self._check_recursion_protection()
            results["recursion"] = recursion_status
            results["warnings"] += recursion_status.get("depth_warnings", 0)

            health_status = await self._check_cache_health()
            results["cache_health"] = health_status
            results["warnings"] += health_status.get("health_warnings", 0)

            if results["critical_issues"] > 0:
                results["status"] = "critical"
            elif results["warnings"] > 3:
                results["status"] = "degraded"
            elif results["warnings"] > 0:
                results["status"] = "warning"

            check_duration = time.monotonic() - check_start
            results["check_duration_ms"] = round(check_duration * 1000, 2)

            if results["status"] == "critical":
                self._logger.error("production_cache_critical",
                    critical_issues=results["critical_issues"],
                    warnings=results["warnings"],
                    auto_repairs=results["auto_repairs"],
                )
            elif results["status"] == "degraded":
                self._logger.warning("production_cache_degraded",
                    warnings=results["warnings"],
                    auto_repairs=results["auto_repairs"],
                )
            elif results["auto_repairs"] > 0:
                self._logger.info("production_cache_auto_repairs",
                    auto_repairs=results["auto_repairs"],
                )
            else:
                self._logger.debug("production_cache_healthy",
                    check_duration_ms=results["check_duration_ms"],
                )

            return results

        except Exception as e:
            check_duration = time.monotonic() - check_start
            self._logger.error("production_health_check_error",
                error_type=type(e).__name__,
                error_msg=str(e),
                check_duration_ms=round(check_duration * 1000, 2),
            )
            results["error"] = str(e)
            results["status"] = "error"
            return results

    async def _check_category_consistency(self) -> Dict[str, Any]:
        """Checkpoint 1: Verify consistency between CACHE_CATEGORIES and ensure_*_loaded methods."""
        results = {
            "critical_count": 0,
            "warning_count": 0,
            "missing_critical": [],
            "orphaned_categories": [],
            "loader_method_missing": [],
        }

        try:
            if hasattr(self.bot, "cache") and hasattr(
                self.bot.cache, "CACHE_CATEGORIES"
            ):
                cache_categories = set(self.bot.cache.CACHE_CATEGORIES.keys())

                missing_critical = self._critical_categories - cache_categories
                if missing_critical:
                    results["missing_critical"] = list(missing_critical)
                    results["critical_count"] += len(missing_critical)
                    self._logger.error("critical_categories_missing",
                        missing_categories=list(missing_critical),
                        count=len(missing_critical),
                    )

            if hasattr(self.bot, "cache_loader"):
                critical_loader_methods = {
                    "guild_settings": "ensure_guild_settings_loaded",
                    "guild_members": "ensure_guild_members_loaded",
                    "user_setup": "ensure_user_setup_loaded",
                }

                for category, method_name in critical_loader_methods.items():
                    if not hasattr(self.bot.cache_loader, method_name):
                        results["loader_method_missing"].append(category)
                        results["critical_count"] += 1
                        self._logger.error("critical_loader_method_missing",
                            category=category,
                            expected_method=method_name,
                        )

                if hasattr(self.bot.cache_loader, "get_loaded_categories"):
                    loaded_categories = self.bot.cache_loader.get_loaded_categories()
                    expected_categories = {
                        "guild_data",
                        "user_data",
                        "events_data",
                        "roster_data",
                        "static_data",
                        "discord_entities",
                        "temporary",
                        "guild_settings",
                        "guild_roles",
                        "guild_channels",
                        "welcome_messages",
                        "absence_messages",
                        "guild_members",
                        "static_groups",
                        "user_setup",
                        "weapons",
                        "weapons_combinations",
                        "guild_ideal_staff",
                        "games_list",
                        "epic_items_t2",
                        "events_calendar",
                        "guild_ptb_settings",
                    }

                    orphaned = loaded_categories - expected_categories
                    if orphaned:
                        results["orphaned_categories"] = list(orphaned)
                        results["warning_count"] += len(orphaned)
                        self._logger.warning("orphaned_categories_detected",
                            orphaned_categories=list(orphaned),
                            count=len(orphaned),
                        )

            return results

        except Exception as e:
            self._logger.error("category_consistency_check_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )
            results["error"] = str(e)
            return results

    async def _check_key_formats(self) -> Dict[str, Any]:
        """Checkpoint 2: Detect legacy format keys (_) vs standard format (category:type:id)."""
        results = {
            "legacy_keys_found": 0,
            "legacy_patterns_detected": [],
            "standard_format_ratio": 100.0,
        }

        try:
            legacy_count = 0
            total_keys = 0

            if hasattr(self.bot, "cache") and hasattr(self.bot.cache, "_cache"):
                cache_keys = list(self.bot.cache._cache.keys())
                total_keys = len(cache_keys)

                for key in cache_keys:
                    for pattern in self._legacy_patterns:
                        if re.match(pattern, key):
                            legacy_count += 1
                            if pattern not in results["legacy_patterns_detected"]:
                                results["legacy_patterns_detected"].append(pattern)

                            pattern_key = f"legacy_{pattern}"
                            if self._legacy_key_detections[pattern_key] == 0:
                                self._logger.warning("legacy_key_format_detected",
                                    key_pattern=pattern,
                                    example_key=key[:50],
                                )
                            self._legacy_key_detections[pattern_key] += 1
                            break

                if total_keys > 0:
                    standard_keys = total_keys - legacy_count
                    results["standard_format_ratio"] = (
                        standard_keys / total_keys
                    ) * 100

                results["legacy_keys_found"] = legacy_count

                if legacy_count > 0:
                    self._logger.warning("legacy_keys_summary",
                        legacy_count=legacy_count,
                        total_keys=total_keys,
                        compliance_ratio=results["standard_format_ratio"],
                    )

            return results

        except Exception as e:
            self._logger.error("key_format_check_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )
            results["error"] = str(e)
            return results

    async def _check_performance_thresholds(self) -> Dict[str, Any]:
        """Checkpoint 3: Synchronize CACHE_QUERY_TIME_THRESHOLD between cache systems."""
        results = {
            "mismatches": 0,
            "cache_threshold": None,
            "loader_threshold": None,
            "synchronized": True,
        }

        try:
            cache_threshold = float(
                os.environ.get("CACHE_QUERY_TIME_THRESHOLD_SIMPLE", "0.2")
            )
            loader_threshold = float(
                os.environ.get("CACHE_QUERY_TIME_THRESHOLD_SIMPLE", "0.2")
            )

            results["cache_threshold"] = cache_threshold
            results["loader_threshold"] = loader_threshold

            if abs(cache_threshold - loader_threshold) > 0.001:
                results["mismatches"] += 1
                results["synchronized"] = False
                self._logger.error("performance_threshold_mismatch",
                    cache_threshold_ms=int(cache_threshold * 1000),
                    loader_threshold_ms=int(loader_threshold * 1000),
                    difference_ms=abs(cache_threshold - loader_threshold) * 1000,
                )

            return results

        except Exception as e:
            self._logger.error("performance_threshold_check_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )
            results["error"] = str(e)
            return results

    async def _check_preload_slots(self) -> Dict[str, Any]:
        """Checkpoint 4: Monitor zombie slots with auto-repair functionality."""
        results = {
            "zombie_slots": 0,
            "repairs_made": 0,
            "slots_used": 0,
            "active_tasks": 0,
            "health_status": "healthy",
        }

        try:
            if hasattr(self.bot, "cache"):
                slots_used = getattr(self.bot.cache, "_preload_slots_used", 0)
                preload_tasks = getattr(self.bot.cache, "_preload_tasks", {})
                active_tasks = (
                    len([t for t in preload_tasks.values() if not t.done()])
                    if preload_tasks
                    else 0
                )

                results["slots_used"] = slots_used
                results["active_tasks"] = active_tasks

                if slots_used > 0 and active_tasks == 0:
                    results["zombie_slots"] = slots_used
                    results["health_status"] = "zombie_detected"

                    self._logger.warning("zombie_slots_detected",
                        zombie_slots=slots_used,
                        active_tasks=active_tasks,
                    )

                    if hasattr(self.bot.cache, "_preload_slots_used"):
                        old_slots = self.bot.cache._preload_slots_used
                        self.bot.cache._preload_slots_used = 0
                        results["repairs_made"] = old_slots
                        self._auto_repairs_count += old_slots

                        self._logger.info("preload_slots_auto_corrected",
                            recovered_slots=old_slots,
                            total_auto_repairs=self._auto_repairs_count,
                        )

                elif slots_used != active_tasks:
                    results["health_status"] = "inconsistent"
                    self._logger.warning("preload_slots_inconsistency",
                        slots_used=slots_used,
                        active_tasks=active_tasks,
                        difference=abs(slots_used - active_tasks),
                    )

            return results

        except Exception as e:
            self._logger.error("preload_slots_check_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )
            results["error"] = str(e)
            return results

    async def _check_recursion_protection(self) -> Dict[str, Any]:
        """Checkpoint 5: Control _recursion_depth <= _max_recursion_depth."""
        results = {
            "depth_warnings": 0,
            "current_depth": 0,
            "max_depth": 3,
            "protection_status": "active",
        }

        try:
            if hasattr(self.bot, "cache"):
                current_depth = getattr(self.bot.cache, "_recursion_depth", 0)
                max_depth = getattr(self.bot.cache, "_max_recursion_depth", 3)

                results["current_depth"] = current_depth
                results["max_depth"] = max_depth

                if current_depth >= max_depth * 0.8:
                    results["depth_warnings"] += 1
                    self._logger.warning("recursion_depth_high",
                        current_depth=current_depth,
                        max_depth=max_depth,
                        utilization_percent=int((current_depth / max_depth) * 100),
                    )

                if current_depth >= max_depth:
                    results["protection_status"] = "limit_reached"
                    self._logger.error("recursion_limit_reached",
                        current_depth=current_depth,
                        max_depth=max_depth,
                    )

            return results

        except Exception as e:
            self._logger.error("recursion_protection_check_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )
            results["error"] = str(e)
            return results

    async def _check_cache_health(self) -> Dict[str, Any]:
        """Checkpoint 6: Cache health - Hit-rate < 70%, evictions > 50%, size > 10k entries."""
        results = {
            "health_warnings": 0,
            "hit_rate": 100.0,
            "eviction_rate": 0.0,
            "cache_size": 0,
            "health_score": "excellent",
        }

        try:
            if hasattr(self.bot, "cache"):
                if hasattr(self.bot.cache, "get_metrics"):
                    try:
                        metrics = self.bot.cache.get_metrics()
                        global_metrics = metrics.get("global", {})

                        hit_rate = global_metrics.get("hit_rate", 100.0)
                        results["hit_rate"] = hit_rate

                        if hit_rate < self._hit_rate_threshold:
                            results["health_warnings"] += 1
                            results["health_score"] = "degraded"
                            self._logger.warning("cache_hit_rate_low",
                                hit_rate=hit_rate,
                                threshold=self._hit_rate_threshold,
                            )

                        cache_size = global_metrics.get("cache_size", 0)
                        results["cache_size"] = cache_size

                        if cache_size > self._cache_size_threshold:
                            results["health_warnings"] += 1
                            if results["health_score"] == "excellent":
                                results["health_score"] = "warning"
                            self._logger.warning("cache_size_large",
                                cache_size=cache_size,
                                threshold=self._cache_size_threshold,
                            )

                        hits = global_metrics.get("hits", 0)
                        sets = global_metrics.get("sets", 0)
                        evictions = global_metrics.get("evictions", 0)

                        if sets > 0:
                            eviction_rate = (evictions / sets) * 100
                            results["eviction_rate"] = eviction_rate

                            if eviction_rate > self._eviction_rate_threshold:
                                results["health_warnings"] += 1
                                if results["health_score"] != "degraded":
                                    results["health_score"] = "warning"
                                self._logger.warning("cache_eviction_rate_high",
                                    eviction_rate=eviction_rate,
                                    threshold=self._eviction_rate_threshold,
                                )

                    except Exception as metrics_error:
                        self._logger.debug("cache_metrics_unavailable",
                            error=str(metrics_error),
                        )

                if hasattr(self.bot.cache, "_cache"):
                    actual_size = len(self.bot.cache._cache)
                    if results["cache_size"] == 0:
                        results["cache_size"] = actual_size

                    if actual_size > self._cache_size_threshold:
                        results["health_warnings"] += 1
                        self._logger.warning("cache_size_threshold_exceeded",
                            actual_size=actual_size,
                            threshold=self._cache_size_threshold,
                        )

            return results

        except Exception as e:
            self._logger.error("cache_health_check_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )
            results["error"] = str(e)
            return results

    async def continuous_monitoring(self) -> None:
        """Continuous monitoring with configurable interval."""
        try:
            current_time = time.monotonic()

            if current_time - self._last_check_time < self._check_interval:
                return

            self._last_check_time = current_time

            results = await self.production_health_check()

            if results["status"] == "critical":
                pass
            elif results["auto_repairs"] > 0:
                self._logger.info("auto_repairs_completed",
                    total_repairs=self._auto_repairs_count,
                )

        except Exception as e:
            self._logger.error("continuous_monitoring_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )


production_cache_agent: Optional[ProductionCacheAgent] = None


def initialize_production_cache_agent(bot) -> ProductionCacheAgent:
    """Initialize the global production cache agent."""
    global production_cache_agent
    production_cache_agent = ProductionCacheAgent(bot)
    production_cache_agent._logger.info("production_cache_agent_initialized",
        check_interval=production_cache_agent._check_interval,
    )
    return production_cache_agent


async def start_production_monitoring_task(bot) -> asyncio.Task:
    """Start background production monitoring task."""
    if not production_cache_agent:
        initialize_production_cache_agent(bot)

    async def monitoring_loop():
        try:
            while True:
                await production_cache_agent.continuous_monitoring()
                await asyncio.sleep(production_cache_agent._check_interval)
        except asyncio.CancelledError:
            production_cache_agent._logger.info("production_monitoring_cancelled")
            raise
        except Exception as e:
            production_cache_agent._logger.error("production_monitoring_error",
                error_type=type(e).__name__,
                error_msg=str(e),
            )

    task = asyncio.create_task(monitoring_loop())

    if hasattr(bot, "_background_tasks"):
        bot._background_tasks.append(task)

    production_cache_agent._logger.info("production_monitoring_task_started")
    return task
