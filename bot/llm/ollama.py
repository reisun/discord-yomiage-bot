import asyncio
import logging
import os
import random
import re
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=2)
_KEEP_ALIVE = "10m"
_KEEPALIVE_INTERVAL = 4 * 60
_NUMBER_RE = re.compile(r"\d+")

_PROMPT_TEMPLATE = (
    "{prefix}"
    "Classify the emotion of the following Japanese text.\n"
    "Reply with ONLY the number. Do not add any other text.\n\n"
    "{choices}\n\n"
    "Text: {text}\n"
    "Number:"
)


@dataclass(frozen=True)
class ModelConfig:
    num_predict: int = 4
    prompt_prefix: str = ""
    extra_params: dict = field(default_factory=dict)


_MODEL_CONFIGS: dict[str, ModelConfig] = {
    "llama3.2": ModelConfig(
        prompt_prefix="/no_think\n",
    ),
    "llama3.1": ModelConfig(
        num_predict=8,
    ),
    "qwen3": ModelConfig(
        extra_params={"think": False},
    ),
}


def _get_model_config(model_name: str) -> ModelConfig:
    for prefix, config in _MODEL_CONFIGS.items():
        if model_name.startswith(prefix):
            return config
    return ModelConfig()


_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:2b")
_CONFIG = _get_model_config(_MODEL)

_STYLE_TO_ENGLISH: dict[str, str] = {
    "あまあま": "sweet / affectionate / flirting",
    "うきうき": "excited / looking forward to something",
    "おこ": "mildly annoyed / pouting",
    "おちつき": "calm / serious / thoughtful",
    "おどおど": "anxious / uncertain / apologizing",
    "おどろき": "shocked / surprised / disbelief",
    "かなしい": "sad / disappointed / lonely",
    "かなしみ": "deep sadness / mourning / loss",
    "こわがり": "scared / worried / something bad might happen",
    "ささやき": "secret / quiet / gentle confession",
    "しっとり": "gentle / tender / sentimental",
    "たのしい": "having fun / playful / joking",
    "なみだめ": "holding back tears / moved / touched",
    "ぬいぐるみver.": "cute / innocent / childlike wonder",
    "のんびり": "relaxed / lazy / not in a hurry",
    "びえーん": "bawling / overwhelmed / tantrum",
    "びくびく": "startled / paranoid / on edge",
    "ふつう": "neutral / normal",
    "ぶりっ子": "acting cute / begging / pleading",
    "へろへろ": "exhausted / sleepy / giving up",
    "わーい": "celebrating / cheering / great news",
    "アナウンス": "formal / informing / reporting facts",
    "クイーン": "proud / confident / commanding",
    "セクシー": "teasing / suggestive / charming",
    "セクシー／あん子": "teasing / suggestive / charming",
    "ツンギレ": "snapping / fed up / explosive anger",
    "ツンツン": "cold / sarcastic / refusing",
    "ノーマル": "neutral / normal",
    "ヒソヒソ": "gossiping / secret / conspiring",
    "ヘロヘロ": "exhausted / drained / giving up",
    "ボーイ": "bold / adventurous / daring",
    "ロリ": "innocent / childlike / naive",
    "不機嫌": "grumpy / irritated / complaining",
    "人見知り": "shy / embarrassed / meeting someone new",
    "人間ver.": "natural / conversational / everyday",
    "人間（怒り）ver.": "genuinely angry / confrontational",
    "低血圧": "drowsy / just woke up / half-asleep",
    "元気": "energetic / hyped / motivated",
    "内緒話": "telling a secret / private / confidential",
    "喜び": "happy / grateful / pleased",
    "囁き": "whispering / intimate / soft",
    "実況風": "narrating action / describing events live",
    "怒り": "angry / furious / outraged",
    "恐怖": "terrified / horror / panic",
    "悲しみ": "sorrowful / heartbroken / regretful",
    "楽々": "carefree / easy-going / no worries",
    "泣き": "crying / sobbing / emotional breakdown",
    "熱血": "passionate / fired up / inspiring speech",
    "第二形態": "intense / powered up / dramatic moment",
    "絶望と敗北": "hopeless / defeated / given up completely",
    "覚醒": "determined / resolved / awakening to truth",
    "読み聞かせ": "storytelling / explaining / teaching",
    "鬼ver.": "fierce / threatening / intimidating",
}


def _style_label(style_name: str) -> str:
    return _STYLE_TO_ENGLISH.get(style_name, style_name)


class OllamaClient:
    def __init__(self, host: str | None = None):
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://llm-internal-proxy/llm")).rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._keepalive_task: asyncio.Task | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        return self._session

    async def warmup(self):
        try:
            session = await self._get_session()
            async with session.post(
                f"{self.host}/api/generate",
                json={"model": _MODEL, "prompt": "hi", "stream": False, "keep_alive": _KEEP_ALIVE, **_CONFIG.extra_params},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
            logger.info("Ollama warmup complete (model=%s, config=%s)", _MODEL, _CONFIG)
        except Exception:
            logger.warning("Ollama warmup failed", exc_info=True)
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _keepalive_loop(self):
        while True:
            await asyncio.sleep(_KEEPALIVE_INTERVAL)
            try:
                session = await self._get_session()
                async with session.post(
                    f"{self.host}/api/generate",
                    json={"model": _MODEL, "prompt": "", "stream": False, "keep_alive": _KEEP_ALIVE, **_CONFIG.extra_params},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                logger.info("Ollama keepalive sent")
            except Exception:
                logger.warning("Ollama keepalive failed", exc_info=True)

    async def close(self):
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._session and not self._session.closed:
            await self._session.close()

    async def infer_style(self, text: str, style_names: list[str]) -> str | None:
        if not style_names:
            return None

        shuffled = list(style_names)
        random.shuffle(shuffled)

        choices = "\n".join(
            f"{i+1}. {_style_label(name)}" for i, name in enumerate(shuffled)
        )
        prompt = _PROMPT_TEMPLATE.format(
            prefix=_CONFIG.prompt_prefix,
            choices=choices,
            text=text,
        )

        try:
            session = await self._get_session()
            payload = {
                "model": _MODEL,
                "prompt": prompt,
                "stream": False,
                "keep_alive": _KEEP_ALIVE,
                "options": {"num_predict": _CONFIG.num_predict},
                **_CONFIG.extra_params,
            }
            async with session.post(
                f"{self.host}/api/generate",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

            response_text = data.get("response", "").strip()

            m = _NUMBER_RE.search(response_text)
            if m:
                idx = int(m.group()) - 1
                if 0 <= idx < len(shuffled):
                    logger.info("LLM inferred style %r (response=%r)", shuffled[idx], response_text)
                    return shuffled[idx]

            logger.warning("LLM response did not match: %r (candidates: %s)", response_text, style_names)
            return None

        except Exception:
            logger.warning("LLM infer_style failed", exc_info=True)
            return None
