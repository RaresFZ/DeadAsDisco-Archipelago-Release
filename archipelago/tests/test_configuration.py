import importlib.util
import json
import random
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('disco_configuration',ROOT/'archipelago/apworld/dead_as_disco/configuration.py')
configuration=importlib.util.module_from_spec(spec);spec.loader.exec_module(configuration)


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ROOT/'archipelago/apworld/dead_as_disco/catalog.json'
        cls.catalog=json.loads(path.read_text())

    def resolve(self,**options):
        return configuration.resolve(self.catalog,options,random.Random(17))

    def test_free_starter_skills_are_start_inventory_not_checks(self):
        rows,items,*_=self.resolve(include_skills=True,shuffle_skills=True,shuffle_powers=True)
        starters=set(self.catalog['starter_tags'])
        self.assertEqual(len(starters),3)
        self.assertFalse([r for r in rows if r.get('item_tag') in starters])
        self.assertEqual({r['tag'] for r in items}&starters,starters)

    def test_density_sliders_sample_deterministically(self):
        full, *_ = self.resolve(rank_checks=3, difficulty_checks=['Easy', 'Hard'])
        half, *_ = self.resolve(rank_checks=3, difficulty_checks=['Easy', 'Hard'], rank_percentage=50, difficulty_percentage=25)
        count = lambda rows, family: len([r for r in rows if r['family'] == family])
        self.assertLess(count(half, 'rank'), count(full, 'rank'))
        self.assertLess(count(half, 'difficulty'), count(full, 'difficulty'))
        self.assertGreaterEqual(count(half, 'rank') * 2, count(full, 'rank') - 1)
        self.assertEqual(count(half, 'story'), count(full, 'story'))  # goal records are never sampled away
        with self.assertRaises(ValueError):
            self.resolve(rank_percentage=0)

    def test_categories_and_exact_difficulty(self):
        rows,items,goal,options=self.resolve(include_memorabilia=False,include_skills=False,
            include_upgrades=False,difficulty_checks=['Hard'],rank_checks=0)
        self.assertFalse(any(r['family'] in ('memorabilia','skill','upgrade','rank') for r in rows))
        self.assertEqual({r['difficulty'] for r in rows if r['family']=='difficulty'},{'Hard'})
        self.assertTrue(any(r['family']=='challenge' for r in rows))

    def test_subset_is_seeded_and_dependent_ranks_follow(self):
        rows,*_=self.resolve(challenge_percentage=10,rank_checks=3)
        challenges=[r for r in rows if r['family']=='challenge']
        self.assertEqual(len(challenges),7)
        self.assertTrue(all(r['tag'] in {c['tag'] for c in challenges} for r in rows
            if r['family']=='rank' and r['completion_family']=='challenge'))
        self.assertEqual(rows,self.resolve(challenge_percentage=10,rank_checks=3)[0])

    def test_selected_stars_and_item_family_switches(self):
        rows,items,*_=self.resolve(rank_checks=2,star_thresholds=['2','5'],include_skill_items=False)
        self.assertEqual({r['threshold'] for r in rows if r['family']=='rank'},{2,5})
        self.assertFalse(any(r['family']=='skill' for r in items))

    def test_invalid_goals_and_unverified_mutations_are_refused(self):
        for options in (dict(goal=2,include_challenges=False),dict(goal=1,goal_count=6),
            dict(difficulty_checks=['Impossible']),dict(shuffle_skills=True,include_skill_items=False),
            dict(traps=True,no_stamina_trap_weight=1)):
            with self.subTest(options=options),self.assertRaises(ValueError):
                self.resolve(**options)

    def test_noncheck_story_goal_and_deathlink_setting(self):
        rows,items,goal,options=self.resolve(include_story=False,death_link=False,traps=False)
        self.assertFalse(any(r['family']=='story' for r in rows))
        self.assertEqual(len(goal['story_records']),5)
        self.assertFalse(options['death_link'])
        self.assertFalse(any(r['family']=='trap' for r in items))

    def test_ap_toggle_values_emit_boolean_runtime_options(self):
        *_,options=self.resolve(traps=1,shuffle_skills=1,death_link=0)
        self.assertIs(options['traps'],True)
        self.assertIs(options['shuffle_skills'],True)
        self.assertIs(options['death_link'],False)

    def test_shipped_songs_and_dependent_milestones(self):
        rows,*_=self.resolve(include_songs=True,rank_checks=3,difficulty_checks=['Easy','Normal','Hard','Very Hard'],include_optional=True)
        songs=[r for r in rows if r['family']=='song' or r.get('completion_family')=='song']
        self.assertEqual(len(rows),1103)
        self.assertEqual(len(songs),360)
        self.assertTrue(all(self.catalog['song_support'][r['tag']]['supported'] for r in songs))
        subset=self.resolve(include_songs=True,song_percentage=10,rank_checks=3,difficulty_checks=['Hard'])[0]
        selected={r['tag'] for r in subset if r['family']=='song'}
        self.assertEqual(len(selected),4)
        self.assertTrue(all(r['tag'] in selected for r in subset if r.get('completion_family')=='song'))
        old={k:v for k,v in self.catalog.items() if k!='song_support'}
        with self.assertRaises(ValueError):configuration.resolve(old,{'include_songs':True},random.Random(1))
