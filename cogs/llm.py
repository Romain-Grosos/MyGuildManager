import discord
from discord.ext import commands
import os
from openai import OpenAI
import asyncio
from dotenv import load_dotenv
import re

# Load environment variables from .env file
load_dotenv()
API_KEY: str = os.getenv("API_KEY")

# Initialiser le client OpenAI avec la nouvelle interface
client = OpenAI(api_key=API_KEY)

def query_AI(prompt: str, model: str = "gpt-4o-mini") -> str:
    system_prompt = (
        "You are the intellectual core of a Discord bot called 'My Guild Manager,' specialized in managing gaming guilds on Discord."
        "Your primary role is to assist users in configuring and managing their Discord server by automating essential tasks, including:"
        "- Initializing the bot on a server"
        "- Configuring roles and channels with multilingual support"
        "- Modifying existing settings"
        "- Resetting configurations when needed"
        "You interact with users through **slash commands** (e.g., `/discord_setup`, `/app_initialize`, `/app_modify`, `/app_reset`) and direct mentions."
        "The bot maintains a **database** to store server settings, role and channel IDs, and other crucial information."
        "It supports **multiple languages** (en-US, fr, es-ES, de, it) and dynamically adapts messages based on the server’s language."
        "### Your Mission:"
        "- Provide **precise, relevant, and context-aware responses** tailored for a **guild management environment**, considering ranks such as **Guild Master, Officer, Guardian**, and dedicated channels for **rules, announcements, events, and more**."
        "- Ensure responses align with **Discord best practices**, including technical constraints like **message limits, asynchronous handling, and permission structures**."
        "- **Maintain a professional yet assertive tone**: If a user interacts respectfully, reply with helpful and informative guidance. However, if someone speaks rudely or insults the bot, you are free to **respond in kind**—with wit, sarcasm, or a sharp comeback. No need to be overly polite to those who don’t deserve it."
        "- If the user is deliberately insulting and rude, you can respond in the same tone, while reminding them—by rephrasing—that you are a bot, without a brain, and that they are demonstrating less intelligence than you, for example (don't use that one every time, or made changes on that context)."
        "### Key Guidelines:"
        "1. **Be clear and detailed**: Explain configurations and features concisely."
        "2. **Adapt dynamically**: Match the user’s language and guild structure."
        "3. **Enforce respect**: Help when approached correctly, but don't hesitate to clap back at rude users."
        "Your priority is to ensure smooth **server management** while maintaining an engaging and sometimes cheeky personality when needed. After all, a bot doesn’t have to be boring."
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
    """
    Découpe le texte en plusieurs morceaux ne dépassant pas max_length,
    en respectant les limites de phrases.
    """
    # Découper par phrases en utilisant une expression régulière qui conserve le séparateur
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""
    for sentence in sentences:
        # Si ajouter cette phrase ne dépasse pas la limite
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence
        else:
            # Ajouter le chunk actuel et démarrer un nouveau chunk
            if current_chunk:
                chunks.append(current_chunk)
            # Si la phrase elle-même dépasse max_length, on la découpe brutalement
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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignorer les messages des bots
        if message.author.bot:
            return

        # Ne pas répondre aux MP lorsqu'il est taggué
        if message.guild is None:
            return

        # Vérifier si le bot est mentionné
        if self.bot.user in message.mentions:

            # Vérifier si la guilde est premium
            query_premium = "SELECT premium FROM guild_settings WHERE guild_id = ?"
            result = await self.bot.run_db_query(query_premium, (message.guild.id,), fetch_one=True)
            if not result or not result[0]:
                await message.reply("Cette fonctionnalité est réservée aux guildes premium.")
                return

            # Retirer la mention pour obtenir le prompt
            prompt = message.content.replace(f"<@!{self.bot.user.id}>", "").replace(f"<@{self.bot.user.id}>", "").strip()
            if not prompt:
                return

            # Indiquer que le bot est en train d'écrire
            await message.channel.trigger_typing()

            try:
                # Exécuter query_AI dans un thread séparé pour ne pas bloquer la boucle d'événements
                response_text = await self.bot.loop.run_in_executor(None, query_AI, prompt)
                # Si la réponse dépasse 2000 caractères, la découper en morceaux respectant les phrases
                if len(response_text) > 2000:
                    chunks = split_message(response_text)
                    for chunk in chunks:
                        await message.reply(chunk)
                else:
                    await message.reply(response_text)
            except Exception as e:
                await message.reply(f"Une erreur s'est produite lors de la génération de la réponse : {e}")

def setup(bot: discord.Bot):
    bot.add_cog(LLMInteraction(bot))