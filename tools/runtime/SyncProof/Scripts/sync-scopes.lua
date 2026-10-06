-- Explicit one-shot selective read, only after corroborated direct ownership.
-- AllScopes inventories contexts; only selected persisted variables are decoded.
local ue=require('ue-values')
local selected=require('sync-selection')
local M={}
local function plainName(o)
    assert(o and o:IsValid(),'Invalid scope object')
    local n=o:GetFullName();assert(not n:find('Default__',1,true),'Default scope object');return n
end
local function map(m,cap,fn)
    assert(type(m)=='userdata' and m:type()=='TMap' and m:IsValid(),'Unsupported map wrapper')
    assert(#m<=cap,'Map size cap');local count=0
    m:ForEach(function(k,v) count=count+1;assert(count<=cap,'Map iteration cap');fn(k:get(),v:get()) end)
    assert(count==#m,'Incomplete map')
end
local function tag(v) return ue.string(v.TagName,'NameProperty') end
local function state(v,path,out,budget,depth)
    assert(depth<=4,'Composite depth cap');plainName(v)
    budget.n=budget.n+1;assert(budget.n<=96,'Selected variable cap')
    local class=v:GetClass()
    if class:IsChildOf(StaticFindObject('/Script/Pagoda.PagodaProgressionValue')) then
        local current,viewed=v.CurrentState,v.ViewedState
        assert(math.type(current)=='integer' and math.type(viewed)=='integer','Unsupported int64 wrapper')
        assert(not out[path],'Duplicate child identity')
        out[path]={current=tostring(current),viewed=tostring(viewed)}
    elseif class:IsChildOf(StaticFindObject('/Script/Pagoda.PagodaProgressionComposite')) then
        map(v.InnerVariables,32,function(key,child)
            local name=ue.string(key,'StrProperty')
            assert(name~='' and not name:find('/',1,true),'Unsupported child identity')
            assert(child:GetOuter():GetFullName()==v:GetFullName(),'Wrong composite child owner')
            state(child,path..'/'..name,out,budget,depth+1)
        end)
    else error('Unsupported selected variable variant') end
end
function M.snapshot(world)
    local subsystem=nil
    for _,o in ipairs(FindAllOf('PagodaProgressionSubsystem') or {}) do
        if o:IsValid() and not o:GetFullName():find('Default__',1,true) and o:GetWorld():IsValid() then
            assert(not subsystem,'Ambiguous progression subsystem');subsystem=o
        end
    end
    assert(subsystem,'No progression subsystem');plainName(subsystem)
    assert(subsystem:GetClass():GetFullName()=='Class /Script/Pagoda.PagodaProgressionSubsystem','Wrong progression class')
    assert(subsystem:GetWorld():GetFullName()==world,'Cross-world progression')
    local result={owner=subsystem:GetFullName(),world=world,active={},contexts={}}
    map(subsystem.ActiveScopes,16,function(k,v)
        plainName(v);local scope=tag(k)
        assert(scope==tag(v.ScopeTag),'Active scope key mismatch')
        result.active[scope]={context=ue.string(v.ContextId,'NameProperty'),owner=v:GetFullName()}
    end)
    local total,budget=0,{n=0}
    map(subsystem.AllScopes,16,function(k,group)
        local scope=tag(k)
        map(group.Map,32,function(context,v)
            total=total+1;assert(total<=32,'Context cap');plainName(v)
            local id=ue.string(context,'NameProperty')
            assert(scope==tag(v.ScopeTag) and id==ue.string(v.ContextId,'NameProperty'),'AllScopes key mismatch')
            assert(v:GetClass():GetFullName()=='Class /Script/Pagoda.PagodaProgressionScope','Wrong scope class')
            assert(v:GetOuter():GetFullName()==subsystem:GetFullName(),'Wrong scope owner')
            local key=scope..'|'..id;assert(not result.contexts[key],'Duplicate context')
            local row={scope=scope,context=id,owner=v:GetFullName(),active=result.active[scope]~=nil and result.active[scope].owner==v:GetFullName(),selected={}}
            result.contexts[key]=row
            if selected[scope] then
                map(v.Variables,1024,function(variableTag,variable)
                    local t=tag(variableTag)
                    if selected[scope][t] then
                        assert(variable:GetOuter():GetFullName()==v:GetFullName(),'Wrong variable owner')
                        assert(tag(variable.Tag)==t,'Variable tag mismatch')
                        local leaves={};state(variable,'',leaves,budget,0)
                        row.selected[t]=leaves
                    end
                end)
            end
        end)
    end)
    for scope,active in pairs(result.active) do
        local c=result.contexts[scope..'|'..active.context]
        assert(c and c.owner==active.owner,'Active scope missing from AllScopes')
    end
    result.selectedObjects=budget.n
    return result
end
return M
