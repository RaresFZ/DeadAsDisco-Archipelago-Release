-- Game-specific AP adapter. One EngineTick scheduler, no game UFunction hooks.
-- Protected transaction/launch lease AND exact saved-context anchors are required.
local config=require('ap-config')
local authority=require('authority')
local plain=require('plain-json')
local players=require('players')
local scopes=require('sync-scopes') -- unchanged verified bounded context decoder
local production=config.productionEnabled and require('production') or nil
local deaths=config.deathLinkEnabled and require('deathlink') or nil
local nodes=config.nodeLocationsEnabled and require('skill-locations') or nil
local access=config.accessEnabled and require('access') or nil
local traps=config.trapsEnabled and require('traps') or nil
local credits=config.fanPacksEnabled and require('credits') or nil
assert(EngineTickAvailable,'Required EngineTick unavailable')
local stopped,busy,sequence=false,false,0
local previous,lastState,lastService=nil,nil,nil
local requestSeen=''
local pending
local callbackStage='observer'
local idleTick,MAX_SCOPE_REUSE=false,2
local costs
local function measured(stage,fn)
    local start=os.clock();local values=table.pack(pcall(fn))
    costs[stage]=(costs[stage] or 0)+(os.clock()-start)*1000
    assert(values[1],values[2]);return table.unpack(values,2,values.n)
end
local function append(row)
    local f=assert(io.open(config.evidence,'a'));assert(f:write(plain.encode(row),'\n'));assert(f:close())
end
local boot=config.launchToken..':'..tostring(os.time())
local function emit(row)
    sequence=sequence+1
    row.protocol,row.generation,row.game_slot=1,config.generation,config.gameSlot
    row.observed_at,row.sequence,row.boot=os.time(),sequence,boot
    measured('snapshot-publication',function() plain.write(config.output..'.'..(sequence%2)..'.json',row) end)
    local state=row.ready and 'ready' or row.reason
    if state~=lastState then
        local f=assert(io.open(config.evidence,'a'));assert(f:write(plain.encode(row),'\n'));assert(f:close())
        print('[APBridge] STATE '..state..'\n');lastState=state
    end
end
local function protected()
    assert(plain.read(config.sessionFile):match('"status"%s*:%s*"isolated"'),'Protected transaction inactive')
    assert(plain.exists(config.parkedSave),'Parked original missing')
    return plain.read(config.lease)==config.launchToken..'\n'
end
local function verify(snapshot,owned,equipped)
    local present={};for _,t in ipairs(owned) do present[t]=true end
    for _,t in ipairs(config.owned) do assert(present[t] or config.suppressedNodes and config.suppressedNodes[t],'Ownership reset/rollback');present[t]=nil end
    for t in pairs(present) do assert(t==config.itemTag or (config.allowedOwnership and config.allowedOwnership[t]),'Unexpected ownership change') end
    local unchanged={}
    for _,t in ipairs(equipped) do
        if not ((config.phase3Enabled and t==config.itemTag) or (config.productionEnabled and config.allowedOwnership[t])) then unchanged[#unchanged+1]=t end
    end
    local expectedEquipment={}
    for t in config.equipped:gmatch('[^|]+') do
        if not ((config.phase3Enabled and t==config.itemTag) or (config.productionEnabled and config.allowedOwnership[t])) then expectedEquipment[#expectedEquipment+1]=t end
    end
    assert(table.concat(unchanged,'|')==table.concat(expectedEquipment,'|'),'Unrelated equipment changed')
    local count=0
    for key,expected in pairs(config.contexts) do
        count=count+1;local current=assert(snapshot.contexts[key],'Missing bound saved context')
        for variable,leaves in pairs(expected) do
            local got=assert(current.selected[variable],'Missing binding anchor')
            if config.productionEnabled then
                for path,old in pairs(leaves) do
                    local current=assert(got[path],'Missing bound leaf')
                    assert(tonumber(current.current)>=tonumber(old.current),'Progression anchor reset')
                end
            else assert(plain.encode(got)==plain.encode(leaves),'Anchor changed/reset') end
        end
    end
    assert(count==(config.boundContextCount or 6),'Bound context count changed')
    local active=assert(snapshot.active[config.checkScope],'No active Playthrough scope')
    assert(active.context==config.checkContext,'Wrong active Playthrough context')
    local selected=assert(snapshot.contexts[config.checkScope..'|'..config.checkContext].selected[config.checkTag],'Missing selected check')
    local state=assert(selected[''],'Check is not scalar').current
    assert(state=='3' or state=='4','Unsupported check state')
    return state=='4',state
end
local function sample()
    callbackStage=pending and pending.stage or 'observer'
    players.begin()
    local command=measured('control-read',function() return plain.read(config.control) end)
    if command=='stop\n' then if traps then traps.cleanup() end;pending=nil;stopped=true;emit({ready=false,reason='stopped'});return end
    if not measured('protection-check',protected) then if deaths then deaths.invalidate() end;if traps then traps.cleanup() end;assert(not pending,'Protected lease lost with pending intent');previous=nil;emit({ready=false,reason='no-protected-launch-lease'});return end
    if access then measured('access-service',function() access.service(config) end) end
    local boundary,reason,data,savesOwner=measured('authority-scan',function() return authority.boundary(config.gameSlot) end)
    if not boundary then if deaths then deaths.invalidate() end;if traps then traps.service(config,nil) end;assert(not pending,'Loaded boundary lost with pending intent');previous=nil;emit({ready=false,reason=reason});return end
    -- A single ordered intent, only plain data across services. Native dispatch
    -- has no scoped traversal, snapshot serialization or post-call player scan.
    if pending then
        assert(plain.encode(boundary)==pending.boundary,'Pending intent boundary changed')
        local proof=require('proof')
        if pending.stage=='prepare' then
            pending.intent=proof.prepare(pending.command,config,boundary,data);pending.stage='dispatch'
        elseif pending.stage=='dispatch' then
            pending.intent=proof.dispatch(pending.intent,config,boundary,data);pending.stage='observe'
            append({kind='phase3-native-return',command=pending.command,native_ms=pending.intent.native_ms})
        else
            append(proof.complete(pending.intent,config,boundary,data));pending=nil
        end
        previous=nil
        emit({ready=false,reason='proof-observation'});return
    end
    -- First boundary observation never reads containers.
    local key=plain.encode(boundary)
    if not previous or previous.boundary~=key then previous={boundary=key};emit({ready=false,reason='corroborating-owner'});return end
    local owned,equipped=measured('ownership-read',function() return authority.tags(data.PlayerData.OwnedUpgrades),authority.tags(data.PlayerData.EquippedUpgrades) end)
    -- The full progression traversal is the most expensive read (~30 ms on a fast PC). On a purely timer-driven idle tick it is reused
    -- for up to MAX_SCOPE_REUSE ticks (<= 12 s); the boundary identity, ownership/equipment and every anchor check are still re-run
    -- each tick against it. Any tick caused by a changed file or something in flight, and every native hook, reads fresh.
    local cached=previous.cache
    local snapshot
    if idleTick and cached and cached.age<MAX_SCOPE_REUSE then
        snapshot=cached.snapshot;cached.age=cached.age+1
    else
        snapshot=measured('scope-read',function() return scopes.snapshot(boundary.world) end)
        previous.cache={snapshot=snapshot,age=0}
    end
    local after=measured('authority-recheck',function() return authority.recheck(savesOwner,config.gameSlot) end)
    assert(after and plain.encode(after)==key,'Boundary changed during read')
    local complete,state=measured('context-verify',function() return verify(snapshot,owned,equipped) end)
    local fingerprint=measured('fingerprint',function() return plain.encode({owned=plain.array(owned),equipped=plain.array(equipped),scopes=snapshot}) end)
    if previous.fingerprint~=fingerprint then
        previous={boundary=key,fingerprint=fingerprint};emit({ready=false,reason='corroborating-state'});return
    end
    if nodes and measured('node-service',function() return nodes.service(config,boundary,data) end) then previous=nil;emit({ready=false,reason='reward-suppression'});return end
    if traps then measured('trap-service',function() traps.service(config,boundary) end) end
    if credits then measured('credits-service',function() credits.service(config,boundary,data) end) end
    if production and measured('production-service',function() return production.service(config,boundary,data) end) then
        previous=nil;emit({ready=false,reason='ownership-dispatch'});return
    end
    -- Optional targeted read-only inspection uses the direct joined object, never census authority.
    local inspection
    if command~=requestSeen and command~='' then
        requestSeen=command
        if command~='inspect\n' then
            if command=='proof-grant\n' or command=='proof-duplicate\n' then
                assert(config.phase3Enabled,'Targeted Phase 3 mode not provisioned')
                pending={stage='prepare',command=command,boundary=key}
                emit({ready=false,reason='proof-enqueued'});return
            end
            local row=require('proof').run(command,config,boundary,data)
            local f=assert(io.open(config.evidence,'a'));assert(f:write(plain.encode(row),'\n'));assert(f:close())
            previous=nil -- reacquire/corroborate after any proof operation
            emit({ready=false,reason='proof-observation'});return
        end
        local definition=StaticFindObject(config.itemAsset)
        assert(definition:IsValid(),'Mapped item definition not naturally loaded')
        assert(definition:IsA(StaticFindObject('/Script/Pagoda.PagodaPlayerUpgradeDefinition')),'Wrong item definition class')
        local tag=require('ue-values').string(definition.UpgradeIdTag.TagName,'NameProperty')
        assert(tag==config.itemTag,'Definition ownership tag mismatch')
        inspection={asset=definition:GetFullName(),tag=tag,owned=data:IsUpgradeOwned(definition.UpgradeIdTag)}
    end
    if previous.purchaseState~=state then
        local purchased,join=require('purchase').read(config,snapshot)
        assert(purchased==complete,'Native purchase and persistent state disagree')
        previous.purchaseState,previous.purchaseJoin=state,join
        local f=assert(io.open(config.evidence,'a'));assert(f:write(plain.encode({kind='selected-purchase',purchased=purchased,state=state,join=join,boundary=boundary}),'\n'));assert(f:close())
    end
    if inspection then
        local f=assert(io.open(config.evidence,'a'));assert(f:write(plain.encode({kind='item-inspection',inspection=inspection,boundary=boundary}),'\n'));assert(f:close())
    end
    local player=deaths and measured('deathlink-service',function() return deaths.service(config,boundary) end) or nil
    local loadable=production and plain.array(measured('loadable-scan',function() return production.available(config,owned) end)) or nil
    emit({ready=true,authority_verified=true,contexts_verified=true,protection_token=config.launchToken,
        checks=plain.array(complete and {config.locationId} or {}),owned=plain.array(owned),
        equipped=plain.array(equipped),boundary=boundary,scopes=snapshot,check_state=state,inspection=inspection,player=player,
        loadable_ownership=loadable})
end
print('[APBridge] LOADED '..(config.phase3Enabled and 'targeted-proof-production-grants-disabled' or 'grants-disabled')..'\n')
config.authorizeMutation=function(boundary,data)
    assert(not stopped,'Runtime refused; mutation disabled')
    local snapshot=scopes.snapshot(boundary.world)
    local owned,equipped=authority.tags(data.PlayerData.OwnedUpgrades),authority.tags(data.PlayerData.EquippedUpgrades)
    verify(snapshot,owned,equipped)
    local after=authority.recheck(data:GetOuter(),config.gameSlot)
    assert(after and plain.encode(after)==plain.encode(boundary),'Node boundary changed')
end
config.refuseMutation=function(err)
    config.mutationsRefused=true
    stopped=true
    if traps then traps.cleanup() end
    local f=io.open(config.refusal,'w');if f then f:write(tostring(err));f:close() end
    print('[APBridge] FAILED native-hook\n')
end
if deaths then deaths.start(config) end
if nodes then nodes.start(config) end
if access then access.start(config) end
-- A service that takes long is usually just a slower PC or a heavy scene, not a fault: back off (skip a few ticks so the game
-- keeps its frame rate) and only stop on a credible stall or a real error. The first slow tick of a hub load must never end a session.
local SLOW_MS,STALL_MS,MAX_SKIPPED_WAKEUPS=250,3000,6
local WAKE_MS,BUSY_INTERVAL,IDLE_INTERVAL=1000,2,4
local skipTicks=0
-- Cadence: a full service costs 50+ ms on the game thread. The loop wakes every second, but a wake-up only costs a few small file
-- reads (the watched control/entitlement files). A full service runs at once when a watched file changed or a grant is prepared
-- (a received item, trap or DeathLink is noticed within ~1 s), every 2 s while anything is in flight (grant, trap, kill request,
-- proof, non-ready state), and every 4 s when idle (the client accepts snapshots up to 10 s old).
local watched={}
for _,key in ipairs({'control','productionControl','trapControl','deathLinkControl','creditsControl','accessFile','entitlementFile','completedNodesFile'}) do
    if config[key] then watched[#watched+1]=config[key] end
end
local function signature()
    local parts={};for i,path in ipairs(watched) do parts[i]=plain.read(path) end
    return table.concat(parts,'\0')
end
local function inFlight()
    return pending~=nil or lastState~='ready' or (production and production.busy()) or (deaths and deaths.busy()) or (traps and traps.busy())
end
local lastSignature,lastFull,tickCount=nil,-math.huge,0
local function costSummary()
    local rows={};for stage,ms in pairs(costs or {}) do rows[#rows+1]={stage,ms} end
    table.sort(rows,function(a,b) return a[2]>b[2] end)
    local parts={};for i=1,math.min(4,#rows) do parts[i]=rows[i][1]..'='..string.format('%.0f',rows[i][2])..'ms' end
    return table.concat(parts,' ')
end
LoopInGameThreadWithDelay(WAKE_MS,function()
    if stopped then return end
    if skipTicks>0 then skipTicks=skipTicks-1;return end
    local current,clock,flying=signature(),os.clock(),inFlight()
    local changed=current~=lastSignature or (production and production.busy())
    if not changed and clock-lastFull<(flying and BUSY_INTERVAL or IDLE_INTERVAL)-0.25 then return end
    idleTick=not changed and not flying
    lastFull=clock
    if busy then stopped=true;print('[APBridge] FAILED reentry\n');return end
    local now=os.time()
    if lastService and now-lastService>15 then stopped=true;emit({ready=false,reason='service-gap'});print('[APBridge] FAILED service-gap\n');return end
    lastSignature=current
    lastService=now;busy=true;costs={};local start=os.clock();local ok,err=pcall(sample);busy=false
    local workMs=(os.clock()-start)*1000
    local accounted=0;for _,v in pairs(costs) do accounted=accounted+v end
    costs['unaccounted']=workMs-accounted
    -- Small diagnostic publication is measured separately; disk/AP durability
    -- lives in the external operator/ledger, never in the native-call bracket.
    local telemetryStart=os.clock()
    -- The timing row is a disk write on the game thread: keep every error/slow/non-observer tick, the first few and one in ten.
    tickCount=tickCount+1
    local logged,logError=true,nil
    if not ok or callbackStage~='observer' or workMs>50 or tickCount<=3 or tickCount%10==0 then
        logged,logError=pcall(append,{kind='callback-timing',stage=callbackStage,work_ms=workMs,
            costs=costs,clock='Windows CRT elapsed os.clock; not isolated CPU',observed_at=os.time(),ok=ok})
    end
    local totalMs=(os.clock()-start)*1000
    -- 50 ms is telemetry, not a correctness failure. Stop on a real error or a credible stall; merely slow ticks back off.
    if totalMs>50 then print('[APBridge] slow service '..tostring(totalMs)..' ms\n') end
    local failure
    if not ok then failure=err==nil and 'service raised an error without a message' or tostring(err)
    elseif not logged then failure='evidence write failed: '..tostring(logError)
    elseif totalMs>STALL_MS then failure='callback-time-budget (one service took '..string.format('%.0f',totalMs)..' ms)' end
    if failure then
        stopped=true
        config.mutationsRefused=true
        if traps then traps.cleanup() end
        pending=nil
        local f=io.open(config.refusal,'w');if f then f:write(failure,
            '\nstage=',tostring(callbackStage),' work_ms=',tostring(workMs),' total_ms=',tostring(totalMs),
            ' telemetry_ms=',tostring((os.clock()-telemetryStart)*1000),'\ncosts: ',costSummary());f:close() end
        emit({ready=false,reason='refused'});print('[APBridge] FAILED bounded-read\n')
    elseif totalMs>SLOW_MS then
        skipTicks=math.min(MAX_SKIPPED_WAKEUPS,2*math.floor(totalMs/SLOW_MS))
    end
end)
