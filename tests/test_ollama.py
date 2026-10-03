import asyncio
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web

from bot.llm import ollama


class OllamaClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.response = {"answers": {"style": {"type": "choice", "choice": "喜び"}}}
        self.status = 200
        self.delay = 0
        self.raw_response = None
        app = web.Application()
        app.router.add_post("/{tail:.*}", self.handle_request)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.host = f"http://127.0.0.1:{port}"
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        await self.runner.cleanup()

    async def handle_request(self, request):
        self.requests.append((request.path, await request.json()))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raw_response is not None:
            return web.Response(text=self.raw_response, content_type="application/json")
        return web.json_response(self.response, status=self.status)

    def client(self, mode="systemone", model="test-model"):
        client = ollama.OllamaClient(host=self.host + "/", model=model, api_mode=mode)
        self.clients.append(client)
        return client

    async def test_systemone_preserves_text_and_validates_choice(self):
        client = self.client()
        text = "ありがとう！\nとても嬉しいです"
        self.assertEqual(await client.infer_style(text, ["ノーマル", "喜び"]), "喜び")
        path, payload = self.requests[0]
        self.assertEqual(path, "/v1/systemone")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["state"], text)
        self.assertEqual(payload["keep_alive"], "10m")
        question = payload["questions"]["style"]
        self.assertEqual(question["type"], "choice")
        self.assertTrue(question["instructions"])
        self.assertEqual(question["criteria"]["喜び"], ollama._style_label("喜び"))
        self.assertEqual(set(question["criteria"]), {"ノーマル", "喜び"})

    async def test_unknown_style_description_and_deduplication(self):
        self.response = {"answers": {"style": {"type": "choice", "choice": "未知スタイル"}}}
        result = await self.client().infer_style("例文", ["未知スタイル", "喜び", "未知スタイル"])
        self.assertEqual(result, "未知スタイル")
        criteria = self.requests[0][1]["questions"]["style"]["criteria"]
        self.assertEqual(criteria["未知スタイル"], "未知スタイル")
        self.assertEqual(len(criteria), 2)

    async def test_empty_single_and_duplicate_single_skip_network(self):
        for mode in ("generate", "systemone"):
            client = self.client(mode)
            self.assertIsNone(await client.infer_style("例文", []))
            self.assertEqual(await client.infer_style("例文", ["喜び"]), "喜び")
            self.assertEqual(await client.infer_style("例文", ["喜び", "喜び"]), "喜び")
        self.assertEqual(self.requests, [])

    async def test_systemone_candidate_limit_counts_unique_names(self):
        client = self.client()
        names = [f"style-{index}" for index in range(24)]
        self.response = {"answers": {"style": {"type": "choice", "choice": names[0]}}}
        self.assertEqual(await client.infer_style("例文", names + names), names[0])
        self.assertIsNone(await client.infer_style("例文", names + ["extra"]))
        self.assertEqual(len(self.requests), 1)

    async def test_systemone_rejects_invalid_or_malformed_answers(self):
        client = self.client()
        for response in (
            {}, {"answers": None}, {"answers": []}, {"answers": {"style": None}},
            {"answers": {"style": {}}},
            {"answers": {"style": {"choice": "喜び"}}},
            {"answers": {"style": {"type": "score", "choice": "喜び"}}},
            {"answers": {"style": {"type": "choice", "choice": 1}}},
            {"answers": {"style": {"type": "choice", "choice": "喜び "}}},
            {"answers": {"style": {"type": "choice", "choice": "怒り"}}}, [], None,
        ):
            with self.subTest(response=response):
                self.response = response
                self.assertIsNone(await client.infer_style("例文", ["ノーマル", "喜び"]))

    async def test_http_and_json_errors_fall_back(self):
        client = self.client()
        self.status = 503
        self.assertIsNone(await client.infer_style("例文", ["ノーマル", "喜び"]))
        self.status = 200
        self.raw_response = "invalid json"
        self.assertIsNone(await client.infer_style("例文", ["ノーマル", "喜び"]))

    async def test_inference_timeout_falls_back(self):
        self.delay = 1.0
        client = self.client()
        self.assertEqual((await client._get_session()).timeout.total, 0.75)
        self.assertIsNone(await client.infer_style("例文", ["ノーマル", "喜び"]))

    async def test_generate_legacy_number_mapping(self):
        self.response = {"response": "2"}
        with patch.object(ollama.random, "shuffle", lambda names: None):
            result = await self.client("generate", "qwen3.5:2b").infer_style("ありがとう", ["ノーマル", "喜び"])
        self.assertEqual(result, "喜び")
        path, payload = self.requests[0]
        self.assertEqual(path, "/api/generate")
        self.assertEqual(payload["model"], "qwen3.5:2b")
        self.assertIn("ありがとう", payload["prompt"])
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["think"])

    async def test_generate_invalid_number_falls_back(self):
        client = self.client("generate")
        for response in ("0", "3", "no answer"):
            self.response = {"response": response}
            self.assertIsNone(await client.infer_style("例文", ["ノーマル", "喜び"]))

    async def test_systemone_warmup_uses_choice_request(self):
        client = self.client()
        # Exceed the ordinary inference timeout to ensure warmup overrides it.
        self.delay = 0.05
        with (
            patch.object(ollama, "_TIMEOUT", aiohttp.ClientTimeout(total=0.01)),
            patch.object(ollama.logger, "warning") as warning,
        ):
            await client.warmup()
            warning.assert_not_called()
        path, payload = self.requests[0]
        self.assertEqual(path, "/v1/systemone")
        self.assertEqual(payload["model"], "test-model")
        self.assertTrue(payload["state"])
        self.assertEqual(len(payload["questions"]["style"]["criteria"]), 2)
        self.assertFalse(client._keepalive_task.done())

    async def test_systemone_keepalive_uses_choice_request(self):
        client = self.client()
        with patch.object(ollama, "_KEEPALIVE_INTERVAL", 0.01):
            await client.warmup()
            for _ in range(50):
                if len(self.requests) >= 2:
                    break
                await asyncio.sleep(0.01)
            await client.close()
        self.assertGreaterEqual(len(self.requests), 2)
        for path, payload in self.requests:
            self.assertEqual(path, "/v1/systemone")
            self.assertEqual(len(payload["questions"]["style"]["criteria"]), 2)

    async def test_invalid_api_mode_is_rejected(self):
        for mode in ("unknown", "", "SYSTEMONE"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                ollama.OllamaClient(host=self.host, model="test-model", api_mode=mode)

    async def test_close_releases_session_and_keepalive(self):
        client = self.client()
        await client.warmup()
        session = client._session
        task = client._keepalive_task
        await client.close()
        await asyncio.sleep(0)
        self.assertTrue(session.closed)
        self.assertTrue(task.done())
        await client.close()


if __name__ == "__main__":
    unittest.main()
