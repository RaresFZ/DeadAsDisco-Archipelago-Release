package.path='archipelago/game-mod/?.lua;'..package.path
local owned={Target=true,Other=true};local equipped={Target=true,Other=true}
local slots={[0]='Target',[1]='Other'};local states={[0]=true,[1]=true}
local function set(values) return {Remove=function(_,id) values[id.TagName]=nil end} end
local function map(values) return {Remove=function(_,slot) values[slot]=nil end} end
local function array(tags)
 local values={}
 for _,tag in ipairs(tags) do values[#values+1]={UpgradeDef={IsValid=function() return true end,UpgradeIdTag={TagName=tag}}} end
 return setmetatable({ForEach=function(_,fn) for i,v in ipairs(values) do fn(i,{get=function() return v end}) end end},{__len=function() return #values end})
end
local component={IsValid=function() return true end,GetFullName=function() return 'component' end,
 AppliedUpgrades=array({'Target','Other'}),SlottedBossAbilityStates=map(states),
 IsUpgradeEquipped=function(_,id) return equipped[id.TagName] or false end}
local cleanup=0
component.HandleUpgradeEquippedStateChanged=function(_,id,enabled)
 assert(id.TagName=='Target' and enabled==false);cleanup=cleanup+1
 component.AppliedUpgrades=array({'Other'})
end
local player={IsValid=function() return true end,GetFullName=function() return 'player' end,
 GetWorld=function() return {IsValid=function() return true end,GetFullName=function() return 'world' end} end,
 Controller={IsValid=function() return true end,Player={IsValid=function() return true end,IsA=function() return true end}},
 PlayerUpgradeComponent=component}
component.GetOuter=function() return player end
local data={GetFullName=function() return 'data' end,PlayerData={OwnedUpgrades=set(owned),EquippedUpgrades=set(equipped),SlottedBossAbilityUpgrades=map(slots)}}
package.loaded.authority={boundary=function() return {world='world'},nil,data end,
 identity=function(o,class) assert(o==component and class=='PagodaPlayerUpgradeComponent') end,
 slotted=function() local out={};for k,v in pairs(slots) do out[k]=v end;return out end}
package.loaded['ue-values']={string=function(v) return v end}
FindAllOf=function(class) assert(class=='PagodaPlayerCharacter');return {player} end
StaticFindObject=function() return {} end
local config={powerRemovalTest=true,gameSlot='slot',authorizeMutation=function(_,d) assert(d==data) end}
local module=require('power-removal');module.remove(config,data,{TagName='Target'},'Target')
assert(not owned.Target and not equipped.Target and not slots[0] and not states[0] and cleanup==1)
assert(owned.Other and equipped.Other and slots[1]=='Other' and states[1],'Other target state must survive')
component.AppliedUpgrades=array({'Target','Other'})
component.HandleUpgradeEquippedStateChanged=function() component.AppliedUpgrades=array({}) end
assert(not pcall(module.remove,config,data,{TagName='Target'},'Target'),'Unrelated native cleanup must refuse')
-- Effect evidence for any owned-upgrade family: clean only a leaked target effect.
component.AppliedUpgrades=array({'Target','Other'});cleanup=0
component.HandleUpgradeEquippedStateChanged=function(_,id,enabled) assert(id.TagName=='Target' and enabled==false);cleanup=cleanup+1;component.AppliedUpgrades=array({'Other'}) end
equipped.Target=nil
local effect=module.effect(config,data,{TagName='Target'},'Target')
assert(effect.pawn and effect.applied_before and effect.cleaned and cleanup==1 and not effect.still_equipped,'Leaked effect must be cleaned exactly once')
effect=module.effect(config,data,{TagName='Target'},'Target')
assert(effect.pawn and not effect.applied_before and not effect.cleaned and cleanup==1,'Absent effect must not call native cleanup')
component.AppliedUpgrades=array({'Target','Other'});component.HandleUpgradeEquippedStateChanged=function() component.AppliedUpgrades=array({}) end
assert(not pcall(module.effect,config,data,{TagName='Target'},'Target'),'Effect cleanup must refuse unrelated grant loss')
local original=FindAllOf;FindAllOf=function() return {} end
assert(not module.effect(config,data,{TagName='Target'},'Target').pawn,'No pawn means no applied effect to clean')
FindAllOf=original
-- Slot gate: clears only the target slot/state/applied effect and never touches ownership.
owned.Target=true;equipped.Target=true;slots[0]='Target';states[0]=true
component.AppliedUpgrades=array({'Target','Other'});cleanup=0
component.HandleUpgradeEquippedStateChanged=function(_,id,enabled) assert(id.TagName=='Target' and enabled==false);cleanup=cleanup+1;component.AppliedUpgrades=array({'Other'}) end
local gate=module.gate(config,data,{TagName='Target'},'Target')
assert(gate.slots_cleared==1 and not slots[0] and not states[0] and cleanup==1,'Gate must clear the slot and applied effect')
assert(owned.Target and equipped.Target and slots[1]=='Other','Gate must leave ownership/equipment and other slots alone')
component.AppliedUpgrades=array({'Target','Other'});component.HandleUpgradeEquippedStateChanged=function() component.AppliedUpgrades=array({}) end
assert(not pcall(module.gate,config,data,{TagName='Target'},'Target'),'Gate must refuse unrelated grant loss')
print('PASS: exact power ownership/equipment/slot removal, native cleanup, effect evidence and unrelated grant refusal')
