-- Fan Packs: one native AddCredits per durable, token-bound reservation. At-most-once, acknowledged by file.
local plain=require('plain-json')
local M={}
local seen,attempted='',{}
function M.service(config,boundary,data)
    if not config.fanPacksEnabled then return end
    local command=plain.read(config.creditsControl)
    if command=='' or command==seen then return end
    local index,id,token,epoch=command:match('^credits\n(%d+)\n(%d+)\n([^\n]+)\n(%d+)\n$')
    assert(index and token==config.launchToken,'Wrong fan pack binding')
    assert(os.time()-tonumber(epoch)<=30 and tonumber(epoch)<=os.time()+2,'Expired fan pack')
    assert(plain.read(config.creditsControl..'.intent-'..index)==command,'No durable fan pack reservation')
    assert(config.fanPacksValidated or config.fanPacksTest,'Fan pack capability unvalidated')
    local amount=assert(config.fanPacks[id],'Unknown fan pack ID')
    assert(math.type(amount)=='integer' and amount>0 and amount<=100000,'Invalid fan pack amount')
    assert(not attempted[index],'Ambiguous fan pack attempt')
    seen=command;attempted[index]=true -- consume before the native call; never replay
    local before=data:GetCredits()
    -- bIncrementProgressionCounter=false: received fans are not "earned" fans (no stat/achievement credit).
    data:AddCredits(amount,false)
    local after=data:GetCredits()
    assert(after==before+amount,'Native credits did not change by exactly the pack amount')
    local evidence={kind='fan-pack-applied',index=tonumber(index),item=tonumber(id),amount=amount,before=before,after=after}
    local f=assert(io.open(config.evidence,'a'));f:write(plain.encode(evidence),'\n');f:close()
    plain.write(config.creditsControl..'.applied-'..index,evidence)
end
return M
