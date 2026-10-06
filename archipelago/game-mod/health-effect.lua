-- Native instant health reduction shared by traps and genuine DeathLink.
-- Verified call shape (protected test): PagodaCombatFunctionLibrary:ApplySetByCallerEffect with the normally
-- loaded GE_Damage_SetByCaller and SetByCaller.Damage reduces player health. One application is capped by the
-- game's per-hit damage limit, so a lethal request is a bounded sequence of natural damage applications.
-- GE_Healing_SetByCaller is NOT used: its CDO does not expose exactly one modifier (live Half Heart refusal).
local ue=require('ue-values')
local M={}
local path='/Game/Pagoda/Characters/Common/Effects/GE_Damage_SetByCaller.GE_Damage_SetByCaller_C'
local magnitudeTag='SetByCaller.Damage'
local library='/Script/Pagoda.Default__PagodaCombatFunctionLibrary'
function M.available() return StaticFindObject(path):IsValid() and StaticFindObject(library):IsValid() end
local function health(player) return ue.number(player.HealthAttributeSet.Health.CurrentValue) end
function M.damage(player,amount)
    assert(type(amount)=='number' and amount>0 and amount<=100000,'Invalid damage amount')
    local effect=StaticFindObject(path);assert(effect:IsValid(),'Native damage effect unavailable')
    local lib=StaticFindObject(library);assert(lib:IsValid(),'Missing native effect API')
    local before=health(player)
    local maximum=ue.number(player.HealthAttributeSet.MaxHealth.CurrentValue)
    lib:ApplySetByCallerEffect(player,effect,{TagName=FName(magnitudeTag)},amount+0.0)
    assert(ue.number(player.HealthAttributeSet.MaxHealth.CurrentValue)==maximum,'Native damage changed MaxHealth')
    return before-health(player)
end
-- Natural lethal path: bounded repeats until the game's own death listener takes over.
function M.kill(player,limit)
    local applications,total=0,0
    while health(player)>0 and applications<(limit or 12) do
        local dealt=M.damage(player,100000)
        applications=applications+1;total=total+dealt
        assert(dealt>0 or health(player)<=0,'Native damage did not reduce health')
    end
    return {applications=applications,total=total,health=health(player)}
end
return M
