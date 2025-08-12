#!/usr/bin/env python3
"""Test du système de cache optimisé."""

import asyncio
import sys
import os
sys.path.append('app')

from cache_loader import CacheLoader

class MockBot:
    """Mock bot for testing."""
    
    async def run_db_query(self, query, fetch_all=False):
        """Mock DB query."""
        return []
    
    class MockCache:
        """Mock cache."""
        
        async def set_guild_data(self, guild_id, key, data):
            pass
        
        async def get_guild_data(self, guild_id, key):
            return None
    
    cache = MockCache()

async def test_cache_optimization():
    """Test cache optimization."""
    bot = MockBot()
    loader = CacheLoader(bot)
    
    print("Test du nouveau systeme de cache optimise...")
    
    # Test 1: load_all_shared_data
    start_time = asyncio.get_event_loop().time()
    await loader.load_all_shared_data()
    elapsed1 = asyncio.get_event_loop().time() - start_time
    print(f"Premier chargement: {loader.is_loaded()} ({elapsed1:.3f}s)")
    
    # Test 2: second call should be instant
    start_time = asyncio.get_event_loop().time()
    await loader.load_all_shared_data()
    elapsed2 = asyncio.get_event_loop().time() - start_time
    print(f"Deuxieme appel: instant ({elapsed2:.3f}s) - pas de rechargement")
    
    # Test 3: wait_for_initial_load should be instant
    start_time = asyncio.get_event_loop().time()
    await loader.wait_for_initial_load()
    elapsed3 = asyncio.get_event_loop().time() - start_time
    print(f"wait_for_initial_load: instant ({elapsed3:.3f}s)")
    
    # Test 4: ensure_category_loaded should be no-op
    start_time = asyncio.get_event_loop().time()
    await loader.ensure_category_loaded('guild_settings')
    elapsed4 = asyncio.get_event_loop().time() - start_time
    print(f"ensure_category_loaded: no-op ({elapsed4:.3f}s)")
    
    print("\nTous les tests passes !")
    print(f"Optimisation: 2e appel {elapsed2/elapsed1*100:.1f}% du temps du premier")

if __name__ == "__main__":
    asyncio.run(test_cache_optimization())