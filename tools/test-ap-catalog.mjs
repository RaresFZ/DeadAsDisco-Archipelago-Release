import fs from 'node:fs';
import assert from 'node:assert/strict';
import {completed,victory} from './ap-location-predicates.mjs';
const catalog=JSON.parse(fs.readFileSync(process.argv[2]??'archipelago/apworld/dead_as_disco/catalog.json'));
const schemas=new Map(JSON.parse(fs.readFileSync('archipelago/data/save-variables.json')).filter(r=>r.scope==='Progression.Scope.Playthrough').map(r=>[r.tag,r]));
assert.equal(new Set(catalog.locations.map(r=>r.id)).size,catalog.locations.length);
assert.equal(new Set(catalog.locations.map(r=>r.name)).size,catalog.locations.length);
assert.equal(new Set(catalog.items.map(r=>r.id)).size,catalog.items.length);
assert.equal(new Set(catalog.items.map(r=>r.name)).size,catalog.items.length);
const regionNames=new Set(['The Encore','Song Challenges',...catalog.regions.map(r=>r.name)]);
for(const row of catalog.locations){
 assert(schemas.has(row.tag));assert(regionNames.has(row.region??'The Encore'));
 if(row.path)assert(schemas.get(row.tag).children.includes(row.path.slice(1)));
 if(row.predicate==='node-interaction'){
  assert(catalog.items.some(i=>i.tag===row.item_tag));
  assert(!completed(row,{'':'4'}),'AP receipt must not manufacture a node check');
  assert(completed(row,{'':'0'},new Set([row.id])));
 }else if(row.predicate==='counter-threshold'){
  assert(!completed(row,{[row.path]:String(row.threshold-1)}));
  assert(completed(row,{[row.path]:String(row.threshold)}));
 }
}
assert(!completed({predicate:'counter-threshold',path:'/Easy Stats/Completion Count',threshold:1},{'/Hard Stats/Completion Count':'1'}),'Exact difficulty must not alias or-higher stats');
assert(!completed({predicate:'highest-stars',threshold:5},{'/Normal Stats/Highest Score':'99999999'}),'Raw score must not become star rating');
assert(completed({predicate:'highest-stars',threshold:5},{'/Hard Stats/Highest Star Rating':'5'}));
assert(!completed({predicate:'challenge-completion'},{'/Highest Star Rating':'5','/Completion Count':'0'}));
const stories=catalog.locations.filter(r=>r.family==='story');
const variables=new Map(stories.map(r=>[r.tag,{'/Easy Stats/Completion Count':'1','/Easy Stats/Highest Star Rating':'4'}]));
const goal={kind:4,count:stories.length,records:stories.map(r=>r.id),story_records:stories.map(r=>r.id)};
assert(!victory(goal,catalog,variables,new Set()));
for(const v of variables.values())v['/Easy Stats/Highest Star Rating']='5';
assert(victory(goal,catalog,variables,new Set()));
console.log(JSON.stringify({status:'catalog-and-terminal-predicates-pass',locations:catalog.locations.length,items:catalog.items.length}));
