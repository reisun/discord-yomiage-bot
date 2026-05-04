import asyncio
import logging
import re
import tempfile
from pathlib import Path

import alkana
import discord
from discord import app_commands
from discord.ext import commands

from bot.llm.ollama import OllamaClient
from bot.tts.voicevox import VoicevoxClient

logger = logging.getLogger(__name__)

MAX_READ_LENGTH = 100
URL_PATTERN = re.compile(r"https?://\S+")
CUSTOM_EMOJI_PATTERN = re.compile(r"<a?:\w+:\d+>")
SPOILER_PATTERN = re.compile(r"\|\|.+?\|\|")
CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
INLINE_CODE_PATTERN = re.compile(r"`[^`]+`")
ENGLISH_PHRASE_PATTERN = re.compile(r"[a-zA-Z]+(?:\s+[a-zA-Z]+)*")


def _english_phrase_to_kana(match: re.Match) -> str:
    words = match.group(0).split()
    return "".join(alkana.get_kana(w.lower()) or w for w in words)


def sanitize_text(text: str, guild: discord.Guild | None = None) -> str:
    text = CODE_BLOCK_PATTERN.sub("コード省略", text)
    text = INLINE_CODE_PATTERN.sub("コード", text)
    text = SPOILER_PATTERN.sub("ネタバレ", text)
    text = URL_PATTERN.sub("URL省略", text)
    text = CUSTOM_EMOJI_PATTERN.sub("", text)

    text = re.sub(r"<@!?(\d+)>", _replace_member_mention(guild), text)
    text = re.sub(r"<#(\d+)>", _replace_channel_mention(guild), text)
    text = re.sub(r"<@&(\d+)>", _replace_role_mention(guild), text)

    text = ENGLISH_PHRASE_PATTERN.sub(_english_phrase_to_kana, text)

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
    def __init__(
        self,
        bot: commands.Bot,
        voicevox: VoicevoxClient,
        ollama: OllamaClient,
        default_speaker: int,
    ):
        self.bot = bot
        self.voicevox = voicevox
        self.ollama = ollama
        self.default_speaker = default_speaker
        # guild_id -> user_id -> voice_name
        self._user_voice: dict[int, dict[int, str]] = {}
        # guild_id -> user_id -> style_name (None = auto)
        self._user_style: dict[int, dict[int, str | None]] = {}
        self._queue: asyncio.Queue[tuple[discord.VoiceClient, str, int]] = asyncio.Queue()
        self._player_task: asyncio.Task | None = None
        self._active_channels: dict[int, int] = {}
        self._speakers_cache: list[dict] | None = None

    async def _fetch_speakers(self) -> list[dict]:
        if self._speakers_cache is None:
            self._speakers_cache = await self.voicevox.get_speakers()
        return self._speakers_cache

    def _default_voice_name(self, speakers: list[dict]) -> str:
        """Return the voice name that owns *self.default_speaker*."""
        for sp in speakers:
            for st in sp.get("styles", []):
                if st["id"] == self.default_speaker:
                    return sp["name"]
        return speakers[0]["name"] if speakers else ""

    @staticmethod
    def _find_speaker_id(
        speakers: list[dict], voice_name: str, style_name: str,
    ) -> int | None:
        for sp in speakers:
            if sp["name"] == voice_name:
                for st in sp.get("styles", []):
                    if st["name"] == style_name:
                        return st["id"]
        return None

    @staticmethod
    def _fallback_speaker_id(speakers: list[dict], voice_name: str) -> int | None:
        """Return the 'normal' style id for *voice_name*, or the first style."""
        for sp in speakers:
            if sp["name"] == voice_name:
                styles = sp.get("styles", [])
                if not styles:
                    return None
                for st in styles:
                    if st["name"] == "ノーマル":
                        return st["id"]
                return styles[0]["id"]
        return None

    async def _get_speaker(self, guild_id: int, user_id: int, text: str) -> int:
        speakers = await self._fetch_speakers()
        if not speakers:
            return self.default_speaker

        voice_name = self._user_voice.get(guild_id, {}).get(
            user_id, self._default_voice_name(speakers),
        )
        style = self._user_style.get(guild_id, {}).get(user_id)  # None = auto

        # Explicit style
        if style is not None:
            sid = self._find_speaker_id(speakers, voice_name, style)
            if sid is not None:
                return sid
            return self.default_speaker

        # Auto style
        for sp in speakers:
            if sp["name"] == voice_name:
                styles = sp.get("styles", [])
                if len(styles) == 1:
                    return styles[0]["id"]

                non_normal = [st["name"] for st in styles if st["name"] != "ノーマル"]
                if not non_normal:
                    return styles[0]["id"]

                inferred = await self.ollama.infer_style(text, non_normal)
                if inferred:
                    sid = self._find_speaker_id(speakers, voice_name, inferred)
                    if sid is not None:
                        logger.info("Auto style: %s -> %s (id=%d) text=%r", voice_name, inferred, sid, text)
                        return sid

                # Fallback
                fallback = self._fallback_speaker_id(speakers, voice_name) or self.default_speaker
                logger.info("Auto style fallback: %s -> id=%d text=%r", voice_name, fallback, text)
                return fallback

        return self.default_speaker

    async def cog_load(self):
        self._player_task = asyncio.create_task(self._player_loop())

    async def cog_unload(self):
        if self._player_task:
            self._player_task.cancel()
        await self.voicevox.close()
        await self.ollama.close()

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
        if isinstance(interaction.channel, discord.VoiceChannel):
            voice_channel = interaction.channel
        elif interaction.user.voice and interaction.user.voice.channel:
            voice_channel = interaction.user.voice.channel
        else:
            await interaction.response.send_message(
                "音声チャンネルのチャットから実行するか、音声チャンネルに参加してください！",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            if interaction.guild.voice_client:
                await interaction.guild.voice_client.move_to(voice_channel)
            else:
                await voice_channel.connect(timeout=30, self_deaf=True)

            self._active_channels[interaction.guild_id] = interaction.channel_id


            await interaction.followup.send(
                f"🔊 {voice_channel.name} に参加しました！このチャンネルのメッセージを読み上げます。"
            )
        except Exception:
            logger.exception("Failed to join voice channel")
            await interaction.followup.send(
                "音声チャンネルへの接続に失敗しました。もう一度試してください。",
                ephemeral=True,
            )

    @app_commands.command(name="yo_leave", description="音声チャンネルから退出します")
    async def yo_leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message(
                "どの音声チャンネルにも参加していません。", ephemeral=True
            )
            return

        await interaction.response.defer()
        self._active_channels.pop(interaction.guild_id, None)
        await vc.disconnect()
        await interaction.followup.send("👋 退出しました。")

    @app_commands.command(name="yo_voice", description="自分の読み上げボイスを変更します")
    @app_commands.describe(voice="ボイス名", style="話し方（「自動」でLLMが自動選択）")
    async def yo_voice(self, interaction: discord.Interaction, voice: str, style: str):
        try:
            speakers = await self._fetch_speakers()
        except Exception:
            await interaction.response.send_message(
                "ボイス情報の取得に失敗しました。", ephemeral=True
            )
            return

        # Validate voice name exists
        voice_found = False
        for sp in speakers:
            if sp["name"] == voice:
                voice_found = True
                break
        if not voice_found:
            await interaction.response.send_message(
                f"「{voice}」が見つかりませんでした。", ephemeral=True
            )
            return

        if style == "自動":
            self._user_voice.setdefault(interaction.guild_id, {})[interaction.user.id] = voice
            self._user_style.setdefault(interaction.guild_id, {})[interaction.user.id] = None
            await interaction.response.send_message(
                f"🎤 {interaction.user.display_name} のボイスを **{voice}**（自動）に変更しました。"
            )
            return

        for sp in speakers:
            if sp["name"] == voice:
                for st in sp.get("styles", []):
                    if st["name"] == style:
                        self._user_voice.setdefault(interaction.guild_id, {})[interaction.user.id] = voice
                        self._user_style.setdefault(interaction.guild_id, {})[interaction.user.id] = style
                        await interaction.response.send_message(
                            f"🎤 {interaction.user.display_name} のボイスを **{voice}**（{style}）に変更しました。"
                        )
                        return

        await interaction.response.send_message(
            f"「{voice}」の「{style}」が見つかりませんでした。", ephemeral=True
        )

    @yo_voice.autocomplete("voice")
    async def _voice_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            speakers = await self._fetch_speakers()
        except Exception:
            return []
        names: list[str] = []
        seen: set[str] = set()
        for sp in speakers:
            if sp["name"] not in seen:
                seen.add(sp["name"])
                names.append(sp["name"])
        if current:
            names = [n for n in names if current.lower() in n.lower()]
        return [app_commands.Choice(name=n, value=n) for n in names[:25]]

    @yo_voice.autocomplete("style")
    async def _style_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            speakers = await self._fetch_speakers()
        except Exception:
            return []
        voice_value = interaction.namespace.voice
        styles: list[str] = ["自動"]
        if voice_value:
            for sp in speakers:
                if sp["name"] == voice_value:
                    styles += [st["name"] for st in sp.get("styles", [])]
                    break
        else:
            seen: set[str] = set()
            for sp in speakers:
                for st in sp.get("styles", []):
                    if st["name"] not in seen:
                        seen.add(st["name"])
                        styles.append(st["name"])
        if current:
            styles = [s for s in styles if current.lower() in s.lower()]
        return [app_commands.Choice(name=s, value=s) for s in styles[:25]]

    @app_commands.command(name="yo_speakers", description="利用可能なボイス一覧を表示します")
    async def yo_speakers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            speakers = await self._fetch_speakers()
            lines = []
            for sp in speakers:
                styles = sp.get("styles", [])
                style_names = "、".join(st["name"] for st in styles)
                lines.append(f"🎤 **{sp['name']}**\n　　話し方: {style_names}")
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

        speaker_id = await self._get_speaker(message.guild.id, message.author.id, text)
        await self._queue.put((vc, text, speaker_id))

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        vc = member.guild.voice_client
        if not vc or not vc.is_connected():
            return

        # Bot以外が誰もいなくなったら自動退出
        members = [m for m in vc.channel.members if not m.bot]
        if not members:
            self._active_channels.pop(member.guild.id, None)
            await vc.disconnect()
            logger.info("Auto-disconnected from %s (no members left)", vc.channel.name)


async def setup(
    bot: commands.Bot,
    voicevox: VoicevoxClient,
    ollama: OllamaClient,
    default_speaker: int,
):
    await bot.add_cog(YomiageCog(bot, voicevox, ollama, default_speaker))
