"""Exact persistent catalog, selected runtime contract and shuffled progression."""
import hashlib
import json
from importlib.resources import files
from BaseClasses import Item, ItemClassification, Location, Region
from worlds.AutoWorld import WebWorld, World
from .options import DeadAsDiscoOptions, OPTION_GROUPS
from .configuration import DEFAULTS, resolve

CONTENT=json.loads(files(__package__).joinpath('slice.json').read_text(encoding='utf-8'))
CATALOG=json.loads(files(__package__).joinpath('catalog.json').read_text(encoding='utf-8'))


class DeadAsDiscoItem(Item):
    game='Dead as Disco'


class DeadAsDiscoLocation(Location):
    game='Dead as Disco'


class DeadAsDiscoWeb(WebWorld):
    option_groups=OPTION_GROUPS


class DeadAsDiscoWorld(World):
    game='Dead as Disco'
    web=DeadAsDiscoWeb()
    options_dataclass=DeadAsDiscoOptions
    required_client_version=(0,6,8)
    topology_present=True
    item_name_to_id={r['name']:r['id'] for r in CONTENT['items']+CATALOG['items']}
    location_name_to_id={r['name']:r['id'] for r in CONTENT['locations']+CATALOG['locations']}

    # Groups make AP's standard exclude_locations / priority_locations / local_items / start_hints usable by theme.
    location_name_groups={}
    for _row in CATALOG['locations']:
        _family=_row['family']
        _theme={'memorabilia':'Memorabilia','challenge':'Challenges','quest':'Quests','cosmetic':'Cosmetic Purchases',
                'dance':'Dance Purchases','story':'Story Completions','optional':'Achievements','song':'Song Completions',
                'skill':'Skill Nodes','upgrade':'Upgrade Nodes'}.get(_family)
        if _family=='rank':
            _theme='Song Star Ratings' if _row.get('completion_family') in ('song','challenge') else 'Story Star Ratings'
        elif _family=='difficulty':
            _theme='Song Difficulty Checks' if _row.get('completion_family')=='song' else 'Story Difficulty Checks'
        if _theme:
            location_name_groups.setdefault(_theme,set()).add(_row['name'])
        if _row.get('predicate')=='node-interaction' and _row.get('item_tag','').split('.')[3:4]==['Charlie']:
            location_name_groups.setdefault('Charlie Tree Nodes',set()).add(_row['name'])
    item_name_groups={}
    for _item in CATALOG['items']:
        _group={'power':'Idol Powers','skill':'Active Skills','upgrade':'Passive Upgrades','access':'Mission Access','trap':'Traps','filler':'Filler'}.get(_item['family'])
        if _group:
            item_name_groups.setdefault(_group,set()).add(_item['name'])
    del _row,_family,_theme,_item,_group

    def generate_early(self):
        self.content=CATALOG if self.options.content_profile else CONTENT
        if not self.options.content_profile:
            self.rows=self.content['locations']
            self.item_rows=self.content['items']
            self.runtime_goal=None
            self.settings={}
            return
        supplied={name:getattr(self.options,name).value if hasattr(self.options,name) else default for name,default in DEFAULTS.items()}
        self.rows,self.item_rows,self.runtime_goal,self.settings=resolve(self.content,supplied,self.random)

    def create_regions(self):
        menu=Region('Menu',self.player,self.multiworld)
        encore=Region('The Encore',self.player,self.multiworld)
        menu.connect(encore)
        self.regions_by_name={'The Encore':encore}
        if self.options.content_profile:
            for row in CATALOG['regions']:
                region=Region(row['name'],self.player,self.multiworld)
                encore.connect(region)
                self.regions_by_name[region.name]=region
            challenges=Region('Song Challenges',self.player,self.multiworld)
            encore.connect(challenges)
            self.regions_by_name[challenges.name]=challenges
        for row in self.rows:
            name=row.get('region','The Encore')
            if row['family']=='challenge':
                name='Song Challenges'
            region=self.regions_by_name[name]
            region.locations.append(DeadAsDiscoLocation(self.player,row['name'],row['id'],region))
        self.multiworld.regions.extend([menu,*self.regions_by_name.values()])

    def create_item(self,name):
        row=next((r for r in self.content['items'] if r['name']==name),None)
        if row is None:
            raise ValueError('Unknown Dead as Disco item: '+name)
        return DeadAsDiscoItem(name,getattr(ItemClassification,row['classification']),row['id'],self.player)

    def create_items(self):
        pool=self.item_rows[:]
        if self.options.content_profile:
            starters=set(CATALOG.get('starter_tags',[]))
            for row in [r for r in pool if r.get('tag') in starters]:
                # Vanilla gives these three skills free at New Game; AP mirrors that as start inventory.
                self.multiworld.push_precollected(self.create_item(row['name']))
                pool.remove(row)
        if self.options.content_profile and self.settings['shuffle_access']:
            region=CATALOG['regions'][self.settings['starting_mission']]['name']
            start=next(r for r in pool if r['family']=='access' and r['region']==region)
            self.multiworld.push_precollected(self.create_item(start['name']))
            pool.remove(start)
        self.multiworld.itempool.extend(self.create_item(r['name']) for r in pool)
        surplus=len(self.rows)-len(pool)
        traps=[]
        if self.options.content_profile and self.settings['traps']:
            import math
            candidates=[r for r in CATALOG['items'] if r['family']=='trap']
            weights=[self.settings['half_heart_trap_weight'] if r['effect']=='half-heart' else self.settings['silence_trap_weight'] for r in candidates]
            traps=self.random.choices(candidates,weights=weights,k=math.ceil(surplus*self.settings['trap_percentage']/100))
        self.multiworld.itempool.extend(self.create_item(r['name']) for r in traps)
        fan_share=self.settings.get('fan_pack_percentage',0) if self.options.content_profile else 0
        sizes=['Tiny Fan Pack','Small Fan Pack','Fan Pack','Large Fan Pack','Huge Fan Pack']
        filler=[self.random.choices(sizes,weights=[25,30,25,15,5])[0] if self.random.random()*100<fan_share else self.get_filler_item_name()
                for _ in range(surplus-len(traps))]
        self.multiworld.itempool.extend(self.create_item(name) for name in filler)

    def get_filler_item_name(self):
        return 'Disco Hint' if self.options.content_profile and self.settings.get('fan_pack_percentage',60)<100 else 'Fan Pack'

    def set_rules(self):
        if not self.options.content_profile:
            self.multiworld.completion_condition[self.player]=lambda state:state.has(CONTENT['items'][0]['name'],self.player)
            return
        powers=[r['name'] for r in self.item_rows if r['family'] in ('power','skill')]
        require_powers=lambda state:state.has_all(powers,self.player)
        access_names=[r['name'] for r in self.item_rows if r['family']=='access']
        self.multiworld.get_entrance('The Encore -> Song Challenges',self.player).access_rule=lambda state:require_powers(state) and state.has_all(access_names,self.player)
        if self.settings['shuffle_access']:
            access=[r for r in self.item_rows if r['family']=='access']
            for row in access:
                self.multiworld.get_entrance('The Encore -> '+row['region'],self.player).access_rule=lambda state,name=row['name']:state.has(name,self.player)
            # Optional hub rewards can depend on any Idol/story source. Do not
            # place entrance keys behind apparently early but locked shop stock.
            for row in self.rows:
                if row.get('region','The Encore')=='The Encore':
                    if row.get('predicate')=='node-interaction':
                        tree=row['item_tag'].split('.')[3]
                        key=next((r['name'] for r in access if r['region']=='Level.Lookup.'+tree),None)
                        # Charlie's initial tree is available in the hub. Idol
                        # trees follow their own mission, never every entrance
                        # key or the ability being shuffled at this node.
                        self.multiworld.get_location(row['name'],self.player).access_rule=lambda state,key=key:key is None or state.has(key,self.player)
                    else:
                        self.multiworld.get_location(row['name'],self.player).access_rule=lambda state:state.has_all([r['name'] for r in access],self.player)
        for row in self.rows:
            if row['family']=='rank' or row['family']=='difficulty' and row['difficulty'] in ('Hard','Very Hard'):
                location=self.multiworld.get_location(row['name'],self.player)
                previous=location.access_rule
                location.access_rule=lambda state,previous=previous:previous(state) and require_powers(state)
        # Node access never requires the ability rewarded by that node.
        by_id={r['id']:r for r in CATALOG['locations']}
        goal_ids=set(self.runtime_goal['records'])
        if self.runtime_goal['kind']==5:
            goal_ids.update(self.runtime_goal['story_records'])
        names={}
        for ident in sorted(goal_ids):
            row=by_id[ident]
            region=self.regions_by_name['Song Challenges' if row['family']=='challenge' else row.get('region','The Encore')]
            event=DeadAsDiscoLocation(self.player,'Goal record: '+row['name'],None,region)
            if row in self.rows:
                event.access_rule=self.multiworld.get_location(row['name'],self.player).access_rule
            if row['family']=='story':
                event.access_rule=require_powers
            name='Goal achieved: '+str(ident)
            event.place_locked_item(DeadAsDiscoItem(name,ItemClassification.progression,None,self.player))
            region.locations.append(event)
            names[ident]=name
        count=self.runtime_goal['count']
        required=[names[i] for i in self.runtime_goal['records']]
        story=[names[i] for i in self.runtime_goal['story_records'] if i in names]
        self.multiworld.completion_condition[self.player]=lambda state:sum(state.has(n,self.player) for n in required)>=count and (self.runtime_goal['kind']!=5 or state.has_all(story,self.player))

    def fill_slot_data(self):
        return dict(protocol=self.content['protocol'],pool=self.content['pool'],
            content_sha256=hashlib.sha256(json.dumps(self.content,sort_keys=True).encode()).hexdigest(),
            world_version=self.content['world_version'],location_ids=[r['id'] for r in self.rows],
            item_ids=[r['id'] for r in self.item_rows],options={k:sorted(v) if isinstance(v,(set,frozenset)) else v for k,v in self.settings.items()},
            goal=self.runtime_goal,death_link=bool(self.options.death_link),
            integration_mode='shuffled' if any(self.settings.get(k) for k in ('shuffle_skills','shuffle_powers','shuffle_upgrades','shuffle_access')) else 'additive',
            required_capabilities=['ownership']+(['node-interaction'] if any(r.get('predicate')=='node-interaction' for r in self.rows) else [])+
                (['reward-suppression'] if any(self.settings.get(k) for k in ('shuffle_skills','shuffle_powers','shuffle_upgrades')) else [])+
                (['mission-access'] if self.settings.get('shuffle_access') else [])+(['temporary-traps'] if self.settings.get('traps') else [])+(['fan-packs'] if self.settings.get('fan_pack_percentage') else []))
