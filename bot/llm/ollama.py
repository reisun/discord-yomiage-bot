import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=2)

_PROMPT_TEMPLATE = (
    "/no_think\n"
    "以下のテキストの雰囲気に最も合う話し方を、選択肢から1つだけ選んでください。\n"
    "選択肢以外の文字は出力しないでください。\n\n"
    "選択肢: {styles}\n"
    "テキスト: {text}\n\n"
    "回答:"
)


class OllamaClient:
    def __init__(self, host: str | None = None):
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://ollama:11434")).rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def infer_style(self, text: str, style_names: list[str]) -> str | None:
        """Infer the best speaking style for the given text.

        Returns one of *style_names* or ``None`` on any failure.
        """
        if not style_names:
            return None

        prompt = _PROMPT_TEMPLATE.format(
            styles="、".join(style_names),
            text=text,
        )

        try:
            session = await self._get_session()
            async with session.post(
                f"{self.host}/api/generate",
                json={"model": "llama3.2:1b", "prompt": prompt, "stream": False},
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

            response_text = data.get("response", "").strip()
            for name in style_names:
                if name in response_text:
                    return name

            logger.debug("LLM response did not match any style: %r", response_text)
            return None

        except Exception:
            logger.debug("LLM infer_style failed", exc_info=True)
            return None
