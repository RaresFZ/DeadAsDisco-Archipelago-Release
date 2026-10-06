"""Which native mechanisms this build may enable. Promotion requires protected live evidence.

Evidence: archipelago/data/evidence/ap-fresh-profile-20261006-live.json (fresh profile, dadap play) and
archipelago/data/evidence/ap-cold-20261006b-round-trip.json (ownership round trip).
"""
VALIDATED = {"ownership": True, "node-interaction": True, "reward-suppression": True,
             "mission-access": True, "temporary-traps": True, "death-link": True,
             "fan-packs": False}  # promoted only after a protected live run (AddCredits unverified)
REQUIRED_KEYS = {name: name for name in VALIDATED}


EXPERIMENTAL = ("fan-packs",)  # run in protected test mode by default until validated live; removed on promotion


def resolve(features=None):
    """features: None (validated only) | 'all' | iterable of names -> enabled in protected TEST mode."""
    caps = dict(VALIDATED)
    for name in EXPERIMENTAL:
        if not caps[name]:
            caps[name] = "test"
    if features:
        names = list(VALIDATED) if features == "all" else list(features)
        for name in names:
            if name not in VALIDATED:
                raise ValueError("Unknown capability: " + name)
            if not VALIDATED[name]:
                caps[name] = "test"
    return caps
