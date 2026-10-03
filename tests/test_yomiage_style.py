import unittest
from unittest.mock import AsyncMock, Mock

from bot.cogs.yomiage import YomiageCog


class ReadingStyleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ollama = Mock()
        self.ollama.infer_style = AsyncMock(return_value="ノーマル")
        self.voicevox = Mock()
        self.voicevox.get_speakers = AsyncMock(return_value=[{
            "name": "ずんだもん",
            "styles": [{"name": "ノーマル", "id": 3}, {"name": "あまあま", "id": 1}],
        }])
        self.cog = YomiageCog(Mock(), self.voicevox, self.ollama, 3)

    async def test_neutral_can_be_chosen_automatically(self):
        self.assertEqual(await self.cog._get_speaker(1, 2, "明日は九時集合です"), 3)
        self.ollama.infer_style.assert_awaited_once_with("明日は九時集合です", ["ノーマル", "あまあま"])

    async def test_failed_inference_uses_normal_style(self):
        self.ollama.infer_style.return_value = None
        self.assertEqual(await self.cog._get_speaker(1, 2, "文章"), 3)

    async def test_explicit_style_skips_inference(self):
        self.cog._user_style = {1: {2: "あまあま"}}
        self.assertEqual(await self.cog._get_speaker(1, 2, "文章"), 1)
        self.ollama.infer_style.assert_not_awaited()

    async def test_voice_without_styles_uses_default(self):
        self.voicevox.get_speakers.return_value = [{"name": "ずんだもん", "styles": []}]
        self.assertEqual(await self.cog._get_speaker(1, 2, "文章"), 3)
        self.ollama.infer_style.assert_not_awaited()
