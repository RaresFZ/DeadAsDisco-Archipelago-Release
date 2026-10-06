"""Decode stable autosaves externally while the authoritative live boundary is ready."""
import asyncio
import json
import time
from pathlib import Path
from .reconciliation import ReconciliationError


class SavedStateReader:
    def __init__(self, protection, catalog_path, root):
        self.protection = Path(protection)
        self.catalog = Path(catalog_path)
        self.root = Path(root)
        self.last = None
        self.next_read = 0
        self.settings = None

    def configure(self, settings):
        self.settings = settings
        self.last = None
        self.next_read = 0

    async def read(self, snapshot):
        if snapshot is None:
            self.last = None
            return None
        if time.monotonic() < self.next_read:
            return self.last
        self.next_read = time.monotonic() + 3
        process = await asyncio.create_subprocess_exec('node', str(self.root / 'tools/ap-saved-state.mjs'),
            str(self.protection), str(self.catalog), cwd=self.root,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            output, errors = await asyncio.wait_for(process.communicate(json.dumps(self.settings).encode()), 8)
        except asyncio.TimeoutError:
            process.kill(); await process.wait()
            raise ReconciliationError('Saved-state decoder timeout')
        if process.returncode:
            # A partially replaced autosave may be retried; it never creates checks.
            self.last = None
            return None
        try:
            state = json.loads(output)
        except (ValueError, UnicodeError):
            raise ReconciliationError('Malformed saved-state output')
        if state.get('protocol') != 2 or not isinstance(state.get('checks'), list):
            raise ReconciliationError('Unsupported saved-state output')
        # A save from an older natural autosave remains valid for checks; item
        # application requires the target in BOTH saved and freshly live ownership.
        self.last = state
        return state
