-- One protected representative mutation proof, not a production grant dispatcher.
local authority=require('authority')
local plain=require('plain-json')
local ue=require('ue-values')
local M={}
local baseline
local attempted={}
local function equipment(config,row)
    local out={}
    for _,t in ipairs(row.equippedTags.__array) do if t~=config.itemTag then out[#out+1]=t end end
    return plain.encode(plain.array(out))
end
local function player(world)
    local found
    for _,p in ipairs(FindAllOf('PagodaPlayerCharacter') or {}) do
        if p:IsValid() and not p:GetFullName():find('Default__',1,true) then
            local c=p.Controller
            if c:IsValid() and c.Player:IsValid() and c.Player:IsA(StaticFindObject('/Script/Engine.LocalPlayer')) then
                assert(not found,'Multiple local players');found=p
            end
        end
    end
    assert(found and found:GetWorld():GetFullName()==world,'No matching local player')
    assert(ue.number(found.HealthAttributeSet.Health.CurrentValue)>0,'Local player not alive')
    return found
end
local function capture(config,boundary,data)
    assert(boundary.world:find('/Levels/DiveBar/',1,true),'Proof restricted to idle Encore')
    local definition=StaticFindObject(config.itemAsset)
    assert(definition:IsValid() and definition:IsA(StaticFindObject('/Script/Pagoda.PagodaPlayerUpgradeDefinition')),'Wrong/absent mapped definition')
    assert(ue.string(definition.UpgradeIdTag.TagName,'NameProperty')==config.itemTag,'Wrong mapped item tag')
    assert(ue.number(definition.EnabledState)==0,'Item is not runtime Enabled')
    assert(definition.bIsToggleable==false,'Representative must be passive')
    local p=player(boundary.world)
    local row={owned=data:IsUpgradeOwned(definition.UpgradeIdTag),equipped=data:IsUpgradeEquipped(definition.UpgradeIdTag),
        ownedTags=plain.array(authority.tags(data.PlayerData.OwnedUpgrades)),equippedTags=plain.array(authority.tags(data.PlayerData.EquippedUpgrades)),
        credits=ue.number(data.PlayerData.Credits),maxHealth=ue.number(p.HealthAttributeSet.MaxHealth.CurrentValue),
        health=ue.number(p.HealthAttributeSet.Health.CurrentValue),player=p:GetFullName(),dataOwner=boundary.dataOwner,
        enabledState=0,passive=true}
    assert(type(row.owned)=='boolean' and type(row.equipped)=='boolean','Unsupported owned/equipped Bool')
    return row,definition
end
function M.run(command,config,boundary,data)
    assert(config.phase3Enabled==true,'Targeted Phase 3 mode not provisioned')
    local before,definition=capture(config,boundary,data)
    if command=='baseline\n' then
        assert(not baseline,'Baseline already captured');assert(not before.owned,'Representative already owned')
        baseline=before
        return {kind='phase3-baseline',state=before}
    end
    if command=='observe\n' then return {kind='phase3-observe',state=before} end
    error('Mutation requires staged prepare/dispatch/observe')
end
function M.prepare(command,config,boundary,data)
    assert(not config.coldRecoveryOnly,'Cold recovery forbids all native grants')
    assert(config.phase3Enabled==true,'Targeted Phase 3 mode not provisioned')
    assert(command=='proof-grant\n' or command=='proof-duplicate\n','Unsupported proof command')
    assert(baseline,'Fresh local baseline required')
    local before=capture(config,boundary,data)
    assert(before.credits==baseline.credits and equipment(config,before)==equipment(config,baseline),'Unrelated baseline changed')
    local marker=config.proofMarker..(command=='proof-grant\n' and '.grant' or '.duplicate')
    -- The external operator persists and fsyncs the reservation before publishing
    -- the command. No disk durability operation runs around the native mutation.
    assert(plain.read(marker)==config.launchToken..'\n'..command,'No durable external intent')
    assert(not attempted[command],'Proof command already attempted; never blindly retry')
    if command=='proof-grant\n' then
        assert(not before.owned and plain.encode(before.ownedTags)==plain.encode(baseline.ownedTags),'Ownership changed before grant')
        assert(before.maxHealth==baseline.maxHealth,'Max-health baseline changed')
    else
        assert(attempted['proof-grant\n'] and before.owned,'No prior proof grant in this process')
        assert(before.maxHealth==baseline.maxHealth+10,'First effect not established before duplicate')
        local expected={};for _,t in ipairs(baseline.ownedTags.__array) do expected[#expected+1]=t end
        expected[#expected+1]=config.itemTag;table.sort(expected)
        assert(plain.encode(before.ownedTags)==plain.encode(plain.array(expected)),'Unrelated ownership changed before duplicate')
    end
    return {command=command,before=before,boundary=plain.encode(boundary)}
end
function M.dispatch(intent,config,boundary,data)
    assert(config.phase3Enabled==true and baseline,'Unprepared dispatch')
    assert(plain.encode(boundary)==intent.boundary,'Boundary changed before dispatch')
    assert(not attempted[intent.command],'Native dispatch already attempted')
    local permit=plain.read(config.proofPermit)
    local token,epoch=permit:match('^([^\n]+)\n(%d+)\n$')
    assert(token==config.launchToken and tonumber(epoch)<=os.time() and os.time()-tonumber(epoch)<=10,'Expired/unreviewed network permit')
    local before,definition=capture(config,boundary,data)
    assert(plain.encode(before)==plain.encode(intent.before),'Proof state changed before dispatch')
    local marker=config.proofMarker..(intent.command=='proof-grant\n' and '.grant' or '.duplicate')
    assert(plain.read(marker)==config.launchToken..'\n'..intent.command,'Durable intent changed')
    attempted[intent.command]=true -- ambiguity after any error is never retried
    local start=os.clock()
    data:AddOwnedUpgrade(definition.UpgradeIdTag)
    intent.native_ms=(os.clock()-start)*1000
    return intent
end
function M.complete(intent,config,boundary,data)
    assert(plain.encode(boundary)==intent.boundary,'Boundary changed after dispatch')
    assert(attempted[intent.command],'No native attempt')
    local before=intent.before
    local after=capture(config,boundary,data)
    assert(after.owned,'Grant did not establish ownership')
    assert(after.credits==before.credits and equipment(config,after)==equipment(config,before),'Grant changed unrelated credits/equipment')
    local previous={};for _,t in ipairs(before.ownedTags.__array) do previous[t]=true end
    local current={};for _,t in ipairs(after.ownedTags.__array) do current[t]=true end
    for t in pairs(previous) do assert(current[t],'Grant removed ownership');current[t]=nil end
    for t in pairs(current) do assert(t==config.itemTag,'Grant changed unrelated ownership') end
    return {kind=intent.command=='proof-grant\n' and 'phase3-grant' or 'phase3-duplicate',before=before,after=after,
        native_ms=intent.native_ms,observation='separate-game-thread-service'}
end
return M
