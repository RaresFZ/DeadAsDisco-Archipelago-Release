-- Mission access is AP-owned permission; no fabricated story completion flags.
local plain=require('plain-json')
local ue=require('ue-values')
local M={}
local originals={}
local seen=''
local refreshing
local function permit(config)
    return not config.mutationsRefused and plain.read(config.lease)==config.launchToken..'\n' and plain.exists(config.parkedSave)
end
local function enabled(config,tag)
    return not config.accessItems[tag] or ('\n'..plain.read(config.accessFile)):find('\n'..tag..'\n',1,true)~=nil
end
local function tags(values)
    local out={}
    assert(#values<=32,'Unexpected level tag count')
    values:ForEach(function(_,value) out[#out+1]=ue.string(value:get().TagName,'NameProperty') end)
    return out
end
local function replace(array,values)
    -- Pinned TArray::__newindex grows and assigns reflected struct elements.
    -- Avoid nested Lua-table -> ArrayProperty conversion (wrong stack-length
    -- index in this UE4SS build). Mutate the native parameter, never a save.
    array:Empty()
    for i,tag in ipairs(values) do array[i]={TagName=FName(tag)} end
    assert(table.concat(tags(array),'|')==table.concat(values,'|'),'Level TArray replacement refused')
end
function M.start(config)
    if not config.accessEnabled then return end
    assert(config.accessValidated or config.accessTest,'Mission gate capability unvalidated')
    print('[APBridge] ACCESS '..(config.accessTest and 'protected-test' or 'validated')..'\n')
    RegisterHook('/Script/Pagoda.PagodaLevelSelectWidget:SetEnabledLevelTags',function(context,value)
        local ok,err=pcall(function()
        if not permit(config) then return end
        local name=context:get():GetFullName()
        local incoming=value:get()
        local list=tags(incoming.GameplayTags)
        -- All original flags/prerequisites remain. Only selected AP gates are
        -- removed; a received item cannot enable unshipped/test levels.
        if refreshing~=name then originals[name]={tags=list,parents=tags(incoming.ParentTags)} end
        local original=assert(originals[name],'Missing original level permission')
        list=original.tags
        local filtered={};for _,tag in ipairs(list) do if enabled(config,tag) then filtered[#filtered+1]=tag end end
        local parents={}
        for _,parent in ipairs(original.parents) do
            for _,tag in ipairs(filtered) do
                if tag==parent or tag:sub(1,#parent+1)==parent..'.' then parents[#parents+1]=parent;break end
            end
        end
        replace(incoming.GameplayTags,filtered);replace(incoming.ParentTags,parents)
        local f=assert(io.open(config.evidence,'a'))
        f:write(plain.encode({kind='access-filter',available=plain.array(filtered),original_count=#list}),'\n');f:close()
        end)
        if not ok then config.refuseMutation('access-filter: '..tostring(err)) end
    end)
end
function M.service(config)
    if not config.accessEnabled or not permit(config) then return end
    local current=plain.read(config.accessFile)
    if seen==current then return end
    seen=current
    for _,widget in ipairs(FindAllOf('PagodaLevelSelectWidget') or {}) do
        if widget:IsValid() then
            local name=widget:GetFullName()
            if originals[name] then
                refreshing=name
                local ok,err=pcall(function() widget:SetEnabledLevelTags(widget.EnabledLevelTags) end)
                refreshing=nil;assert(ok,err)
            end
        end
    end
end
return M
