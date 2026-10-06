-- Independent node interactions. AP AddOwnedUpgrade is never a node interaction.
-- Reward suppression is a separate, protected, representative-test capability.
-- Native ownership removal is enabled only by a verified/test capability.
local authority=require('authority')
local ue=require('ue-values')
local plain=require('plain-json')
local M={}
local pending
local taken={}
local suppressing=false
local append
local rootTags={}
local tierCacheKey
local tierCounts={}
local failedSuppression={}
local gateEntitled,gateSlots={},{}
local attempts={}
local function ready(config)
    assert(plain.read(config.lease)==config.launchToken..'\n','Node hook has no protected launch lease')
    local boundary,_,data=authority.boundary(config.gameSlot)
    assert(boundary and boundary.slot==config.gameSlot,'Ambiguous node playthrough')
    assert(config.authorizeMutation,'Missing runtime context verifier')
    config.authorizeMutation(boundary,data)
    return boundary,data
end
local function entitled(config,tag,snapshot)
    if snapshot then return snapshot[tag]==true end
    return ('\n'..plain.read(config.entitlementFile)):find('\n'..tag..'\n',1,true)~=nil
end
local function record(config,tag,interaction)
    local row=config.nodeItems[tag]
    if row and not taken[row.id] then
        append(config,{kind='node-interaction',id=row.id,tag=tag,interaction=interaction})
        taken[row.id]=true
        tierCacheKey=nil
    end
end
local function suppress(config,data,id,tag,entitlements)
    if config.suppressionTestTags and not config.suppressionTestTags[tag] then return end
    if suppressing or not config.suppressedNodes or not config.suppressedNodes[tag] or entitled(config,tag,entitlements) then return end
    assert(config.rewardSuppressionValidated or config.rewardSuppressionTest,'Unvalidated reward removal refused')
    local nodeRow=config.nodeItems[tag]
    if nodeRow and nodeRow.ownershipFamily=='power' and not config.powerOwnershipRemoval then
        -- Live runs g/h: the game re-grants removed powers on its own schedule, so
        -- raw ownership cannot be held down. A power is only usable through a boss
        -- slot/applied effect; withhold exactly that and leave ownership alone.
        local slotted=false
        for _,t in pairs(authority.slotted(data)) do if t==tag then slotted=true end end
        if not slotted then return end
        attempts[tag]=(attempts[tag] or 0)+1
        if attempts[tag]>4 then
            append(config,{kind='node-suppression-oscillation',tag=tag,attempts=attempts[tag]})
            error({kind='isolated-suppression-refusal',reason='Slot gate did not converge: '..tag})
        end
        append(config,{kind='node-power-gate-attempt',tag=tag})
        suppressing=true
        local ok,err=pcall(function()
            config.phase='power-gate'
            local result=require('power-removal').gate(config,data,id,tag)
            result.kind='node-power-gated';result.tag=tag;append(config,result)
            for _,t in pairs(authority.slotted(data)) do assert(t~=tag,'Power remains slotted: '..tag) end
        end)
        suppressing=false;config.phase=nil
        if not ok then
            -- Collateral damage to other applied grants is a safety stop; any other failure is isolated.
            if tostring(err):find('unrelated',1,true) then error(err) end
            error({kind='isolated-suppression-refusal',reason=tostring(err)})
        end
        return true
    end
    if data:IsUpgradeOwned(id) then
        attempts[tag]=(attempts[tag] or 0)+1
        if attempts[tag]>4 then
            append(config,{kind='node-suppression-oscillation',tag=tag,attempts=attempts[tag]})
            error({kind='isolated-suppression-refusal',reason='Removal did not converge: '..tag})
        end
        local beforeOwned=authority.tags(data.PlayerData.OwnedUpgrades)
        local beforeEquipped=authority.tags(data.PlayerData.EquippedUpgrades)
        local beforeSlots=authority.slotted(data)
        append(config,{kind='node-suppression-attempt',tag=tag,owned=true,equipped=data:IsUpgradeEquipped(id)})
        suppressing=true
        local ok,err=pcall(function()
            if data:IsUpgradeEquipped(id) then
                local row=assert(config.nodeItems[tag],'Missing removal definition')
                local definition=StaticFindObject(row.asset);assert(definition:IsValid(),'Removal definition unloaded')
                local found
                for _,catalog in ipairs(FindAllOf('PagodaPlayerUpgradeCatalogSubsystem') or {}) do
                    if catalog:IsValid() and catalog:GetLocalPlayerPlaythroughData():IsValid() and
                        catalog:GetLocalPlayerPlaythroughData():GetFullName()==data:GetFullName() then
                        assert(not found,'Ambiguous removal catalog');found=catalog
                    end
                end
                assert(found,'Missing exact-owner removal catalog')
                local toggleable=definition.bIsToggleable
                assert(type(toggleable)=='boolean','Unsupported native toggleability flag')
                -- Active skills are normally always equipped. The catalog toggle
                -- intentionally ignores non-toggleable definitions. Enable only
                -- this in-memory target for the synchronous native cleanup call,
                -- restoring the definition before any further ownership mutation.
                config.phase='toggle-unequip'
                local toggled,toggleError=pcall(function()
                    definition.bIsToggleable=true
                    found:ToggleUpgradeEquippedState(definition)
                end)
                definition.bIsToggleable=toggleable
                assert(definition.bIsToggleable==toggleable,'Toggleability restoration failed')
                assert(toggled,toggleError)
                append(config,{kind='node-native-unequip',tag=tag,was_toggleable=toggleable,
                    equipped=data:IsUpgradeEquipped(id)})
            end
            -- Live run g: native RemoveOwnedUpgrade re-awards any other removed power
            -- through its ownership callbacks (A removed -> B re-granted -> B removed
            -- -> A re-granted, forever). The reflected set removal has no callbacks.
            local row=config.nodeItems[tag]
            if config.nativeOwnershipRemoval then
                config.phase='native-remove'
                data:RemoveOwnedUpgrade(id)
            else
                config.phase='raw-owned-remove'
                data.PlayerData.OwnedUpgrades:Remove(id)
            end
            if row and row.ownershipFamily=='power' and (not config.nativeOwnershipRemoval or data:IsUpgradeOwned(id)) and
                (config.powerRemovalTest or config.powerRemovalValidated) then
                require('power-removal').remove(config,data,id,tag)
                append(config,{kind='node-power-cleanup',tag=tag})
            end
            if config.powerRemovalTest or config.powerRemovalValidated then
                -- Native ownership absence is not effect proof: record and, when a
                -- leaked applied effect exists, clean exactly this target.
                config.phase='effect-cleanup'
                local okEffect,effect=pcall(require('power-removal').effect,config,data,id,tag)
                if okEffect then
                    effect.kind='node-effect-cleanup';effect.tag=tag;append(config,effect)
                    assert(not effect.still_equipped,'Native component still reports target equipped: '..tag)
                else
                    append(config,{kind='node-effect-cleanup-error',tag=tag,reason=tostring(effect)})
                    assert(config.powerRemovalTest and not config.powerRemovalValidated,effect)
                end
            end
            local afterOwned=authority.tags(data.PlayerData.OwnedUpgrades)
            local afterEquipped=authority.tags(data.PlayerData.EquippedUpgrades)
            local afterSlots=authority.slotted(data)
            -- Boss slots follow the same rule as ownership: another shuffled power that
            -- native cleanup re-grants/re-slots is a cascade handled by its own pass.
            local function shuffled(t) return t==tag or (config.suppressedNodes[t] and not entitled(config,t)) end
            local slotCascade
            for slot,t in pairs(beforeSlots) do
                if afterSlots[slot]~=t then
                    assert(shuffled(t),'Removal changed unrelated boss slot')
                    slotCascade=true
                end
            end
            for slot,t in pairs(afterSlots) do
                if beforeSlots[slot]~=t then
                    assert(shuffled(t),'Removal added unrelated boss slot')
                    slotCascade=true
                end
            end
            if slotCascade then
                local function slotText(map) local out={};for slot,t in pairs(map) do out[#out+1]=slot..'='..t end;table.sort(out);return table.concat(out,'|') end
                append(config,{kind='node-suppression-slot-cascade',tag=tag,before=slotText(beforeSlots),after=slotText(afterSlots)})
            end
            -- Native cleanup can re-grant or auto-equip OTHER shuffled rewards (e.g. a
            -- power re-awarded while another node is unequipped). Those are suppressed
            -- targets in their own right and are removed by their own pass; anything
            -- else changing is an unrelated mutation and stops the run.
            local function relevant(list)
                local out={};for _,t in ipairs(list) do
                    if t~=tag and not (config.suppressedNodes[t] and not entitled(config,t)) then out[#out+1]=t end
                end;return table.concat(out,'|')
            end
            local function changes(before,after)
                local old,new,added,removed={},{},{},{}
                for _,t in ipairs(before) do old[t]=true end
                for _,t in ipairs(after) do new[t]=true;if not old[t] then added[#added+1]=t end end
                for _,t in ipairs(before) do if not new[t] then removed[#removed+1]=t end end
                return table.concat(added,'|'),table.concat(removed,'|')
            end
            if relevant(beforeOwned)~=relevant(afterOwned) or relevant(beforeEquipped)~=relevant(afterEquipped) then
                local ownedAdded,ownedRemoved=changes(beforeOwned,afterOwned)
                local equippedAdded,equippedRemoved=changes(beforeEquipped,afterEquipped)
                append(config,{kind='node-suppression-unrelated-change',tag=tag,owned_added=ownedAdded,owned_removed=ownedRemoved,
                    equipped_added=equippedAdded,equipped_removed=equippedRemoved})
                error('Removal changed unrelated ownership/equipment: '..tag)
            end
            local ownedAdded,ownedRemoved=changes(beforeOwned,afterOwned)
            local equippedAdded,equippedRemoved=changes(beforeEquipped,afterEquipped)
            if ownedAdded~='' or ownedRemoved~=tag and ownedRemoved~='' or equippedAdded~='' or equippedRemoved~=tag and equippedRemoved~='' then
                append(config,{kind='node-suppression-cascade',tag=tag,owned_added=ownedAdded,owned_removed=ownedRemoved,
                    equipped_added=equippedAdded,equipped_removed=equippedRemoved})
            end
            local rawOwned=false;for _,t in ipairs(afterOwned) do if t==tag then rawOwned=true end end
            append(config,{kind='node-suppression-result',tag=tag,raw_owned=rawOwned,
                native_owned=data:IsUpgradeOwned(id),native_equipped=data:IsUpgradeEquipped(id)})
            local slotted=false;for _,t in pairs(afterSlots) do if t==tag then slotted=true end end
            if rawOwned or data:IsUpgradeOwned(id) or data:IsUpgradeEquipped(id) or slotted then
                error({kind='isolated-suppression-refusal',reason='Target remains owned/equipped: '..tag})
            end
        end)
        suppressing=false;config.phase=nil;assert(ok,err)
        append(config,{kind='node-reward-suppressed',tag=tag})
        return true
    end
end
append=function(config,row)
    row.generation,row.game_slot,row.protection_token=config.generation,config.gameSlot,config.launchToken
    local f=assert(io.open(config.nodeJournal,'a'),'Node journal unavailable')
    assert(f:write(plain.encode(row),'\n'));assert(f:flush());assert(f:close())
end
function M.start(config)
    if not config.nodeLocationsEnabled then return end
    assert(config.nodeLocationsValidated or config.nodeLocationsTest,'Node interaction capability not validated')
    assert(config.nodeJournal and config.nodeItems,'No node mapping/journal')
    local function guarded(fn)
        return function(...)
            if config.mutationsRefused then return end
            local result=table.pack(pcall(fn,...))
            if not result[1] then
                local err=result[2]
                -- One failed withholding must never stop the whole bridge (live: a power the game kept re-slotting).
                if type(err)=='table' and err.kind=='isolated-suppression-refusal' then
                    append(config,{kind='node-suppression-refused',reason=tostring(err.reason),source='hook'})
                    return
                end
                config.refuseMutation(err);return
            end
            return table.unpack(result,2,result.n)
        end
    end
    local function register(path,pre,post)
        if post then RegisterHook(path,guarded(pre),guarded(post))
        else RegisterHook(path,guarded(pre)) end
    end
    print('[APBridge] SKILLLOCATIONS '..(config.nodeLocationsTest and 'protected-test' or 'validated')..'\n')
    register('/Script/Pagoda.PagodaPlayerUpgradeCatalogSubsystem:TryBuyUpgradeWithCredits',function(_,definition)
        local d=definition:get();if not d:IsValid() then return end
        local tag=ue.string(d.UpgradeIdTag.TagName,'NameProperty')
        local row=config.nodeItems[tag];if not row then return end
        assert(not pending,'Reentrant skill purchase')
        local boundary,data=ready(config)
        pending={tag=tag,id=row.id,boundary=plain.encode(boundary),owned=data:IsUpgradeOwned(d.UpgradeIdTag),credits=data:GetCredits()}
    end,function(_,originalReturn,definition)
        if not pending then return end
        local request=pending;pending=nil
        if originalReturn:get()~=true then return end
        local d=definition:get();assert(d:IsValid(),'Purchase definition lost')
        assert(ue.string(d.UpgradeIdTag.TagName,'NameProperty')==request.tag,'Purchase target changed')
        local boundary,data=ready(config);assert(plain.encode(boundary)==request.boundary,'Purchase identity changed')
        if request.owned or not data:IsUpgradeOwned(d.UpgradeIdTag) then return end
        assert(request.credits>=data:GetCredits(),'Purchase unexpectedly awarded credits')
        -- CreditsCost only applies when bOverrideCost is true; vanilla resolves
        -- the tier price for other definitions. Preserve that native pricing.
        record(config,request.tag,'purchase')
        suppress(config,data,d.UpgradeIdTag,request.tag)
    end)
    -- An AP item may arrive before the player takes the node. The owned node's
    -- normal equip/toggle interaction then claims its location; item delivery
    -- alone never does. This also works for a previously owned vanilla node.
    register('/Script/Pagoda.PagodaPlayerUpgradeCatalogSubsystem:ToggleUpgradeEquippedState',function(_,definition)
        if suppressing or config.internalToggle then return end
        local d=definition:get();if not d:IsValid() then return end
        local tag=ue.string(d.UpgradeIdTag.TagName,'NameProperty')
        if not config.nodeItems[tag] then return end
        local _,data=ready(config)
        if data:IsUpgradeOwned(d.UpgradeIdTag) or config.suppressedNodes[tag] then record(config,tag,'node-toggle') end
        if config.suppressedNodes[tag] and not entitled(config,tag) then
            -- The virtual purchased state represents the location, not a usable
            -- AP ability. The native catalog accepts a null definition and exits.
            definition:set(nil)
        end
    end)
    register('/Script/Pagoda.PagodaPlayerUpgradeComponent:EquipOrSwapBossAbilityAtSlot',function(_,definition)
        if suppressing then return end
        local d=definition:get();if not d:IsValid() then return end
        local tag=ue.string(d.UpgradeIdTag.TagName,'NameProperty')
        if not config.nodeItems[tag] then return end
        ready(config)
        -- This native component method can also run during grant/reload. It is
        -- only an effect gate, never evidence of a player taking a node.
        if config.suppressedNodes[tag] and not entitled(config,tag) then definition:set(nil) end
    end)
    if config.suppressedNodes and next(config.suppressedNodes) then
        print('[APBridge] REWARDSUPPRESSION '..(config.rewardSuppressionTest and 'protected-test' or 'validated')..'\n')
        register('/Script/Pagoda.PagodaPlaythroughPlayerData:AddOwnedUpgrade',function() end,function(context,id)
            if suppressing then
                append(config,{kind='native-add-during-suppression',tag=ue.string(id:get().TagName,'NameProperty'),phase=config.phase or 'unknown'})
                return
            end
            -- Loading a save also invokes ownership notifications. Withhold
            -- only after authoritative binding; the service covers startup.
            if plain.read(config.lease)~=config.launchToken..'\n' then return end
            if not authority.boundary(config.gameSlot) then return end
            local tag=ue.string(id:get().TagName,'NameProperty')
            if not config.suppressedNodes[tag] or (pending and pending.tag==tag) then return end
            local boundary,data=ready(config)
            assert(context:get():GetFullName()==boundary.dataOwner,'Wrong native reward owner')
            if config.nodeItems[tag] and config.nodeItems[tag].ownershipFamily=='power' and not entitled(config,tag) then
                record(config,tag,'vanilla-power-award')
            end
            suppress(config,data,id:get(),tag)
        end)
        -- Pinned UE4SS post callbacks insert OriginalReturnValue immediately
        -- after Context, before the reflected input/out parameters.
        register('/Script/Pagoda.PagodaPlayerUpgradeCatalogSubsystem:GetNumOwnedUpgradesInTree',function() end,function(context,originalReturn,root)
            if suppressing then return end
            if plain.read(config.lease)~=config.launchToken..'\n' then return end
            local catalog=context:get()
            local data=catalog:GetLocalPlayerPlaythroughData()
            if not data:IsValid() then return end
            local boundary=authority.recheck(data:GetOuter(),config.gameSlot)
            if not boundary or boundary.dataOwner~=data:GetFullName() then return end
            local tree=ue.string(root:get().TagName,'NameProperty')
            local list=authority.tags(data.PlayerData.OwnedUpgrades)
            local cacheKey=table.concat(list,'|')
            if tierCacheKey==cacheKey then return tierCounts[tree] or 0 end
            tierCounts={}
            local owned={}
            for _,tag in ipairs(list) do owned[tag]=true end
            local tags={};for tag in pairs(owned) do tags[tag]=true end
            for tag in pairs(config.suppressedNodes) do tags[tag]=true end
            for tag in pairs(tags) do
                local node=config.nodeItems[tag]
                local has=config.suppressedNodes[tag] and node and taken[node.id] or not config.suppressedNodes[tag] and owned[tag]
                if has then
                    rootTags[tag]=rootTags[tag] or ue.string(catalog:GetSkillTreeRootTag({TagName=FName(tag)}).TagName,'NameProperty')
                    local key=rootTags[tag];tierCounts[key]=(tierCounts[key] or 0)+1
                end
            end
            tierCacheKey=cacheKey
            return tierCounts[tree] or 0
        end)
        -- Second layer: an unreceived power cannot be ACTIVATED even if the game re-slots it. The map and
        -- entitlements are plain data refreshed every service; the hook itself reads no files.
        register('/Script/Pagoda.PagodaPlayerUpgradeComponent:CanActivateBossAbilityAtSlot',function() end,function(_,originalReturn,slot)
            if suppressing then return end
            local tag=gateSlots[slot:get()]
            if tag and config.suppressedNodes[tag] and not gateEntitled[tag] then return false end
        end)
        register('/Script/Pagoda.PagodaPlayerUpgradeCatalogSubsystem:GetUpgradeAccessStateForLocalPlayer',function() end,function(_,originalReturn,id)
            if suppressing then return end
            if plain.read(config.lease)~=config.launchToken..'\n' then return end
            local tag=ue.string(id:get().TagName,'NameProperty')
            local node=config.nodeItems[tag]
            -- Preserve the bought node/tier interaction after withholding its
            -- ability. Native ownership remains absent until AP delivery.
            if node and config.suppressedNodes[tag] and taken[node.id] then return 4 end
        end)
    end
end
function M.service(config,boundary,data)
    if not config.nodeLocationsEnabled then return end
    -- One synchronous authorization snapshot per service, not one disk open per
    -- mapped node. Native hooks still read fresh authorization independently.
    local entitlements={}
    for tag in plain.read(config.entitlementFile):gmatch('[^\r\n]+') do entitlements[tag]=true end
    for _,row in ipairs(config.baselineNodes or {}) do record(config,row.tag,'legacy-vanilla-save') end
    for tag,row in pairs(config.nodeItems) do
        if row.ownershipFamily=='power' and not entitled(config,tag,entitlements) and data:IsUpgradeOwned({TagName=FName(tag)}) then
            record(config,tag,'vanilla-power-award')
        end
    end
    -- Reconcile AP-confirmed nodes after reconnect/cold reload without relying
    -- on AP-written vanilla purchase scalars.
    for id in plain.read(config.completedNodesFile):gmatch('%d+') do
        id=tonumber(id);if not taken[id] then taken[id]=true;tierCacheKey=nil end
    end
    gateEntitled=entitlements
    gateSlots=authority.slotted(data)
    local changed=false
    local ordered={};for tag in pairs(config.suppressedNodes or {}) do ordered[#ordered+1]=tag end;table.sort(ordered)
    for _,tag in ipairs(ordered) do
        local retryAt=failedSuppression[tag]
        if retryAt and os.clock()>=retryAt then failedSuppression[tag]=nil;attempts[tag]=0;retryAt=nil end
        if (not config.suppressionTestTags or config.suppressionTestTags[tag]) and not entitled(config,tag,entitlements) and not retryAt then
            local ok,result=pcall(suppress,config,data,{TagName=FName(tag)},tag,entitlements)
            if not ok then
                -- An isolated failed representative must not conceal independent
                -- access/health proofs. Only protected service tests can proceed;
                -- purchases/hooks and production still refuse unsafe removal.
                assert(type(result)=='table' and result.kind=='isolated-suppression-refusal',result)
                failedSuppression[tag]=os.clock()+30 -- back off; the bridge stays alive
                append(config,{kind='node-suppression-refused',tag=tag,reason=result.reason})
            elseif result then changed=true end
        end
    end
    return changed
end
return M
