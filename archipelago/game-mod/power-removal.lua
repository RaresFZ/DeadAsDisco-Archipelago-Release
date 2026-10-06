-- Distinct protected power-removal path: exact target sets + native effect cleanup.
local authority=require('authority')
local ue=require('ue-values')
local players=require('players')
local M={}
local function applied(component)
    local list=component.AppliedUpgrades;assert(#list<=128,'Applied upgrade cap')
    local out={}
    list:ForEach(function(_,value)
        local definition=value:get().UpgradeDef
        assert(definition:IsValid(),'Invalid applied upgrade definition')
        out[#out+1]=ue.string(definition.UpgradeIdTag.TagName,'NameProperty')
    end)
    assert(#out==#list,'Partial applied upgrade read');table.sort(out);return out
end
function M.remove(config,data,id,tag)
    assert(config.powerRemovalTest or config.powerRemovalValidated,'Unvalidated power removal refused')
    local boundary,_,current=authority.boundary(config.gameSlot)
    assert(boundary and current:GetFullName()==data:GetFullName(),'Power removal owner changed')
    config.authorizeMutation(boundary,data)
    local found
    for _,p in ipairs(FindAllOf('PagodaPlayerCharacter') or {}) do
        if p:IsValid() and not p:GetFullName():find('Default__',1,true) and p:GetWorld():IsValid() and p:GetWorld():GetFullName()==boundary.world then
            local controller=p.Controller
            if controller:IsValid() and controller.Player:IsValid() and controller.Player:IsA(StaticFindObject('/Script/Engine.LocalPlayer')) then
                assert(not found,'Ambiguous power cleanup player');found=p
            end
        end
    end
    assert(found,'No authoritative power cleanup player')
    local component=found.PlayerUpgradeComponent
    authority.identity(component,'PagodaPlayerUpgradeComponent')
    assert(component:GetOuter():GetFullName()==found:GetFullName(),'Wrong power cleanup component owner')
    local before=applied(component)
    local slots=authority.slotted(data)
    config.phase='power-owned-remove'
    data.PlayerData.OwnedUpgrades:Remove(id)
    config.phase='power-equipped-remove'
    data.PlayerData.EquippedUpgrades:Remove(id)
    for slot,t in pairs(slots) do
        if t==tag then
            config.phase='power-slot-remove'
            data.PlayerData.SlottedBossAbilityUpgrades:Remove(slot)
            config.phase='power-slot-state-remove'
            component.SlottedBossAbilityStates:Remove(slot)
        end
    end
    config.phase='power-handle-unequipped'
    component:HandleUpgradeEquippedStateChanged(id,false)
    local after=applied(component)
    local expected={};for _,t in ipairs(before) do if t~=tag then expected[#expected+1]=t end end
    assert(table.concat(after,'|')==table.concat(expected,'|'),'Power cleanup changed unrelated native grants')
    assert(not component:IsUpgradeEquipped(id),'Native power still equipped')
end
-- Withhold only the usable form of a power: boss slots, slot states and any applied
-- native effect. Ownership/equipment sets are never touched (the game re-grants them).
function M.gate(config,data,id,tag)
    assert(config.powerRemovalTest or config.powerRemovalValidated,'Unvalidated power gate refused')
    local boundary,_,current=authority.boundary(config.gameSlot)
    assert(boundary and current:GetFullName()==data:GetFullName(),'Power gate owner changed')
    config.authorizeMutation(boundary,data)
    local slots=authority.slotted(data)
    local player=players.fresh(boundary.world)
    local component,before
    if player then
        component=player.PlayerUpgradeComponent
        authority.identity(component,'PagodaPlayerUpgradeComponent')
        assert(component:GetOuter():GetFullName()==player:GetFullName(),'Wrong power gate component owner')
        before=applied(component)
    end
    local cleared=0
    for slot,t in pairs(slots) do
        if t==tag then
            config.phase='gate-slot-remove'
            data.PlayerData.SlottedBossAbilityUpgrades:Remove(slot)
            if component then component.SlottedBossAbilityStates:Remove(slot) end
            cleared=cleared+1
        end
    end
    if component then
        config.phase='gate-handle-unequipped'
        component:HandleUpgradeEquippedStateChanged(id,false)
        local after=applied(component)
        local expected={};for _,t in ipairs(before) do if t~=tag then expected[#expected+1]=t end end
        assert(table.concat(after,'|')==table.concat(expected,'|'),'Power gate changed unrelated native grants')
    end
    return {slots_cleared=cleared,pawn=component~=nil}
end
-- Effect evidence/cleanup after native ownership removal for ANY owned-upgrade
-- family. A pawn that does not exist yet has nothing applied; its component
-- builds effects from ownership later. Returns plain evidence only.
function M.effect(config,data,id,tag)
    local boundary,_,current=authority.boundary(config.gameSlot)
    assert(boundary and current:GetFullName()==data:GetFullName(),'Effect cleanup owner changed')
    local player=players.fresh(boundary.world)
    if not player then return {pawn=false} end
    local component=player.PlayerUpgradeComponent
    authority.identity(component,'PagodaPlayerUpgradeComponent')
    assert(component:GetOuter():GetFullName()==player:GetFullName(),'Wrong effect cleanup component owner')
    local before=applied(component)
    local had=false;for _,t in ipairs(before) do if t==tag then had=true end end
    local cleaned=false
    if had then
        component:HandleUpgradeEquippedStateChanged(id,false)
        local after=applied(component)
        local expected={};for _,t in ipairs(before) do if t~=tag then expected[#expected+1]=t end end
        assert(table.concat(after,'|')==table.concat(expected,'|'),'Effect cleanup changed unrelated native grants')
        cleaned=true
    end
    return {pawn=true,applied_before=had,cleaned=cleaned,still_equipped=component:IsUpgradeEquipped(id)}
end
return M
