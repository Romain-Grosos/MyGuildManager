"""
Epic Items Scraper Cog - Scrapes and manages Throne and Liberty Epic T2 items from questlog.gg
Uses Selenium for JavaScript-heavy site scraping with multilingual support
"""

import asyncio
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, time as datetime_time
from typing import Dict, List, Optional, Any, Tuple
import discord
from discord.ext import commands, tasks
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from core.reliability import discord_resilient
from db import run_db_query, run_db_transaction
from core.functions import get_user_message
from core.translation import translations as global_translations

EPIC_ITEMS_DATA = global_translations.get("epic_items", {})

class EpicItemsScraper(commands.Cog):
    """Cog for scraping and managing Epic T2 items from questlog.gg"""
    
    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the Epic Items Scraper cog.
        
        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.base_urls = {
            'en': "https://questlog.gg/throne-and-liberty/en/db/items?grade=5",
            'fr': "https://questlog.gg/throne-and-liberty/fr/db/items?grade=5",
            'es': "https://questlog.gg/throne-and-liberty/es/db/items?grade=5",
            'de': "https://questlog.gg/throne-and-liberty/de/db/items?grade=5"
        }
        self.languages = ['en', 'fr', 'es', 'de']

        self._register_loot_commands()

        asyncio.create_task(self._init_cache())
    
    async def _init_cache(self):
        """Initialize cache from database on startup using cache_loader."""
        try:
            await asyncio.sleep(2)
            await self.bot.cache_loader.ensure_epic_items_t2_loaded()
            logging.info(f"[EpicItemsScraper] Cache initialized via cache_loader")
        except Exception as e:
            logging.error(f"[EpicItemsScraper] Failed to initialize cache: {e}")
    
    def _register_loot_commands(self):
        """Register epic items commands with the centralized loot group."""
        if hasattr(self.bot, 'loot_group'):
            self.bot.loot_group.command(
                name=EPIC_ITEMS_DATA.get("name", {}).get("en-US", "search_item"),
                description=EPIC_ITEMS_DATA.get("description", {}).get("en-US", "Search for Epic T2 items from Throne and Liberty"),
                name_localizations=EPIC_ITEMS_DATA.get("name", {}),
                description_localizations=EPIC_ITEMS_DATA.get("description", {})
            )(self.epic_items)

    async def scrape_epic_items(self) -> None:
        """
        Main method to scrape Epic T2 items from questlog.gg using Selenium.
        
        Scrapes items from all supported languages, processes them, and stores
        them in the database with proper deduplication and caching.
        
        Raises:
            Exception: If scraping fails or no items are found
        """
        start_time = datetime.now()
        items_scraped = 0
        items_added = 0
        items_updated = 0
        items_failed = 0
        
        try:
            logging.info("Starting Epic T2 items scraping with Selenium")

            multilang_items = await self.scrape_multilingual_items()
            
            if not multilang_items:
                raise Exception("No items scraped from any language")

            existing_items_query = "SELECT item_id FROM epic_items_t2"
            existing_result = await run_db_query(existing_items_query, fetch_all=True)
            existing_item_ids = {row[0] for row in existing_result} if existing_result else set()
            
            queries_and_params = []
            
            for item in multilang_items:
                item_id = item.get('item_id')
                
                insert_query = """
                INSERT INTO epic_items_t2 (
                    item_id, item_type, item_category,
                    item_name_en, item_name_fr, item_name_es, item_name_de,
                    item_url, item_icon_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    item_type = VALUES(item_type),
                    item_category = VALUES(item_category),
                    item_name_en = VALUES(item_name_en),
                    item_name_fr = VALUES(item_name_fr),
                    item_name_es = VALUES(item_name_es),
                    item_name_de = VALUES(item_name_de),
                    item_url = VALUES(item_url),
                    item_icon_url = VALUES(item_icon_url),
                    updated_at = CURRENT_TIMESTAMP
                """
                
                data = (
                    item_id,
                    item.get('item_type'),
                    item.get('item_category'),
                    item.get('item_name_en', ''),
                    item.get('item_name_fr', ''),
                    item.get('item_name_es', ''),
                    item.get('item_name_de', ''),
                    item.get('item_url', ''),
                    item.get('item_icon_url', '')
                )
                
                queries_and_params.append((insert_query, data))
                items_scraped += 1

                if item_id in existing_item_ids:
                    items_updated += 1
                else:
                    items_added += 1

            success = await run_db_transaction(queries_and_params)
            
            if success:
                logging.info(f"Epic T2: {items_scraped} items ({items_added} new, {items_updated} upd)")

                await self.update_cache(multilang_items)

                execution_time = int((datetime.now() - start_time).total_seconds())
                await self.log_scraping_success(items_scraped, items_added, items_updated, items_failed, execution_time)
            else:
                raise Exception("Database transaction failed")
                
        except Exception as e:
            execution_time = int((datetime.now() - start_time).total_seconds())
            logging.error(f"Scraping error: {str(e)[:100]}")
            await self.log_scraping_error(str(e), execution_time)
            raise

    async def scrape_multilingual_items(self) -> List[Dict[str, Any]]:
        """
        Scrape items from all language versions and merge them into multilingual records.

        Uses Selenium to scrape items from English (base), French, Spanish, and German
        versions of questlog.gg, then merges the data to create multilingual item records.

        Returns:
            List of item dictionaries with multilingual names and metadata
        """
        
        def run_selenium_scraper():
            """
            Run Selenium scraper in separate thread with memory optimization.
            
            Returns:
                List of multilingual item dictionaries or empty list on failure
            """
            try:
                logging.info("Starting memory-optimized Epic T2 scraping")

                logging.info("Scraping English items for base list...")
                base_items = self.scrape_language_items_optimized('en')
                
                if not base_items:
                    logging.error("No base items found in English")
                    return []
                
                logging.info(f"Base items: {len(base_items)}")

                multilang_items = {}
                for item in base_items:
                    item_id = item['item_id']
                    multilang_items[item_id] = {
                        'item_id': item_id,
                        'item_type': item['item_type'],
                        'item_category': item['item_category'],
                        'item_url': item['item_url'],
                        'item_icon_url': item['item_icon_url'],
                        'item_name_en': item['item_name']
                    }

                for lang in ['fr', 'es', 'de']:
                    logging.info(f"{lang.upper()} scraping...")
                    try:
                        lang_items = self.scrape_language_items_optimized(lang)

                        for item in lang_items:
                            item_id = item['item_id']
                            if item_id in multilang_items:
                                multilang_items[item_id][f'item_name_{lang}'] = item['item_name']
                        
                        logging.info(f"{lang.upper()}: {len(lang_items)}")
                        
                    except Exception as e:
                        logging.warning(f"{lang} fail: {str(e)[:50]}")
                        for item_id in multilang_items:
                            if f'item_name_{lang}' not in multilang_items[item_id]:
                                multilang_items[item_id][f'item_name_{lang}'] = multilang_items[item_id]['item_name_en']
                
                logging.info(f"Total scraped: {len(multilang_items)}")
                return list(multilang_items.values())
                
            except Exception as e:
                logging.error(f"Selenium error: {str(e)[:100]}")
                return []

        try:
            return await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, run_selenium_scraper),
                timeout=3600
            )
        except asyncio.TimeoutError:
            logging.error("[EpicItemsScraper] Scraping timeout after 1 hour")
            return []

    def scrape_language_items_optimized(self, language: str) -> List[Dict[str, Any]]:
        """
        Scrape items from a specific language with memory-optimized driver.

        Creates a new Firefox WebDriver instance with memory optimizations and
        scrapes all items from the specified language version of questlog.gg.

        Args:
            language: Language code ('en', 'fr', 'es', 'de')

        Returns:
            List of item dictionaries with metadata for the specified language
        """
        driver = None
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-plugins')
            options.add_argument('--disable-images')
            options.add_argument('--disable-javascript')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--memory-pressure-off')
            options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            options.set_preference('browser.cache.disk.enable', False)
            options.set_preference('browser.cache.memory.enable', False)
            options.set_preference('browser.cache.offline.enable', False)
            options.set_preference('network.http.use-cache', False)
            options.set_preference('browser.sessionhistory.max_total_viewers', 0)
            options.set_preference('browser.sessionstore.max_tabs_undo', 0)
            options.set_preference('media.memory_cache_max_size', 0)
            
            logging.info(f"Creating Firefox driver: {language}")
            driver = webdriver.Firefox(options=options)
            driver.set_page_load_timeout(30)
            
            items = self.scrape_language_items(driver, language)
            logging.info(f"{language}: {len(items)} items")
            
            return items
            
        except Exception as e:
            logging.error(f"{language} error: {str(e)[:100]}")
            return []
        finally:
            if driver:
                try:
                    driver.quit()
                    logging.debug(f"Driver closed: {language}")
                except Exception as e:
                    logging.warning(f"Close error {language}: {str(e)[:50]}")

    def scrape_language_items(self, driver, language: str) -> List[Dict[str, Any]]:
        """
        Scrape items from a specific language version with automatic pagination detection.

        Uses an existing WebDriver instance to scrape all pages for a language,
        automatically detecting the total number of pages and handling pagination.

        Args:
            driver: WebDriver instance to use for scraping
            language: Language code ('en', 'fr', 'es', 'de')

        Returns:
            List of item dictionaries scraped from all pages
        """
        items = []
        base_url = self.base_urls[language]
        
        try:
            max_pages = self.detect_total_pages(driver, base_url, language)
            logging.info(f"{language}: {max_pages} pages")
            
            for page in range(1, max_pages + 1):
                page_url = f"{base_url}&page={page}"
                logging.debug(f"{language} p{page}/{max_pages}")
                
                try:
                    driver.get(page_url)

                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.TAG_NAME, "body"))
                    )

                    time.sleep(2)

                    html_content = driver.page_source
                    soup = BeautifulSoup(html_content, 'html.parser')

                    item_links = soup.find_all('a', href=re.compile(r'/items?/'))
                    page_items = []
                    
                    for link in item_links:
                        try:
                            item = self.extract_item_from_link(link, language)
                            if item and self.should_include_item(item['item_id']):
                                page_items.append(item)
                        except Exception as e:
                            logging.debug(f"Extract fail: {str(e)[:50]}")
                            continue
                        
                    items.extend(page_items)
                    logging.debug(f"p{page}: {len(page_items)} items")
                    
                except Exception as page_error:
                    logging.warning(f"{language} p{page} error: {str(page_error)[:50]}")
                    continue
            
            logging.info(f"{language} total: {len(items)}")
            return items
            
        except Exception as e:
            logging.error(f"{language} scrape error: {str(e)[:100]}")
            return []

    def detect_total_pages(self, driver, base_url: str, language: str) -> int:
        """
        Detect the total number of pages by examining pagination elements.
        
        Args:
            driver: WebDriver instance to use
            base_url: Base URL for the language version
            language: Language code for logging
            
        Returns:
            Total number of pages detected, defaults to 20 if detection fails
        """
        try:
            first_page_url = f"{base_url}&page=1"
            driver.get(first_page_url)
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            import time
            time.sleep(3)
            
            html_content = driver.page_source
            soup = BeautifulSoup(html_content, 'html.parser')

            pagination_selectors = [
                'nav[aria-label*="pagination"]',
                '.pagination',
                '[class*="pagination"]',
                '[class*="pager"]',
                'nav[class*="page"]',
                '.page-navigation',
                '[data-testid*="pagination"]'
            ]
            
            max_page = 1
            
            for selector in pagination_selectors:
                pagination_container = soup.select_one(selector)
                if pagination_container:
                    page_links = pagination_container.find_all('a', href=re.compile(r'page=\d+'))
                    for link in page_links:
                        href = link.get('href', '')
                        page_match = re.search(r'page=(\d+)', str(href))
                        if page_match:
                            page_num = int(page_match.group(1))
                            max_page = max(max_page, page_num)

                    page_texts = pagination_container.find_all(text=re.compile(r'\d+'))
                    for text in page_texts:
                        numbers = re.findall(r'\d+', str(text).strip())
                        for num_str in numbers:
                            try:
                                num = int(num_str)
                                if 1 <= num <= 100:
                                    max_page = max(max_page, num)
                            except ValueError:
                                continue
                    
                    if max_page > 1:
                        logging.debug(f"Max page: {max_page}")
                        break

            if max_page == 1:
                max_page = self.binary_search_last_page(driver, base_url, language)

            if max_page == 1:
                logging.warning(f"{language}: pagination fallback (20)")
                max_page = 20
            
            return max_page
            
        except Exception as e:
            logging.error(f"{language} page detect error: {str(e)[:50]}")
            return 20

    def binary_search_last_page(self, driver, base_url: str, language: str) -> int:
        """
        Use binary search to find the last page with Epic T2 items specifically.
        
        Args:
            driver: WebDriver instance to use
            base_url: Base URL for the language version
            language: Language code for logging
            
        Returns:
            Estimated number of pages with Epic T2 items
        """
        try:
            low, high = 1, 30
            last_epic_page = 1
            consecutive_empty = 0

            while low <= high and consecutive_empty < 3:
                mid = (low + high) // 2
                test_url = f"{base_url}&page={mid}"
                driver.get(test_url)
                
                import time
                time.sleep(1)
                
                html_content = driver.page_source
                soup = BeautifulSoup(html_content, 'html.parser')
                item_links = soup.find_all('a', href=re.compile(r'/items?/'))

                epic_items_found = 0
                for link in item_links:
                    try:
                        href = link.get('href', '')
                        item_id_match = re.search(r'/items?/(?:[^/?]+/)*([^/?]+)', str(href))
                        if item_id_match:
                            item_id = item_id_match.group(1)
                            if self.should_include_item(item_id):
                                epic_items_found += 1
                    except:
                        continue

                logging.debug(f"p{mid}: {epic_items_found} items")

                if epic_items_found > 0:
                    last_epic_page = mid
                    consecutive_empty = 0
                    low = mid + 1
                else:
                    consecutive_empty += 1
                    high = mid - 1

            final_pages = min(last_epic_page + 2, 25)
            logging.info(f"{language}: pages {final_pages} (last T2: p{last_epic_page})")
            return final_pages
            
        except Exception as e:
            logging.error(f"{language} binary search: {str(e)[:50]}")
            return 20

    def extract_item_from_link(self, link_element, language: str) -> Optional[Dict[str, Any]]:
        """
        Extract item data from a link element.
        
        Args:
            link_element: BeautifulSoup link element containing item data
            language: Language code for the current scraping session
            
        Returns:
            Dictionary with item data or None if extraction fails
        """
        try:
            href = link_element.get('href', '')
            if not href:
                return None

            item_id_match = re.search(r'/items?/(?:[^/?]+/)*([^/?]+)', href)
            if not item_id_match:
                return None
            
            item_id = item_id_match.group(1)

            item_name = link_element.get_text(strip=True)
            if not item_name:
                return None

            item_type, item_category = self.classify_item_by_id(item_id)

            base_domain = "https://questlog.gg"
            item_url = f"{base_domain}{href}" if href.startswith('/') else href

            icon_url = ""
            img_element = link_element.find('img')
            if img_element and img_element.get('src'):
                icon_src = img_element['src']
                if icon_src.startswith('/'):
                    icon_url = f"{base_domain}{icon_src}"
                elif icon_src.startswith('http'):
                    icon_url = icon_src
            
            return {
                'item_id': item_id,
                'item_name': item_name,
                'item_type': item_type,
                'item_category': item_category,
                'item_url': item_url,
                'item_icon_url': icon_url
            }
            
        except Exception as e:
            logging.debug(f"Extract error: {str(e)[:30]}")
            return None

    def should_include_item(self, item_id: str) -> bool:
        """
        Check if item should be included based on ID patterns.
        
        Args:
            item_id: Item identifier to check
            
        Returns:
            True if item should be included, False otherwise
        """
        if not item_id:
            return False

        exclude_patterns = [
            "_blueprint", "_traitextract", "package_", "perk_", 
            "contract_", "material_", "guild_", "_extract"
        ]
        
        for pattern in exclude_patterns:
            if pattern in item_id.lower():
                return False

        include_patterns = [
            "bow_", "sword_", "sword2h_", "staff_", "dagger_", "crossbow_", "spear_",
            "wand_", "longbow_", "axe_", "hammer_",
            "head_", "chest_", "legs_", "hands_", "feet_", 
            "ring_", "necklace_", "bracelet_", "belt_", "earring_", "ear_",
            "cape_", "cloak_"
        ]
        
        for pattern in include_patterns:
            if item_id.lower().startswith(pattern):
                return True
        
        return False
    
    def classify_item_by_id(self, item_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Classify item type and category based on ID patterns.
        
        Args:
            item_id: Item identifier to classify
            
        Returns:
            Tuple of (item_type, item_category) or (None, None) if unrecognized
        """
        if not item_id:
            return None, None
        
        item_id_lower = item_id.lower()

        weapon_patterns = {
            "bow_": "Bow", "longbow_": "Bow",
            "sword_": "Sword", "sword2h_": "Greatsword",
            "staff_": "Staff", "wand_": "Wand",
            "dagger_": "Dagger", "crossbow_": "Crossbow",
            "spear_": "Spear", "axe_": "Axe", "hammer_": "Hammer"
        }
        
        for pattern, category in weapon_patterns.items():
            if item_id_lower.startswith(pattern):
                return "Weapon", category

        armor_patterns = {
            "head_": "Head", "chest_": "Chest",
            "legs_": "Legs", "hands_": "Hands",
            "feet_": "Feet", "cape_": "Cape", "cloak_": "Cloak"
        }
        
        for pattern, category in armor_patterns.items():
            if item_id_lower.startswith(pattern):
                return "Armor", category

        accessory_patterns = {
            "ring_": "Ring", "necklace_": "Necklace",
            "bracelet_": "Bracelet", "belt_": "Belt",
            "earring_": "Earring", "ear_": "Earring"
        }
        
        for pattern, category in accessory_patterns.items():
            if item_id_lower.startswith(pattern):
                return "Accessory", category
        
        return None, None

    async def get_translated_item_info(self, ctx: discord.ApplicationContext, item_type: str, item_category: str) -> "Tuple[str, str]":
        """
        Get translated item type and category based on user's locale.
        
        Args:
            ctx: Discord application context with locale information
            item_type: Item type to translate
            item_category: Item category to translate
            
        Returns:
            Tuple of (translated_type, translated_category)
        """
        try:
            from core.functions import get_effective_locale
            locale = await get_effective_locale(ctx.bot, ctx.guild.id, ctx.author.id)
        except Exception:
            locale = "en-US"

        translated_type = EPIC_ITEMS_DATA.get("item_types", {}).get(item_type, {}).get(locale)
        if not translated_type:
            translated_type = EPIC_ITEMS_DATA.get("item_types", {}).get(item_type, {}).get("en-US", item_type)

        translated_category = EPIC_ITEMS_DATA.get("item_categories", {}).get(item_category, {}).get(locale)
        if not translated_category:
            translated_category = EPIC_ITEMS_DATA.get("item_categories", {}).get(item_category, {}).get("en-US", item_category)
        
        return translated_type or item_type, translated_category or item_category

    async def update_cache(self, items: List[Dict[str, Any]]) -> None:
        """
        Update the cache with scraped items.
        
        Args:
            items: List of item dictionaries to cache
        """
        await self.bot.cache.set_static_data('epic_items_t2', items)
        logging.info(f"Cache updated: {len(items)} items")

    async def log_scraping_success(self, items_scraped: int, items_added: int, items_updated: int, items_failed: int, execution_time: int) -> None:
        """
        Log successful scraping to database.
        
        Args:
            items_scraped: Total number of items scraped
            items_added: Number of new items added
            items_updated: Number of existing items updated
            items_failed: Number of items that failed processing
            execution_time: Total execution time in seconds
        """
        try:
            status = 'success' if items_failed == 0 else 'partial' if items_failed < items_scraped else 'error'
            
            query = """
            INSERT INTO epic_items_scraping_history (
                items_scraped, items_added, items_updated, items_deleted,
                status, execution_time_seconds
            ) VALUES (?, ?, ?, ?, ?, ?)
            """
            
            await run_db_query(
                query, 
                (items_scraped, items_added, items_updated, 0, status, execution_time),
                commit=True
            )
            
            logging.info(f"Logged scraping success: {items_scraped} scraped, {items_failed} failed")
            
        except Exception as e:
            logging.error(f"Failed to log scraping success: {e}")

    async def log_scraping_error(self, error_message: str, execution_time: int) -> None:
        """
        Log scraping error to database.
        
        Args:
            error_message: Error message to log
            execution_time: Total execution time in seconds before error
        """
        try:
            query = """
            INSERT INTO epic_items_scraping_history (
                items_scraped, items_added, items_updated, items_deleted,
                status, execution_time_seconds, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            
            await run_db_query(
                query, 
                (0, 0, 0, 0, 'error', execution_time, error_message),
                commit=True
            )
            
            logging.info(f"Logged scraping error: {error_message}")
            
        except Exception as e:
            logging.error(f"Failed to log scraping error: {e}")

    @discord_resilient(service_name='discord_api', max_retries=3)
    async def epic_items(
        self,
        ctx: discord.ApplicationContext,
        search: str = discord.Option(
            description=EPIC_ITEMS_DATA.get("options", {}).get("search", {}).get("description", {}).get("en-US", "Search for specific item by name"),
            description_localizations=EPIC_ITEMS_DATA.get("options", {}).get("search", {}).get("description", {}),
            required=True
        )
    ):
        """
        Command to search items from the Epic T2 database.
        
        Args:
            ctx: Discord application context
            search: Search filter for item names (required)
        """
        await ctx.defer()
        
        try:
            items = await self.bot.cache.get_static_data('epic_items_t2')
            
            if not items:
                query = """
                SELECT item_id, item_name_en, item_type, item_category, 
                       item_icon_url, item_url,
                       item_name_fr, item_name_es, item_name_de
                FROM epic_items_t2
                """
                params = []
                conditions = []
                
                search_conditions = [
                    "item_name_en LIKE ?",
                    "item_name_fr LIKE ?", 
                    "item_name_es LIKE ?",
                    "item_name_de LIKE ?"
                ]
                conditions.append(f"({' OR '.join(search_conditions)})")
                search_param = f"%{search}%"
                params.extend([search_param, search_param, search_param, search_param])
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                
                query += " ORDER BY item_name_en"
                
                results = await run_db_query(query, tuple(params) if params else (), fetch_all=True)
                
                if results:
                    items = []
                    for row in results:
                        items.append({
                            "item_id": row[0],
                            "item_name_en": row[1],
                            "item_type": row[2] or "Unknown", 
                            "item_category": row[3] or "Unknown",
                            "item_icon_url": row[4],
                            "item_url": row[5] or f"https://questlog.gg/throne-and-liberty/en/db/item/{row[0]}",
                            "item_name_fr": row[6] or "",
                            "item_name_es": row[7] or "",
                            "item_name_de": row[8] or ""
                        })
            else:
                filtered_items = []
                search_lower = search.lower().strip()
                
                for item in items:
                    item_names = [
                        item.get("item_name_en", ""),
                        item.get("item_name_fr", ""), 
                        item.get("item_name_es", ""),
                        item.get("item_name_de", "")
                    ]
                    
                    found = False
                    for name in item_names:
                        if name and search_lower in name.lower():
                            found = True
                            break
                    
                    if found:
                        filtered_items.append(item)
                
                items = filtered_items
            
            if not items:
                no_items_msg = await get_user_message(ctx, EPIC_ITEMS_DATA, "messages.no_items_found")
                await ctx.respond(no_items_msg)
                return

            embeds = []
            items_per_page = 5
            
            for i in range(0, len(items), items_per_page):
                search_title = await get_user_message(ctx, EPIC_ITEMS_DATA, "messages.search_title")
                search_title += f" : `{search}`"
                
                embed = discord.Embed(
                    title=search_title,
                    color=discord.Color.purple()
                )
                
                type_label = await get_user_message(ctx, EPIC_ITEMS_DATA, "messages.item_type_label")
                category_label = await get_user_message(ctx, EPIC_ITEMS_DATA, "messages.item_category_label")
                view_label = await get_user_message(ctx, EPIC_ITEMS_DATA, "messages.view_on_questlog")
                
                page_items = items[i:i+items_per_page]
                for j, item in enumerate(page_items):
                    item_name = item.get("item_name_en", "Unknown")
                    item_type_val = item.get('item_type', 'Unknown')
                    item_category_val = item.get('item_category', 'Unknown')
                    item_url = item.get('item_url', '')

                    translated_type, translated_category = await self.get_translated_item_info(ctx, item_type_val, item_category_val)
                    
                    field_value = f"`{item_name}`\n\n"
                    field_value += f"**{type_label}:** {translated_type}\n"
                    field_value += f"**{category_label}:** {translated_category}\n"
                    if item_url:
                        field_value += f"[{view_label}]({item_url})"
                    
                    if j < len(page_items) - 1:
                        field_value += "\n\n" + "─" * 30
                    
                    embed.add_field(
                        name=f"\u200b",
                        value=field_value,
                        inline=False
                    )
                
                if page_items and page_items[0].get('item_icon_url'):
                    embed.set_thumbnail(url=page_items[0]['item_icon_url'])
                
                if len(items) > items_per_page:
                    current_page = (i//items_per_page)+1
                    total_pages = ((len(items)-1)//items_per_page)+1
                    embed.set_footer(text=f"Page {current_page}/{total_pages}")
                
                embeds.append(embed)

            await ctx.respond(embed=embeds[0])
                
        except Exception as e:
            logging.error(f"Error in epic_items command: {e}")
            error_msg = await get_user_message(ctx, EPIC_ITEMS_DATA, "messages.error")
            await ctx.respond(error_msg, ephemeral=True)

def setup(bot):
    """
    Setup function to add this cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(EpicItemsScraper(bot))
