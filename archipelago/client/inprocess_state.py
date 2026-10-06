"""In-process replacement for the Node saved-state decoder (same interface as SavedStateReader)."""
import asyncio
import json
import time
from pathlib import Path

from ..dadap import gvas, saved_state
from .reconciliation import ReconciliationError


class InProcessSavedStateReader:
    def __init__(self, protection, catalog_path):
        self.data = protection.data
        self.catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        self.session = json.loads(Path(self.data["session_file"]).read_text(encoding="utf-8-sig"))
        self.path = str(Path(self.session["saved"]) / "SaveGames" / (self.data["game_slot"] + ".sav"))
        self.last = None
        self.next_read = 0
        self.settings = None

    def configure(self, settings):
        self.settings = settings
        self.last = None
        self.next_read = 0

    def _decode(self):
        nodes = saved_state.node_interactions(self.data.get("node_journal"), self.data["generation"], self.data["game_slot"],
                                              self.data["launch_token"], self.catalog)
        return saved_state.decode(self.path, self.data["game_slot"], self.catalog, self.settings,
                                  expected_context=self.data["check_context"], nodes=nodes)

    async def read(self, snapshot):
        if snapshot is None:
            self.last = None
            return None
        if time.monotonic() < self.next_read:
            return self.last
        self.next_read = time.monotonic() + 3
        try:
            state = await asyncio.to_thread(self._decode)
        except (gvas.SaveError, FileNotFoundError, PermissionError):
            # A partially replaced autosave is retried; it never creates checks.
            self.last = None
            return None
        except (ValueError, KeyError) as error:
            raise ReconciliationError("Saved-state decoder refused: " + str(error))
        self.last = state
        return state
