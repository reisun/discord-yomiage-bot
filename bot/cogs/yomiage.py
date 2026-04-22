import asyncio
import io
import logging
import re
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.tts.voicevox import VoicevoxClient

logger = logging.getLogger(__name__)

MAX_READ_LENGTH = 100
URL_PATTERN = re.compile(r"https?://\S+")
CUSTOM_EMOJI_PATTERN = re.compile(r"<a?:\w+:\d+>")
SPOILER_PATTERN = re.compile(r"\|\|.+?\|\|")
CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
INLINE_CODE_PATTERN = re.compile(r"`[^`]+`")


def sanitize_text(text: str, guild: discord.Guild | None = None) -> str:
    text = CODE_BLOCK_PATTERN.sub("コード省略", text)
    text = INLINE_CODE_PATTERN.sub("コード", text)
    text = SPOILER_PATTERN.sub("ネタバレ", text)
    text = URL_PATTERN.sub("URL省略", text)
    text = CUSTOM_EMOJI_PATTERN.sub("", text)

    text = re.sub(r"<@!?(\d+)>", _replace_member_mention(guild), text)
    text = re.sub(r"<#(\d+)>", _replace_channel_mention(guild), text)
    text = re.sub(r"<@&(\d+)>", _replace_role_mention(guild), text)

    text = text.strip()
    if len(text) > MAX_READ_LENGTH:
        text = text[:MAX_READ_LENGTH] + "、以下省略"
    return text


def _replace_member_mention(guild: discord.Guild | None):
    def replacer(m: re.Match) -> str:
        if guild:
            member = guild.get_member(int(m.group(1)))
            if member:
                return f"{member.display_name}さん"
        return "だれかさん"
    return replacer


def _replace_channel_mention(guild: discord.Guild | None):
    def replacer(m: re.Match) -> str:
        if guild:
            ch = guild.get_channel(int(m.group(1)))
            if ch:
                return f"{ch.name}チャンネル"
        return "どこかのチャンネル"
    return replacer


def _replace_role_mention(guild: discord.Guild | None):
    def replacer(m: re.Match) -> str:
        if guild:
            role = guild.get_role(int(m.group(1)))
            if role:
                return f"{role.name}ロール"
        return "なんかのロール"
    return replacer


class YomiageCog(commands.Cog):
    def __init__(self, bot: commands.Bot, voicevox: VoicevoxClient, default_speaker: int):
        self.bot = bot
        self.voicevox = voicevox
        self.default_speaker = default_speaker
        self._guild_speakers: dict[int, int] = {}
        self._queue: asyncio.Queue[tuple[discord.VoiceClient, str, int]] = asyncio.Queue()
        self._player_task: asyncio.Task | None = None
        self._active_channels: dict[int, int] = {}

    async def cog_load(self):
        self._player_task = asyncio.create_task(self._player_loop())

    async def cog_unload(self):
        if self._player_task:
            self._player_task.cancel()
        await self.voicevox.close()

    def _get_speaker(self, guild_id: int) -> int:
        return self._guild_speakers.get(guild_id, self.default_speaker)

    async def _player_loop(self):
        while True:
            vc, text, speaker_id = await self._queue.get()
            try:
                if not vc.is_connected():
                    continue
                audio_buf = await self.voicevox.synthesize(text, speaker_id)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(audio_buf.read())
                    tmp_path = tmp.name

                source = discord.FFmpegPCMAudio(tmp_path)
                done = asyncio.Event()
                vc.play(source, after=lambda e: done.set())
                await done.wait()

                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                logger.exception("Failed to play audio")
            finally:
                self._queue.task_done()

    @app_commands.command(name="yo_join", description="音声チャンネルに参加して読み上げを開始します")
    async def yo_join(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "先に音声チャンネルに参加してください！", ephemeral=True
            )
            return

        voice_channel = interaction.user.voice.channel

        if interaction.guild.voice_client:
            await interaction.guild.voice_client.move_to(voice_channel)
        else:
            await voice_channel.connect()

        self._active_channels[interaction.guild_id] = interaction.channel_id

        await interaction.response.send_message(
            f"🔊 {voice_channel.name} に参加しました！このチャンネルのメッセージを読み上げます。"
        )

    @app_commands.command(name="yo_leave", description="音声チャンネルから退出します")
    async def yo_leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message(
                "どの音声チャンネルにも参加していません。", ephemeral=True
            )
            return

        self._active_channels.pop(interaction.guild_id, None)
        await vc.disconnect()
        await interaction.response.send_message("👋 退出しました。")

    @app_commands.command(name="yo_voice", description="読み上げボイスを変更します")
    @app_commands.describe(speaker_id="VOICEVOXのspeaker ID（例: 3=ずんだもん）")
    async def yo_voice(self, interaction: discord.Interaction, speaker_id: int):
        self._guild_speakers[interaction.guild_id] = speaker_id
        await interaction.response.send_message(
            f"🎤 読み上げボイスを speaker_id={speaker_id} に変更しました。"
        )

    @app_commands.command(name="yo_speakers", description="利用可能なボイス一覧を表示します")
    async def yo_speakers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            speakers = await self.voicevox.get_speakers()
            lines = []
            for sp in speakers:
                for style in sp.get("styles", []):
                    lines.append(f"**{sp['name']}** ({style['name']}) — ID: `{style['id']}`")
            text = "\n".join(lines[:50])
            if len(lines) > 50:
                text += f"\n...他 {len(lines) - 50} 件"
            await interaction.followup.send(text, ephemeral=True)
        except Exception:
            logger.exception("Failed to fetch speakers")
            await interaction.followup.send(
                "ボイス一覧の取得に失敗しました。VOICEVOX Engineが起動しているか確認してください。",
                ephemeral=True,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        active_text_channel = self._active_channels.get(message.guild.id)
        if active_text_channel != message.channel.id:
            return

        vc = message.guild.voice_client
        if not vc or not vc.is_connected():
            return

        text = sanitize_text(message.content, message.guild)
        if not text:
            return

        speaker_id = self._get_speaker(message.guild.id)
        await self._queue.put((vc, text, speaker_id))


async def setup(bot: commands.Bot, voicevox: VoicevoxClient, default_speaker: int):
    await bot.add_cog(YomiageCog(bot, voicevox, default_speaker))
