-- Shared native ownership path. Plain intents only across EngineTick services.
local authority=require('authority')
local ue=require('ue-values')
local plain=require('plain-json')
local M={}
local seen,attempted='',{}
local intent
-- Asset lookup by path is expensive (~2-8 ms each on a slow PC, ~48 items: a 400 ms freeze when all were scanned at once).
-- Only a received (entitled) item the game does not own yet can be waiting for a grant, so only those are looked up, a few
-- per tick, with a per-tag cache. A tag missing from the list is simply retried by the client on the next snapshot.
local looked={}
local assets,assetsFrom
local LOADED_TTL,UNLOADED_TTL,MAX_LOOKUPS=20,6,6
function M.available(config,owned)
    if assetsFrom~=config.productionItems then
        assets,assetsFrom,looked={},config.productionItems,{}
        for _,row in pairs(config.productionItems or {}) do assets[row.tag]=row.asset end
    end
    local have={};for _,t in ipairs(owned or {}) do have[t]=true end
    local now,lookups,tags=os.clock(),0,{}
    local text=config.entitlementFile and plain.read(config.entitlementFile) or ''
    for tag in text:gmatch('[^\r\n]+') do
        local asset=assets[tag]
        if asset and not have[tag] then
            local entry=looked[tag]
            if (not entry or now-entry.at>(entry.loaded and LOADED_TTL or UNLOADED_TTL)) and lookups<MAX_LOOKUPS then
                lookups=lookups+1
                entry={loaded=StaticFindObject(asset):IsValid(),at=now};looked[tag]=entry
            end
            if entry and entry.loaded then tags[#tags+1]=tag end
        end
    end
    table.sort(tags)
    return tags
end
-- True while a grant is prepared and waiting for its native call (the next service must not be delayed).
function M.busy() return intent~=nil end
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
