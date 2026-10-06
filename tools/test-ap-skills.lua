-- Shared-mechanism fixture. This is not native gameplay validation.
package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local root='artifacts/ap-skill-fixture'
local function put(p,s) local f=assert(io.open(p,'w'));f:write(s);f:close() end
local values={}
local function name(text)
 local u=assert(io.tmpfile());u:close();values[u]=text
 debug.setmetatable(u,{__index={type=function() return 'FName' end,ToString=function(s) return values[s] end}})
 return u
end
FName=name
local owned,equipped={},{}
local calls=0
local data={IsValid=function() return true end,PlayerData={OwnedUpgrades=owned,EquippedUpgrades=equipped},
 GetFullName=function() return 'owner' end,GetCredits=function() return 50 end,
 IsUpgradeOwned=function(_,id) return owned[values[id.TagName]] or false end,
 IsUpgradeEquipped=function(_,id) return equipped[values[id.TagName]] or false end,
 RemoveOwnedUpgrade=function(_,id) calls=calls+1;owned[values[id.TagName]]=nil;equipped[values[id.TagName]]=nil end}
local boundary={slot='slot',dataOwner='owner'}
package.loaded.authority={boundary=function() return boundary,nil,data end,slotted=function() return {} end,
 tags=function(list) local out={};for tag,has in pairs(list) do if has then out[#out+1]=tag end end;table.sort(out);return out end}
local hooks={}
RegisterHook=function(path,pre,post) hooks[path:match(':([^:]+)$')]={pre=pre,post=post} end
local refused
local effects={}
package.loaded['power-removal']={effect=function(_,_,_,tag) effects[#effects+1]=tag;return {pawn=true,applied_before=false,cleaned=false,still_equipped=false} end,remove=function() end}
local config={nodeLocationsEnabled=true,nodeLocationsTest=true,rewardSuppressionTest=true,powerRemovalTest=true,nativeOwnershipRemoval=true,powerOwnershipRemoval=true,
 nodeJournal=root..'.journal',entitlementFile=root..'.entitlements',lease=root..'.lease',launchToken='test',
 gameSlot='slot',generation='test',nodeItems={['Tag.One']={id=1,asset='fixture'},['Tag.Two']={id=2},['Tag.Power']={id=3,ownershipFamily='power'}},
 suppressedNodes={['Tag.One']=true,['Tag.Two']=true,['Tag.Power']=true},
 authorizeMutation=function() end,refuseMutation=function(err) refused=err end}
put(config.lease,'test\n');put(config.entitlementFile,'');put(config.nodeJournal,'')
local module=require('skill-locations');module.start(config)
local function def(tag) return {IsValid=function() return true end,bIsToggleable=false,UpgradeIdTag={TagName=name(tag)}} end
local function param(v) return {get=function() return v end,set=function(_,next) v=next end} end
local loaded=def('Tag.One')
StaticFindObject=function() return loaded end
local catalog={IsValid=function() return true end,GetLocalPlayerPlaythroughData=function() return data end,
 ToggleUpgradeEquippedState=function(_,definition)
  assert(definition.bIsToggleable,'Native toggle policy must be enabled for active skill cleanup')
  hooks.ToggleUpgradeEquippedState.pre(nil,param(definition));equipped[values[definition.UpgradeIdTag.TagName]]=nil
 end}
FindAllOf=function() return {catalog} end
local a=def('Tag.One')
hooks.TryBuyUpgradeWithCredits.pre(nil,param(a));owned['Tag.One']=true;equipped['Tag.One']=true
hooks.TryBuyUpgradeWithCredits.post(nil,param(true),param(a))
assert(not refused and not owned['Tag.One'] and calls==1,'Purchased reward must be withheld')
assert(not loaded.bIsToggleable,'Shared definition flag must be restored synchronously')
local blocked=param(a);hooks.ToggleUpgradeEquippedState.pre(nil,blocked)
assert(blocked:get()==nil,'Taking a virtual node must not equip an unreceived skill')
local blockedPower=param(def('Tag.Power'));hooks.EquipOrSwapBossAbilityAtSlot.pre(nil,blockedPower)
assert(blockedPower:get()==nil,'Power slot interaction must not leak an unreceived reward')
-- Repeating a purchase cannot emit another location record.
hooks.TryBuyUpgradeWithCredits.pre(nil,param(a));owned['Tag.One']=true
hooks.TryBuyUpgradeWithCredits.post(nil,param(true),param(a))
assert(hooks.GetUpgradeAccessStateForLocalPlayer.post(nil,param(2),param({TagName=name('Tag.One')}))==4,
 'Post hooks receive original return before native inputs')
put(config.entitlementFile,'Tag.One\nTag.Two\n');owned['Tag.One']=true;owned['Tag.Two']=true
local before=assert(io.open(config.nodeJournal)):read('a')
hooks.AddOwnedUpgrade.post(param(data),param({TagName=name('Tag.Two')}))
assert(owned['Tag.Two'] and not refused,'AP entitlement must preserve native grant')
assert(assert(io.open(config.nodeJournal)):read('a')==before,'AP delivery must not claim node')
hooks.ToggleUpgradeEquippedState.pre(nil,param(def('Tag.Two')))
owned['Tag.Power']=true
hooks.AddOwnedUpgrade.post(param(data),param({TagName=name('Tag.Power')}))
assert(not owned['Tag.Power'] and not refused,'Vanilla power award must be checked and withheld')
local journal=assert(io.open(config.nodeJournal)):read('a')
local n=0;for _ in journal:gmatch('"kind":"node%-interaction"') do n=n+1 end
assert(n==3,'Exactly one check per real node interaction')
-- Protected tests may isolate a target-only refusal, never unrelated mutations.
config.suppressionTestTags={['Tag.One']=true,['Tag.Two']=true,['Tag.Power']=true}
config.completedNodesFile=root..'.completed';put(config.completedNodesFile,'');put(config.entitlementFile,'')
owned['Tag.One']=true;owned['Tag.Two']=true
data.RemoveOwnedUpgrade=function(_,id) if values[id.TagName]~='Tag.One' then owned[values[id.TagName]]=nil end end
assert(module.service(config,boundary,data) and owned['Tag.One'] and not owned['Tag.Two'],
 'One target-only refusal must not block an independent representative')
owned['Tag.Power']=true;owned['Unrelated']=true
data.RemoveOwnedUpgrade=function(_,id) owned[values[id.TagName]]=nil;owned['Unrelated']=nil end
assert(not pcall(module.service,config,boundary,data),'Unrelated ownership mutation must stop the run')
-- Native cleanup that re-grants ANOTHER suppressed target is a cascade, not an unrelated mutation.
put(config.entitlementFile,'');owned['Tag.Two']=true;owned['Tag.One']=nil;owned['Unrelated']=nil
data.RemoveOwnedUpgrade=function(_,id) owned[values[id.TagName]]=nil;owned['Tag.One']=true end
config.suppressionTestTags={['Tag.Two']=true}
assert(pcall(module.service,config,boundary,data),'Re-granted suppressed target must be tolerated')
assert(assert(io.open(config.nodeJournal)):read('a'):find('node%-suppression%-cascade'),'Cascade must be journaled')
-- Mutation errors signal refusal instead of silently leaving a leaked reward.
config.authorizeMutation=function() error('ambiguous owner') end
hooks.TryBuyUpgradeWithCredits.pre(nil,param(a));assert(refused)
assert(#effects>=1 and assert(io.open(config.nodeJournal)):read('a'):find('node%-effect%-cleanup'),'Every suppression must journal native effect evidence')
print('PASS: node purchase/check, withheld reward, AP item-before-node, power award, duplicate journal and hook refusal')
