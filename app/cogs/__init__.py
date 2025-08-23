"""
Cogs Package - Enterprise-grade Discord bot extensions for comprehensive guild management.

This package provides modular, enterprise-level cogs (extensions) that handle various
aspects of Discord guild management, from member profiles to event coordination.

Architecture:
    - All cogs follow enterprise patterns with defensive programming
    - Comprehensive error handling and structured logging throughout
    - Database operations use transaction patterns for data integrity
    - Real-time cache management with TTL and invalidation strategies
    - Multi-language support with fallback mechanisms

Performance:
    - Async/await patterns for non-blocking operations
    - Connection pooling and circuit breaker patterns
    - Batch processing for database operations
    - Memory-efficient caching with cleanup routines

Security:
    - Input validation and sanitization
    - Permission checks before sensitive operations
    - Rate limiting and abuse prevention
    - Secure handling of user data and credentials
"""

from typing import Dict, List, Optional, Tuple, Any
import logging

# Core cogs providing fundamental guild functionality
CORE_COGS = [
    "core",           # Guild initialization and settings management
    "guild_init",     # Server setup and configuration workflows
    "guild_members",  # Member profile and roster management
    "notification",   # Join/leave notifications and welcome messages
]

# Event and attendance management cogs
EVENT_COGS = [
    "guild_events",     # Event creation, scheduling, and registration
    "guild_attendance", # DKP tracking and attendance monitoring
    "absence",          # Absence management and role handling
    "guild_ptb",        # Public Test Branch server coordination
]

# Member experience and engagement cogs
MEMBER_COGS = [
    "autorole",       # Automatic role assignment on rule acceptance
    "profile_setup",  # Member onboarding and profile creation
    "contract",       # Guild contract selection and publishing
    "dynamic_voice",  # Temporary voice channel management
]

# Gaming and utility cogs
UTILITY_COGS = [
    "epic_items_scraper", # Throne & Liberty items scraping
    "loot_wishlist",      # Epic/Legendary items wishlist management
    "llm",               # AI-powered interactions and normalization
]

AVAILABLE_COGS = CORE_COGS + EVENT_COGS + MEMBER_COGS + UTILITY_COGS

COG_METADATA: Dict[str, Dict[str, Any]] = {
    "core": {
        "category": "Core",
        "description": "Guild initialization and settings management",
        "priority": "critical",
        "dependencies": [],
    },
    "guild_init": {
        "category": "Core", 
        "description": "Server setup and configuration workflows",
        "priority": "critical",
        "dependencies": ["core"],
    },
    "guild_members": {
        "category": "Core",
        "description": "Member profile and roster management", 
        "priority": "critical",
        "dependencies": ["core"],
    },
    "notification": {
        "category": "Core",
        "description": "Join/leave notifications and welcome messages",
        "priority": "high",
        "dependencies": ["core"],
    },
    "guild_events": {
        "category": "Events",
        "description": "Event creation, scheduling, and registration",
        "priority": "high", 
        "dependencies": ["core", "guild_members"],
    },
    "guild_attendance": {
        "category": "Events",
        "description": "DKP tracking and attendance monitoring",
        "priority": "high",
        "dependencies": ["core", "guild_members", "guild_events"],
    },
    "absence": {
        "category": "Events",
        "description": "Absence management and role handling",
        "priority": "medium",
        "dependencies": ["core", "guild_members"],
    },
    "guild_ptb": {
        "category": "Events", 
        "description": "Public Test Branch server coordination",
        "priority": "medium",
        "dependencies": ["core", "guild_members"],
    },
    "autorole": {
        "category": "Members",
        "description": "Automatic role assignment on rule acceptance",
        "priority": "high",
        "dependencies": ["core"],
    },
    "profile_setup": {
        "category": "Members",
        "description": "Member onboarding and profile creation", 
        "priority": "high",
        "dependencies": ["core", "guild_members"],
    },
    "contract": {
        "category": "Members",
        "description": "Guild contract selection and publishing",
        "priority": "medium",
        "dependencies": ["core"],
    },
    "dynamic_voice": {
        "category": "Members",
        "description": "Temporary voice channel management",
        "priority": "medium", 
        "dependencies": ["core"],
    },
    "epic_items_scraper": {
        "category": "Utility",
        "description": "Throne & Liberty items scraping and management",
        "priority": "medium",
        "dependencies": ["core"],
    },
    "loot_wishlist": {
        "category": "Utility", 
        "description": "Epic/Legendary items wishlist management",
        "priority": "medium",
        "dependencies": ["core", "guild_members", "epic_items_scraper"],
    },
    "llm": {
        "category": "Utility",
        "description": "AI-powered interactions and weapon normalization",
        "priority": "low",
        "dependencies": ["core"],
    },
}

def get_cog_path(cog_name: str) -> str:
    """
    Get the full import path for a specified cog.
    
    Args:
        cog_name: Name of the cog to get path for
        
    Returns:
        Full import path for the cog module
        
    Raises:
        ValueError: If cog_name is not in AVAILABLE_COGS
    """
    if cog_name not in AVAILABLE_COGS:
        raise ValueError(f"Unknown cog '{cog_name}'. Available: {AVAILABLE_COGS}")
    return f"app.cogs.{cog_name}"

def get_cogs_by_category(category: str) -> List[str]:
    """
    Get all cogs belonging to a specific category.
    
    Args:
        category: Category name ("Core", "Events", "Members", "Utility")
        
    Returns:
        List of cog names in the specified category
    """
    return [
        cog_name for cog_name, metadata in COG_METADATA.items()
        if metadata["category"] == category
    ]

def get_cogs_by_priority(priority: str) -> List[str]:
    """
    Get all cogs with a specific priority level.
    
    Args:
        priority: Priority level ("critical", "high", "medium", "low")
        
    Returns:
        List of cog names with the specified priority
    """
    return [
        cog_name for cog_name, metadata in COG_METADATA.items()
        if metadata["priority"] == priority
    ]

def get_cog_dependencies(cog_name: str) -> List[str]:
    """
    Get the dependency list for a specific cog.
    
    Args:
        cog_name: Name of the cog to check dependencies for
        
    Returns:
        List of cog names that this cog depends on
        
    Raises:
        KeyError: If cog_name is not found in metadata
    """
    return COG_METADATA[cog_name]["dependencies"]

def validate_cog_loading_order(cogs_to_load: List[str]) -> Tuple[List[str], List[str]]:
    """
    Validate and sort cogs for loading based on their dependencies.
    
    Args:
        cogs_to_load: List of cog names to load
        
    Returns:
        Tuple of (sorted_cogs, missing_dependencies)
        - sorted_cogs: Cogs sorted in dependency-safe loading order
        - missing_dependencies: List of missing dependencies that need to be loaded
    """
    sorted_cogs = []
    remaining_cogs = cogs_to_load.copy()
    missing_dependencies = []
    
    while remaining_cogs:
        progress_made = False
        
        for cog_name in remaining_cogs.copy():
            if cog_name not in COG_METADATA:
                logging.warning(f"Unknown cog '{cog_name}' - skipping")
                remaining_cogs.remove(cog_name)
                continue
                
            dependencies = COG_METADATA[cog_name]["dependencies"]

            deps_satisfied = all(
                dep in sorted_cogs or dep not in cogs_to_load 
                for dep in dependencies
            )
            
            if deps_satisfied:
                for dep in dependencies:
                    if dep not in cogs_to_load and dep not in missing_dependencies:
                        missing_dependencies.append(dep)
                
                sorted_cogs.append(cog_name)
                remaining_cogs.remove(cog_name)
                progress_made = True

        if not progress_made and remaining_cogs:
            logging.error(f"Circular dependency detected in cogs: {remaining_cogs}")
            sorted_cogs.extend(remaining_cogs)
            break
    
    return sorted_cogs, missing_dependencies

def get_migration_status() -> Dict[str, str]:
    """
    Get the enterprise migration status for all cogs.
    
    Returns:
        Dictionary mapping cog names to migration status
        ("migrated", "in_progress", "pending")
    """
    return {cog_name: "migrated" for cog_name in AVAILABLE_COGS}

__all__ = [
    "AVAILABLE_COGS",
    "CORE_COGS", 
    "EVENT_COGS",
    "MEMBER_COGS",
    "UTILITY_COGS",
    "COG_METADATA",
    "get_cog_path",
    "get_cogs_by_category",
    "get_cogs_by_priority", 
    "get_cog_dependencies",
    "validate_cog_loading_order",
    "get_migration_status",
]
