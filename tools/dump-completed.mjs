// Reference completed-record/victory list for parity testing the Python decoder.
import fs from 'node:fs';
import path from 'node:path';
import {readTaggedSave} from './read-tagged-save.mjs';
import {savedScopes,field,tag} from './sync-proof-offline.mjs';
import {completed,victory} from './ap-location-predicates.mjs';
const [file,catalogFile,settingsFile]=process.argv.slice(2);
const catalog=JSON.parse(fs.readFileSync(catalogFile));
const settings=settingsFile&&fs.existsSync(settingsFile)?JSON.parse(fs.readFileSync(settingsFile)):null;
const save=readTaggedSave(fs.readFileSync(file),path.basename(file));
const PT=savedScopes(save).filter(c=>c.scope==='Progression.Scope.Playthrough')[0];
function leaves(v,p='',out={}){if(v.structType.endsWith('ValueSnapshot'))out[p]=String(field(v.fields,'CurrentState'));else for(const e of field(v.fields,'InnerVariables'))leaves(e.value,p+'/'+e.key,out);return out;}
const variables=new Map(PT.variables.map(v=>[tag(v.key),leaves(v.value)]));
const allowed=new Set(settings?.location_ids??catalog.locations.map(r=>r.id));
const checks=catalog.locations.filter(r=>allowed.has(r.id)&&completed(r,variables.get(r.tag),new Set(),r.alt_tag?variables.get(r.alt_tag):null)).map(r=>r.id);
console.log(JSON.stringify({checks,victory:victory(settings?.goal,catalog,variables,new Set(checks))}));
