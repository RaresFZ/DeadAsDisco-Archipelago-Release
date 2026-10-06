"""Validate the authenticated world selection before any checks or grants."""
from .reconciliation import ReconciliationError


class SlotContract:
    def __init__(self, catalog, packet):
        known_locations = {r['id'] for r in catalog['locations']}
        known_items = {r['id'] for r in catalog['items']}
        self.locations = self._ids(packet.get('location_ids', sorted(known_locations)), known_locations, 'location')
        # Filler/traps may be inserted after the unique progression pool.
        self.items = self._ids(packet.get('item_ids', sorted(known_items)), known_items, 'item')
        self.items.update(r['id'] for r in catalog['items'] if r['classification'] == 'filler' or r['classification'] == 'trap' and self.options_enabled(packet, 'traps'))
        self.options = packet.get('options', {})
        if not isinstance(self.options, dict):
            raise ReconciliationError('Malformed runtime options')
        self.goal = packet.get('goal')
        if self.goal is not None:
            if not isinstance(self.goal, dict) or type(self.goal.get('kind')) is not int or self.goal['kind'] not in range(6):
                raise ReconciliationError('Malformed runtime goal')
            for key in ('records', 'story_records'):
                self._ids(self.goal.get(key), known_locations, 'goal')
            count = self.goal.get('count')
            if type(count) is not int or not 1 <= count <= len(self.goal['records']):
                raise ReconciliationError('Impossible runtime goal count')
        self.death_link = packet.get('death_link', False)
        if type(self.death_link) is not bool:
            raise ReconciliationError('Malformed DeathLink option')

    @staticmethod
    def options_enabled(packet, name):
        options = packet.get('options', {})
        return isinstance(options, dict) and options.get(name) in (True, 1)

    @staticmethod
    def _ids(values, known, label):
        if (not isinstance(values, list) or any(type(v) is not int for v in values)
                or len(values) != len(set(values)) or not set(values) <= known):
            raise ReconciliationError('Unknown/duplicate ' + label + ' IDs in slot data')
        return set(values)

    def decoder_settings(self):
        return dict(location_ids=sorted(self.locations), goal=self.goal, options=self.options)
