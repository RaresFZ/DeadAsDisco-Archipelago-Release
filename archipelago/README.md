# Dead as Disco Archipelago (release 0.5.10, world 0.5.5)

Players: read [the main README](../README.md). Exact support numbers: [FINAL_AUDIT.md](../docs/FINAL_AUDIT.md).

Components:

- `apworld/dead_as_disco`: the AP world (1164 candidate location records, 57 item types, regions/rules, options, goal,
  traps). `catalog.json` is the frozen content/ID map; slot data carries its hash so a changed world is refused.
- `client`: headless AP client (exact seed/team/slot/profile binding, SQLite received-history and check ledger,
  ownership/access/trap/DeathLink dispatch, in-process saved-state decoder, entitlements published before launch).
- `dadap`: the portable runtime (stdlib only): `setup`, `newprofile`, `play`, `recover`, `uninstall`; reversible
  save-park/AP-profile/restore transaction, pinned UE4SS core staging, per-session mod configuration and binding.
- `game-mod`: the UE4SS Lua bridge (read-only corroborated snapshots, skill-node purchase interception, reward
  withholding, power gating, native grants + equip, mission access filter, traps, DeathLink).
- `tests`: 59 Python tests (decoder parity against the JavaScript reference on real saves, session transaction crash
  recovery, play flow with fakes, ledger/production/DeathLink state machines). Lua fixtures live in `tools/test-ap-*.lua`.
