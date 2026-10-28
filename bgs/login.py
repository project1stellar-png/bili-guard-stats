"""扫码登录：python -m bgs.login
终端里打出二维码，用 B站 App 扫一下，拿到的 cookie 自动写进 config.toml。
用的是网页端登录接口（passport.bilibili.com），不是开放平台，不需要申请。"""
import asyncio
import re
import sys
from pathlib import Path

import aiohttp
import qrcode

from .api import UA

GEN = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
SPI = "https://api.bilibili.com/x/frontend/finger/spi"


async def login() -> str:
    headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/", "Accept-Encoding": "gzip"}
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.get(GEN) as r:
            d = (await r.json())["data"]
        qr = qrcode.QRCode(border=1)
        qr.add_data(d["url"])
        qr.print_ascii(invert=True)
        print("用 B站 App 扫描上方二维码并确认登录（3 分钟内有效）…")
        while True:
            await asyncio.sleep(2)
            async with s.get(POLL, params={"qrcode_key": d["qrcode_key"]}) as r:
                p = (await r.json())["data"]
            code = p.get("code")
            if code == 0:
                ck = {c.key: c.value for c in s.cookie_jar}
                break
            if code == 86038:
                raise SystemExit("二维码已过期，重新运行一次")
            if code == 86090:
                print("已扫码，请在手机上确认…", end="\r")
        async with s.get(SPI) as r:
            fp = (await r.json())["data"]
        ck["buvid3"], ck["buvid4"] = fp["b_3"], fp["b_4"]
    keys = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5", "buvid3", "buvid4"]
    return "; ".join(f"{k}={ck[k]}" for k in keys if k in ck)


def write_config(cookie: str, path: str = "config.toml") -> None:
    p = Path(path)
    text = p.read_text() if p.exists() else Path("config.example.toml").read_text()
    line = f'cookie = "{cookie}"'
    if re.search(r"^cookie\s*=", text, re.M):
        text = re.sub(r"^cookie\s*=.*$", line, text, count=1, flags=re.M)
    else:
        text += "\n" + line + "\n"
    p.write_text(text)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"
    cookie = asyncio.run(login())
    uid = re.search(r"DedeUserID=(\d+)", cookie)
    write_config(cookie, path)
    print(f"\n登录成功，uid {uid.group(1) if uid else '?'}，cookie 已写入 {path}")


if __name__ == "__main__":
    main()
