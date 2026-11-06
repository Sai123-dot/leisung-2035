import socket
import tempfile
import unittest

from hisense_remote.config import ConfigStore
from hisense_remote.tv import HisenseTV, NotConnected, TVError, TVUnreachable, magic_packet


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MagicPacketTests(unittest.TestCase):
    def test_packet_layout(self):
        packet = magic_packet("aa:bb:cc:dd:ee:ff")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("aabbccddeeff"))
        self.assertEqual(magic_packet("AA-BB-CC-DD-EE-FF"), packet)

    def test_invalid_mac(self):
        with self.assertRaises(ValueError):
            magic_packet("not a mac")


class HisenseTVTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_unreachable_tv(self):
        port = _free_port()
        tv = HisenseTV(self.store, "127.0.0.1", api_port=port, pair_port=port)
        with self.assertRaises(TVUnreachable):
            await tv.connect()
        self.assertEqual(tv.status, "unreachable")
        self.assertTrue(self.store.has_certificate(), "a client certificate is generated on first use")
        snap = tv.snapshot()
        self.assertEqual(snap["host"], "127.0.0.1")
        self.assertFalse(snap["needs_pairing"])
        self.assertIsNone(snap["is_on"])
        with self.assertRaises(NotConnected):
            tv.send_key("home")
        await tv.disconnect()
        self.assertEqual(tv.status, "disconnected")

    async def test_pairing_unreachable(self):
        port = _free_port()
        tv = HisenseTV(self.store, "127.0.0.1", api_port=port, pair_port=port)
        with self.assertRaises(TVUnreachable):
            await tv.start_pairing()
        with self.assertRaises(TVError):
            await tv.finish_pairing("123456")
        await tv.disconnect()

    async def test_no_host(self):
        tv = HisenseTV(self.store)
        self.assertIsNone(tv.host)
        with self.assertRaises(TVError):
            await tv.connect()

    async def test_known_tv_details_are_loaded(self):
        self.store.remember_tv("10.0.0.9", name="Lounge", mac="00:11:22:33:44:55")
        tv = HisenseTV(self.store)
        self.assertEqual(tv.host, "10.0.0.9")
        self.assertEqual(tv.name, "Lounge")
        self.assertEqual(tv.mac, "00:11:22:33:44:55")
        events = []
        tv.add_listener(events.append)
        with self.assertRaises(TVUnreachable):
            await tv.connect(f"127.0.0.1")
        self.assertTrue(events)
        self.assertEqual(events[-1]["status"], "unreachable")


if __name__ == "__main__":
    unittest.main()
