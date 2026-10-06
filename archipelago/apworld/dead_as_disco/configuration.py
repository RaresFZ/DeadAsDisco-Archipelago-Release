"""Generation/runtime share this selection contract; no disconnected YAML fields."""
import math

DEFAULTS = dict(include_missions=True, include_story=True, include_quests=True,
    include_challenges=True, include_memorabilia=True, include_cosmetics=True,
    include_skills=True, include_upgrades=True, include_songs=False, include_optional=False,
    challenge_percentage=100, memorabilia_percentage=100, song_percentage=100, rank_checks=1,
    star_thresholds=["3", "5"], difficulty_checks=[], include_power_items=True,
    include_skill_items=True, include_upgrade_items=True, shuffle_skills=False,
    shuffle_powers=False, shuffle_upgrades=False, shuffle_access=False,
    shuffle_accessories=False, goal=0, goal_count=5, traps=False,
    trap_percentage=10, half_heart_trap_weight=1, no_stamina_trap_weight=0,
    trap_duration=10, silence_trap_weight=1, starting_mission=0, death_link=False,
    rank_percentage=100, difficulty_percentage=100, death_link_amnesty=0, death_link_cooldown=0,
    fan_pack_percentage=100, fan_pack_amount=500)


def resolve(catalog, supplied, rng):
    options = {**DEFAULTS, **supplied}
    # AP Toggle.value is 0/1. Emit actual JSON booleans in the runtime contract.
    for name, default in DEFAULTS.items():
        if type(default) is bool:
            options[name] = bool(options[name])
    for name in ("shuffle_accessories",):
        if options[name]:
            raise ValueError(name + ": native reward suppression/access replacement is not live-validated; refusing an additive seed presented as a randomizer")
    if options['traps'] and options['no_stamina_trap_weight']:
        raise ValueError('No Stamina Trap: this game build has no stamina resource; select Half Heart/Silence instead')
    if options['traps'] and not options['half_heart_trap_weight']+options['silence_trap_weight']:
        raise ValueError('Traps enabled with zero supported trap weights')
    for shuffle, pool in [('shuffle_skills','include_skill_items'),('shuffle_powers','include_power_items'),('shuffle_upgrades','include_upgrade_items')]:
        if options[shuffle] and not options[pool]:
            raise ValueError(shuffle+' requires '+pool)
    if options['shuffle_access'] and not (options['include_missions'] and options['include_story']):
        raise ValueError('Mission access shuffle requires mission checks for a safe initial progression path')
    for shuffle, checks in [('shuffle_skills','include_skills'),('shuffle_powers','include_skills'),('shuffle_upgrades','include_upgrades')]:
        if options[shuffle] and not options[checks]:
            raise ValueError(shuffle+' requires independent '+checks+' node checks')
    if options["include_songs"] and not catalog.get('song_support'):
        raise ValueError('Song checks require exact shipped player-facing song/access joins')
    for name in ('rank_percentage', 'difficulty_percentage'):
        if not 1 <= options[name] <= 100:
            raise ValueError(name + ' must be between 1 and 100')
    thresholds = {5} if options["rank_checks"] == 1 else set(range(1, 6)) if options["rank_checks"] == 3 else {int(x) for x in options["star_thresholds"]} if options["rank_checks"] == 2 else set()
    if not thresholds <= set(catalog["star_ratings"]):
        raise ValueError("Unknown star threshold")
    difficulties = set(options["difficulty_checks"])
    if not difficulties <= set(catalog["recorded_difficulties"]):
        raise ValueError("Unknown recorded difficulty")
    switches = {"story": options["include_missions"] and options["include_story"],
        "quest": options["include_quests"], "challenge": options["include_challenges"],
        "memorabilia": options["include_memorabilia"], "cosmetic": options["include_cosmetics"],
        "dance": options["include_cosmetics"], "skill": options["include_skills"],
        "upgrade": options["include_upgrades"], "song": options["include_songs"],
        "optional": options["include_optional"]}
    sampled = {}
    for family, percentage in (("challenge", options["challenge_percentage"]), ("memorabilia", options["memorabilia_percentage"]), ('song',options['song_percentage'])):
        if not 1 <= percentage <= 100:
            raise ValueError(f'{family} percentage must be between 1 and 100')
        source = [r["id"] for r in catalog["locations"] if r["family"] == family
            and (family!='song' or catalog.get('song_support',{}).get(r['tag'],{}).get('supported'))]
        sampled[family] = set(rng.sample(source, math.ceil(len(source) * percentage / 100)))
    sampled_tags={family:{r['tag'] for r in catalog['locations'] if r['id'] in ids} for family,ids in sampled.items()}
    starters = set(catalog.get('starter_tags', []))
    free_start = set(catalog.get('free_start_locations', []))
    rows = []
    for row in catalog["locations"]:
        family = row["family"]
        if row['id'] in free_start:
            continue  # owned at New Game (default outfit/dances/debug): can never be a real check
        if row.get('item_tag') in starters:
            continue  # free starting skill: it can never be bought, so it is start inventory, not a check
        if (family=='song' or row.get('completion_family')=='song') and not catalog.get('song_support',{}).get(row['tag'],{}).get('supported'):
            continue
        if family in ("rank", "difficulty"):
            if not switches.get(row["completion_family"], False):
                continue
            if family == "rank" and row["threshold"] not in thresholds:
                continue
            if family == "difficulty" and row["difficulty"] not in difficulties:
                continue
            if row['completion_family'] in sampled_tags and row['tag'] not in sampled_tags[row['completion_family']]:
                continue
        elif not switches.get(family, False) or family in sampled and row["id"] not in sampled[family]:
            continue
        rows.append(row)
    for family, name in (('rank', 'rank_percentage'), ('difficulty', 'difficulty_percentage')):
        if options[name] < 100:
            members = [r for r in rows if r['family'] == family]
            keep = {r['id'] for r in rng.sample(members, math.ceil(len(members) * options[name] / 100))} if members else set()
            rows = [r for r in rows if r['family'] != family or r['id'] in keep]
    item_switches = dict(power=options["include_power_items"], skill=options["include_skill_items"], upgrade=options["include_upgrade_items"],access=options['shuffle_access'])
    items = [r for r in catalog["items"] if item_switches.get(r["family"], False)]
    if not rows or len([r for r in items if r['tag'] not in starters]) > len(rows):
        raise ValueError("Enabled locations must accommodate every enabled ownership item")
    goal = int(options["goal"])
    goal_count = int(options["goal_count"])
    goal_rows = [r for r in catalog["locations"] if r["family"] == "story"]
    if goal in (2, 5):
        required = [r for r in rows if r["family"] == "challenge"]
    elif goal == 3:
        required = [r for r in rows if r["family"] == "memorabilia"]
    elif goal == 1:
        required = goal_rows
    else:
        required = goal_rows
        goal_count = len(goal_rows)
    if not 1 <= goal_count <= len(required):
        raise ValueError("Goal count exceeds enabled reliable completion records")
    return rows, items, {"kind": goal, "count": goal_count,
        "records": [r["id"] for r in required], "story_records": [r["id"] for r in goal_rows]}, options
