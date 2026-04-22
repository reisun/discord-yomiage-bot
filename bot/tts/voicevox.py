import io

import aiohttp


class VoicevoxClient:
    def __init__(self, host: str = "http://voicevox-engine:50021"):
        self.host = host.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def synthesize(self, text: str, speaker_id: int = 3) -> io.BytesIO:
        session = await self._get_session()

        async with session.post(
            f"{self.host}/audio_query",
            params={"text": text, "speaker": speaker_id},
        ) as resp:
            resp.raise_for_status()
            query = await resp.json()

        query["speedScale"] = 1.2

        async with session.post(
            f"{self.host}/synthesis",
            params={"speaker": speaker_id},
            json=query,
        ) as resp:
            resp.raise_for_status()
            audio = await resp.read()

        buf = io.BytesIO(audio)
        buf.seek(0)
        return buf

    async def get_speakers(self) -> list[dict]:
        session = await self._get_session()
        async with session.get(f"{self.host}/speakers") as resp:
            resp.raise_for_status()
            return await resp.json()
