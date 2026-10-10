"""In-process replacement for the Node saved-state decoder (same interface as SavedStateReader)."""
import asyncio
import json
import os
import time
from pathlib import Path

from ..dadap import gvas, saved_state
from .reconciliation import ReconciliationError

# The decode is a pure function of the save file, the node journal and the settings, so it only reruns when one of the files changed
# (checked with a cheap stat once a second). A forced rerun every 30 s guards against a coarse file timestamp.
POLL_SECONDS = 1.0
FORCE_SECONDS = 30.0


class InProcessSavedStateReader:
    def __init__(self, protection, catalog_path):
        self.data = protection.data
        self.catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        self.session = json.loads(Path(self.data["session_file"]).read_text(encoding="utf-8-sig"))
        self.path = str(Path(self.session["saved"]) / "SaveGames" / (self.data["game_slot"] + ".sav"))
        self.last = None
        self.next_read = 0
        self.key = None
        self.force_at = 0
        self.settings = None

    def configure(self, settings):
        self.settings = settings
        self.last = None
        self.key = None
        self.next_read = 0

    def _stamp(self):
        """(mtime, size) of every input file; None for a missing one."""
        stamps = []
        for path in (self.path, self.data.get("node_journal")):
            try:
                info = os.stat(path)
                stamps.append((info.st_mtime_ns, info.st_size))
            except (OSError, TypeError):
                stamps.append(None)
        return tuple(stamps)

    def _decode(self):
        nodes = saved_state.node_interactions(self.data.get("node_journal"), self.data["generation"], self.data["game_slot"],
                                              self.data["launch_token"], self.catalog)
        return saved_state.decode(self.path, self.data["game_slot"], self.catalog, self.settings,
                                  expected_context=self.data["check_context"], nodes=nodes)

    async def read(self, snapshot):
        if snapshot is None:
            self.last = None
            self.key = None
            return None
        now = time.monotonic()
        if now < self.next_read:
            return self.last
        self.next_read = now + POLL_SECONDS
        key = self._stamp()  # taken before decoding: a change during the decode forces another one
        if self.last is not None and key == self.key and now < self.force_at:
            return self.last
        try:
            state = await asyncio.to_thread(self._decode)
        except (gvas.SaveError, FileNotFoundError, PermissionError):
            # A partially replaced autosave is retried; it never creates checks.
            self.last = None
            self.key = None
            return None
        except (ValueError, KeyError) as error:
            raise ReconciliationError("Saved-state decoder refused: " + str(error))
        self.last, self.key, self.force_at = state, key, now + FORCE_SECONDS
        return state
