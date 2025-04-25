import discord
from discord.ext import commands
import os
from openai import OpenAI
from dotenv import load_dotenv
import re
import logging
from translation import translations as global_translations

GUILD_MEMBERS = global_translations.get("llm", {})

load_dotenv()
API_KEY: str = os.getenv("API_KEY")
client = OpenAI(api_key=API_KEY)

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
    system = (
        "You convert weapon lists for the game Throne and Liberty.\n"
        "Return only the codes (B, CB, DG, GS, S, SNS, SP, W) separated by '/'.\n"
        "Ignore unknown weapons."
    )
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    out = client.chat.completions.create(model="gpt-4o", messages=msgs, temperature=0)
    return out.choices[0].message.content.strip()

def query_AI(prompt: str, model: str = "gpt-4o") -> str:
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

    async def normalize_weapons(self, raw: str) -> str:
        try:
            ai_out = await self.bot.loop.run_in_executor(None, _ask_ai, f"Input: {raw}")
            codes = re.findall(r"\b(?:B|CB|DG|GS|S|SNS|SP|W)\b", ai_out.upper())
            if codes:
                return "/".join(dict.fromkeys(codes))[:32]
        except Exception:
            logging.error("[LLM Interaction] AI normalisation failed", exc_info=True)
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
            locale = message.guild.preferred_locale or "en-US"
            try:
                query_premium = "SELECT premium FROM guild_settings WHERE guild_id = ?"
                result = await self.bot.run_db_query(query_premium, (message.guild.id,), fetch_one=True)
            except Exception as e:
                logging.error("[LLM Interaction] Error checking premium status", exc_info=True)
                error_msg = GUILD_MEMBERS.get("error_check_premium", {}).get(locale,GUILD_MEMBERS.get("error_check_premium", {}).get("en-US"))
                await message.reply(error_msg.format(error=e))
                return

            if not result or not result[0]:
                not_premium = GUILD_MEMBERS.get("not_premium", {}).get(locale, GUILD_MEMBERS.get("not_premium", {}).get("en-US"))
                await message.reply(not_premium)
                return

            prompt = message.content.replace(f"<@!{self.bot.user.id}>", "").replace(f"<@{self.bot.user.id}>", "").strip()
            if not prompt:
                logging.debug("[LLM Interaction] Received mention, but prompt is empty after removing bot mentions.")
                return

            await message.channel.trigger_typing()

            try:
                response_text = await self.bot.loop.run_in_executor(None, query_AI, prompt)
                if len(response_text) > 2000:
                    chunks = split_message(response_text)
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response_text)
            except Exception as e:
                logging.error("[LLM Interaction] Error generating AI response", exc_info=True)
                error_gen = GUILD_MEMBERS.get("error_generation", {}).get(locale, GUILD_MEMBERS.get("error_generation", {}).get("en-US"))
                await message.reply(error_gen.format(error=e))

def setup(bot: discord.Bot):
    bot.add_cog(LLMInteraction(bot))
