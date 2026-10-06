// External read-only reconciliation: never executes in the game thread.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {readTaggedSave} from './read-tagged-save.mjs';
import {savedScopes,field,tag,sha} from './sync-proof-offline.mjs';
import {completed,victory} from './ap-location-predicates.mjs';
const [provisioningFile,catalogFile]=process.argv.slice(2);
const provision=JSON.parse(fs.readFileSync(provisioningFile));
const session=JSON.parse(fs.readFileSync(provision.session_file));
assert.equal(session.status,'isolated');assert.equal(session.parked,provision.parked);
assert.equal(session.copySource,provision.source);
assert.equal(sha(fs.readFileSync(provision.parked+'/SaveGames/'+provision.game_slot+'.sav')),provision.original_save_sha256);
const catalog=JSON.parse(fs.readFileSync(catalogFile));
assert.equal(catalog.protocol,2);
const input=fs.readFileSync(0,'utf8');
const settings=input.trim()?JSON.parse(input):null;
const known=new Set(catalog.locations.map(r=>r.id));
const allowed=new Set(settings?.location_ids??known);
assert([...allowed].every(id=>known.has(id)),'Unknown enabled location');
const path=session.saved+'/SaveGames/'+provision.game_slot+'.sav';
const before=fs.statSync(path),bytes=fs.readFileSync(path),after=fs.statSync(path);
assert.equal(before.mtimeMs,after.mtimeMs,'Save changed during observation');
assert.equal(before.size,bytes.length);
const save=readTaggedSave(bytes,provision.game_slot+'.sav');
const contexts=savedScopes(save);
const PT=contexts.filter(c=>c.scope==='Progression.Scope.Playthrough');
assert.equal(PT.length,1);assert.equal(PT[0].context,provision.check_context,'Wrong saved playthrough');
function leaves(v,p='',out={}){
 if(v.structType.endsWith('ValueSnapshot'))out[p]=String(field(v.fields,'CurrentState'));
 else {assert(v.structType.endsWith('CompositeSnapshot'));for(const e of field(v.fields,'InnerVariables'))leaves(e.value,p+'/'+e.key,out);}
 return out;
}
const variables=new Map(PT[0].variables.map(v=>[tag(v.key),leaves(v.value)]));
const checks=[];
const nodes=new Set();
if(provision.node_journal&&fs.existsSync(provision.node_journal)){
 const lines=fs.readFileSync(provision.node_journal,'utf8').split('\n');
 // Last incomplete append may be retried; no partial record becomes a check.
 if(lines.at(-1)!=='')lines.pop();
 for(const line of lines.filter(Boolean)){
  const row=JSON.parse(line);
  assert.equal(row.generation,provision.generation);assert.equal(row.game_slot,provision.game_slot);
  assert.equal(row.protection_token,provision.launch_token);
  if(row.kind==='node-interaction'){
   const location=catalog.locations.find(l=>l.id===row.id&&l.item_tag===row.tag);
   assert(location?.predicate==='node-interaction','Invalid node journal mapping');nodes.add(row.id);
  }
 }
}
for(const row of catalog.locations){
 if(!allowed.has(row.id))continue;
 assert.equal(row.scope,'Progression.Scope.Playthrough','Cross-playthrough global checks forbidden');
 if(completed(row,variables.get(row.tag),nodes,row.alt_tag?variables.get(row.alt_tag):null))checks.push(row.id);
}
const player=field(save.properties,'PlayerData');
console.log(JSON.stringify({protocol:2,save_sha256:sha(bytes),checks,owned:field(player,'OwnedUpgrades').map(tag).sort(),
 victory:victory(settings?.goal,catalog,variables,new Set(checks))}));
