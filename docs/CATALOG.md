# The catalog (`archipelago/apworld/dead_as_disco/catalog.json`)

The catalog is the single source of truth for the world: every check (location), every item, and how each is detected or granted in
the game. The apworld, the client and the Lua mod all read it (a hash of it travels in the slot data, so a client refuses a seed made
from a different catalog). IDs are stable: **never renumber or reuse an id**, because multiworlds are generated against them.

## Top level

| Key | Meaning |
|---|---|
| `world_version` | Bumped on every release; it is also written into the YAML (`requires`) and the apworld manifest |
| `locations` | 1164 candidate checks (see below) |
| `items` | Items the multiworld can send (see below) |
| `regions` | The five Idol missions: display name, world asset, completion tag |
| `goal` | Story completion tags used by the story goal |
| `starter_tags`, `free_start_locations` | Skills/cosmetics owned at New Game: they are start inventory, never checks |
| `quarantined` | Game definitions that were found but are deliberately not used (with the reason) |
| `song_support` | Per Infinite Disco song: whether it can be a check, and why not if it cannot (these are the 50 BLOCKED records) |
| `recorded_difficulties`, `star_ratings` | Values the star/difficulty checks are built from |

## A location

```json
{"id": 3404260001, "name": "Rebel Magazine Collected", "family": "memorabilia", "scope": "Progression.Scope.Playthrough",
 "tag": "Progression.Memorabilia.Trinkets.Magazine.Rebel", "predicate": "purchased",
 "alt_tag": "Progression.PickupItem.Trinkets.Magazine.Rebel", "alt_threshold": 1, "asset": "/Game/Pagoda/Collectibles/..."}
```

`tag` names a variable in the game's progression save (`archipelago/data/save-variables.json` lists the known variables and field
types). `predicate` says when the check counts:

| predicate | true when |
|---|---|
| `purchased` | the variable's state is 4 |
| `unlocked` | the state is 1 |
| `challenge-completion` | `/Completion Count` > 0 |
| `story-completion` | any `/Completion Count` > 0 |
| `counter-threshold` | the counter at `path` is >= `threshold` (difficulty and star counts) |
| `highest-stars` | `/Highest Star Rating` >= `threshold` |
| `node-interaction` | the skill-tree node was bought (tracked in-game, because the vanilla reward is withheld) |

`alt_tag` lets a second variable (for example a pickup) also trigger the check. Predicates are implemented twice, kept in sync by tests:
`tools/ap-location-predicates.mjs` (JavaScript reference) and `archipelago/dadap/saved_state.py` (what the app uses).

## An item

`mechanism` selects how the item is delivered: `owned-upgrade` (skills, powers and passive upgrades, granted natively and equipped),
`mission-access` (Access items), `temporary-trap`, `fan-pack` (`scale` multiplies `fan_pack_amount`), `client-hint`. Skills, powers and
upgrades carry the asset and tags the mod needs (`tag`, `progression_tag`, `grant_components`, `requirements`).

## Changing it

1. Edit `catalog.json` (keep ids stable; new records get new ids in the existing id ranges, see the neighbouring records).
2. `node tools/test-ap-catalog.mjs` checks every predicate against the schema in `archipelago/data/save-variables.json`.
3. Run the Python tests, regenerate with `python tools/ap-slice-dev.py Generate --run test`, then `tools/audit-release.py`.
4. Anything that changes how a check is *detected* or an item *granted* needs a real play test (see `CONTRIBUTING.md`).

## Where the data came from

Asset identifiers, tags and variable schemas were extracted from the installed game by tooling that is not part of this repository
(it needs the game files and large third-party tools). Records are therefore edited by hand here; adding content that requires a fresh
extraction is possible but not yet reproducible from a clone. If you want that pipeline published or ported, open an issue.
