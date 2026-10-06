-- Plain-data encoding only. Tables represent objects; arrays are explicit.
local M={}
function M.array(values) return {__array=values} end
function M.encode(v)
    if type(v)=='string' then return '"'..v:gsub('[%z\1-\31\\"]',function(c) return string.format('\\u%04x',string.byte(c)) end)..'"' end
    if type(v)=='number' then assert(v==v and math.abs(v)<math.huge,'Invalid JSON number');return tostring(v) end
    if type(v)=='boolean' then return tostring(v) end
    assert(type(v)=='table','Only plain data can cross bridge')
    local out={}
    if v.__array then
        for _,x in ipairs(v.__array) do out[#out+1]=M.encode(x) end
        return '['..table.concat(out,',')..']'
    end
    for k,x in pairs(v) do assert(type(k)=='string','JSON object key');out[#out+1]=M.encode(k)..':'..M.encode(x) end
    table.sort(out);return '{'..table.concat(out,',')..'}'
end
function M.read(path)
    local f=io.open(path,'r');if not f then return '' end
    local value=f:read('*a');f:close();return value
end
function M.exists(path)
    local f=io.open(path,'r');if not f then return false end;f:close();return true
end
function M.write(path,row)
    -- Windows CRT rename does not replace existing files. The other slot remains
    -- intact during replacement; readers select the highest complete sequence.
    local tmp=path..'.tmp';local f=assert(io.open(tmp,'w'))
    assert(f:write(M.encode(row)));assert(f:close())
    os.remove(path)
    assert(os.rename(tmp,path),'Snapshot publish failed')
end
return M
