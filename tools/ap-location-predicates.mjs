// Pure exact-schema predicates, shared by the decoder and mapping fixtures.
import assert from 'node:assert/strict';
export function completed(row, states, nodeInteractions=new Set(), altStates=null) {
    if(altStates&&BigInt(altStates['']??'0')>=BigInt(row.alt_threshold??1))return true;
    if(row.predicate==='node-interaction')return nodeInteractions.has(row.id);
    if(!states)return false;
    if(row.predicate==='purchased')return states['']==='4';
    if(row.predicate==='unlocked')return states['']==='1';
    if(row.predicate==='challenge-completion')return BigInt(states['/Completion Count']??'0')>0n;
    if(row.predicate==='story-completion')return Object.entries(states).some(([p,s])=>p.endsWith('/Completion Count')&&BigInt(s)>0n);
    if(row.predicate==='counter-threshold')return BigInt(states[row.path]??'0')>=BigInt(row.threshold);
    if(row.predicate==='highest-stars')return Object.entries(states).some(([p,s])=>p.endsWith('/Highest Star Rating')&&BigInt(s)>=BigInt(row.threshold));
    assert.fail('Unknown terminal predicate: '+row.predicate);
}
export function victory(goal,catalog,variables,checks){
    if(!goal?.records)return catalog.goal.tags.every(tag=>Object.entries(variables.get(tag)??{}).some(([p,s])=>p.endsWith('/Completion Count')&&BigInt(s)>0n));
    const byId=new Map(catalog.locations.map(r=>[r.id,r]));
    const done=id=>{const row=assertRow(id);return completed(row,variables.get(row.tag));};
    const assertRow=id=>{const row=byId.get(id);assert(row,'Unknown goal record');return row;};
    const story=goal.story_records.every(done);
    if(goal.kind===4)return goal.story_records.every(id=>completed({predicate:'highest-stars',threshold:5},variables.get(assertRow(id).tag)));
    const enough=goal.records.filter(id=>done(id)||checks.has(id)).length>=goal.count;
    return goal.kind===5?story&&enough:enough;
}
