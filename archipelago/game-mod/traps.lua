-- Transient effects only. No permanent attribute, save or progression writes.
local plain=require('plain-json')
local ue=require('ue-values')
local healthEffect=require('health-effect')
local M={}
local seen=''
local attempted={}
local active
local player=require('players').find
local configForEvidence
local function restore()
    if not active then return end
    -- Reacquire by exact component identity; never restore on a replacement pawn.
    for _,p in ipairs(FindAllOf('PagodaPlayerCharacter') or {}) do
        if p:IsValid() and p:GetFullName()==active.player and p.AbilitySystemComponent:IsValid() and p.AbilitySystemComponent:GetFullName()==active.component then
            p.AbilitySystemComponent:SetUserAbilityActivationInhibited(active.previous)
            assert(p.AbilitySystemComponent:GetUserAbilityActivationInhibited()==active.previous,'Silence restoration failed')
        end
    end
    if configForEvidence then
        local f=assert(io.open(configForEvidence.evidence,'a'))
        f:write(plain.encode({kind='trap-restored',index=tonumber(active.index),previous=active.previous}),'\n');f:close()
    end
    active=nil
end
function M.cleanup() restore() end
function M.service(config,boundary)
    configForEvidence=config
    if active and (os.time()>=active.untilTime or not boundary or boundary.world~=active.world) then restore() end
    if not config.trapsEnabled or not boundary then return end
    -- Idle ticks must not scan for the player: only an active effect or a fresh
    -- command needs the pawn.
    local command=plain.read(config.trapControl)
    if not active and (command=='' or command==seen) then return end
    local p=player(boundary.world)
    if not p or not p:IsAlive() or ue.number(p.HealthAttributeSet.Health.CurrentValue)<=0 then restore();return end
    if command=='' or command==seen then return end
    local index,id,token,epoch=command:match('^trap\n(%d+)\n(%d+)\n([^\n]+)\n(%d+)\n$')
    assert(token==config.launchToken and index,'Wrong trap binding')
    assert(os.time()-tonumber(epoch)<=30 and tonumber(epoch)<=os.time()+2,'Expired trap')
    assert(plain.read(config.trapControl..'.intent-'..index)==command,'No durable trap reservation')
    local kind=assert(config.trapItems[id],'Unknown trap ID')
    assert(config.trapsValidated or config.trapsTest,'Trap capability unvalidated')
    assert(not attempted[index],'Ambiguous trap attempt')
    seen=command;attempted[index]=true
    local evidence={kind='trap-applied',index=tonumber(index),item=tonumber(id),effect=kind}
    if kind=='half-heart' then
        local old=ue.number(p.HealthAttributeSet.Health.CurrentValue)
        local maximum=ue.number(p.HealthAttributeSet.MaxHealth.CurrentValue)
        local damage=math.min(5,math.max(0,old-1)) -- nonlethal; one heart = 10 HP
        local dealt=0
        if damage>0 then
            dealt=healthEffect.damage(p,damage)
        end
        evidence.requested=damage
        evidence.health_delta=ue.number(p.HealthAttributeSet.Health.CurrentValue)-old
        evidence.max_health_delta=ue.number(p.HealthAttributeSet.MaxHealth.CurrentValue)-maximum
        -- The game may mitigate damage (armor); the contract is nonlethal, temporary, MaxHealth untouched.
        assert(evidence.health_delta<=0 and ue.number(p.HealthAttributeSet.Health.CurrentValue)>0 and evidence.max_health_delta==0,
            'Half-heart effect did not match temporary health contract')
    elseif kind=='silence' then
        restore()
        local asc=p.AbilitySystemComponent;assert(asc:IsValid(),'Missing local ability system')
        active={index=index,player=p:GetFullName(),component=asc:GetFullName(),world=boundary.world,previous=asc:GetUserAbilityActivationInhibited(),untilTime=os.time()+config.trapDuration}
        asc:SetUserAbilityActivationInhibited(true)
        assert(asc:GetUserAbilityActivationInhibited(),'Temporary silence did not apply')
        evidence.duration=config.trapDuration
        -- Independent cleanup still runs if the AP observer stops/refuses.
        ExecuteInGameThreadWithDelay(config.trapDuration*1000,function() if active and active.index==index then restore() end end)
    else error('Unsupported trap mechanism') end
    local f=assert(io.open(config.evidence,'a'));f:write(plain.encode(evidence),'\n');f:close()
    plain.write(config.trapControl..'.applied-'..index,evidence)
end
return M
