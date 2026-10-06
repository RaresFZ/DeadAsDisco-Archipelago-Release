package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local root='artifacts/ap-production-fixture'
local function put(p,s) local f=assert(io.open(p,'w'));f:write(s);f:close() end
local meta={}
local function name(value)
    local u=assert(io.tmpfile());u:close();meta[u]=value
    debug.setmetatable(u,{__index={type=function() return 'FName' end,ToString=function(s) return meta[s] end}})
    return u
end
local enabled=0
local definition={UpgradeIdTag={TagName=name('Tag.One')},IsValid=function() return true end,IsA=function() return true end}
setmetatable(definition,{__index=function(_,k) if k=='EnabledState' then return enabled end end})
StaticFindObject=function(path) return definition end
local owned=false;local calls=0
local data={IsUpgradeEquipped=function() return true end,IsUpgradeOwned=function() return owned end,AddOwnedUpgrade=function(_,t) assert(t==definition.UpgradeIdTag);calls=calls+1;owned=true end}
local config={productionEnabled=true,productionItems={['42']={asset='exact',tag='Tag.One'}},launchToken='fixture',productionControl=root,evidence=root..'.log'}
if arg[1] then
    local generated=assert(loadfile(arg[1]))()
    assert(generated.productionEnabled and type(generated.productionItems)=='table')
    local count=0
    for id,row in pairs(generated.productionItems) do
        assert(type(id)=='string' and tonumber(id) and row.tag and row.asset)
        count=count+1
    end
    assert(count==44,'Generated production map must contain all 44 supported IDs')
end
local boundary={world='fixture-world',dataOwner='fixture-direct-owner'}
local service=require('production').service
put(root,'');assert(not service(config,boundary,data));assert(calls==0)
local function command(i,id,token,epoch)
    local text='grant\n'..i..'\n'..id..'\n'..token..'\n'..epoch..'\n'
    put(root,text);put(root..'.intent-'..i,text)
end
command(0,42,'wrong',os.time());assert(not pcall(service,config,boundary,data));assert(calls==0)
command(0,999,'fixture',os.time());assert(not pcall(service,config,boundary,data));assert(calls==0)
command(0,42,'fixture',os.time()-40);assert(not pcall(service,config,boundary,data));assert(calls==0)
command(0,42,'fixture',os.time());enabled=2;assert(not pcall(service,config,boundary,data));assert(calls==0)
enabled=0;assert(service(config,boundary,data));assert(calls==0,'Preparation must not mutate')
assert(service(config,boundary,data));assert(calls==1 and owned)
assert(not service(config,boundary,data));assert(calls==1,'Same command must not replay')
command(1,42,'fixture',os.time());assert(not service(config,boundary,data));assert(calls==1,'Already-owned receipt must not regrant')
os.remove(root);os.remove(root..'.intent-0');os.remove(root..'.intent-1');os.remove(root..'.log')
print('PASS: actual production Lua refuses wrong binding/unknown ID/expired/disabled item; separates preparation; grants once; already-owned receipt skips native.')
