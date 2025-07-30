"""
Performance Profiler - Profile les fonctions les plus lentes du bot Discord.
"""

import asyncio
import logging
import time
import functools
from typing import Dict, List, Callable, Any, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta
import inspect

class PerformanceProfiler:
    """Profiler de performances pour fonctions async et sync."""
    
    def __init__(self, max_entries: int = 1000):
        self.max_entries = max_entries
        self._function_stats = defaultdict(lambda: {
            'calls': 0,
            'total_time': 0.0,
            'min_time': float('inf'),
            'max_time': 0.0,
            'recent_times': deque(maxlen=50),
            'errors': 0,
            'last_called': None
        })
        self._slow_calls = deque(maxlen=100)  # Garde les 100 appels les plus lents
        self._active_calls = {}  # call_id -> (function_name, start_time)
        self._call_counter = 0
        
    def profile_function(self, threshold_ms: float = 10.0):
        """Décorateur pour profiler une fonction."""
        def decorator(func: Callable) -> Callable:
            func_name = f"{func.__module__}.{func.__name__}" if hasattr(func, '__module__') else func.__name__
            
            if asyncio.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    return await self._profile_async_call(func, func_name, threshold_ms, *args, **kwargs)
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    return self._profile_sync_call(func, func_name, threshold_ms, *args, **kwargs)
                return sync_wrapper
        
        return decorator
    
    async def _profile_async_call(self, func: Callable, func_name: str, threshold_ms: float, *args, **kwargs):
        """Profile un appel de fonction asynchrone."""
        call_id = self._call_counter
        self._call_counter += 1
        
        start_time = time.time()
        self._active_calls[call_id] = (func_name, start_time)
        
        try:
            # Exécute la fonction
            result = await func(*args, **kwargs)
            
            # Calcule le temps d'exécution
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000  # en ms
            
            # Enregistre les statistiques
            self._record_call(func_name, execution_time, threshold_ms, success=True)
            
            return result
            
        except Exception as e:
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000
            
            self._record_call(func_name, execution_time, threshold_ms, success=False, error=str(e))
            raise
            
        finally:
            if call_id in self._active_calls:
                del self._active_calls[call_id]
    
    def _profile_sync_call(self, func: Callable, func_name: str, threshold_ms: float, *args, **kwargs):
        """Profile un appel de fonction synchrone."""
        call_id = self._call_counter
        self._call_counter += 1
        
        start_time = time.time()
        self._active_calls[call_id] = (func_name, start_time)
        
        try:
            # Exécute la fonction
            result = func(*args, **kwargs)
            
            # Calcule le temps d'exécution
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000  # en ms
            
            # Enregistre les statistiques
            self._record_call(func_name, execution_time, threshold_ms, success=True)
            
            return result
            
        except Exception as e:
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000
            
            self._record_call(func_name, execution_time, threshold_ms, success=False, error=str(e))
            raise
            
        finally:
            if call_id in self._active_calls:
                del self._active_calls[call_id]
    
    def _record_call(self, func_name: str, execution_time: float, threshold_ms: float, success: bool = True, error: str = None):
        """Enregistre les statistiques d'un appel de fonction."""
        stats = self._function_stats[func_name]
        stats['calls'] += 1
        stats['total_time'] += execution_time
        stats['min_time'] = min(stats['min_time'], execution_time)
        stats['max_time'] = max(stats['max_time'], execution_time)
        stats['recent_times'].append(execution_time)
        stats['last_called'] = datetime.now()
        
        if not success:
            stats['errors'] += 1
        
        # Enregistre les appels lents
        if execution_time > threshold_ms:
            slow_call = {
                'function': func_name,
                'duration_ms': execution_time,
                'timestamp': datetime.now(),
                'success': success,
                'error': error
            }
            self._slow_calls.append(slow_call)
            
            # Log si très lent
            if execution_time > 1000:  # > 1 seconde
                logging.warning(f"[PerformanceProfiler] Very slow call: {func_name} took {execution_time:.1f}ms")
    
    def get_function_stats(self, top_n: int = 20) -> List[Dict[str, Any]]:
        """Retourne les statistiques des fonctions les plus lentes."""
        stats_list = []
        
        for func_name, stats in self._function_stats.items():
            if stats['calls'] == 0:
                continue
                
            avg_time = stats['total_time'] / stats['calls']
            recent_avg = sum(stats['recent_times']) / len(stats['recent_times']) if stats['recent_times'] else 0
            
            stats_list.append({
                'function': func_name,
                'calls': stats['calls'],
                'total_time_ms': stats['total_time'],
                'avg_time_ms': avg_time,
                'min_time_ms': stats['min_time'] if stats['min_time'] != float('inf') else 0,
                'max_time_ms': stats['max_time'],
                'recent_avg_ms': recent_avg,
                'errors': stats['errors'],
                'error_rate': (stats['errors'] / stats['calls'] * 100) if stats['calls'] > 0 else 0,
                'last_called': stats['last_called']
            })
        
        # Trie par temps total décroissant
        stats_list.sort(key=lambda x: x['total_time_ms'], reverse=True)
        return stats_list[:top_n]
    
    def get_slow_calls(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retourne les appels les plus lents récents."""
        return list(self._slow_calls)[-limit:]
    
    def get_active_calls(self) -> List[Dict[str, Any]]:
        """Retourne les appels actuellement en cours."""
        current_time = time.time()
        active = []
        
        for call_id, (func_name, start_time) in self._active_calls.items():
            duration_ms = (current_time - start_time) * 1000
            active.append({
                'call_id': call_id,
                'function': func_name,
                'duration_ms': duration_ms,
                'started_at': datetime.fromtimestamp(start_time)
            })
        
        active.sort(key=lambda x: x['duration_ms'], reverse=True)
        return active
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """Retourne un résumé des statistiques de performance."""
        total_calls = sum(stats['calls'] for stats in self._function_stats.values())
        total_time = sum(stats['total_time'] for stats in self._function_stats.values())
        total_errors = sum(stats['errors'] for stats in self._function_stats.values())
        
        functions_with_errors = sum(1 for stats in self._function_stats.values() if stats['errors'] > 0)
        
        slow_calls_count = len(self._slow_calls)
        very_slow_calls = sum(1 for call in self._slow_calls if call['duration_ms'] > 1000)
        
        return {
            'total_functions_profiled': len(self._function_stats),
            'total_calls': total_calls,
            'total_time_ms': total_time,
            'avg_call_time_ms': total_time / total_calls if total_calls > 0 else 0,
            'total_errors': total_errors,
            'error_rate': (total_errors / total_calls * 100) if total_calls > 0 else 0,
            'functions_with_errors': functions_with_errors,
            'slow_calls_count': slow_calls_count,
            'very_slow_calls_count': very_slow_calls,
            'active_calls_count': len(self._active_calls)
        }
    
    def reset_stats(self):
        """Remet à zéro toutes les statistiques."""
        self._function_stats.clear()
        self._slow_calls.clear()
        self._active_calls.clear()
        self._call_counter = 0
        logging.info("[PerformanceProfiler] Statistics reset")
    
    def get_recommendations(self) -> List[str]:
        """Génère des recommandations d'optimisation."""
        recommendations = []
        stats_list = self.get_function_stats(10)
        
        for stat in stats_list:
            func_name = stat['function']
            avg_time = stat['avg_time_ms']
            calls = stat['calls']
            error_rate = stat['error_rate']
            
            # Recommandations basées sur les métriques
            if avg_time > 500:  # > 500ms en moyenne
                recommendations.append(f"🐌 {func_name}: Très lent ({avg_time:.1f}ms avg) - Considérer l'optimisation")
            
            elif avg_time > 100 and calls > 50:  # Appelé souvent et relativement lent
                recommendations.append(f"⚡ {func_name}: Optimisation recommandée ({calls} calls, {avg_time:.1f}ms avg)")
            
            if error_rate > 10:  # > 10% d'erreurs
                recommendations.append(f"❌ {func_name}: Taux d'erreur élevé ({error_rate:.1f}%) - Vérifier la logique")
            
            if stat['max_time_ms'] > stat['avg_time_ms'] * 5:  # Variance élevée
                recommendations.append(f"📊 {func_name}: Performance inconsistante - Analyser les cas extrêmes")
        
        # Recommandations générales
        summary = self.get_summary_stats()
        if summary['error_rate'] > 5:
            recommendations.append(f"🔧 Taux d'erreur global élevé ({summary['error_rate']:.1f}%) - Améliorer la gestion d'erreurs")
        
        if summary['very_slow_calls_count'] > 10:
            recommendations.append(f"🚨 {summary['very_slow_calls_count']} appels très lents détectés - Investigation requise")
        
        return recommendations[:10]  # Limite à 10 recommandations

# Instance globale du profiler
global_profiler = PerformanceProfiler()

def profile_performance(threshold_ms: float = 10.0):
    """Décorateur simple pour profiler une fonction."""
    return global_profiler.profile_function(threshold_ms)

def get_profiler() -> PerformanceProfiler:
    """Retourne l'instance globale du profiler."""
    return global_profiler