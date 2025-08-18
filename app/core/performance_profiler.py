"""
Performance Profiler - Enterprise-grade function performance monitoring and analysis.

Provides comprehensive performance profiling for Discord bot functions with features including:
- Real-time performance tracking for async and sync functions
- Statistical analysis with min/max/average execution times
- Recent execution time history with configurable sample sizes
- Error rate monitoring and tracking
- Slow function detection and alerting
- Memory-efficient data structures with automatic cleanup
- Comprehensive performance reports and analytics
"""

import asyncio
import functools
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, List, Callable, Any, Optional, DefaultDict
from typing_extensions import TypedDict

from core.logger import ComponentLogger

_logger = ComponentLogger("performance_profiler")

class FunctionStats(TypedDict):
    """Type definition for function statistics."""
    calls: int
    total_time: float
    min_time: float
    max_time: float
    recent_times: "deque[float]"
    errors: int
    last_called: Optional[datetime]

class PerformanceProfiler:
    """Performance profiler for async and sync functions."""

    def __init__(self, max_entries: int = 1000):
        """
        Initialize performance profiler with tracking structures.

        Args:
            max_entries: Maximum number of entries to track
        """
        self.max_entries = max_entries
        self._function_stats: DefaultDict[str, FunctionStats] = defaultdict(
            lambda: {
                "calls": 0,
                "total_time": 0.0,
                "min_time": float("inf"),
                "max_time": 0.0,
                "recent_times": deque(maxlen=50),
                "errors": 0,
                "last_called": None,
            }
        )
        self._slow_calls = deque(maxlen=100)
        self._active_calls = {}
        self._call_counter = 0

    def profile_function(self, threshold_ms: float = 10.0):
        """
        Decorator to profile function execution time and statistics.

        Args:
            threshold_ms: Threshold in milliseconds to log slow calls

        Returns:
            Decorated function with profiling capabilities
        """

        def decorator(func: Callable) -> Callable:
            func_name = (
                f"{func.__module__}.{func.__name__}"
                if hasattr(func, "__module__")
                else func.__name__
            )

            if asyncio.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    return await self._profile_async_call(
                        func, func_name, threshold_ms, *args, **kwargs
                    )

                return async_wrapper
            else:

                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    return self._profile_sync_call(
                        func, func_name, threshold_ms, *args, **kwargs
                    )

                return sync_wrapper

        return decorator

    async def _profile_async_call(
        self, func: Callable, func_name: str, threshold_ms: float, *args, **kwargs
    ):
        """
        Profile an asynchronous function call with timing and error tracking.

        Args:
            func: Function to profile
            func_name: Name of the function for logging
            threshold_ms: Threshold for slow call detection
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Result of function execution
        """
        call_id = self._call_counter
        self._call_counter += 1

        start_time = time.time()
        self._active_calls[call_id] = (func_name, start_time)

        try:
            result = await func(*args, **kwargs)

            end_time = time.time()
            execution_time = (end_time - start_time) * 1000

            self._record_call(func_name, execution_time, threshold_ms, success=True)

            return result

        except Exception as e:
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000

            self._record_call(
                func_name, execution_time, threshold_ms, success=False, error=str(e)
            )
            raise

        finally:
            if call_id in self._active_calls:
                del self._active_calls[call_id]

    def _profile_sync_call(
        self, func: Callable, func_name: str, threshold_ms: float, *args, **kwargs
    ):
        """
        Profile a synchronous function call with timing and error tracking.

        Args:
            func: Function to profile
            func_name: Name of the function for logging
            threshold_ms: Threshold for slow call detection
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Result of function execution
        """
        call_id = self._call_counter
        self._call_counter += 1

        start_time = time.time()
        self._active_calls[call_id] = (func_name, start_time)

        try:
            result = func(*args, **kwargs)

            end_time = time.time()
            execution_time = (end_time - start_time) * 1000

            self._record_call(func_name, execution_time, threshold_ms, success=True)

            return result

        except Exception as e:
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000

            self._record_call(
                func_name, execution_time, threshold_ms, success=False, error=str(e)
            )
            raise

        finally:
            if call_id in self._active_calls:
                del self._active_calls[call_id]

    def _record_call(
        self,
        func_name: str,
        execution_time: float,
        threshold_ms: float,
        success: bool = True,
        error: Optional[str] = None,
    ):
        """
        Record statistics and metrics for a function call.

        Args:
            func_name: Name of the function
            execution_time: Execution time in milliseconds
            threshold_ms: Threshold for slow call detection
            success: Whether the call succeeded
            error: Error message if call failed
        """
        stats = self._function_stats[func_name]
        stats["calls"] += 1
        stats["total_time"] += execution_time
        stats["min_time"] = min(stats["min_time"], execution_time)
        stats["max_time"] = max(stats["max_time"], execution_time)
        stats["recent_times"].append(execution_time)
        stats["last_called"] = datetime.now()

        if not success:
            stats["errors"] += 1

        if execution_time > threshold_ms:
            slow_call = {
                "function": func_name,
                "duration_ms": execution_time,
                "timestamp": datetime.now(),
                "success": success,
                "error": error,
            }
            self._slow_calls.append(slow_call)

            if execution_time > 1000:
                _logger.warning("very_slow_call",
                    function=func_name,
                    duration_ms=round(execution_time, 1)
                )

    def get_function_stats(self, top_n: int = 20) -> List[Dict[str, Any]]:
        """
        Get statistics for the slowest functions sorted by total execution time.

        Args:
            top_n: Number of top functions to return

        Returns:
            List of function statistics dictionaries
        """
        stats_list = []

        for func_name, stats in self._function_stats.items():
            if stats["calls"] == 0:
                continue

            avg_time = stats["total_time"] / stats["calls"]
            recent_avg = (
                sum(stats["recent_times"]) / len(stats["recent_times"])
                if stats["recent_times"]
                else 0
            )

            stats_list.append(
                {
                    "function": func_name,
                    "calls": stats["calls"],
                    "total_time_ms": stats["total_time"],
                    "avg_time_ms": avg_time,
                    "min_time_ms": (
                        stats["min_time"] if stats["min_time"] != float("inf") else 0
                    ),
                    "max_time_ms": stats["max_time"],
                    "recent_avg_ms": recent_avg,
                    "errors": stats["errors"],
                    "error_rate": (
                        (stats["errors"] / stats["calls"] * 100)
                        if stats["calls"] > 0
                        else 0
                    ),
                    "last_called": stats["last_called"],
                }
            )

        stats_list.sort(key=lambda x: x["total_time_ms"], reverse=True)
        return stats_list[:top_n]

    def get_slow_calls(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent slowest calls above the threshold.

        Args:
            limit: Maximum number of slow calls to return

        Returns:
            List of slow call information dictionaries
        """
        return list(self._slow_calls)[-limit:]

    def get_active_calls(self) -> List[Dict[str, Any]]:
        """
        Get information about currently executing functions.

        Returns:
            List of active call information dictionaries
        """
        current_time = time.time()
        active = []

        for call_id, (func_name, start_time) in self._active_calls.items():
            duration_ms = (current_time - start_time) * 1000
            active.append(
                {
                    "call_id": call_id,
                    "function": func_name,
                    "duration_ms": duration_ms,
                    "started_at": datetime.fromtimestamp(start_time),
                }
            )

        active.sort(key=lambda x: x["duration_ms"], reverse=True)
        return active

    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive summary of all performance statistics.

        Returns:
            Dictionary containing aggregated performance metrics
        """
        total_calls = sum(stats["calls"] for stats in self._function_stats.values())
        total_time = sum(stats["total_time"] for stats in self._function_stats.values())
        total_errors = sum(stats["errors"] for stats in self._function_stats.values())

        functions_with_errors = sum(
            1 for stats in self._function_stats.values() if stats["errors"] > 0
        )

        slow_calls_count = len(self._slow_calls)
        very_slow_calls = sum(
            1 for call in self._slow_calls if call["duration_ms"] > 1000
        )

        return {
            "total_functions_profiled": len(self._function_stats),
            "total_calls": total_calls,
            "total_time_ms": total_time,
            "avg_call_time_ms": total_time / total_calls if total_calls > 0 else 0,
            "total_errors": total_errors,
            "error_rate": (total_errors / total_calls * 100) if total_calls > 0 else 0,
            "functions_with_errors": functions_with_errors,
            "slow_calls_count": slow_calls_count,
            "very_slow_calls_count": very_slow_calls,
            "active_calls_count": len(self._active_calls),
        }

    def reset_stats(self):
        """
        Reset all collected statistics and clear tracking data.
        """
        self._function_stats.clear()
        self._slow_calls.clear()
        self._active_calls.clear()
        self._call_counter = 0
        _logger.info("stats_reset")

    def get_recommendations(self) -> List[str]:
        """
        Generate optimization recommendations based on collected performance data.

        Returns:
            List of actionable optimization recommendations
        """
        recommendations = []
        stats_list = self.get_function_stats(10)

        for stat in stats_list:
            func_name = stat["function"]
            avg_time = stat["avg_time_ms"]
            calls = stat["calls"]
            error_rate = stat["error_rate"]

            if avg_time > 500:
                recommendations.append(
                    f"🐌 {func_name}: Very slow ({avg_time:.1f}ms avg) - Consider optimization"
                )

            elif avg_time > 100 and calls > 50:
                recommendations.append(
                    f"⚡ {func_name}: Optimization recommended ({calls} calls, {avg_time:.1f}ms avg)"
                )

            if error_rate > 10:
                recommendations.append(
                    f"❌ {func_name}: High error rate ({error_rate:.1f}%) - Check logic"
                )

            if stat["max_time_ms"] > stat["avg_time_ms"] * 5:
                recommendations.append(
                    f"📊 {func_name}: Inconsistent performance - Analyze edge cases"
                )

        summary = self.get_summary_stats()
        if summary["error_rate"] > 5:
            recommendations.append(
                f"🔧 High global error rate ({summary['error_rate']:.1f}%) - Improve error handling"
            )

        if summary["very_slow_calls_count"] > 10:
            recommendations.append(
                f"🚨 {summary['very_slow_calls_count']} very slow calls detected - Investigation required"
            )

        return recommendations[:10]

global_profiler = PerformanceProfiler()

def profile_performance(threshold_ms: float = 10.0):
    """
    Simple decorator to profile a function using the global profiler.

    Args:
        threshold_ms: Threshold in milliseconds for slow call detection

    Returns:
        Profiling decorator
    """
    return global_profiler.profile_function(threshold_ms)

def get_profiler() -> PerformanceProfiler:
    """
    Get the global profiler instance.

    Returns:
        Global PerformanceProfiler instance
    """
    return global_profiler
