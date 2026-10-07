"""Read-only GVAS decoder for the two progression saves of the verified build (port of tools/read-tagged-save.mjs).

Output mirrors the JavaScript decoder exactly so both can be compared on real saves: a list of properties
{name,type,flags,size,value,status}; Int64 values are decimal strings; GameplayTag structs are property lists.
"""
import struct

# Engine version stamped in the save header: the game build before (33649) and after (33836) the October 2026 update.
# The property layout was checked against real saves written by both.
SUPPORTED_ENGINES = {(5, 7, 4, 33649), (5, 7, 4, 33836)}
SUPPORTED_CLASSES = {
    "PagodaGP_Main.sav": "/Script/Pagoda.PagodaGlobalProgressSaveGame",
    "PagodaPT_M_0.sav": "/Script/Pagoda.PagodaPlaythroughSaveGame",
}


class SaveError(RuntimeError):
    pass


def _fstring(b, o, limit):
    n = struct.unpack_from("<i", b, o)[0]
    o += 4
    if n == 0:
        return "", o
    if abs(n) > limit:
        raise SaveError("Invalid FString length")
    size = abs(n) * (2 if n < 0 else 1)
    if o + size > len(b):
        raise SaveError("Invalid FString")
    text = b[o:o + size].decode("utf-16-le" if n < 0 else "utf-8")
    if not text.endswith("\0"):
        raise SaveError("FString lacks terminator")
    return text[:-1], o + size


def header(b):
    if b[:4] != b"GVAS":
        raise SaveError("Not a GVAS save")
    o = 4
    save_version, ue4 = struct.unpack_from("<ii", b, o)
    o += 8
    ue5 = None
    if save_version >= 3:
        ue5 = struct.unpack_from("<i", b, o)[0]
        o += 4
    major, minor, patch = struct.unpack_from("<HHH", b, o)
    o += 6
    changelist = struct.unpack_from("<I", b, o)[0] & 0x7FFFFFFF
    o += 4
    _branch, o = _fstring(b, o, 100000)
    o += 4  # custom version format
    count = struct.unpack_from("<i", b, o)[0]
    o += 4
    if count < 0 or count > 10000:
        raise SaveError("Invalid custom-version count")
    o += count * 20
    save_class, o = _fstring(b, o, 100000)
    return {"ue5": ue5, "engine": (major, minor, patch, changelist), "save_class": save_class, "offset": o}


class _Reader:
    def __init__(self, b, p, end=None):
        self.b, self.p, self.end = b, p, len(b) if end is None else end

    def ensure(self, n):
        if n < 0 or self.p + n > self.end:
            raise SaveError(f"Read out of bounds @{self.p}")

    def i32(self):
        self.ensure(4)
        v = struct.unpack_from("<i", self.b, self.p)[0]
        self.p += 4
        return v

    def u8(self):
        self.ensure(1)
        v = self.b[self.p]
        self.p += 1
        return v

    def str(self):
        n = self.i32()
        if not n:
            return ""
        if abs(n) > 1000000:
            raise SaveError("Invalid FString length")
        size = abs(n) * (2 if n < 0 else 1)
        self.ensure(size)
        text = self.b[self.p:self.p + size].decode("utf-16-le" if n < 0 else "utf-8")
        self.p += size
        if not text.endswith("\0"):
            raise SaveError("Nonterminated FString")
        return text[:-1]

    def type(self, depth=0):
        if depth > 20:
            raise SaveError("Type recursion limit")
        name, n = self.str(), self.i32()
        if n < 0 or n > 10:
            raise SaveError("Invalid type arity")
        return (name, [self.type(depth + 1) for _ in range(n)])


def _type_text(t):
    return t[0] + ("(" + ",".join(_type_text(a) for a in t[1]) + ")" if t[1] else "")


def _value(r, t, flags=0, depth=0):
    if depth > 25:
        raise SaveError("Value recursion limit")
    name, args = t
    if name == "BoolProperty":
        return bool(r.u8()) if flags == -1 else bool(flags & 16)
    if name == "IntProperty":
        return r.i32()
    if name in ("Int64Property", "UInt64Property"):
        r.ensure(8)
        v = struct.unpack_from("<q", r.b, r.p)[0]
        r.p += 8
        return str(v)
    if name == "FloatProperty":
        r.ensure(4)
        v = struct.unpack_from("<f", r.b, r.p)[0]
        r.p += 4
        return v
    if name == "DoubleProperty":
        r.ensure(8)
        v = struct.unpack_from("<d", r.b, r.p)[0]
        r.p += 8
        return v
    if name in ("NameProperty", "StrProperty", "EnumProperty", "ObjectProperty"):
        return r.str()
    if name == "ByteProperty":
        return r.str() if args else r.u8()
    if name == "StructProperty":
        st = args[0][0] if args else None
        if st == "GameplayTag":
            return _properties(r, depth + 1)
        if st == "InstancedStruct":
            struct_type, size = r.str(), r.i32()
            r.ensure(size)
            sub = _Reader(r.b, r.p, r.p + size)
            fields = _properties(sub, depth + 1)
            if sub.p != sub.end:
                raise SaveError("InstancedStruct boundary mismatch")
            r.p += size
            return {"structType": struct_type, "fields": fields}
        if st == "GameplayTagContainer":
            n = r.i32()
            if n < 0 or n > 100000:
                raise SaveError("Bad tag count")
            return [r.str() for _ in range(n)]
        if st in ("DateTime", "Timespan"):
            r.ensure(8)
            r.p += 8
            return {"native": st, "bytes": 8}
        return _properties(r, depth + 1)
    if name == "MapProperty":
        if r.i32() != 0:
            raise SaveError("Nonempty removed-map keys unsupported")
        n = r.i32()
        if n < 0 or n > 100000:
            raise SaveError("Bad map count")
        return [{"key": _value(r, args[0], -1, depth + 1), "value": _value(r, args[1], -1, depth + 1)} for _ in range(n)]
    if name == "SetProperty":
        if r.i32() != 0:
            raise SaveError("Nonempty removed-set unsupported")
        n = r.i32()
        if n < 0 or n > 100000:
            raise SaveError("Bad set count")
        return [_value(r, args[0], -1, depth + 1) for _ in range(n)]
    if name == "ArrayProperty":
        n = r.i32()
        if n < 0 or n > 100000:
            raise SaveError("Bad array count")
        return [_value(r, args[0], 0, depth + 1) for _ in range(n)]
    raise SaveError("Unsupported type " + _type_text(t))


def _properties(r, depth=0):
    result = []
    while r.p < r.end:
        name = r.str()
        if name == "None":
            return result
        t = r.type()
        size = r.i32()
        flags = r.u8()
        if flags & ~63:
            raise SaveError("Unknown tag flags")
        if flags & 1:
            r.i32()
        if flags & 2:
            r.ensure(16)
            r.p += 16
        if flags & 4:
            ext = r.u8()
            if ext & ~3:
                raise SaveError("Unknown extensions")
            if ext & 2:
                r.u8()
                r.i32()
        r.ensure(size)
        end = r.p + size
        sub = _Reader(r.b, r.p, end)
        try:
            value = _value(sub, t, flags, depth + 1)
            if sub.p != end:
                raise SaveError("Payload consumption mismatch")
        except SaveError as error:
            raise SaveError(f"Opaque property {name}: {error}") from None
        result.append({"name": name, "type": _type_text(t), "flags": flags, "size": size, "value": value, "status": "decoded"})
        r.p = end
    raise SaveError("Missing None property terminator")


def read_tagged_save(b, name):
    h = header(b)
    if h["ue5"] != 1018 or h["engine"] not in SUPPORTED_ENGINES:
        raise SaveError("Unsupported save header")
    if SUPPORTED_CLASSES.get(name) != h["save_class"]:
        raise SaveError("Only current global/playthrough progression saves are supported")
    r = _Reader(b, h["offset"])
    if r.u8() != 0:
        raise SaveError("Unsupported archive preamble")
    props = _properties(r)
    if len(b) - r.p != 4 or struct.unpack_from("<I", b, r.p)[0] != 0:
        raise SaveError("Unexpected save trailer")
    return {"header": h, "properties": props}


def field(fields, name):
    rows = [p for p in fields if p["name"] == name and p["status"] == "decoded"]
    if len(rows) != 1:
        raise SaveError(f"Missing/ambiguous decoded field {name}")
    return rows[0]["value"]


def tag(v):
    return field(v, "TagName")


def saved_scopes(parsed):
    """[{scope, context, variables:[{key,value}]}] exactly as sync-proof-offline.savedScopes."""
    is_global = parsed["header"]["save_class"].endswith(".PagodaGlobalProgressSaveGame")
    if is_global:
        scopes = [{"scope": "Progression.Scope.Global", "context": "None", "fields": field(parsed["properties"], "GlobalScopeSnapshot")}]
    else:
        scopes = [{"scope": tag(field(s["key"], "Tag")), "context": field(s["key"], "Context"), "fields": s["value"]}
                  for s in field(parsed["properties"], "ScopeSnapshots")]
    seen = set()
    for s in scopes:
        key = (s["scope"], s["context"])
        if key in seen:
            raise SaveError("Duplicate scope context")
        seen.add(key)
        s["variables"] = field(s["fields"], "Variables")
        tags = [tag(x["key"]) for x in s["variables"]]
        if len(set(tags)) != len(tags):
            raise SaveError("Duplicate scoped variable")
    return scopes


def leaves(v, prefix="", out=None):
    """Flatten a Value/CompositeSnapshot into {path: CurrentState string} (decoder contract of ap-saved-state)."""
    out = {} if out is None else out
    if v["structType"].endswith("ValueSnapshot"):
        out[prefix] = str(field(v["fields"], "CurrentState"))
    else:
        if not v["structType"].endswith("CompositeSnapshot"):
            raise SaveError("Unexpected snapshot type")
        for entry in field(v["fields"], "InnerVariables"):
            leaves(entry["value"], prefix + "/" + entry["key"], out)
    return out
