-- Executes the actual adapter with UE4SS-shaped userdata fixtures. No game/save access.
package.path='archipelago/game-mod/?.lua;tools/runtime/Common/?.lua;'..package.path
local meta={}
local function wrap(kind,value)
 local u=assert(io.tmpfile());u:close();meta[u]={kind=kind,value=value}
 debug.setmetatable(u,{__index={type=function(s) return meta[s].kind end,ToString=function(s) return meta[s].value end,
  IsValid=function() return true end,ForEach=function(s,fn) for _,v in ipairs(meta[s].value) do fn({get=function() return {TagName=wrap('FName',v)} end}) end end},__len=function(s) return #meta[s].value end});return u
end
local reads=0
local invalid={IsValid=function() return false end}
local function obj(name,class,world)
 return {IsValid=function() reads=reads+1;return true end,GetFullName=function() return name end,
 GetClass=function() return {GetFullName=function() return 'Class /Script/Pagoda.'..class end} end,GetWorld=function() return world end}
end
local hub=obj('World /Game/Pagoda/Levels/DiveBar/L_DiveBar.L_DiveBar','World',invalid)
local title=obj('World /Game/Pagoda/Levels/Main_Menu/Level_MainMenu.Level_MainMenu','World',invalid)
local data=obj('data','PagodaPlaythroughPlayerData',hub)
local saves=obj('saves','PagodaGameSavesSubsystem',hub)
data.GetOuter=function() return saves end
data.bWasLoaded=true;data.PlayerData={OwnedUpgrades=wrap('TSet',{'old'}),EquippedUpgrades=wrap('TSet',{})}
saves.PlaythroughPlayerData=data;saves.CurrentPlaythroughSlotName=wrap('FString','slot')
local root='artifacts/runtime/fixtures/ap-bridge'
local function put(path,text) local f=assert(io.open(path,'w'));f:write(text);f:close() end
local contexts,current={},{}
for i=1,6 do
 local key='scope|'..i
 contexts[key]={anchor={['']={current='4',viewed='4'}}}
 current[key]={owner='scope'..i,selected={anchor={['']={current='4',viewed='4'}}}}
end
current['scope|1'].selected.check={['']={current='4',viewed='4'}}
local config={generation='generation',launchToken='token',gameSlot='slot',sessionFile=root..'-session.json',
 parkedSave=root..'-original',lease=root..'-lease',control=root..'-control',output=root..'-snapshot',
 evidence=root..'-evidence.jsonl',refusal=root..'-refusal',owned={'old'},equipped='',contexts=contexts,
 checkScope='scope',checkContext='1',checkTag='check',itemTag='new',locationId=101}
package.preload['ap-config']=function() return config end
local scopeReads,predicateReads=0,0
local onScopeRead
package.preload['sync-scopes']=function() return {snapshot=function(w)
 scopeReads=scopeReads+1;if onScopeRead then onScopeRead() end
 return {owner='progression',world=w,active={scope={context='1',owner='scope1'}},contexts=current}
end} end
package.preload['purchase']=function() return {read=function() predicateReads=predicateReads+1;return true,{owner='purchase'} end} end
local rows,poll={},nil;local originalPrint=print
print=function(s) rows[#rows+1]=s end
EngineTickAvailable=true
local list={saves};local authorityScans=0
FindAllOf=function(c) assert(c=='PagodaGameSavesSubsystem');authorityScans=authorityScans+1;return list end
LoopInGameThreadWithDelay=function(delay,fn) assert(delay==2000);poll=fn end
local function fresh()
 put(config.sessionFile,'{"status":"isolated"}');put(config.parkedSave,'original fixture');put(config.lease,'token\n');put(config.control,'')
 rows={};dofile('archipelago/game-mod/main.lua')
end
fresh();poll();assert(scopeReads==0);poll();poll();assert(rows[#rows]:find('STATE ready',1,true));assert(predicateReads==1)
local scans=authorityScans
poll();assert(predicateReads==1,'Repeated native predicate');assert(authorityScans==scans+1,'Redundant authority census returned')
-- Title rejects containers; natural reload repeats authority/native join.
saves.GetWorld=function() return title end;saves.CurrentPlaythroughSlotName=wrap('FString','')
local n=scopeReads;poll();poll();assert(scopeReads==n)
saves.GetWorld=function() return hub end;saves.CurrentPlaythroughSlotName=wrap('FString','slot')
poll();poll();poll();assert(predicateReads==2)
-- No lease means no UObject reads, even with a surviving config/sidecar.
fresh();put(config.lease,'');local before=reads;poll();assert(reads==before)
for _,bad in ipairs({'outer','reset','anchor','ambiguous','unreviewed-grant','original-restored','wrong-slot'}) do
 fresh()
 if bad=='outer' then data.GetOuter=function() return hub end
 elseif bad=='reset' then data.PlayerData.OwnedUpgrades=wrap('TSet',{})
 elseif bad=='anchor' then current['scope|2'].selected.anchor[''].current='0'
 elseif bad=='ambiguous' then list={saves,saves}
 elseif bad=='unreviewed-grant' then put(config.control,'grant\n')
 elseif bad=='original-restored' then put(config.sessionFile,'{"status":"restored"}')
 else saves.CurrentPlaythroughSlotName=wrap('FString','other') end
 poll();poll();poll();assert(rows[#rows]:find('FAILED',1,true),bad)
 before=reads;poll();assert(reads==before,'Read after refusal')
 data.GetOuter=function() return saves end;data.PlayerData.OwnedUpgrades=wrap('TSet',{'old'})
 current['scope|2'].selected.anchor[''].current='4';list={saves};saves.CurrentPlaythroughSlotName=wrap('FString','slot')
end
-- Same-callback recheck still catches direct-owner replacement during traversal.
fresh();poll();local replacement=obj('replacement-data','PagodaPlaythroughPlayerData',hub)
replacement.GetOuter=function() return saves end;replacement.bWasLoaded=true
onScopeRead=function() saves.PlaythroughPlayerData=replacement end
poll();assert(rows[#rows]:find('FAILED',1,true),'Lost direct-owner change guard')
onScopeRead=nil;saves.PlaythroughPlayerData=data
fresh();poll();put(config.control,'stop\n');before=reads;poll();poll();assert(reads==before)
-- A slow PC or a heavy scene must back off, never end the session; only a credible stall or a real error stops the bridge.
local realClock,fakeNow=os.clock,0
os.clock=function() return fakeNow end
local function refusalText() local f=assert(io.open(config.refusal,'r'));local t=f:read('a');f:close();return t end
local function slowTick(ms) onScopeRead=function() fakeNow=fakeNow+ms/1000 end end
fresh();poll();poll();poll();assert(rows[#rows]:find('STATE ready',1,true))
slowTick(400);poll();assert(not rows[#rows]:find('FAILED',1,true),'One slow tick ended the session')
local sc=scopeReads;poll();assert(scopeReads==sc,'Slow tick did not back off');poll();assert(scopeReads==sc+1,'Did not resume after backing off')
poll();poll();poll();poll();assert(not rows[#rows]:find('FAILED',1,true),'Repeated slow ticks ended the session')
fresh();poll();poll();poll();slowTick(3500);poll()
assert(rows[#rows]:find('FAILED',1,true),'A credible stall did not stop the bridge')
assert(refusalText():find('callback-time-budget',1,true) and refusalText():find('stage=',1,true),'Stall reason missing')
onScopeRead=function() error() end
fresh();poll();poll();poll();poll();assert(rows[#rows]:find('FAILED',1,true),'Error without a message did not stop the bridge')
assert(refusalText():find('without a message',1,true) and not refusalText():find('callback-time-budget',1,true),'Nil error mislabelled as a time budget')
onScopeRead=nil;os.clock=realClock
-- The actual scheduler must not combine preparation, native call and post-read.
config.phase3Enabled=true
local prepared,dispatched,completed=0,0,0
package.loaded.proof={prepare=function(command,_,boundary)
 prepared=prepared+1;return {command=command,boundary=boundary}
end,dispatch=function(intent)
 dispatched=dispatched+1;intent.native_ms=1;return intent
end,complete=function()
 completed=completed+1;return {kind='fixture-completed'}
end}
fresh();poll();poll();poll();put(config.control,'proof-grant\n')
local n=scopeReads;poll();assert(prepared==0 and dispatched==0)
poll();assert(prepared==1 and dispatched==0 and scopeReads==n+1)
poll();assert(dispatched==1 and completed==0 and scopeReads==n+1)
poll();assert(completed==1 and scopeReads==n+1)
poll();poll();poll();assert(dispatched==1,'Repeated control re-dispatched')
fresh();poll();poll();poll();put(config.control,'proof-grant\n');poll();poll()
put(config.control,'stop\n');poll();poll();assert(dispatched==1,'Stop did not cancel pending dispatch')
config.phase3Enabled=false;package.loaded.proof=nil
print=originalPrint
print('PASS: actual AP adapter corroboration, native-predicate cadence, title/reload, missing lease, wrong Outer/slot, reset/anchor, ambiguity, grants-disabled and no reads after stop/refusal. Fixtures only.')
