import random
import struct
import unittest

from archipelago.dadap import gvas

NAME = "PagodaPT_M_0.sav"


def fstring(text):
    raw = text.encode("utf-8") + b"\0"
    return struct.pack("<i", len(raw)) + raw


def valid_header(engine_changelist=33836, save_class="/Script/Pagoda.PagodaPlaythroughSaveGame"):
    return (b"GVAS" + struct.pack("<ii", 3, 522) + struct.pack("<i", 1018) + struct.pack("<HHH", 5, 7, 4)
            + struct.pack("<I", engine_changelist) + fstring("++UE5+Release-5.7") + struct.pack("<i", 3) + struct.pack("<i", 0)
            + fstring(save_class))


class UnreadableSaveTests(unittest.TestCase):
    """A save that is cut off or damaged (the game may be writing it) must only ever raise SaveError."""

    def test_every_prefix_of_a_header_is_a_save_error(self):
        data = valid_header() + b"\x00"
        for cut in range(len(data)):
            with self.assertRaises(gvas.SaveError, msg=f"cut at {cut}"):
                gvas.read_tagged_save(data[:cut], NAME)

    def test_random_garbage_after_the_magic_is_a_save_error(self):
        rng = random.Random(20261101)
        for _ in range(400):
            data = b"GVAS" + bytes(rng.randrange(256) for _ in range(rng.randrange(0, 160)))
            with self.assertRaises(gvas.SaveError):
                gvas.read_tagged_save(data, NAME)

    def test_a_damaged_body_after_a_good_header_is_a_save_error(self):
        rng = random.Random(7)
        for _ in range(300):
            body = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 120)))
            try:
                gvas.read_tagged_save(valid_header() + body, NAME)
            except gvas.SaveError:
                pass

    def test_invalid_utf8_text_is_a_save_error(self):
        data = valid_header().replace(b"++UE5+Release-5.7", b"++UE5+Release-\xff\xfe\xfd")
        with self.assertRaises(gvas.SaveError):
            gvas.read_tagged_save(data, NAME)


if __name__ == "__main__":
    unittest.main()
