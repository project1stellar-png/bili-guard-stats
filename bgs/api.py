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

    async def received_gift_stream(self, day: str) -> list[dict]:
        """主播后台的礼物流水（官方账），按天拉全。需要主播本人的登录 cookie。
        day: YYYY-MM-DD。返回项：id, uid, uname, gift_id, gift_name, gift_num, normal_gold(金瓜子), time, ...
        来源：boxie123/Bilibili_GetReceivedGiftStream 用的同一个接口。"""
        url = "https://api.live.bilibili.com/xlive/revenue/v1/giftStream/getReceivedGiftStreamNextList"
        headers = {"Referer": "https://link.bilibili.com/p/center/index"}
        out: list[dict] = []
        params = {"limit": 200, "coin_type": 0, "gift_id": "", "begin_time": day, "uname": ""}
        while True:
            async with self.session.get(url, params=params, headers=headers) as r:
                d = await r.json()
            if d.get("code") != 0:
                raise RuntimeError(f"礼物流水接口 code={d.get('code')} {d.get('message')}（需要主播本人登录）")
            data = d.get("data") or {}
            items = data.get("list") or []
            out.extend(items)
            if not data.get("has_more") or not items:
                return out
            params["last_id"] = items[-1]["id"]

    async def medal_wall(self, uid: int) -> list[dict]:
        """某用户的粉丝勋章墙（公开数据，需登录态）。过滤掉 B站自动生成的「周报」牌子。"""
        d = await self._get("https://api.live.bilibili.com/xlive/web-ucenter/user/MedalWall", target_id=uid)
        out = []
        for it in d.get("list") or []:
            mi = it.get("medal_info") or {}
            name = it.get("target_name") or ""
            if name.endswith("周报"):
                continue
            out.append({"target_id": int(mi.get("target_id") or 0), "target_name": name,
                        "medal_name": mi.get("medal_name", ""), "level": int(mi.get("level") or 0),
                        "intimacy": int(mi.get("intimacy") or 0), "guard_level": int(mi.get("guard_level") or 0),
                        "wearing": int(mi.get("wearing_status") or 0)})
        return out

    async def user_card(self, uid: int) -> dict:
        """B站公开的用户名片：等级、签名、粉丝数、关注数、认证、大会员。"""
        async with self.session.get("https://api.bilibili.com/x/web-interface/card", params={"mid": uid},
                                    headers={"Referer": "https://www.bilibili.com/"}) as r:
            d = await r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"card code={d.get('code')} {d.get('message')}")
        c = (d.get("data") or {}).get("card") or {}
        ov = c.get("Official") or {}
        return {"uid": uid, "name": c.get("name", ""), "sign": c.get("sign", ""), "sex": c.get("sex", ""),
                "level": int((c.get("level_info") or {}).get("current_level") or 0),
                "fans": int(c.get("fans") or 0), "attention": int(c.get("attention") or 0),
                "official": ov.get("title") or "", "vip": int((c.get("vip") or {}).get("vipStatus") or 0),
                "face": c.get("face", "")}
