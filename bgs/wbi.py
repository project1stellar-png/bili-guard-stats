"""WBI 签名：B站 web 接口的参数签名。key 从 nav 接口的 wbi_img 取，按打乱表重排后取前 32 位。"""
import hashlib
import time
import urllib.parse

MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29,
             28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25,
             54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]


def mixin_key(img_key: str, sub_key: str) -> str:
    s = img_key + sub_key
    return "".join(s[i] for i in MIXIN_TAB)[:32]


def key_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1].split(".")[0]


def sign(params: dict, mixin: str) -> dict:
    p = dict(params)
    p["wts"] = int(time.time())
    p = {k: "".join(ch for ch in str(v) if ch not in "!'()*") for k, v in sorted(p.items())}
    query = urllib.parse.urlencode(p)
    p["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return p
