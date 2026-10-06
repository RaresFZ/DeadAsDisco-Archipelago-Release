-- Fresh wrappers only; the Phase-2C direct-owner contract, with strict Outer check.
local ue=require('ue-values')
local M={}
function M.identity(o,expected)
    assert(o and o:IsValid(),'Invalid object')
    local name=o:GetFullName();assert(not name:find('Default__',1,true),'Default object')
    if expected then assert(o:GetClass():GetFullName()=='Class /Script/Pagoda.'..expected,'Wrong class') end
    return name
end
function M.one(class)
    local found
    for _,o in ipairs(FindAllOf(class) or {}) do
        if o:IsValid() and not o:GetFullName():find('Default__',1,true) and o:GetWorld():IsValid() then
            assert(not found,'Ambiguous subsystem');found=o
        end
    end
    return found
end
function M.tags(container)
    assert(type(container)=='userdata' and container:type()=='TSet' and container:IsValid(),'Unsupported ownership wrapper')
    assert(#container<=256,'Ownership cap')
    local out,seen={},{}
    container:ForEach(function(element)
        assert(#out<256,'Ownership iteration cap')
        local tag=ue.string(element:get().TagName,'NameProperty')
        assert(tag~='' and tag~='None' and not seen[tag],'Invalid/duplicate tag')
        seen[tag]=true;out[#out+1]=tag
    end)
    assert(#out==#container,'Partial ownership read');table.sort(out)
    return out
end
function M.slotted(data)
    local container=data.PlayerData.SlottedBossAbilityUpgrades
    assert(type(container)=='userdata' and container:type()=='TMap' and container:IsValid(),'Unsupported boss-slot wrapper')
    assert(#container<=8,'Boss-slot cap')
    local out,count={},0
    container:ForEach(function(k,v)
        local slot=k:get();assert(math.type(slot)=='integer' and not out[slot],'Invalid/duplicate boss slot')
        out[slot]=ue.string(v:get().TagName,'NameProperty');count=count+1
    end)
    assert(count==#container,'Partial boss-slot read');return out
end
local function inspect(s,slot)
    local owner=M.identity(s,'PagodaGameSavesSubsystem')
    local world=s:GetWorld():GetFullName()
    local current=ue.string(s.CurrentPlaythroughSlotName,'StrProperty')
    if current=='' or world:find('/Main_Menu/',1,true) or world:find('/Startup/',1,true) then return nil,'title-or-loading' end
    assert(current==slot,'Wrong active slot')
    local d=s.PlaythroughPlayerData;M.identity(d,'PagodaPlaythroughPlayerData')
    assert(type(d.bWasLoaded)=='boolean','Unsupported loaded Bool')
    if not d.bWasLoaded then return nil,'unloaded' end
    assert(d:GetWorld():IsValid() and d:GetWorld():GetFullName()==world,'Wrong data world')
    assert(d:GetOuter():IsValid() and d:GetOuter():GetFullName()==owner,'Wrong direct owner Outer')
    return {world=world,slot=current,savesOwner=owner,dataOwner=d:GetFullName()},nil,d,s
end
function M.boundary(slot)
    local s=M.one('PagodaGameSavesSubsystem')
    if not s then return nil,'no-subsystem' end
    return inspect(s,slot)
end
function M.recheck(s,slot)
    -- Same-callback only. Reacquire the direct data field and all identity/state
    -- guards; avoid a second GUObjectArray census. Never retain s across services.
    return inspect(s,slot)
end
-- The one upgrade catalog bound to this exact playthrough owner (never a census guess).
function M.catalog(data)
    local found
    for _,catalog in ipairs(FindAllOf('PagodaPlayerUpgradeCatalogSubsystem') or {}) do
        if catalog:IsValid() and catalog:GetLocalPlayerPlaythroughData():IsValid() and
            catalog:GetLocalPlayerPlaythroughData():GetFullName()==data:GetFullName() then
            assert(not found,'Ambiguous upgrade catalog');found=catalog
        end
    end
    return found
end
return M
