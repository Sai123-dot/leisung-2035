import json
import tempfile
import unittest
from pathlib import Path

from hisense_remote.config import ConfigStore


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_store(self):
        self.assertIsNone(self.store.default_host)
        self.assertEqual(self.store.tvs, {})
        self.assertFalse(self.store.has_certificate())
        self.assertTrue(Path(self.store.cert_path).parent.is_dir())

    def test_remember_sets_default_and_merges(self):
        self.store.remember_tv("192.168.1.5", name="Living room", mac=None)
        self.assertEqual(self.store.default_host, "192.168.1.5")
        self.assertEqual(self.store.tvs["192.168.1.5"], {"name": "Living room"})
        self.store.remember_tv("192.168.1.5", mac="AA:BB:CC:DD:EE:FF", name="")
        self.assertEqual(self.store.tvs["192.168.1.5"], {"name": "Living room", "mac": "AA:BB:CC:DD:EE:FF"})
        self.store.remember_tv("192.168.1.6", name="Bedroom")
        self.assertEqual(self.store.default_host, "192.168.1.5")

    def test_forget(self):
        self.store.remember_tv("a", name="A")
        self.store.remember_tv("b", name="B")
        self.store.forget_tv("a")
        self.assertEqual(self.store.default_host, "b")
        self.store.forget_tv("b")
        self.assertIsNone(self.store.default_host)

    def test_survives_corrupt_file(self):
        self.store.config_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.store.load()["tvs"], {})
        self.store.default_host = "x"
        self.assertEqual(json.loads(self.store.config_path.read_text())["default_host"], "x")


if __name__ == "__main__":
    unittest.main()
