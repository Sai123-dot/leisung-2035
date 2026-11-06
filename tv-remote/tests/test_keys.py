import unittest

from hisense_remote.keys import ALIASES, UnknownKey, all_keycodes, list_aliases, resolve_direction, resolve_key


class ResolveKeyTests(unittest.TestCase):
    def test_common_aliases(self):
        cases = {
            "up": "KEYCODE_DPAD_UP",
            "ok": "KEYCODE_DPAD_CENTER",
            "back": "KEYCODE_BACK",
            "home": "KEYCODE_HOME",
            "vol+": "KEYCODE_VOLUME_UP",
            "vol-": "KEYCODE_VOLUME_DOWN",
            "mute": "KEYCODE_VOLUME_MUTE",
            "hdmi2": "KEYCODE_TV_INPUT_HDMI_2",
            "playpause": "KEYCODE_MEDIA_PLAY_PAUSE",
            "power": "KEYCODE_POWER",
        }
        for alias, expected in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(resolve_key(alias), expected)

    def test_every_alias_is_a_real_keycode(self):
        valid = set(all_keycodes())
        for alias in ALIASES:
            self.assertIn(resolve_key(alias), valid, alias)

    def test_full_bare_and_sloppy_names(self):
        self.assertEqual(resolve_key("KEYCODE_HOME"), "KEYCODE_HOME")
        self.assertEqual(resolve_key("keycode_home"), "KEYCODE_HOME")
        self.assertEqual(resolve_key("Home"), "KEYCODE_HOME")
        self.assertEqual(resolve_key("dpad-up"), "KEYCODE_DPAD_UP")
        self.assertEqual(resolve_key(" DPAD UP "), "KEYCODE_DPAD_UP")
        self.assertEqual(resolve_key("MEDIA_PLAY_PAUSE"), "KEYCODE_MEDIA_PLAY_PAUSE")

    def test_digits(self):
        for digit in "0123456789":
            self.assertEqual(resolve_key(digit), f"KEYCODE_{digit}")

    def test_integers(self):
        self.assertEqual(resolve_key(26), 26)
        with self.assertRaises(UnknownKey):
            resolve_key(10**6)
        with self.assertRaises(UnknownKey):
            resolve_key(True)

    def test_text_passthrough(self):
        self.assertEqual(resolve_key("text:hello world"), "text:hello world")

    def test_unknown(self):
        with self.assertRaises(UnknownKey):
            resolve_key("definitely-not-a-key")
        with self.assertRaises(UnknownKey):
            resolve_key(None)  # type: ignore[arg-type]

    def test_direction(self):
        self.assertEqual(resolve_direction(None), "SHORT")
        self.assertEqual(resolve_direction("short"), "SHORT")
        self.assertEqual(resolve_direction(" start_long "), "START_LONG")
        with self.assertRaises(ValueError):
            resolve_direction("sideways")

    def test_listings(self):
        codes = all_keycodes()
        self.assertIn("KEYCODE_POWER", codes)
        self.assertNotIn("KEYCODE_UNKNOWN", codes)
        self.assertEqual(list_aliases()["up"], "KEYCODE_DPAD_UP")


if __name__ == "__main__":
    unittest.main()
