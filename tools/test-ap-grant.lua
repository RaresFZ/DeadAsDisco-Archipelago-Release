package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local meta={}
local function wrap(kind,value)
 local u=assert(io.tmpfile());u:close();meta[u]={kind=kind,value=value}
 debug.setmetatable(u,{__index={type=function(s) return meta[s].kind end,ToString=function(s) return meta[s].value end,
 IsValid=function() return true end,ForEach=function(s,fn) for _,t in ipairs(meta[s].value) do fn({get=function() return {TagName=wrap('FName',t)} end}) end end},__len=function(s) return #meta[s].value end});return u
end
local root='artifacts/runtime/fixtures/ap-grant'
local function put(p,s) local f=assert(io.open(p,'w'));f:write(s);f:close() end
local valid={IsValid=function() return true end}
local world={GetFullName=function() return 'World /Game/Pagoda/Levels/DiveBar/L_DiveBar' end}
local player={IsValid=function() return true end,GetFullName=function() return 'local-player' end,GetWorld=function() return world end,
 Controller={IsValid=valid.IsValid,Player={IsValid=valid.IsValid,IsA=function(_,cls) return cls=='/Script/Engine.LocalPlayer' end}},
 HealthAttributeSet={Health={CurrentValue=100},MaxHealth={CurrentValue=100}}}
local definition={IsValid=valid.IsValid,IsA=function() return true end,EnabledState=0,bIsToggleable=false,UpgradeIdTag={TagName=wrap('FName','new')}}
StaticFindObject=function(p) if p=='asset' then return definition end;return p end
FindAllOf=function(c) assert(c=='PagodaPlayerCharacter');return {player} end
local owned=false;local calls=0
local data={PlayerData={OwnedUpgrades=wrap('TSet',{'old'}),EquippedUpgrades=wrap('TSet',{}),Credits=20}}
data.IsUpgradeOwned=function() return owned end;data.IsUpgradeEquipped=function() return false end
data.AddOwnedUpgrade=function(_,id)
 assert(id==definition.UpgradeIdTag);calls=calls+1
 if not owned then owned=true;data.PlayerData.OwnedUpgrades=wrap('TSet',{'old','new'}) end
end
local config={phase3Enabled=true,itemAsset='asset',itemTag='new',launchToken='token',proofPermit=root..'-permit',proofMarker=root..'-attempt'}
local boundary={world=world:GetFullName(),dataOwner='direct-data'}
os.remove(config.proofMarker..'.grant');os.remove(config.proofMarker..'.duplicate');os.remove(config.proofPermit)
local proof=require('proof')
local b=proof.run('baseline\n',config,boundary,data);assert(b.kind=='phase3-baseline' and b.state.enabledState==0)
assert(not pcall(proof.run,'proof-grant\n',config,boundary,data));assert(calls==0,'Inline grant forbidden')
assert(not pcall(proof.prepare,'proof-grant\n',config,boundary,data));assert(calls==0,'Grant without durable reservation')
put(config.proofMarker..'.grant','token\nproof-grant\n')
definition.EnabledState=2;assert(not pcall(proof.prepare,'proof-grant\n',config,boundary,data));assert(calls==0);definition.EnabledState=0
config.itemTag='other';assert(not pcall(proof.prepare,'proof-grant\n',config,boundary,data));assert(calls==0);config.itemTag='new'
local intent=proof.prepare('proof-grant\n',config,boundary,data);assert(calls==0,'Preparation mutated game')
assert(not pcall(proof.dispatch,intent,config,boundary,data));assert(calls==0,'Dispatch without permit')
put(config.proofPermit,'token\n'..(os.time()-20)..'\n')
assert(not pcall(proof.dispatch,intent,config,boundary,data));assert(calls==0,'Expired permit')
put(config.proofPermit,'token\n'..os.time()..'\n')
assert(not pcall(proof.dispatch,intent,config,{world=boundary.world,dataOwner='other'},data));assert(calls==0)
local dispatched=proof.dispatch(intent,config,boundary,data);assert(calls==1 and owned)
assert(not pcall(proof.dispatch,intent,config,boundary,data));assert(calls==1,'Blind dispatch replay')
local g=proof.complete(dispatched,config,boundary,data);assert(g.after.owned and g.after.maxHealth-g.before.maxHealth==0 and calls==1)
assert(type(g.native_ms)=='number')
put(config.proofMarker..'.duplicate','token\nproof-duplicate\n')
assert(not pcall(proof.prepare,'proof-duplicate\n',config,boundary,data));assert(calls==1,'Ownership is not active effect')
-- Fixture models natural reconstruction, not a forced native effect.
player.HealthAttributeSet.MaxHealth.CurrentValue=110
data.PlayerData.EquippedUpgrades=wrap('TSet',{'new'})
data.IsUpgradeEquipped=function() return true end
local dup=proof.prepare('proof-duplicate\n',config,boundary,data)
proof.dispatch(dup,config,boundary,data)
local d=proof.complete(dup,config,boundary,data);assert(d.after.maxHealth==110 and calls==2)
assert(not pcall(proof.dispatch,dup,config,boundary,data));assert(calls==2)
config.phase3Enabled=false;assert(not pcall(proof.run,'observe\n',config,boundary,data))
print('PASS: actual staged proof separates preparation/native/deferred capture; requires durable intent/fresh permit/stable authority; ownership alone refuses duplicate; reconstructed target equipment/effect and at-most-once dispatch. Fixture only.')
