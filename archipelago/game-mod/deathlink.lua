-- One process-lifetime FinishDeath hook; no container wrappers cross callbacks.
local ue=require('ue-values')
local plain=require('plain-json')
local healthEffect=require('health-effect')
local M={}
local sequence=0
local seenDeaths={}
local seenCommand=''
local lastWorld
local remotePending
local killRequest
local players=require('players')
local listenerCache={}
local function deathListener(p)
    -- The listener ability lives as long as the pawn; reuse a positive answer
    -- for a few seconds instead of paying a second object-array scan per tick.
    local name=p:GetFullName()
    local hit=listenerCache[name]
    if hit and os.clock()-hit<10 then return true end
    for _,a in ipairs(FindAllOf('GA_Listen_Death_Player_C') or {}) do
        if a:IsValid() and not a:GetFullName():find('Default__',1,true) then
            local avatar=a:GetAvatarActorFromActorInfo()
            if avatar:IsValid() and avatar:GetFullName()==name then listenerCache={[name]=os.clock()};return true end
        end
    end
    listenerCache={}
    return false
end
local localPlayer=players.find
function M.start(config)
    if not config.deathLinkEnabled then return end
    assert(config.deathLinkValidated or config.deathLinkTest,'Incoming death capability not validated')
    print('[APBridge] DEATHLINK '..(config.deathLinkTest and 'protected-test' or 'validated')..'\n')
    RegisterHook('/Script/Pagoda.PagodaCharacter:FinishDeath',function() end,function(context)
        local ok=pcall(function()
            local p=context:get()
            if not p:IsValid() or not lastWorld or not p:GetWorld():IsValid() or p:GetWorld():GetFullName()~=lastWorld then return end
            local c=p.Controller
            if not c:IsValid() or not c.Player:IsValid() or not c.Player:IsA(StaticFindObject('/Script/Engine.LocalPlayer')) then return end
            local name=p:GetFullName()
            local remote=remotePending and remotePending.name==name and os.time()-remotePending.epoch<=30
            if p:IsAlive() and not remote then return end
            if not seenDeaths[name] then sequence=sequence+1;seenDeaths[name]=true end
            remotePending=nil
            local f=assert(io.open(config.evidence,'a'))
            f:write(plain.encode({kind='deathlink-finish-death',remote=not not remote,death_sequence=sequence}),'\n');f:close()
        end)
        if not ok then lastWorld=nil end
    end)
end
function M.invalidate() lastWorld=nil;remotePending=nil;killRequest=nil end
function M.service(config,boundary)
    if not config.deathLinkEnabled then return nil end
    lastWorld=boundary.world
    local p=localPlayer(boundary.world)
    if not p then return {ready=false} end
    local health=ue.number(p.HealthAttributeSet.Health.CurrentValue)
    local alive=p:IsAlive()
    local canReceive=alive and health>0 and deathListener(p) and healthEffect.available()
    if alive and health>0 then seenDeaths[p:GetFullName()]=nil end
    local command=plain.read(config.deathLinkControl)
    if command~='' and command~=seenCommand and canReceive then
        seenCommand=command -- consume before a native call; never replay
        local token,epoch=command:match('^([^\n]+)\n(%d+)\n$')
        assert(token==config.launchToken,'Wrong DeathLink binding')
        if tonumber(epoch)<=os.time()+2 and os.time()-tonumber(epoch)<=10 and alive and health>0 then
            assert(config.deathLinkValidated or config.deathLinkTest,'Unvalidated incoming death refused')
            remotePending={name=p:GetFullName(),epoch=os.time()}
            -- Positive-health synthetic death made the level result look like a completion.
            -- Establish zero actual health through natural damage; the game's own death
            -- listener owns failure/retry handling. One hit is capped and the game ignores
            -- hits during its hit-react window, so the request continues across services.
            killRequest={name=p:GetFullName(),stopAt=os.time()+60,trace={}}
        end
    end
    if killRequest then
        if not alive or health<=0 or killRequest.name~=p:GetFullName() or os.time()>killRequest.stopAt then
            local f=assert(io.open(config.evidence,'a'))
            f:write(plain.encode({kind='deathlink-kill-finished',final_health=health,alive_after=alive,
                steps=table.concat(killRequest.trace,','),timeout=os.time()>killRequest.stopAt}),'\n');f:close()
            killRequest=nil
        else
            local before=health
            local dealt=healthEffect.damage(p,100000)
            killRequest.trace[#killRequest.trace+1]=string.format('%g>%g',before,before-dealt)
            health=ue.number(p.HealthAttributeSet.Health.CurrentValue);alive=p:IsAlive()
        end
    end
    return {ready=true,alive=alive and health>0,can_receive=canReceive,death_sequence=sequence,
        health=health,max_health=ue.number(p.HealthAttributeSet.MaxHealth.CurrentValue),
        activation_inhibited=p.AbilitySystemComponent:IsValid() and p.AbilitySystemComponent:GetUserAbilityActivationInhibited() or false}
end
return M
