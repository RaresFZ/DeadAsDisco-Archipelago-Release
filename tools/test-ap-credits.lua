-- Fixture for the Fan Pack service (not native gameplay validation).
package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local root='artifacts/ap-credits-fixture'
local function put(p,s) local f=assert(io.open(p,'w'));f:write(s);f:close() end
local credits=1000
local calls={}
local data={GetCredits=function() return credits end,AddCredits=function(_,n,counter) calls[#calls+1]={n,counter};credits=credits+n end}
local config={fanPacksEnabled=true,fanPacksTest=true,launchToken='tok',creditsControl=root..'.ctl',evidence=root..'.log',fanPacks={['77']=500}}
put(config.evidence,'');put(config.creditsControl,'')
local module=require('credits')
local function dispatch(index,id,token,epoch)
 local command='credits\n'..index..'\n'..id..'\n'..token..'\n'..(epoch or os.time())..'\n'
 put(config.creditsControl..'.intent-'..index,command);put(config.creditsControl,command)
end
module.service(config,{},data);assert(#calls==0,'no command, no call')
dispatch(1,77,'tok');module.service(config,{},data)
assert(credits==1500 and #calls==1 and calls[1][1]==500 and calls[1][2]==false,'one AddCredits(500,false)')
assert(assert(io.open(config.creditsControl..'.applied-1')):read('a'):find('"after":1500'),'acknowledged by file')
module.service(config,{},data);assert(#calls==1,'the same command never replays')
-- Refusals happen before any native call.
dispatch(2,77,'wrong');assert(not pcall(module.service,config,{},data),'wrong token refused');assert(#calls==1)
dispatch(3,99,'tok');assert(not pcall(module.service,config,{},data),'unknown pack refused');assert(#calls==1)
dispatch(4,77,'tok',os.time()-100);assert(not pcall(module.service,config,{},data),'expired refused');assert(#calls==1)
put(config.creditsControl,'credits\n5\n77\ntok\n'..os.time()..'\n');os.remove(config.creditsControl..'.intent-5')
assert(not pcall(module.service,config,{},data),'no durable reservation refused');assert(#calls==1)
-- A native call that does not change credits by exactly the amount is a hard stop.
data.AddCredits=function() end
dispatch(6,77,'tok');assert(not pcall(module.service,config,{},data),'inexact native change refused')
config.fanPacksTest=false;dispatch(7,77,'tok');assert(not pcall(module.service,config,{},data),'unvalidated capability refused')
print('PASS: fan pack service applies exactly once with false counter flag, acknowledges durably and refuses every unsafe command before native calls')
