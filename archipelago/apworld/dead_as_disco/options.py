"""Player options for Dead as Disco. The docstrings become the comments of the generated YAML template."""
from dataclasses import dataclass

from Options import (Choice, DeathLink, DefaultOnToggle, OptionGroup, OptionSet, PerGameCommonOptions, Range, Toggle,
                     Visibility)


# ---- Goal and missions ------------------------------------------------------------------------------------------
class Goal(Choice):
    """What counts as finishing the game.

    story: beat all five Idol missions.
    mission_count: beat the number of missions set by goal_count.
    challenges: complete the number of song challenges set by goal_count.
    memorabilia: collect the number of memorabilia set by goal_count.
    five_star_story: get 5 stars on every Idol mission.
    story_and_challenges: beat all five missions AND complete goal_count challenges."""
    display_name = "Goal"
    option_story = 0
    option_mission_count = 1
    option_challenges = 2
    option_memorabilia = 3
    option_five_star_story = 4
    option_story_and_challenges = 5
    default = 0


class GoalCount(Range):
    """How many missions / challenges / memorabilia the chosen goal needs. Only used by the goals that count things;
    a count that cannot be reached with your other options is rejected."""
    display_name = "Goal Count"
    range_start = 1
    range_end = 148
    default = 5


class ShuffleAccess(DefaultOnToggle):
    """Lock the five missions behind Mission Access items sent by the multiworld.

    You can play your starting mission from the beginning; the other four unlock when their Access item arrives."""
    display_name = "Shuffle Mission Access"


class StartingMission(Choice):
    """The mission you can play from the start when Shuffle Mission Access is on. 'random' picks one per seed."""
    display_name = "Starting Mission"
    option_hemlock = 0
    option_arora = 1
    option_dex = 2
    option_prophet = 3
    option_dahlia = 4
    default = 0


# ---- Shuffled rewards -------------------------------------------------------------------------------------------
class ShuffleSkills(DefaultOnToggle):
    """The skill tree becomes an Archipelago shop.

    Buying a node sends a check (it can hold an item for anyone) and gives you nothing itself; the skill only arrives
    when the multiworld sends it, and is then equipped automatically."""
    display_name = "Shuffle Skills"


class ShufflePowers(ShuffleSkills):
    """The six Idol powers are shuffled. Beating an Idol sends its check; the power only arrives from the multiworld
    (until then it cannot be equipped or used)."""
    display_name = "Shuffle Idol Powers"


class ShuffleUpgrades(ShuffleSkills):
    """The 29 passive upgrades are shuffled: buying their node sends a check, the upgrade arrives from the multiworld."""
    display_name = "Shuffle Passive Upgrades"


class IncludeSkills(DefaultOnToggle):
    """Skill and power nodes are check locations."""
    display_name = "Skill Node Checks"


class IncludeUpgrades(DefaultOnToggle):
    """Passive upgrade nodes are check locations."""
    display_name = "Upgrade Node Checks"


class IncludePowerItems(DefaultOnToggle):
    """The Idol powers are items in the multiworld."""
    display_name = "Power Items"


class IncludeSkillItems(DefaultOnToggle):
    """The active skills are items in the multiworld."""
    display_name = "Skill Items"


class IncludeUpgradeItems(DefaultOnToggle):
    """The passive upgrades are items in the multiworld."""
    display_name = "Upgrade Items"


# ---- Which things are checks ------------------------------------------------------------------------------------
class IncludeMissions(DefaultOnToggle):
    """Mission related checks (required by Shuffle Mission Access)."""
    display_name = "Mission Checks"


class IncludeStory(DefaultOnToggle):
    """Beating each Idol's mission is a check (required by Shuffle Mission Access)."""
    display_name = "Story Checks"


class IncludeQuests(DefaultOnToggle):
    """Finishing character quests (item turn-ins) are checks."""
    display_name = "Quest Checks"


class IncludeChallenges(DefaultOnToggle):
    """Completing song challenges is a check."""
    display_name = "Challenge Checks"


class IncludeMemorabilia(DefaultOnToggle):
    """Memorabilia are checks. Most count the moment you PICK THEM UP in a level or the hub; the rest when you buy them."""
    display_name = "Memorabilia Checks"


class IncludeCosmetics(DefaultOnToggle):
    """Buying clothing and dance moves is a check. The cosmetics themselves stay vanilla."""
    display_name = "Cosmetic and Dance Purchase Checks"


class IncludeOptional(DefaultOnToggle):
    """The tutorial and the game's achievements are checks."""
    display_name = "Tutorial and Achievement Checks"


class IncludeSongs(Toggle):
    """Add the 36 shipped Infinite Disco songs: completing each, plus the star and difficulty milestones you selected
    (about 360 extra checks). Off by default because they make a seed much longer."""
    display_name = "Song Checks"


class CheckPercentage(Range):
    """Keeps a seeded random share of this category; 100 keeps every check, lower values make the seed shorter."""
    range_start = 1
    range_end = 100
    default = 100


class ChallengePercentage(CheckPercentage):
    """Share of the challenge checks that are used (1-100)."""
    display_name = "Challenge Percentage"


class MemorabiliaPercentage(CheckPercentage):
    """Share of the memorabilia checks that are used (1-100)."""
    display_name = "Memorabilia Percentage"


class SongPercentage(CheckPercentage):
    """Share of the song checks that are used (1-100). Only matters if Song Checks is on."""
    display_name = "Song Percentage"


class RankChecks(Choice):
    """Star rating checks (the game records stars, not letter grades).

    off: none.
    highest_only: only 5 stars.
    selected_thresholds: the star counts listed in star_thresholds.
    all_milestones: 1, 2, 3, 4 and 5 stars."""
    display_name = "Star Rating Checks"
    option_off = 0
    option_highest_only = 1
    option_selected_thresholds = 2
    option_all_milestones = 3
    default = 2


class StarThresholds(OptionSet):
    """Which star counts are checks when Star Rating Checks is selected_thresholds. Values: 1, 2, 3, 4, 5."""
    display_name = "Star Thresholds"
    valid_keys = frozenset({"1", "2", "3", "4", "5"})
    default = frozenset({"3", "5"})


class RankPercentage(CheckPercentage):
    """Share of the selected star rating checks that are used (1-100)."""
    display_name = "Star Rating Check Percentage"


class DifficultyChecks(OptionSet):
    """Completing a mission on an exact difficulty is a check. Values: Easy, Normal, Hard, Very Hard.
    Empty means none; a harder difficulty does not count for an easier one."""
    display_name = "Difficulty Completion Checks"
    valid_keys = frozenset({"Easy", "Normal", "Hard", "Very Hard"})
    default = frozenset()


class DifficultyPercentage(CheckPercentage):
    """Share of the selected difficulty checks that are used (1-100)."""
    display_name = "Difficulty Check Percentage"


# ---- Filler and traps -------------------------------------------------------------------------------------------
class FanPackPercentage(Range):
    """How much filler is Fan Packs (fans you spend in the skill-tree shop) instead of Disco Hints.
    100 means no Disco Hints at all. Fan Packs come in five sizes."""
    display_name = "Fan Pack Percentage"
    range_start = 0
    range_end = 100
    default = 100


class FanPackAmount(Range):
    """Fans in a normal Fan Pack. The five sizes are 1/4, 1/2, 1x, 2x and 4x of this."""
    display_name = "Fan Pack Amount"
    range_start = 50
    range_end = 5000
    default = 500


class Traps(DefaultOnToggle):
    """Turn some filler into temporary traps. Progression items are never replaced."""
    display_name = "Traps"


class TrapPercentage(Range):
    """Percent of the surplus filler that becomes traps."""
    display_name = "Trap Percentage"
    range_start = 0
    range_end = 100
    default = 10


class TrapWeight(Range):
    range_start = 0
    range_end = 100
    default = 1


class HalfHeartWeight(TrapWeight):
    """How likely a trap is a Half Heart: you lose a little health once (never lethal, max health untouched)."""
    display_name = "Half Heart Trap Weight"


class SilenceWeight(TrapWeight):
    """How likely a trap is Silence: for a few seconds you can run but cannot attack, dodge or use abilities."""
    display_name = "Silence Trap Weight"


class TrapDuration(Range):
    """How many seconds the Silence trap lasts."""
    display_name = "Silence Duration (seconds)"
    range_start = 1
    range_end = 60
    default = 10


# ---- DeathLink tuning (client side) ------------------------------------------------------------------------------
class DeathLinkAmnesty(Range):
    """Incoming DeathLinks to forgive (ignore) at the start of each play session."""
    display_name = "DeathLink Amnesty"
    range_start = 0
    range_end = 10
    default = 0


class DeathLinkCooldown(Range):
    """Seconds after an accepted incoming DeathLink during which further ones are ignored."""
    display_name = "DeathLink Cooldown (seconds)"
    range_start = 0
    range_end = 300
    default = 0


class ContentProfile(Choice):
    """Internal: the full randomizer world (expanded), or a one-check diagnostic seed."""
    display_name = "Content Profile"
    visibility = Visibility.none
    option_vertical_slice = 0
    option_expanded = 1
    default = 1


@dataclass
class DeadAsDiscoOptions(PerGameCommonOptions):
    content_profile: ContentProfile
    goal: Goal
    goal_count: GoalCount
    shuffle_access: ShuffleAccess
    starting_mission: StartingMission
    shuffle_skills: ShuffleSkills
    shuffle_powers: ShufflePowers
    shuffle_upgrades: ShuffleUpgrades
    include_skills: IncludeSkills
    include_upgrades: IncludeUpgrades
    include_power_items: IncludePowerItems
    include_skill_items: IncludeSkillItems
    include_upgrade_items: IncludeUpgradeItems
    include_missions: IncludeMissions
    include_story: IncludeStory
    include_quests: IncludeQuests
    include_challenges: IncludeChallenges
    include_memorabilia: IncludeMemorabilia
    include_cosmetics: IncludeCosmetics
    include_optional: IncludeOptional
    include_songs: IncludeSongs
    challenge_percentage: ChallengePercentage
    memorabilia_percentage: MemorabiliaPercentage
    song_percentage: SongPercentage
    rank_checks: RankChecks
    star_thresholds: StarThresholds
    rank_percentage: RankPercentage
    difficulty_checks: DifficultyChecks
    difficulty_percentage: DifficultyPercentage
    fan_pack_percentage: FanPackPercentage
    fan_pack_amount: FanPackAmount
    traps: Traps
    trap_percentage: TrapPercentage
    half_heart_trap_weight: HalfHeartWeight
    silence_trap_weight: SilenceWeight
    trap_duration: TrapDuration
    death_link: DeathLink
    death_link_amnesty: DeathLinkAmnesty
    death_link_cooldown: DeathLinkCooldown


OPTION_GROUPS = [
    OptionGroup("Goal and Missions", [Goal, GoalCount, ShuffleAccess, StartingMission]),
    OptionGroup("Shuffled Rewards (the skill tree shop)", [ShuffleSkills, ShufflePowers, ShuffleUpgrades, IncludeSkills,
                                                           IncludeUpgrades, IncludePowerItems, IncludeSkillItems,
                                                           IncludeUpgradeItems]),
    OptionGroup("What Counts as a Check", [IncludeMissions, IncludeStory, IncludeQuests, IncludeChallenges,
                                           IncludeMemorabilia, IncludeCosmetics, IncludeOptional, IncludeSongs,
                                           ChallengePercentage, MemorabiliaPercentage, SongPercentage, RankChecks,
                                           StarThresholds, RankPercentage, DifficultyChecks, DifficultyPercentage]),
    OptionGroup("Filler and Traps", [FanPackPercentage, FanPackAmount, Traps, TrapPercentage, HalfHeartWeight,
                                     SilenceWeight, TrapDuration]),
    OptionGroup("DeathLink", [DeathLink, DeathLinkAmnesty, DeathLinkCooldown]),
]
