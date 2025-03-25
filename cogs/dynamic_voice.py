import discord
import logging
from discord.ext import commands
import asyncio
from functions import get_user_message

class DynamicVoice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dynamic_channels = set()
        self.create_room_channels = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # Lancer la tâche asynchrone pour charger les salons surveillés depuis la DB
        asyncio.create_task(self.load_create_room_channels())
        logging.debug("[DynamicVoice] Tâche load_create_room_channels lancée depuis on_ready")
        # Charger les salons dynamiques persistants
        asyncio.create_task(self.load_persistent_channels())
        logging.debug("[DynamicVoice] Tâche load_persistent_channels lancée depuis cog_load")

    async def load_create_room_channels(self):
        logging.debug("[DynamicVoice] Début de load_create_room_channels")
        query = "SELECT guild_id, create_room_channel FROM guild_channels;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                guild_id, channel_id = row
                if guild_id not in self.create_room_channels:
                    self.create_room_channels[guild_id] = set()
                self.create_room_channels[guild_id].add(channel_id)
            logging.debug(f"[DynamicVoice] Salons de création surveillés chargés depuis la DB : {self.create_room_channels}")
        except Exception as e:
            logging.error(f"[DynamicVoice] Erreur lors du chargement des salons depuis la DB : {e}")

    async def load_persistent_channels(self):
        logging.debug("[DynamicVoice] Chargement des salons dynamiques persistants depuis la DB")
        query = "SELECT channel_id FROM dynamic_voice_channels;"
        try:
            rows = await self.bot.run_db_query(query, fetch_all=True)
            for row in rows:
                channel_id = row[0]
                self.dynamic_channels.add(channel_id)
            logging.debug(f"[DynamicVoice] Salons dynamiques chargés depuis la DB : {self.dynamic_channels}")
        except Exception as e:
            logging.error(f"[DynamicVoice] Erreur lors du chargement des salons persistants : {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        monitored_channels = self.create_room_channels.get(guild.id, set())
        logging.debug(f"[DynamicVoice] on_voice_state_update: {member.name} - Before: {before.channel.id if before.channel else None}, After: {after.channel.id if after.channel else None}")
        logging.debug(f"[DynamicVoice] Salons surveillés pour la guilde {guild.id}: {monitored_channels}")

        if after.channel and after.channel.id in monitored_channels:
            logging.debug(f"[DynamicVoice] {member.name} a rejoint le salon surveillé {after.channel.id}. Préparation de la création du salon temporaire.")

            # Récupération de la langue de la guilde depuis la DB
            query = """
            SELECT gs.guild_lang, gr.members, gr.absent_members
            FROM guild_settings gs
            LEFT JOIN guild_roles gr ON gs.guild_id = gr.guild_id
            WHERE gs.guild_id = ?
            """
            result = await self.bot.run_db_query(query, (guild.id,), fetch_one=True)
            if result:
                guild_lang, role_members_id, role_absent_members_id = result
            else:
                guild_lang = "en-US"
                role_members_id = role_absent_members_id = None
            
            # Récupération du template depuis le JSON des traductions
            room_name_template = self.bot.translations.get("dynamic_voice", {}).get(guild_lang, "Channel of {username}")
            channel_name = room_name_template.format(username=member.display_name)
            logging.debug(f"[DynamicVoice] Nom de canal obtenu via JSON : '{channel_name}'")
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                member: discord.PermissionOverwrite(manage_channels=True, mute_members=True, deafen_members=True)
            }
            if role_members_id:
                role_members = guild.get_role(role_members_id)
                if role_members:
                    overwrites[role_members] = discord.PermissionOverwrite(view_channel=True, connect=True)
            if role_absent_members_id:
                role_absent = guild.get_role(role_absent_members_id)
                if role_absent:
                    overwrites[role_absent] = discord.PermissionOverwrite(view_channel=True, connect=True)
            try:
                await asyncio.sleep(0.2)
                logging.debug(f"[DynamicVoice] Tentative de création du salon temporaire pour {member.name} avec le nom '{channel_name}'")
                new_channel = await asyncio.wait_for(
                    guild.create_voice_channel(
                        name=channel_name,
                        category=after.channel.category,
                        overwrites=overwrites
                    ),
                    timeout=10
                )
                logging.debug(f"[DynamicVoice] Salon temporaire créé : {new_channel.name} (ID: {new_channel.id})")
                await member.move_to(new_channel)
                self.dynamic_channels.add(new_channel.id)
                # Insertion en base pour persister le salon dynamique
                query_insert = "INSERT INTO dynamic_voice_channels (channel_id, guild_id) VALUES (?, ?)"
                await self.bot.run_db_query(query_insert, (new_channel.id, guild.id), commit=True)
                logging.debug(f"[DynamicVoice] Salon persistant enregistré en DB pour {member.name}")
            except asyncio.TimeoutError:
                logging.error(f"[DynamicVoice] Timeout lors de la création du salon pour {member.name}")
            except Exception as e:
                logging.error(f"[DynamicVoice] Erreur lors de la création du salon pour {member.name} : {e}")

        # Suppression du salon dynamique lorsqu'il est vide
        if before.channel and before.channel.id in self.dynamic_channels:
            channel = before.channel
            if len(channel.members) == 0:
                try:
                    await channel.delete()
                    self.dynamic_channels.remove(channel.id)
                    logging.debug(f"[DynamicVoice] Salon vocal supprimé : {channel.name} (ID: {channel.id})")
                    # Suppression de l'enregistrement en DB
                    query_delete = "DELETE FROM dynamic_voice_channels WHERE channel_id = ?"
                    await self.bot.run_db_query(query_delete, (channel.id,), commit=True)
                    logging.debug(f"[DynamicVoice] Enregistrement supprimé de la DB pour le salon {channel.id}")
                except discord.Forbidden:
                    logging.error(f"[DynamicVoice] Permissions insuffisantes pour supprimer {channel.name}.")
                except Exception as e:
                    logging.error(f"[DynamicVoice] Erreur lors de la suppression de {channel.name} : {e}")

def setup(bot: discord.Bot):
    bot.add_cog(DynamicVoice(bot))