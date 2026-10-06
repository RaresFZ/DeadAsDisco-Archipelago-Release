# APBridge (UE4SS Lua mod)

Runs inside Dead as Disco under UE4SS. Staged per session by `archipelago/dadap` together with a generated
`ap-config.lua` (anchors, tokens, entitlements); it is never installed into the game folder permanently.

| File | Role |
|---|---|
| `main.lua` | Entry point, EngineTick service (2 s), staged timing, refusal reporting (`ap-refusal.txt`) |
| `skill-locations.lua` | Skill-node purchase interception, reward withholding, reflected-set ownership removal, power gate hook |
| `power-removal.lua` | Idol power removal/gating (slot and applied-effect gate) |
| `production.lua`, `authority.lua`, `purchase.lua`, `proof.lua` | Native grant + auto-equip, authority catalog, purchase detection, at-most-once dispatch |
| `access.lua` | Mission access filter |
| `traps.lua`, `health-effect.lua`, `deathlink.lua`, `players.lua` | Half Heart / Silence traps, incoming DeathLink (damage effect), player lookup |
| `credits.lua` | Fan Packs via `AddCredits` (experimental until live-confirmed) |
| `plain-json.lua` | Minimal JSON writer |

Shared helpers live in `tools/runtime/Common/ue-values.lua` and `tools/runtime/SyncProof/Scripts/sync-scopes.lua`.
Offline fixtures: `tools/test-ap-*.lua` (run from the repo root with a Lua 5.4 interpreter).
