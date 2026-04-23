import logging
import os

import discord
from discord.ext import commands

from bot.cogs.yomiage import setup as setup_yomiage
from bot.tts.voicevox import VoicevoxClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
VOICEVOX_HOST = os.environ.get("VOICEVOX_HOST", "http://voicevox-engine:50021")
DEFAULT_SPEAKER_ID = int(os.environ.get("DEFAULT_SPEAKER_ID", "3"))

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
voicevox = VoicevoxClient(host=VOICEVOX_HOST)


@bot.event
async def on_ready():
    await setup_yomiage(bot, voicevox, DEFAULT_SPEAKER_ID)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    for guild in bot.guilds:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    logger.info("Bot ready as %s — synced commands to %d guilds", bot.user, len(bot.guilds))


def main():
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
