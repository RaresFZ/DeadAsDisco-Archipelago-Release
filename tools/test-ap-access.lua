-- Reflected parameter replacement/refresh fixture; no native gameplay claim.
package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local root='artifacts/ap-access-fixture'
local function put(p,s) local f=assert(io.open(p,'w'));f:write(s);f:close() end
local names={}
FName=function(s)
 local u=assert(io.tmpfile());u:close();names[u]=s
 debug.setmetatable(u,{__index={type=function() return 'FName' end,ToString=function(v) return names[v] end}})
 return u
end
local function array(list)
 local values={};for i,s in ipairs(list) do values[i]={TagName=FName(s)} end
 return setmetatable({}, {__len=function() return #values end,
 __newindex=function(_,i,v) assert(i==#values+1);values[i]=v end,
 __index=function(_,k)
  if k=='Empty' then return function() values={} end end
  if k=='ForEach' then return function(_,fn) for i,v in ipairs(values) do fn(i,{get=function() return v end}) end end end
  return values[k]
 end})
end
local function strings(a) local out={};a:ForEach(function(_,v) out[#out+1]=names[v:get().TagName] end);return out end
local hook
RegisterHook=function(_,pre) hook=pre end
local widget={IsValid=function() return true end,GetFullName=function() return 'widget' end}
function widget:SetEnabledLevelTags(value)
 local native={GameplayTags=array(strings(value.GameplayTags)),ParentTags=array(strings(value.ParentTags))}
 hook({get=function() return self end},{get=function() return native end})
 self.EnabledLevelTags=native
end
FindAllOf=function() return {widget} end
local config={accessEnabled=true,accessTest=true,lease=root..'.lease',launchToken='test',parkedSave=root..'.parked',
 accessFile=root..'.access',evidence=root..'.evidence',accessItems={['Level.A']=true,['Level.B']=true},
 refuseMutation=function(err) error(err) end}
put(config.lease,'test\n');put(config.parkedSave,'protected');put(config.accessFile,'');put(config.evidence,'')
local module=require('access');module.start(config)
widget:SetEnabledLevelTags({GameplayTags=array({'Level.A','Level.B','Hub.Safe'}),ParentTags=array({'Level','Hub'})})
assert(table.concat(strings(widget.EnabledLevelTags.GameplayTags),'|')=='Hub.Safe')
assert(table.concat(strings(widget.EnabledLevelTags.ParentTags),'|')=='Hub')
put(config.accessFile,'Level.A\n');module.service(config)
assert(table.concat(strings(widget.EnabledLevelTags.GameplayTags),'|')=='Level.A|Hub.Safe','Refresh must recover original permission')
assert(table.concat(strings(widget.EnabledLevelTags.ParentTags),'|')=='Level|Hub')
put(config.accessFile,'Level.A\nLevel.B\n');module.service(config)
assert(table.concat(strings(widget.EnabledLevelTags.GameplayTags),'|')=='Level.A|Level.B|Hub.Safe')
config.mutationsRefused=true;put(config.accessFile,'');module.service(config)
assert(#widget.EnabledLevelTags.GameplayTags==3,'Global refusal must stop access mutation')
print('PASS: native parameter array replacement, parent filtering, release refresh and unrelated access preservation')
