import asyncio
import unittest

from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from hisense_remote.fake import FakeTV
from hisense_remote.server import create_app


class ServerTestCase(unittest.IsolatedAsyncioTestCase):
    token = None
    urls = None

    async def asyncSetUp(self):
        self.tv = FakeTV()
        self.client = TestClient(TestServer(create_app(self.tv, token=self.token, urls=self.urls)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()


class ApiTests(ServerTestCase):
    async def test_index_and_static(self):
        res = await self.client.get("/")
        self.assertEqual(res.status, 200)
        self.assertIn("Hisense Remote", await res.text())
        res = await self.client.get("/static/app.js")
        self.assertEqual(res.status, 200)
        res = await self.client.get("/static/app.css")
        self.assertEqual(res.status, 200)

    async def test_pwa_assets(self):
        res = await self.client.get("/manifest.webmanifest")
        self.assertEqual(res.status, 200)
        self.assertTrue(res.headers["Content-Type"].startswith("application/manifest+json"))
        self.assertEqual((await res.json(content_type=None))["display"], "standalone")
        res = await self.client.get("/sw.js")
        self.assertEqual(res.status, 200)
        self.assertIn("javascript", res.headers["Content-Type"])
        for path in ("/static/icon.svg", "/static/icon-192.png", "/static/icon-512.png"):
            res = await self.client.get(path)
            self.assertEqual(res.status, 200, path)

    async def test_info_without_urls(self):
        info = await (await self.client.get("/api/info")).json()
        self.assertIsNone(info["phone_url"])
        self.assertFalse(info["token_required"])
        res = await self.client.get("/api/qr.svg")
        self.assertEqual(res.status, 404)

    async def test_state(self):
        res = await self.client.get("/api/state")
        data = await res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["state"]["status"], "connected")
        self.assertEqual(data["state"]["volume"]["level"], 12)

    async def test_key_alias(self):
        res = await self.client.post("/api/key", json={"key": "up"})
        self.assertEqual(res.status, 200)
        self.assertEqual(self.tv.sent[-1], ("KEYCODE_DPAD_UP", "SHORT"))

    async def test_key_sequence_and_direction(self):
        res = await self.client.post("/api/key", json={"keys": ["home", "ok"], "delay": 0})
        self.assertEqual(res.status, 200)
        self.assertEqual(self.tv.sent, [("KEYCODE_HOME", "SHORT"), ("KEYCODE_DPAD_CENTER", "SHORT")])
        res = await self.client.post("/api/key", json={"key": "vol+", "direction": "start_long"})
        self.assertEqual(res.status, 200)
        self.assertEqual(self.tv.sent[-1], ("KEYCODE_VOLUME_UP", "START_LONG"))

    async def test_bad_requests(self):
        res = await self.client.post("/api/key", json={"key": "nope"})
        self.assertEqual(res.status, 400)
        self.assertEqual((await res.json())["error"], "unknown_key")
        res = await self.client.post("/api/key", json={})
        self.assertEqual(res.status, 400)
        res = await self.client.post("/api/key", data="not json", headers={"Content-Type": "application/json"})
        self.assertEqual(res.status, 400)
        res = await self.client.post("/api/key", json={"key": "ok", "direction": "sideways"})
        self.assertEqual(res.status, 400)
        res = await self.client.post("/api/text", json={"text": ""})
        self.assertEqual(res.status, 400)

    async def test_text_and_app(self):
        res = await self.client.post("/api/text", json={"text": "hello"})
        self.assertEqual(res.status, 200)
        self.assertEqual(self.tv.texts, ["hello"])
        res = await self.client.post("/api/app", json={"app": "com.netflix.ninja"})
        self.assertEqual(res.status, 200)
        state = (await self.client.get("/api/state")).json()
        self.assertEqual((await state)["state"]["current_app_name"], "Netflix")

    async def test_not_connected(self):
        self.tv.status = "disconnected"
        res = await self.client.post("/api/key", json={"key": "ok"})
        self.assertEqual(res.status, 503)
        data = await res.json()
        self.assertEqual(data["error"], "not_connected")
        self.assertEqual(data["state"]["status"], "disconnected")

    async def test_connect_and_pairing_flow(self):
        res = await self.client.post("/api/connect", json={"host": "10.1.1.1"})
        self.assertEqual(res.status, 200)
        self.assertEqual(self.tv.host, "10.1.1.1")
        res = await self.client.post("/api/pair/start", json={})
        self.assertEqual((await res.json())["state"]["status"], "pairing")
        res = await self.client.post("/api/pair/finish", json={"code": "000000"})
        self.assertEqual(res.status, 400)
        self.assertEqual((await res.json())["error"], "pairing_failed")
        res = await self.client.post("/api/pair/finish", json={"code": "123456"})
        self.assertEqual(res.status, 500)  # pairing must be restarted first
        await self.client.post("/api/pair/start", json={})
        res = await self.client.post("/api/pair/finish", json={"code": "123456"})
        self.assertEqual(res.status, 200)
        self.assertEqual((await res.json())["state"]["status"], "connected")

    async def test_wake_apps_keys(self):
        res = await self.client.post("/api/wake")
        self.assertEqual(res.status, 200)
        self.assertEqual(self.tv.woken, 1)
        self.tv.mac = None
        res = await self.client.post("/api/wake")
        self.assertEqual(res.status, 200)  # the fake always "wakes"; the real TV returns 409 without a MAC
        apps = await (await self.client.get("/api/apps")).json()
        self.assertTrue(any(a["name"] == "Netflix" for a in apps["apps"]))
        keys = await (await self.client.get("/api/keys")).json()
        self.assertIn("KEYCODE_HOME", keys["keycodes"])
        self.assertEqual(keys["aliases"]["ok"], "KEYCODE_DPAD_CENTER")

    async def test_websocket(self):
        async with self.client.ws_connect("/ws") as ws:
            first = await ws.receive_json()
            self.assertEqual(first["type"], "state")
            await ws.send_json({"type": "key", "key": "vol+", "id": 1})
            msg = await ws.receive_json()
            while msg["type"] != "ack":
                msg = await ws.receive_json()
            self.assertEqual(msg["id"], 1)
            self.assertEqual(msg["state"]["volume"]["level"], 13)
            self.assertEqual(self.tv.sent[-1], ("KEYCODE_VOLUME_UP", "SHORT"))

            await ws.send_json({"type": "key", "key": "bogus", "id": 2})
            msg = await ws.receive_json()
            while msg["type"] != "error":
                msg = await ws.receive_json()
            self.assertEqual(msg["error"], "unknown_key")

            await ws.send_str("{not json")
            msg = await ws.receive_json()
            self.assertEqual(msg["type"], "error")

            await ws.send_json({"type": "ping", "id": 3})
            msg = await ws.receive_json()
            while msg["type"] != "pong":
                msg = await ws.receive_json()

    async def test_state_broadcast(self):
        async with self.client.ws_connect("/ws") as ws:
            await ws.receive_json()
            # A change made outside the socket (e.g. by the TV itself) is pushed to clients.
            await self.client.post("/api/app", json={"app": "com.spotify.tv.android"})
            msg = await asyncio.wait_for(ws.receive_json(), 2)
            self.assertEqual(msg["type"], "state")
            self.assertEqual(msg["state"]["current_app_name"], "Spotify")


class PhoneUrlTests(ServerTestCase):
    token = "t0k/en"
    urls = ["http://localhost:8765/", "http://192.168.1.10:8765/"]

    async def test_info_and_qr(self):
        res = await self.client.get("/api/info", headers={"X-Auth-Token": self.token})
        info = await res.json()
        self.assertEqual(info["phone_url"], "http://192.168.1.10:8765/?token=t0k%2Fen")
        self.assertTrue(info["token_required"])
        self.assertEqual(info["urls"], self.urls)
        res = await self.client.get("/api/qr.svg?token=t0k%2Fen")
        self.assertEqual(res.status, 200)
        self.assertTrue(res.headers["Content-Type"].startswith("image/svg+xml"))
        self.assertTrue((await res.read()).startswith(b"<svg"))
        res = await self.client.get("/api/qr.svg")
        self.assertEqual(res.status, 401)


class TokenTests(ServerTestCase):
    token = "s3cret"

    async def test_token_required(self):
        res = await self.client.get("/api/state")
        self.assertEqual(res.status, 401)
        res = await self.client.get("/api/state", headers={"X-Auth-Token": "wrong"})
        self.assertEqual(res.status, 401)
        res = await self.client.get("/api/state", headers={"X-Auth-Token": "s3cret"})
        self.assertEqual(res.status, 200)
        res = await self.client.get("/api/state?token=s3cret")
        self.assertEqual(res.status, 200)
        res = await self.client.get("/")
        self.assertEqual(res.status, 200)

    async def test_websocket_token(self):
        with self.assertRaises(WSServerHandshakeError):
            await self.client.ws_connect("/ws")
        async with self.client.ws_connect("/ws?token=s3cret") as ws:
            self.assertEqual((await ws.receive_json())["type"], "state")


if __name__ == "__main__":
    unittest.main()
