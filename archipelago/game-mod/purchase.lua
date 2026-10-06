-- Selected native predicate joined through the current authoritative scope, once
-- per corroborated loaded episode. No filtered UObject census.
local authority=require('authority')
local ue=require('ue-values')
local M={}
function M.read(config,snapshot)
    local progression=assert(authority.one('PagodaProgressionSubsystem'),'No progression subsystem')
    assert(progression:GetFullName()==snapshot.owner,'Progression changed')
    local wanted=snapshot.contexts[config.checkScope..'|'..config.checkContext]
    local scope
    progression.ActiveScopes:ForEach(function(k,v)
        if ue.string(k:get().TagName,'NameProperty')==config.checkScope then
            assert(not scope,'Duplicate active Playthrough scope');scope=v:get()
        end
    end)
    assert(scope and scope:IsValid() and scope:GetFullName()==wanted.owner,'Wrong active purchase scope')
    local variable
    scope.Variables:ForEach(function(k,v)
        if ue.string(k:get().TagName,'NameProperty')==config.checkTag then
            assert(not variable,'Duplicate purchase variable');variable=v:get()
        end
    end)
    assert(variable and variable:IsValid(),'Missing selected purchase')
    assert(variable:GetOuter():GetFullName()==wanted.owner,'Wrong purchase owner')
    assert(ue.string(variable.Tag.TagName,'NameProperty')==config.checkTag,'Wrong purchase tag')
    assert(variable:IsA(StaticFindObject('/Script/Pagoda.PagodaProgressionPurchasableItemBase')),'Wrong purchase class')
    local purchased=variable:IsPurchased();assert(type(purchased)=='boolean','Unsupported purchase Bool')
    return purchased,{owner=variable:GetFullName(),class=variable:GetClass():GetFullName(),scopeOwner=wanted.owner}
end
return M
