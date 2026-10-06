// Read-only GVAS save scope helpers (field/tag/savedScopes) shared by the JavaScript reference decoder tools.
import fs from 'node:fs';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {readTaggedSave} from './read-tagged-save.mjs';
export const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
export const field=(fields,name)=>{const rows=fields.filter(p=>p.name===name&&p.status==='decoded');assert.equal(rows.length,1,`Missing/ambiguous decoded field ${name}`);return rows[0].value;};
export const tag=v=>field(v,'TagName');
export function savedScopes(parsed){
 const global=parsed.header.saveClass.endsWith('.PagodaGlobalProgressSaveGame');
 const scopes=global?[{scope:'Progression.Scope.Global',context:'None',fields:field(parsed.properties,'GlobalScopeSnapshot')}]:field(parsed.properties,'ScopeSnapshots').map(s=>({scope:tag(field(s.key,'Tag')),context:field(s.key,'Context'),fields:s.value}));
 const seen=new Set();
 for(const s of scopes){const k=JSON.stringify([s.scope,s.context]);assert(!seen.has(k),'Duplicate scope context');seen.add(k);s.variables=field(s.fields,'Variables');const tags=s.variables.map(x=>tag(x.key));assert.equal(new Set(tags).size,tags.length,'Duplicate scoped variable');}
 return scopes;
}
