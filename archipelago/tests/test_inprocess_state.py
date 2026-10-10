import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from archipelago.client import inprocess_state
from archipelago.client.inprocess_state import InProcessSavedStateReader
from archipelago.dadap import gvas


def make_reader(folder):
    reader = object.__new__(InProcessSavedStateReader)
    reader.path = str(Path(folder) / "slot.sav")
    reader.data = {"node_journal": str(Path(folder) / "nodes.jsonl")}
    reader.last, reader.next_read, reader.key, reader.force_at, reader.settings = None, 0, None, 0, None
    reader.calls = 0

    def decode():
        reader.calls += 1
        return {"protocol": 2, "checks": [reader.calls]}
    reader._decode = decode
    return reader


class SavedStateChangeDetectionTests(unittest.TestCase):
    def read(self, reader):
        return asyncio.run(reader.read({"ready": True}))

    def test_decode_only_reruns_when_an_input_file_changed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, mock.patch.object(inprocess_state, "POLL_SECONDS", 0):
            reader = make_reader(folder)
            save, journal = Path(reader.path), Path(reader.data["node_journal"])
            save.write_bytes(b"one")
            self.assertEqual(self.read(reader)["checks"], [1])
            self.assertEqual(self.read(reader)["checks"], [1])   # unchanged: cached, no second decode
            self.assertEqual(reader.calls, 1)
            save.write_bytes(b"three")                           # autosave: size changes
            self.assertEqual(self.read(reader)["checks"], [2])
            journal.write_text("{}\n")                           # node interaction recorded by the mod
            self.assertEqual(self.read(reader)["checks"], [3])
            self.assertEqual(self.read(reader)["checks"], [3])
            self.assertEqual(reader.calls, 3)

    def test_forced_refresh_failed_decode_and_reconfigure_never_serve_stale_data(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder, mock.patch.object(inprocess_state, "POLL_SECONDS", 0):
            reader = make_reader(folder)
            Path(reader.path).write_bytes(b"one")
            self.read(reader)
            reader.force_at = 0                                  # the 30 s guard elapsed
            self.assertEqual(self.read(reader)["checks"], [2])
            reader._decode = mock.Mock(side_effect=gvas.SaveError("Save changed during observation"))
            Path(reader.path).write_bytes(b"torn")
            self.assertIsNone(self.read(reader))                 # partial autosave: retried, creates nothing
            self.assertIsNone(reader.last)
            reader._decode = mock.Mock(return_value={"checks": [9]})
            self.assertEqual(self.read(reader)["checks"], [9])   # the same bytes decode again after the failure
            reader.configure({"location_ids": [1]})
            self.assertIsNone(reader.last)
            self.assertEqual(self.read(reader)["checks"], [9])
            self.assertEqual(reader._decode.call_count, 2)       # new settings force a fresh decode
            self.assertIsNone(asyncio.run(reader.read(None)))    # game not ready: nothing is served


if __name__ == "__main__":
    unittest.main()
