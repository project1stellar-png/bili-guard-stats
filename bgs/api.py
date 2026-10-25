"""B站 HTTP 接口：房间信息、弹幕服务器、大航海列表。"""
import aiohttp

from . import wbi

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class BiliApi:
    def __init__(self, cookie: str):
        self.headers = {"User-Agent": UA, "Referer": "https://live.bilibili.com/",
                        "Accept-Encoding": "gzip"}
        if cookie:
            self.headers["Cookie"] = cookie
        self.session: aiohttp.ClientSession | None = None
        self._mixin: str | None = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self

    async def __aexit__(self, *a):
        await self.session.close()

    async def _get(self, url: str, **params) -> dict:
        async with self.session.get(url, params=params) as r:
            d = await r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"{url} -> code={d.get('code')} {d.get('message')}")
        return d["data"]

    async def room_init(self, room_id: int) -> dict:
        """短号 -> 真实 room_id、主播 uid、是否开播。"""
        return await self._get("https://api.live.bilibili.com/room/v1/Room/room_init", id=room_id)

    async def _wbi_mixin(self) -> str:
        if self._mixin is None:
            async with self.session.get("https://api.bilibili.com/x/web-interface/nav") as r:
                d = (await r.json())["data"]["wbi_img"]
            self._mixin = wbi.mixin_key(wbi.key_from_url(d["img_url"]), wbi.key_from_url(d["sub_url"]))
        return self._mixin

    async def danmu_info(self, real_room_id: int) -> dict:
        """弹幕服务器地址和 token。需要 WBI 签名，且基本要带登录 cookie，否则 -352 风控。"""
        params = wbi.sign({"id": real_room_id, "type": 0, "web_location": 444.8}, await self._wbi_mixin())
        return await self._get(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo", **params)

    async def guard_list(self, real_room_id: int, ruid: int) -> list[dict]:
        """拉全量大航海名单，按页翻到底。"""
        rows: list[dict] = []
        page = 1
        while True:
            d = await self._get(
                "https://api.live.bilibili.com/xlive/app-room/v2/guardTab/topList",
                roomid=real_room_id, ruid=ruid, page=page, page_size=29,
            )
            items = (d.get("top3") or []) + (d.get("list") or []) if page == 1 else (d.get("list") or [])
            for it in items:
                medal = it.get("medal_info") or {}
                rows.append({
                    "uid": it.get("uid"),
                    "uname": it.get("username"),
                    "guard_level": it.get("guard_level"),
                    "medal_level": medal.get("medal_level"),
                    "accompany_days": it.get("accompany"),
                    "raw": it,
                })
            info = d.get("info") or {}
            if page >= int(info.get("page", 1)) or not d.get("list"):
                break
            page += 1
        return rows
