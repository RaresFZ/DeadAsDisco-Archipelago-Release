// Canonical summary of a progression save for decoder parity tests (Python port vs this reference).
import fs from 'node:fs';
import path from 'node:path';
import {readTaggedSave} from './read-tagged-save.mjs';
import {savedScopes,field,tag} from './sync-proof-offline.mjs';
function leaves(v,p='',out={}){
 if(v.structType.endsWith('ValueSnapshot'))out[p]=String(field(v.fields,'CurrentState'));
 else for(const e of field(v.fields,'InnerVariables'))leaves(e.value,p+'/'+e.key,out);
 return out;
}
const file=process.argv[2],name=path.basename(file);
const save=readTaggedSave(fs.readFileSync(file),name);
const scopes=savedScopes(save).map(s=>({scope:s.scope,context:s.context,variables:Object.fromEntries(s.variables.map(v=>[tag(v.key),leaves(v.value)]))}));
const out={scopes};
if(name.includes('PT')){const d=field(save.properties,'PlayerData');out.owned=field(d,'OwnedUpgrades').map(tag).sort();out.equipped=field(d,'EquippedUpgrades').map(tag).sort();}
console.log(JSON.stringify(out));
