-- Shared-mechanism fixture for the temporary trap and zero-health DeathLink services.
-- This is not native gameplay validation.
package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local root='artifacts/ap-trap-fixture'
local function put(p,s) local f=assert(io.open(p,'w'));f:write(s);f:close() end
local scans={}
local function world(name) return {IsValid=function() return true end,GetFullName=function() return name end} end
local health,maxHealth,alive=100,100,true
local inhibited=false
local asc={IsValid=function() return true end,GetFullName=function() return 'asc' end,
 GetUserAbilityActivationInhibited=function() return inhibited end,
 SetUserAbilityActivationInhibited=function(_,v) inhibited=v end}
local pawn
pawn={IsValid=function() return true end,GetFullName=function() return 'Pawn_1' end,
 GetWorld=function() return world('World_A') end,IsAlive=function() return alive end,
 Controller={IsValid=function() return true end,Player={IsValid=function() return true end,IsA=function() return true end}},
 AbilitySystemComponent=asc}
setmetatable(pawn,{__index=function(_,k)
 if k=='HealthAttributeSet' then return {Health={CurrentValue=health},MaxHealth={CurrentValue=maxHealth}} end
end})
local listener={IsValid=function() return true end,GetFullName=function() return 'Listener_1' end,
 GetAvatarActorFromActorInfo=function() return pawn end}
FindAllOf=function(class)
 scans[class]=(scans[class] or 0)+1
 if class=='PagodaPlayerCharacter' then return {pawn} end
 if class=='GA_Listen_Death_Player_C' then return {listener} end
 return {}
end
StaticFindObject=function() return {IsValid=function() return true end,IsA=function() return true end} end
FName=function(s) return s end
ExecuteInGameThreadWithDelay=function() end
local changes={}
package.loaded['health-effect']={available=function() return true end,
 damage=function(p,amount)
  local before=health
  amount=math.min(amount,40) -- the game caps a single hit
  changes[#changes+1]=-amount
  health=math.max(0,health-amount);if health<=0 then alive=false end
  return before-health
 end,
 kill=function(p)
  changes[#changes+1]=-health;health=0;alive=false
  return {applications=1,total=0,health=0}
 end}
local players=require('players')
local traps=require('traps')
local deaths=require('deathlink')
local config={trapsEnabled=true,trapsTest=true,launchToken='tok',trapControl=root..'.trap',trapDuration=30,
 trapItems={['1']='half-heart',['2']='silence'},evidence=root..'.evidence',
 deathLinkEnabled=true,deathLinkTest=true,deathLinkControl=root..'.death'}
put(config.evidence,'');put(config.trapControl,'');put(config.deathLinkControl,'')
local boundary={world='World_A'}
local function tick(fn) players.begin();return fn() end
local function trap(index,id)
 local epoch=tostring(os.time())
 local command='trap\n'..index..'\n'..id..'\ntok\n'..epoch..'\n'
 put(config.trapControl..'.intent-'..index,command);put(config.trapControl,command)
end
-- Idle trap ticks never scan for the player.
for _=1,5 do tick(function() traps.service(config,boundary) end) end
assert((scans.PagodaPlayerCharacter or 0)==0,'Idle trap service must not scan the object array')
-- Half Heart: nonlethal five HP, unchanged maximum, applied once.
trap(1,1);tick(function() traps.service(config,boundary) end)
assert(health==95 and maxHealth==100 and changes[1]==-5,'Half Heart must remove exactly five HP')
tick(function() traps.service(config,boundary) end)
assert(health==95,'Applied trap command must never replay')
-- Half Heart cannot kill.
health=3;trap(2,1);tick(function() traps.service(config,boundary) end)
assert(health==1 and alive,'Half Heart must remain nonlethal')
health=100
-- Silence inhibits then restores on duration/world change/death.
trap(3,2);tick(function() traps.service(config,boundary) end)
assert(inhibited,'Silence must inhibit ability activation')
tick(function() traps.service(config,{world='World_B'}) end)
assert(not inhibited,'World transition must restore silence')
trap(4,2);tick(function() traps.service(config,boundary) end);assert(inhibited)
alive=false;tick(function() traps.service(config,boundary) end)
assert(not inhibited,'Player death must restore silence');alive=true
-- One census per tick even when traps and DeathLink are both active.
scans={}
trap(5,2);tick(function() traps.service(config,boundary);deaths.service(config,boundary) end)
assert(scans.PagodaPlayerCharacter==1,'Traps and DeathLink must share one player census, got '..tostring(scans.PagodaPlayerCharacter))
traps.cleanup();assert(not inhibited)
-- DeathLink listener lookup is cached after the first positive answer.
scans={}
for _=1,4 do tick(function() deaths.service(config,boundary) end) end
assert((scans.GA_Listen_Death_Player_C or 0)==0,'Cached listener must not rescan')
-- Incoming DeathLink: capped hits across services (game ignores hits in its hit-react window).
changes={};health=100;alive=true
local epoch=tostring(os.time())
put(config.deathLinkControl,'tok\n'..epoch..'\n')
local hits=0
for _=1,8 do tick(function() return deaths.service(config,boundary) end);if health<=0 then break end end
assert(health==0 and #changes==3,'DeathLink must reach zero real HP through repeated natural damage, got '..#changes..' hits')
tick(function() return deaths.service(config,boundary) end)
assert(#changes==3,'Consumed DeathLink command must not replay')
local journal=assert(io.open(config.evidence)):read('a')
assert(journal:find('deathlink%-kill%-finished'),'Kill sequence must be journaled')
-- Wrong token refuses before mutation.
alive=true;health=100;put(config.deathLinkControl,'bad\n'..epoch..'\n')
assert(not pcall(function() tick(function() return deaths.service(config,boundary) end) end),'Wrong DeathLink binding must refuse')
assert(health==100,'Refused DeathLink must not mutate')
print('PASS: trap census/idle cost, Half Heart nonlethal, Silence restoration, DeathLink zero-health path and replay refusal. Fixtures only.')
