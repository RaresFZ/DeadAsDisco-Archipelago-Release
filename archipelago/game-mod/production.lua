-- Shared native ownership path. Plain intents only across EngineTick services.
local authority=require('authority')
local ue=require('ue-values')
local plain=require('plain-json')
local M={}
local seen,attempted='',{}
local intent
-- Asset lookup by path is expensive (~2 ms each, ~48 items). Definitions only load/unload around
-- level transitions, so a short-lived cache of plain tag strings is enough; an in-flight grant refreshes it.
local cache,cachedAt
function M.available(config,force)
    if not force and cache and os.clock()-cachedAt<20 then return cache end
    local tags={}
    for _,row in pairs(config.productionItems or {}) do
        local d=StaticFindObject(row.asset)
        if d:IsValid() then tags[#tags+1]=row.tag end
    end
    table.sort(tags);cache,cachedAt=tags,os.clock()
    return tags
end
local function definition(config,id)
    local row=assert(config.productionItems[tostring(id)],'Unknown production item')
    local d=StaticFindObject(row.asset)
    if not d:IsValid() then return nil end -- no force-loading game content
    assert(d:IsA(StaticFindObject('/Script/Pagoda.PagodaPlayerUpgradeDefinition')),'Wrong upgrade class')
    assert(ue.string(d.UpgradeIdTag.TagName,'NameProperty')==row.tag,'Wrong exact ownership ID')
    assert(ue.number(d.EnabledState)==0,'Disabled/internal upgrade refused')
    return d,row
end
-- Vanilla purchase equips a skill immediately; a bare AddOwnedUpgrade does not (the effect would wait for a
-- reload). Equip through the native toggle, enabling the target flag only for this synchronous call.
local function equip(config,data,d,row)
    if row.family=='power' then return {skipped='power'} end
    if data:IsUpgradeEquipped(d.UpgradeIdTag) then return {already=true} end
    local catalog=authority.catalog(data)
    if not catalog then return {error='no-catalog'} end
    local toggleable=d.bIsToggleable
    assert(type(toggleable)=='boolean','Unsupported native toggleability flag')
    config.internalToggle=true
    d.bIsToggleable=true
    local ok,err=pcall(function() catalog:ToggleUpgradeEquippedState(d) end)
    d.bIsToggleable=toggleable
    config.internalToggle=false
    assert(d.bIsToggleable==toggleable,'Toggleability restoration failed')
    return {ok=ok,error=(not ok) and tostring(err) or nil,equipped=data:IsUpgradeEquipped(d.UpgradeIdTag)}
end
function M.service(config,boundary,data)
    if not config.productionEnabled then return false end
    assert(not config.coldRecoveryOnly,'Cold recovery cannot mutate')
    if intent then
        assert(plain.encode(boundary)==intent.boundary,'Native intent boundary changed')
        local d,row=definition(config,intent.id)
        if not d then return true end
        assert(os.time()-intent.epoch<=30,'Expired ownership intent')
        assert(plain.read(config.productionControl..'.intent-'..intent.index)==intent.command,'Durable intent changed')
        if data:IsUpgradeOwned(d.UpgradeIdTag) then
            intent=nil -- satisfied; never call native a second time
            return false
        end
        assert(not attempted[intent.index],'Ambiguous native intent refused')
        attempted[intent.index]=true
        data:AddOwnedUpgrade(d.UpgradeIdTag)
        assert(data:IsUpgradeOwned(d.UpgradeIdTag),'Native ownership did not establish target')
        local f=assert(io.open(config.evidence,'a'))
        assert(f:write(plain.encode({kind='production-native-grant',index=intent.index,item=intent.id,tag=row.tag}),'\n'));f:close()
        local result=equip(config,data,d,row)
        result.kind='production-equip';result.tag=row.tag
        local g=assert(io.open(config.evidence,'a'));g:write(plain.encode(result),'\n');g:close()
        intent=nil
        return true
    end
    local command=plain.read(config.productionControl)
    if command=='' or command==seen then return false end
    local index,id,token,epoch=command:match('^grant\n(%d+)\n(%d+)\n([^\n]+)\n(%d+)\n$')
    assert(index and token==config.launchToken,'Malformed/wrong-bound production intent')
    assert(tonumber(epoch)<=os.time()+2 and os.time()-tonumber(epoch)<=30,'Expired production intent')
    assert(plain.read(config.productionControl..'.intent-'..index)==command,'No durable native reservation')
    local d=definition(config,tonumber(id))
    if not d then return false end
    seen=command
    if data:IsUpgradeOwned(d.UpgradeIdTag) then return false end
    intent={index=index,id=tonumber(id),epoch=tonumber(epoch),command=command,boundary=plain.encode(boundary)}
    return true
end
return M
