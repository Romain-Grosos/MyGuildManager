"""
LLM Interaction Cog - Manages AI-powered chat interactions and weapon name normalization.
"""

import asyncio
import os
import re
import time
from typing import List, Dict, Optional, Any

import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from core.logger import ComponentLogger
from core.translation import translations as global_translations
from core.functions import get_effective_locale
from core.reliability import discord_resilient

LLM_DATA = global_translations.get("llm", {})

_logger = ComponentLogger("llm")
_openai_client: Optional[OpenAI] = None

load_dotenv()

DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
MODEL_FALLBACK = os.getenv("LLM_MODEL_FALLBACK", "gpt-4o-mini")

def get_openai_client() -> OpenAI:
    """
    Initialize (once) and return the OpenAI client.
    Prefers OPENAI_API_KEY; falls back to API_KEY for backward compatibility.

    Returns:
        OpenAI client instance

    Raises:
        ValueError: If no API key found in environment variables
    """
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise ValueError("Missing OPENAI_API_KEY (or legacy API_KEY) in environment")

    _openai_client = OpenAI(api_key=api_key)
    return _openai_client

_FALLBACK_REGEXES = [
    (re.compile(r"\b(bow|arc)\b", re.IGNORECASE), "B"),
    (re.compile(r"\b(crossbow|arbalete|arbalète)\b", re.IGNORECASE), "CB"),
    (re.compile(r"\b(dagger|daggers|dague)\b", re.IGNORECASE), "DG"),
    (re.compile(r"\b(greatsword|épée|épées)\b", re.IGNORECASE), "GS"),
    (re.compile(r"\b(staff|baton|bâton)\b", re.IGNORECASE), "S"),
    (re.compile(r"\b(sword and shield|bouclier)\b", re.IGNORECASE), "SNS"),
    (re.compile(r"\b(spear|lance)\b", re.IGNORECASE), "SP"),
    (re.compile(r"\b(wand|baguette)\b", re.IGNORECASE), "W"),
]

def _ask_ai(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """
    Query AI for weapon name normalization with specialized system prompt.

    Args:
        prompt: User input containing weapon names to normalize

    Returns:
        Normalized weapon codes separated by '/'
    """
    client = get_openai_client()
    system = (
        "You convert weapon names into standardized weapon codes for the game Throne and Liberty.\n"
        "Here is the mapping of weapon names to codes:\n"
        "- bow, arc → B\n"
        "- crossbow, arbalète → CB\n"
        "- dagger, daggers, dague → DG\n"
        "- greatsword, épée, épées → GS\n"
        "- staff, baton, bâton → S\n"
        "- sword and shield, bouclier → SNS\n"
        "- spear, lance → SP\n"
        "- wand, baguette → W\n"
        "Given a list of weapon names, return only the corresponding codes (B, CB, DG, GS, S, SNS, SP, W) separated by '/'.\n"
        "Ignore any unknown weapons.\n"
    )
    msgs: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    out = client.chat.completions.create(model=model, messages=msgs, temperature=0)
    return out.choices[0].message.content.strip()

def query_ai(prompt: str, system_prompt: str, model: str = DEFAULT_MODEL) -> str:
    """
    Main AI query function for general chat interactions with dynamic system prompt.

    Args:
        prompt: User question or request
        system_prompt: System prompt with bot commands and context
        model: OpenAI model to use (default: gpt-4o)

    Returns:
        AI-generated response text
    """
    client = get_openai_client()

    messages: List[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    completion = client.chat.completions.create(
        model=model, messages=messages
    )
    return completion.choices[0].message.content or ""

def split_message(text: str, max_length: int = 2000) -> List[str]:
    """
    Split long messages into chunks respecting Discord's message limit.
    Code-fence aware splitting prevents breaking triple-backtick blocks.

    Args:
        text: Text to split into chunks
        max_length: Maximum length per chunk (default: 2000)

    Returns:
        List of text chunks within size limits
    """
    chunks: List[str] = []
    buf = []
    cur_len = 0
    in_fence = False

    def flush():
        nonlocal buf, cur_len
        if buf:
            chunk = "\n".join(buf)
            chunks.append(chunk)
            buf = []
            cur_len = 0

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence

        add_len = (1 if buf else 0) + len(line)
        if cur_len + add_len > max_length and not in_fence:
            flush()

        if not in_fence and len(line) > max_length:
            flush()
            for i in range(0, len(line), max_length):
                chunks.append(line[i:i+max_length])
            continue

        if buf:
            buf.append(line)
            cur_len += 1 + len(line)
        else:
            buf = [line]
            cur_len = len(line)

    flush()
    return chunks

class LLMInteraction(commands.Cog):
    """Cog for managing AI-powered chat interactions and weapon name normalization."""

    def __init__(self, bot: discord.Bot) -> None:
        """
        Initialize the LLMInteraction cog.

        Args:
            bot: Discord bot instance
        """
        self.bot = bot
        self.user_requests: Dict[int, List[float]] = {}
        self.max_requests_per_minute = 6
        self._prompt_cache: Dict[str, tuple[str, float]] = {}
        self._prompt_cache_ttl = 3600

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize LLM data on bot ready."""
        asyncio.create_task(self.bot.cache_loader.wait_for_initial_load())
        _logger.debug("waiting_for_cache_load")
    
    @commands.Cog.listener()
    async def on_application_command_completion(self, ctx):
        """Invalidate prompt cache when commands might have changed."""
        if hasattr(ctx, 'command') and ctx.command and ctx.command.name in ['reload', 'sync', 'bot_reset']:
            await self.invalidate_prompt_cache()
            _logger.debug(
                "cache_invalidated_after_command",
                command=ctx.command.name
            )

    async def discover_bot_commands(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Discover all bot commands and their descriptions dynamically.

        Returns:
            Dictionary mapping cog names to their commands info
        """
        commands_info = {}

        for cog_name, cog in self.bot.cogs.items():
            commands_info[cog_name] = []
            walker = getattr(cog, "walk_commands", None)
            iterable = walker() if callable(walker) else []
            for command in iterable:
                if isinstance(command, discord.SlashCommand):
                    command_data = {
                        'name': command.name,
                        'description': command.description or "No description",
                        'options': []
                    }

                    if hasattr(command, 'options'):
                        for option in command.options:
                            command_data['options'].append(option.name)
                    
                    commands_info[cog_name].append(command_data)

        for group_name in ['admin_bot', 'absence', 'member', 'loot', 'staff', 'events', 'statics']:
            if hasattr(self.bot, f'{group_name}_group'):
                group = getattr(self.bot, f'{group_name}_group')
                if group and hasattr(group, 'subcommands'):
                    commands_info[f'{group_name}_group'] = []
                    for subcommand in group.subcommands:
                        commands_info[f'{group_name}_group'].append({
                            'name': f"/{group_name} {subcommand.name}",
                            'description': subcommand.description or "No description",
                            'options': []
                        })
        
        return commands_info

    def extract_command_translations(self, locale: str = "en-US") -> Dict[str, str]:
        """
        Extract command translations from the global translations.

        Args:
            locale: Language locale to use for translations

        Returns:
            Dictionary of command translations
        """
        translations_data = {}

        for section_key, section_data in global_translations.items():
            if isinstance(section_data, dict):
                for cmd_key, cmd_data in section_data.items():
                    if isinstance(cmd_data, dict):
                        if 'description' in cmd_data and isinstance(cmd_data['description'], dict):
                            if locale in cmd_data['description']:
                                translations_data[f"{section_key}.{cmd_key}"] = cmd_data['description'][locale]

                        if 'commands' in cmd_data and isinstance(cmd_data['commands'], dict):
                            for sub_cmd_key, sub_cmd_data in cmd_data['commands'].items():
                                if isinstance(sub_cmd_data, dict) and 'description' in sub_cmd_data:
                                    if isinstance(sub_cmd_data['description'], dict) and locale in sub_cmd_data['description']:
                                        translations_data[f"{section_key}.commands.{sub_cmd_key}"] = sub_cmd_data['description'][locale]
        
        return translations_data

    async def generate_dynamic_system_prompt(self, locale: str = "en-US") -> str:
        """
        Generate dynamic system prompt with all current commands.

        Args:
            locale: Language locale for the prompt

        Returns:
            Generated system prompt with discovered commands
        """
        try:
            commands_info = await self.discover_bot_commands()
            translations = self.extract_command_translations(locale)

            base_prompt = """You are the intellectual core of 'My Guild Manager', a Discord bot designed to assist guild members with questions and clarifications concerning both the bot's functionalities and the video game 'Throne and Liberty'.

Your core responsibilities include:"""

            commands_section = "\n\n### **Bot Commands Available**:\n"
            
            for cog_name, commands in commands_info.items():
                if commands:
                    display_name = cog_name.replace('_', ' ').title()
                    commands_section += f"\n**{display_name}**:\n"
                    
                    for cmd in commands:
                        translation_key = f"{cog_name.lower()}.{cmd['name']}"
                        description = translations.get(translation_key, cmd['description'])
                        
                        commands_section += f"- **{cmd['name']}"
                        if cmd['options']:
                            commands_section += f" {' '.join(cmd['options'])}"
                        commands_section += f"**: {description}\n"

            weapons_section = """

### **Weapon Codes**:
• B = longbow
• S = staff  
• DG = daggers
• CB = crossbows
• SP = spear
• SNS = sword and shield
• GS = greatsword
• W = wand"""

            game_section = """

### **Game Context**: 
Providing useful context and insights about 'Throne and Liberty', including its mechanics, strategies, and lore. If a question requires details beyond your stored knowledge, indicate that a web search should be performed for up-to-date information.

### Communication Guidelines:
1. **Adapt Your Tone**: Your responses should be accessible, friendly, and humorous. When appropriate, you may be edgy or even playfully insulting—always with clever wordplay—if the question is off-topic or phrased in a disrespectful manner.
2. **Scope of Answer**: Focus exclusively on subjects related to Discord guild management or 'Throne and Liberty'. If a question falls outside these topics, politely refuse to answer and remind the user that you do not retain or have access to channel history.
3. **Do Not Execute Actions**: You only provide guidance and clarifications. You do not execute any Discord actions such as channel management or role assignments.

### Usage Instructions:
• For inquiries regarding bot commands, explain the command functionality and its usage.
• For questions about 'Throne and Liberty', provide relevant game insights, and if uncertain, note that web research is needed.

Remember: You are the specialized knowledge base of 'My Guild Manager'. Always ensure your response is context-aware, concise, and tailored to the question's tone—be it friendly, humorous, or sharply witty. Maintain the focus on the bot's functionality and the game 'Throne and Liberty', and disregard any queries outside these domains."""
            
            return base_prompt + commands_section + weapons_section + game_section
            
        except Exception as e:
            _logger.error(
                "prompt_generation_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )
            return self._get_static_fallback_prompt()

    def _get_static_fallback_prompt(self) -> str:
        """
        Get static fallback prompt if dynamic generation fails.

        Returns:
            Static system prompt as fallback
        """
        return (
            "You are the intellectual core of 'My Guild Manager', a Discord bot designed to assist guild members with "
            "questions and clarifications concerning both the bot's functionalities and the video game 'Throne and Liberty'.\n\n"
            "Your core responsibilities include:\n"
            "  • **Bot Functionality**: Explaining how the bot commands work, such as:\n"
            "       - **/weapons weapon1 weapon2**: Accepts two weapon codes. The available codes are:\n"
            "            • B = longbow\n"
            "            • S = staff\n"
            "            • DG = daggers\n"
            "            • CB = crossbows\n"
            "            • SP = spear\n"
            "            • SNS = sword and shield\n"
            "            • GS = greatsword\n"
            "            • W = wand\n"
            "       - **/build URL**: Submits a URL from Questlog or Maxroll that represents your build.\n"
            "       - **/pseudo NewNickname**: Updates your Discord nickname after you change your in-game name.\n"
            "       - **/gear_score xxxx**: Accepts a numerical equipment score between 500 and 9999.\n"
            "       - **/show_build Pseudo**: Retrieves the build URL associated with the specified member.\n\n"
            "• **Game Context**: Providing useful context and insights about 'Throne and Liberty', including its mechanics, strategies, "
            "and lore. If a question requires details beyond your stored knowledge, indicate that a web search should be performed for "
            "up-to-date information.\n\n"
            "### Communication Guidelines:\n"
            "1. **Adapt Your Tone**: Your responses should be accessible, friendly, and humorous. When appropriate, you may be edgy or even "
            "playfully insulting—always with clever wordplay—if the question is off-topic or phrased in a disrespectful manner.\n"
            "2. **Scope of Answer**: Focus exclusively on subjects related to Discord guild management or 'Throne and Liberty'. If a question "
            "falls outside these topics, politely refuse to answer and remind the user that you do not retain or have access to channel history.\n"
            "3. **Do Not Execute Actions**: You only provide guidance and clarifications. You do not execute any Discord actions such as "
            "channel management or role assignments.\n\n"
            "### Usage Instructions:\n"
            "• For inquiries regarding bot commands, explain the command functionality and its usage.\n"
            "• For questions about 'Throne and Liberty', provide relevant game insights, and if uncertain, note that web research is needed.\n\n"
            "Remember: You are the specialized knowledge base of 'My Guild Manager'. Always ensure your response is context-aware, "
            "concise, and tailored to the question's tone—be it friendly, humorous, or sharply witty. Maintain the focus on the bot's "
            "functionality and the game 'Throne and Liberty', and disregard any queries outside these domains."
        )

    async def get_system_prompt(self, locale: str = "en-US") -> str:
        """
        Get system prompt with intelligent caching.

        Args:
            locale: Language locale for the prompt

        Returns:
            Cached or newly generated system prompt
        """
        cache_key = f"prompt_{locale}"
        current_time = time.time()

        if cache_key in self._prompt_cache:
            cache_value = self._prompt_cache[cache_key]
            if isinstance(cache_value, tuple) and len(cache_value) == 2:
                cached_prompt, timestamp = cache_value
                if isinstance(timestamp, (int, float)) and isinstance(cached_prompt, str):
                    if current_time - timestamp < self._prompt_cache_ttl:
                        _logger.debug(
                            "using_cached_prompt",
                            locale=locale,
                            cache_age=int(current_time - timestamp)
                        )
                        return cached_prompt
                else:
                    _logger.warning(
                        "invalid_cache_entry",
                        cache_key=cache_key,
                        timestamp_type=type(timestamp).__name__
                    )
                    del self._prompt_cache[cache_key]

        _logger.debug("generating_new_prompt", locale=locale)
        prompt = await self.generate_dynamic_system_prompt(locale)

        self._prompt_cache[cache_key] = (prompt, float(current_time))

        self._cleanup_prompt_cache()
        
        return prompt

    def _cleanup_prompt_cache(self) -> None:
        """Clean up expired prompt cache entries."""
        current_time = time.time()
        expired_keys = []
        
        for key, value in self._prompt_cache.items():
            if isinstance(value, tuple) and len(value) == 2:
                _, timestamp = value
                if isinstance(timestamp, (int, float)):
                    if current_time - timestamp > self._prompt_cache_ttl:
                        expired_keys.append(key)
                else:
                    expired_keys.append(key)
        
        for key in expired_keys:
            del self._prompt_cache[key]
        
        if expired_keys:
            _logger.debug(
                "prompt_cache_cleanup",
                expired_count=len(expired_keys)
            )

    async def invalidate_prompt_cache(self) -> None:
        """Invalidate all prompt cache entries."""
        cache_size = len(self._prompt_cache)
        self._prompt_cache.clear()
        _logger.debug(
            "prompt_cache_invalidated",
            cleared_entries=cache_size
        )

    async def get_guild_premium_status(self, guild_id: int) -> bool:
        """
        Check if guild has premium status from centralized cache.

        Args:
            guild_id: Discord guild ID to check

        Returns:
            True if guild has premium status, False otherwise
        """
        premium = await self.bot.cache.get_guild_data(guild_id, "premium")
        return premium in [True, 1, "1"]

    def sanitize_prompt(self, prompt: str) -> str:
        """
        Sanitize user input to prevent prompt injection attacks.

        Args:
            prompt: Raw user input to sanitize

        Returns:
            Sanitized prompt with dangerous patterns filtered
        """
        prompt = prompt[:1000]
        dangerous_patterns = [
            r"ignore.{0,10}previous",
            r"system.{0,10}prompt",
            r"jailbreak",
            r"pretend.{0,10}you.{0,10}are",
        ]
        for pattern in dangerous_patterns:
            prompt = re.sub(pattern, "[FILTERED]", prompt, flags=re.IGNORECASE)
        return prompt


    def check_rate_limit(self, user_id: int) -> bool:
        """
        Check if user has exceeded rate limit for AI requests.

        Args:
            user_id: Discord user ID to check

        Returns:
            True if user can make request, False if rate limited
        """
        now = time.monotonic()
        lst = self.user_requests.setdefault(user_id, [])
        self.user_requests[user_id] = [t for t in lst if now - t < 60]
        if len(self.user_requests[user_id]) >= self.max_requests_per_minute:
            return False
        self.user_requests[user_id].append(now)
        if len(self.user_requests) > 100:
            self._cleanup_rate_limit_data()
        return True
    
    def _cleanup_rate_limit_data(self) -> None:
        """Clean up old rate limit data for users who haven't made requests recently."""
        now = time.monotonic()
        expired = [uid for uid, reqs in self.user_requests.items() if not reqs or now - max(reqs) > 300]
        for uid in expired:
            del self.user_requests[uid]
        if expired:
            _logger.debug("rate_limit_cleanup", cleaned_users=len(expired))

    async def safe_ai_query(self, prompt: str, locale: str = "en-US", max_retries: int = 2) -> str:
        """
        Execute AI query with timeout, retry logic, exponential backoff, and model fallback.

        Args:
            prompt: User prompt to send to AI
            locale: Language locale for the system prompt
            max_retries: Maximum number of retry attempts (default: 2)

        Returns:
            AI response text or timeout message
        """
        system_prompt = await self.get_system_prompt(locale)
        model_to_use = DEFAULT_MODEL

        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(
                    self.bot.loop.run_in_executor(None, query_ai, prompt, system_prompt, model_to_use),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                _logger.error("ai_query_timeout", attempt=attempt + 1, max_retries=max_retries)
                if attempt == max_retries - 1:
                    raise
            except Exception as e:
                msg = str(e).lower()
                if "does not exist" in msg or "unknown model" in msg:
                    if model_to_use != MODEL_FALLBACK:
                        _logger.warning("model_fallback", from_model=model_to_use, to_model=MODEL_FALLBACK)
                        model_to_use = MODEL_FALLBACK
                        await asyncio.sleep(0.5)
                        continue
                await asyncio.sleep(1.0 * (attempt + 1))
                if attempt == max_retries - 1:
                    _logger.error("ai_query_failed", attempt=attempt + 1, error_type=type(e).__name__, error_msg=str(e)[:200], exc_info=True)
                    raise
        return "Request timed out after multiple attempts."

    async def normalize_weapons(self, raw: str) -> str:
        """
        Normalize weapon names to standardized codes using AI and fallback logic.

        Args:
            raw: Raw weapon names input from user

        Returns:
            Normalized weapon codes separated by '/' (max 32 chars)
        """
        try:
            sanitized_input = self.sanitize_prompt(raw)
            ai_out = await asyncio.wait_for(
                self.bot.loop.run_in_executor(
                    None, _ask_ai, f"Input: {sanitized_input}"
                ),
                timeout=15.0,
            )
            codes = re.findall(r"\b(?:B|CB|DG|GS|S|SNS|SP|W)\b", ai_out.upper())
            if codes:
                return "/".join(dict.fromkeys(codes)).upper()[:32]
        except Exception as e:
            _logger.error(
                "ai_normalization_failed",
                error_type=type(e).__name__,
                error_msg=str(e)[:200],
                exc_info=True
            )
        codes = []
        for pat, code in _FALLBACK_REGEXES:
            if pat.search(raw):
                codes.append(code)
        return "/".join(dict.fromkeys(codes)).upper()[:32]

    @commands.Cog.listener()
    @discord_resilient(service_name="discord_api", max_retries=2)
    async def on_message(self, message: discord.Message):
        """
        Handle bot mentions for AI-powered chat interactions.

        Args:
            message: Discord message object that potentially mentions the bot
        """
        if message.author.bot or message.guild is None:
            return

        if self.bot.user in message.mentions:
            if not self.check_rate_limit(message.author.id):
                _logger.warning(
                    "rate_limit_exceeded",
                    user_id=message.author.id,
                    guild_id=message.guild.id
                )
                locale = await get_effective_locale(
                    self.bot, message.guild.id, message.author.id
                )
                rate_limit_msg = LLM_DATA.get("rate_limit", {}).get(
                    locale,
                    LLM_DATA.get("rate_limit", {}).get(
                        "en-US", "⚠️ Too many requests. Please wait before asking again."
                    ),
                )
                await message.reply(rate_limit_msg, allowed_mentions=discord.AllowedMentions.none())
                return

            locale = await get_effective_locale(
                self.bot, message.guild.id, message.author.id
            )
            try:
                is_premium = await self.get_guild_premium_status(message.guild.id)
            except Exception as e:
                _logger.error(
                    "premium_check_failed",
                    guild_id=message.guild.id,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )
                error_msg = LLM_DATA.get("error_check_premium", {}).get(
                    locale, LLM_DATA.get("error_check_premium", {}).get("en-US")
                )
                await message.reply(error_msg.format(error="Cache error"), allowed_mentions=discord.AllowedMentions.none())
                return

            if not is_premium:
                not_premium = LLM_DATA.get("not_premium", {}).get(
                    locale, LLM_DATA.get("not_premium", {}).get("en-US")
                )
                await message.reply(not_premium, allowed_mentions=discord.AllowedMentions.none())
                return

            prompt = (
                message.content.replace(f"<@!{self.bot.user.id}>", "")
                .replace(f"<@{self.bot.user.id}>", "")
                .strip()
            )
            if not prompt:
                _logger.debug(
                    "empty_prompt_received",
                    user_id=message.author.id,
                    guild_id=message.guild.id
                )
                return

            prompt = self.sanitize_prompt(prompt)
            _logger.debug(
                "processing_request",
                user_id=message.author.id,
                guild_id=message.guild.id,
                prompt_length=len(prompt)
            )

            await message.channel.trigger_typing()

            try:
                response_text = await self.safe_ai_query(prompt, locale)

                if not response_text or not response_text.strip():
                    _logger.warning(
                        "empty_ai_response",
                        user_id=message.author.id,
                        guild_id=message.guild.id,
                        prompt_length=len(prompt)
                    )
                    fallback_messages = {
                        "en-US": "I didn't quite get that—could you try rephrasing?",
                        "fr": "Je n'ai pas bien compris—pourriez-vous reformuler ?",
                        "es-ES": "No entendí bien—¿podrías reformular?",
                        "de": "Das habe ich nicht verstanden—könnten Sie es umformulieren?",
                        "it": "Non ho capito bene—potresti riformulare?"
                    }
                    fallback = fallback_messages.get(locale)
                    if not fallback:
                        _logger.debug("fallback_locale_missing", locale=locale)
                        fallback = fallback_messages["en-US"]
                    response_text = fallback
                
                if len(response_text) > 2000:
                    chunks = split_message(response_text)
                    for chunk in chunks:
                        await message.reply(chunk, allowed_mentions=discord.AllowedMentions.none())
                else:
                    await message.reply(response_text, allowed_mentions=discord.AllowedMentions.none())
                _logger.debug(
                    "response_sent",
                    user_id=message.author.id,
                    guild_id=message.guild.id,
                    response_length=len(response_text)
                )
            except Exception as e:
                _logger.error(
                    "ai_response_generation_failed",
                    user_id=message.author.id,
                    guild_id=message.guild.id,
                    error_type=type(e).__name__,
                    error_msg=str(e)[:200],
                    exc_info=True
                )
                error_gen = LLM_DATA.get("error_generation", {}).get(
                    locale, LLM_DATA.get("error_generation", {}).get("en-US")
                )
                await message.reply(
                    error_gen.format(error="Service temporarily unavailable"),
                    allowed_mentions=discord.AllowedMentions.none()
                )

def setup(bot: discord.Bot) -> None:
    """
    Setup function to add the LLMInteraction cog to the bot.

    Args:
        bot: Discord bot instance
    """
    bot.add_cog(LLMInteraction(bot))
