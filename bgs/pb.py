"""最小 protobuf wire 解码：不需要 .proto，把消息解成 {field_no: [values]}。
嵌套消息以 bytes 形式保留，由调用方按需再 decode。"""


def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = s = 0
    while True:
        c = b[i]; i += 1
        r |= (c & 0x7F) << s
        if not c & 0x80:
            return r, i
        s += 7


def decode(b: bytes) -> dict[int, list]:
    out: dict[int, list] = {}
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v = int.from_bytes(b[i:i + 8], "little"); i += 8
        elif wt == 2:
            n, i = _varint(b, i); v = b[i:i + n]; i += n
        elif wt == 5:
            v = int.from_bytes(b[i:i + 4], "little"); i += 4
        else:
            raise ValueError(f"bad wire type {wt}")
        out.setdefault(f, []).append(v)
    return out


def s(d: dict, f: int, default=""):
    v = d.get(f)
    if not v:
        return default
    return v[0].decode("utf-8", "replace") if isinstance(v[0], bytes) else v[0]


def i(d: dict, f: int, default=0) -> int:
    v = d.get(f)
    return int(v[0]) if v and not isinstance(v[0], bytes) else default


def m(d: dict, f: int) -> dict:
    v = d.get(f)
    return decode(v[0]) if v and isinstance(v[0], bytes) else {}
