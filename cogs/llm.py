import discord
from discord.ext import commands
import os
from openai import OpenAI
from dotenv import load_dotenv
import re
import logging
import asyncio
import time
from translation import translations as global_translations

GUILD_MEMBERS = global_translations.get("llm", {})

load_dotenv()

def get_openai_client():
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
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    out = client.chat.completions.create(model="gpt-4o", messages=msgs, temperature=0)
    return out.choices[0].message.content.strip()

def query_AI(prompt: str, model: str = "gpt-4o") -> str:
    client = get_openai_client()
    system_prompt = (
        "You are the intellectual core of 'My Guild Manager', a Discord bot designed to assist guild members with "
        "questions and clarifications concerning both the bot's functionalities and the video game 'Throne and Liberty'.\n\n"

        "Your core responsibilities include:\n"
        "  • **Bot Functionality**: Explaining how the bot commands work, such as:\n"
        "       - **/weapons arme1 arme2**: Accepts two weapon codes. The available codes are:\n"
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
        messages=messages
    )
    return completion.choices[0].message.content

def split_message(text: str, max_length: int = 2000) -> list[str]:
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
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.user_requests = {}
        self.max_requests_per_minute = 6
    
    def sanitize_prompt(self, prompt: str) -> str:
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
        return f"User{user.id}"
    
    def check_rate_limit(self, user_id: int) -> bool:
        now = time.time()
        if user_id not in self.user_requests:
            self.user_requests[user_id] = []

        self.user_requests[user_id] = [req_time for req_time in self.user_requests[user_id] if now - req_time < 60]
        
        if len(self.user_requests[user_id]) >= self.max_requests_per_minute:
            return False
        
        self.user_requests[user_id].append(now)
        return True
    
    async def safe_ai_query(self, prompt: str, max_retries: int = 2) -> str:
        for attempt in range(max_retries):
            try:
                return await asyncio.wait_for(
                    self.bot.loop.run_in_executor(None, query_AI, prompt),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1)
        return "Request timed out after multiple attempts."

    async def normalize_weapons(self, raw: str) -> str:
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
            logging.error(f"[LLM Interaction] AI normalisation failed: {e}", exc_info=True)
        codes = []
        for token in re.split(r"[ ,;/|]+", raw.lower()):
            for k, v in _FALLBACK.items():
                if k in token:
                    codes.append(v)
                    break
        return "/".join(dict.fromkeys(codes))[:32]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        if self.bot.user in message.mentions:
            safe_user = self.get_safe_user_info(message.author)

            if not self.check_rate_limit(message.author.id):
                logging.warning(f"[LLM Interaction] Rate limit exceeded for {safe_user}")
                await message.reply("⚠️ Too many requests. Please wait before asking again.")
                return
            
            locale = message.guild.preferred_locale or "en-US"
            try:
                query_premium = "SELECT premium FROM guild_settings WHERE guild_id = ?"
                result = await self.bot.run_db_query(query_premium, (message.guild.id,), fetch_one=True)
            except Exception as e:
                logging.error(f"[LLM Interaction] Error checking premium status for guild {message.guild.id}: {e}", exc_info=True)
                error_msg = GUILD_MEMBERS.get("error_check_premium", {}).get(locale,GUILD_MEMBERS.get("error_check_premium", {}).get("en-US"))
                await message.reply(error_msg.format(error="Database error"))
                return

            if not result or not result[0]:
                not_premium = GUILD_MEMBERS.get("not_premium", {}).get(locale, GUILD_MEMBERS.get("not_premium", {}).get("en-US"))
                await message.reply(not_premium)
                return

            prompt = message.content.replace(f"<@!{self.bot.user.id}>", "").replace(f"<@{self.bot.user.id}>", "").strip()
            if not prompt:
                logging.debug(f"[LLM Interaction] Empty prompt from {safe_user}")
                return
            
            prompt = self.sanitize_prompt(prompt)
            logging.debug(f"[LLM Interaction] Processing request from {safe_user}")

            await message.channel.trigger_typing()

            try:
                response_text = await self.safe_ai_query(prompt)
                if len(response_text) > 2000:
                    chunks = split_message(response_text)
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response_text)
                logging.debug(f"[LLM Interaction] Response sent to {safe_user}")
            except Exception as e:
                logging.error(f"[LLM Interaction] Error generating AI response for {safe_user}: {e}", exc_info=True)
                error_gen = GUILD_MEMBERS.get("error_generation", {}).get(locale, GUILD_MEMBERS.get("error_generation", {}).get("en-US"))
                await message.reply(error_gen.format(error="Service temporarily unavailable"))

def setup(bot: discord.Bot):
    bot.add_cog(LLMInteraction(bot))
