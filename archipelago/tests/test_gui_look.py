import unittest
from pathlib import Path

from archipelago.dadap import gui

FONTS = Path(__file__).resolve().parents[1] / "dadap/assets/fonts"


class WindowLookTests(unittest.TestCase):
    def test_log_lines_get_a_state_chip_and_lose_their_text_prefix(self):
        self.assertEqual(gui.classify("--- Play ---"), ("run", "Play"))
        self.assertEqual(gui.classify("--- Play: done ---"), ("ok", "Play: done"))
        self.assertEqual(gui.classify("[OK] game build: x"), ("ok", "game build: x"))
        self.assertEqual(gui.classify("[WARN] saves: none"), ("warn", "saves: none"))
        self.assertEqual(gui.classify("[FAIL] disk space: 1 MB"), ("err", "disk space: 1 MB"))
        self.assertEqual(gui.classify("STOPPED: nope"), ("err", "STOPPED: nope"))
        self.assertEqual(gui.classify("> hello"), ("you", "hello"))
        self.assertEqual(gui.classify("Connected as Me (slot 2)")[0], "net")
        self.assertEqual(gui.classify("Ready."), ("info", "Ready."))

    def test_bundled_pixel_fonts_and_their_license_are_present(self):
        for name in ("PressStart2P-Regular.ttf", "Silkscreen-Regular.ttf", "Silkscreen-Bold.ttf", "JetBrainsMono-Regular.ttf",
                     "JetBrainsMono-Bold.ttf", "OFL-PressStart2P.txt"):
            self.assertTrue((FONTS / name).is_file(), name)


    def test_app_icon_is_a_multi_size_ico_made_of_png_images(self):
        import struct
        data = (Path(__file__).resolve().parents[1] / "dadap/webui/icon.ico").read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        sizes = []
        for i in range(count):
            width, height, _c, _r, _planes, bits, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            self.assertEqual(data[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(offset + length <= len(data), True)
            sizes.append(width or 256)
        self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])


if __name__ == "__main__":
    unittest.main()

