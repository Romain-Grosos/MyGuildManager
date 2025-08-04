"""
LLM Interaction Cog - Manages AI-powered chat interactions and weapon name normalization.
"""

import asyncio
import logging
import os
import re
import time
from typing import List, Dict, Any, Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from core.translation import translations as global_translations

LLM_DATA = global_translations.get("llm", {})

load_dotenv()

def get_openai_client():
    """
    Initialize and return OpenAI client with API key from environment.
    
    Returns:
        OpenAI client instance
        
    Raises:
        ValueError: If API_KEY not found in environment variables
    """
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("API_KEY not found in environment")
    return OpenAI(api_key=api_key)

_FALLBACK = {
    "bow": "B",
    "arc": "B",
    "crossbow": "CB",
    "arbalete": "CB",
    "arbalète": "CB",
    "dagger": "DG",
    "dague": "DG",
    "daggers": "DG",
    "greatsword": "GS",
    "épée": "GS",
    "épées": "GS",
    "staff": "S",
    "bâton": "S",
    "baton": "S",
    "sword and shield": "SNS",
    "bouclier": "SNS",
    "spear": "SP",
    "lance": "SP",
    "wand": "W",
    "baguette": "W",
}

def _ask_ai(prompt: str) -> str:
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
    msgs: List[ChatCompletionMessageParam] = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    out = client.chat.completions.create(model="gpt-4o", messages=msgs, temperature=0)
    return out.choices[0].message.content.strip()

def query_ai(prompt: str, model: str = "gpt-4o") -> str:
    """
    Main AI query function for general chat interactions with specialized system prompt.
    
    Args:
        prompt: User question or request
        model: OpenAI model to use (default: gpt-4o)
        
    Returns:
        AI-generated response text
    """
    client = get_openai_client()
    system_prompt = (
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

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    completion = client.chat.completions.create(
        model=model,
        messages=messages  # type: ignore
    )
    return completion.choices[0].message.content or ""

def split_message(text: str, max_length: int = 2000) -> "List[str]":
    """
    Split long messages into chunks respecting Discord's message limit.
    
    Args:
        text: Text to split into chunks
        max_length: Maximum length per chunk (default: 2000)
        
    Returns:
        List of text chunks within size limits
    """
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            if len(sentence) > max_length:
                parts = [sentence[i:i+max_length] for i in range(0, len(sentence), max_length)]
                chunks.extend(parts)
                current_chunk = ""
            else:
                current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk)
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
        self.user_requests = {}
        self.max_requests_per_minute = 6

    @commands.Cog.listener()
    async def on_ready(self):
        """Initialize LLM data on bot ready."""
        asyncio.create_task(self.load_llm_data())
        logging.debug("[LLMInteraction] Cache loading tasks started in on_ready.")

    async def load_llm_data(self) -> None:
        """
        Ensure all required data is loaded via centralized cache loader.
        
        Loads guild settings needed for premium status checks and language preferences.
        """
        logging.debug("[LLMInteraction] Loading LLM data")
        
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        
        logging.debug("[LLMInteraction] LLM data loading completed")

    async def get_guild_premium_status(self, guild_id: int) -> bool:
        """
        Check if guild has premium status from centralized cache.
        
        Args:
            guild_id: Discord guild ID to check
            
        Returns:
            True if guild has premium status, False otherwise
        """
        await self.bot.cache_loader.ensure_category_loaded('guild_settings')
        
        premium = await self.bot.cache.get_guild_data(guild_id, 'premium')
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
            r'ignore.{0,10}previous',
            r'system.{0,10}prompt',
            r'jailbreak',
            r'pretend.{0,10}you.{0,10}are'
        ]
        for pattern in dangerous_patterns:
            prompt = re.sub(pattern, '[FILTERED]', prompt, flags=re.IGNORECASE)
        return prompt
    
    def get_safe_user_info(self, user):
        """
        Get safe user information for logging purposes.
        
        Args:
            user: Discord user object
            
        Returns:
            Safe user identifier string for logs
        """
        return f"User{user.id}"
    
    def check_rate_limit(self, user_id: int) -> bool:
        """
        Check if user has exceeded rate limit for AI requests.
        
        Args:
            user_id: Discord user ID to check
            
        Returns:
            True if user can make request, False if rate limited
        """
        now = time.time()
        if user_id not in self.user_requests:
            self.user_requests[user_id] = []

        self.user_requests[user_id] = [req_time for req_time in self.user_requests[user_id] if now - req_time < 60]
        
        if len(self.user_requests[user_id]) >= self.max_requests_per_minute:
            return False
        
        self.user_requests[user_id].append(now)
        return True
    
    async def safe_ai_query(self, prompt: str, max_retries: int = 2) -> str:
        """
        Execute AI query with timeout and retry logic.
        
        Args:
            prompt: User prompt to send to AI
            max_retries: Maximum number of retry attempts (default: 2)
            
        Returns:
            AI response text or timeout message
        """
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(
                    self.bot.loop.run_in_executor(None, query_ai, prompt),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1)
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
                self.bot.loop.run_in_executor(None, _ask_ai, f"Input: {sanitized_input}"),
                timeout=15.0
            )
            codes = re.findall(r"\b(?:B|CB|DG|GS|S|SNS|SP|W)\b", ai_out.upper())
            if codes:
                return "/".join(dict.fromkeys(codes))[:32]
        except Exception as e:
            logging.error(f"[LLMInteraction] AI normalization failed: {e}", exc_info=True)
        codes = []
        for token in re.split(r"[ ,;/|]+", raw.lower()):
            for k, v in _FALLBACK.items():
                if k in token:
                    codes.append(v)
                    break
        return "/".join(dict.fromkeys(codes))[:32]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Handle bot mentions for AI-powered chat interactions.
        
        Args:
            message: Discord message object that potentially mentions the bot
        """
        if message.author.bot or message.guild is None:
            return

        if self.bot.user in message.mentions:
            safe_user = self.get_safe_user_info(message.author)

            if not self.check_rate_limit(message.author.id):
                logging.warning(f"[LLMInteraction] Rate limit exceeded for {safe_user}")
                locale = message.guild.preferred_locale or "en-US"
                rate_limit_msg = LLM_DATA.get("rate_limit", {}).get(locale, LLM_DATA.get("rate_limit", {}).get("en-US", "⚠️ Too many requests. Please wait before asking again."))
                await message.reply(rate_limit_msg)
                return
            
            locale = message.guild.preferred_locale or "en-US"
            try:
                is_premium = await self.get_guild_premium_status(message.guild.id)
            except Exception as e:
                logging.error(f"[LLMInteraction] Error checking premium status for guild {message.guild.id}: {e}", exc_info=True)
                error_msg = LLM_DATA.get("error_check_premium", {}).get(locale,LLM_DATA.get("error_check_premium", {}).get("en-US"))
                await message.reply(error_msg.format(error="Cache error"))
                return

            if not is_premium:
                not_premium = LLM_DATA.get("not_premium", {}).get(locale, LLM_DATA.get("not_premium", {}).get("en-US"))
                await message.reply(not_premium)
                return

            prompt = message.content.replace(f"<@!{self.bot.user.id}>", "").replace(f"<@{self.bot.user.id}>", "").strip()
            if not prompt:
                logging.debug(f"[LLMInteraction] Empty prompt from {safe_user}")
                return
            
            prompt = self.sanitize_prompt(prompt)
            logging.debug(f"[LLMInteraction] Processing request from {safe_user}")

            await message.channel.trigger_typing()

            try:
                response_text = await self.safe_ai_query(prompt)
                if len(response_text) > 2000:
                    chunks = split_message(response_text)
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response_text)
                logging.debug(f"[LLMInteraction] Response sent to {safe_user}")
            except Exception as e:
                logging.error(f"[LLMInteraction] Error generating AI response for {safe_user}: {e}", exc_info=True)
                error_gen = LLM_DATA.get("error_generation", {}).get(locale, LLM_DATA.get("error_generation", {}).get("en-US"))
                await message.reply(error_gen.format(error="Service temporarily unavailable"))

def setup(bot: discord.Bot) -> None:
    """
    Setup function to add the LLMInteraction cog to the bot.
    
    Args:
        bot: Discord bot instance
    """
    bot.add_cog(LLMInteraction(bot))

