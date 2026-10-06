-- One local-player census per EngineTick service. Wrappers never cross services:
-- begin() is called at the top of every service, so each tick pays for at most
-- one GUObjectArray scan no matter how many features need the player.
local M={}
local cache
function M.begin() cache=nil end
local function scan(world)
    local found
    for _,p in ipairs(FindAllOf('PagodaPlayerCharacter') or {}) do
        if p:IsValid() and not p:GetFullName():find('Default__',1,true) and p:GetWorld():IsValid() and p:GetWorld():GetFullName()==world then
            local c=p.Controller
            if c:IsValid() and c.Player:IsValid() and c.Player:IsA(StaticFindObject('/Script/Engine.LocalPlayer')) then
                assert(not found,'Ambiguous local player');found=p
            end
        end
    end
    return found
end
function M.find(world)
    if cache and cache.world==world then return cache.player end
    local found=scan(world)
    cache={world=world,player=found}
    return found
end
-- Hook callbacks run between services; they never trust the per-service cache.
function M.fresh(world) return scan(world) end
return M
