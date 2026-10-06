-- Schema-directed decoding for pinned UE4SS e3ba1016. Never tostring userdata.
local M = {}
local stringTypes = {StrProperty='FString', NameProperty='FName', TextProperty='FText', Utf8StrProperty='FUtf8String', AnsiStrProperty='FAnsiString'}
function M.string(value, propertyType)
    local expected = assert(stringTypes[propertyType], 'Unsupported reflected string property')
    assert(type(value)=='userdata', expected..' must be UE4SS userdata')
    assert(value:type()==expected, 'Wrong UE4SS string wrapper for '..propertyType)
    local decoded=value:ToString()
    assert(type(decoded)=='string', expected..':ToString() must return Lua string')
    return decoded
end
function M.number(value)
    assert(type(value)=='number' and value==value and math.abs(value)<math.huge, 'Invalid reflected number')
    return value
end
return M
