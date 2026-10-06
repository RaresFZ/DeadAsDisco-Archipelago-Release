-- Fixture: a power the game keeps re-slotting must never stop the bridge (live regression), and unreceived powers
-- cannot be activated even while slotted. Not native gameplay validation.
package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local root='artifacts/ap-gate-fixture'
local function put(p,s) local f=assert(io.open(p,'w'));f:write(s);f:close() end
local values={}
local function name(text)
 local u=assert(io.tmpfile());u:close();values[u]=text
 debug.setmetatable(u,{__index={type=function() return 'FName' end,ToString=function(s) return values[s] end}})
 return u
end
FName=name
local slots={[0]='Tag.Power'}
local data={IsValid=function() return true end,PlayerData={OwnedUpgrades={},EquippedUpgrades={}},
 GetFullName=function() return 'owner' end,IsUpgradeOwned=function() return true end,IsUpgradeEquipped=function() return false end}
local boundary={slot='slot',dataOwner='owner'}
package.loaded.authority={boundary=function() return boundary,nil,data end,slotted=function() local out={};for k,v in pairs(slots) do out[k]=v end;return out end,
 tags=function() return {} end}
local gates=0
package.loaded['power-removal']={gate=function() gates=gates+1;return {slots_cleared=0} end,effect=function() return {pawn=false} end}
local hooks={}
RegisterHook=function(path,pre,post) hooks[path:match(':([^:]+)$')]={pre=pre,post=post} end
local refused
local config={nodeLocationsEnabled=true,nodeLocationsValidated=true,rewardSuppressionValidated=true,powerRemovalValidated=true,
 nodeJournal=root..'.journal',entitlementFile=root..'.entitlements',completedNodesFile=root..'.completed',lease=root..'.lease',
 launchToken='t',gameSlot='slot',generation='g',nodeItems={['Tag.Power']={id=7,ownershipFamily='power'}},
 suppressedNodes={['Tag.Power']=true},authorizeMutation=function() end,refuseMutation=function(err) refused=err end}
put(config.lease,'t\n');put(config.entitlementFile,'');put(config.completedNodesFile,'');put(config.nodeJournal,'')
local module=require('skill-locations');module.start(config)
-- The slot never clears (the game re-slots it): ten services must neither raise nor refuse the bridge.
for _=1,10 do assert(pcall(module.service,config,boundary,data),'a persistently re-slotted power must not raise') end
assert(not refused and not config.mutationsRefused,'bridge must stay alive')
assert(gates<=5,'attempts must be bounded and then back off, got '..gates)
local journal=assert(io.open(config.nodeJournal)):read('a')
assert(journal:find('node%-suppression%-refused') or journal:find('node%-suppression%-oscillation'),'the failure must be journaled')
-- While unreceived, activation is denied even though the power is slotted.
local function param(v) return {get=function() return v end} end
assert(hooks.CanActivateBossAbilityAtSlot.post(nil,param(true),param(0))==false,'unreceived power must not activate')
assert(hooks.CanActivateBossAbilityAtSlot.post(nil,param(true),param(1))==nil,'empty slot is not touched')
-- Once received (entitlement published) the next service lifts the gate.
put(config.entitlementFile,'Tag.Power\n')
module.service(config,boundary,data)
assert(hooks.CanActivateBossAbilityAtSlot.post(nil,param(true),param(0))==nil,'received power must activate normally')
print('PASS: persistent power re-slotting is isolated (bounded, journaled, bridge alive); unreceived powers cannot activate; received ones can')
