"""采集主程序：python -m bgs.collect"""
import asyncio
import logging

from .api import BiliApi, UA
from .config import Config, cookie_dict
from .parse import normalize
from .store import Store
from . import ws

log = logging.getLogger("bgs")


async def snapshot_guards(api: BiliApi, store: Store, room_id: int, ruid: int) -> None:
    rows = await api.guard_list(room_id, ruid)
    store.add_guard_snapshot(room_id, rows)
    log.info("舰长快照：%d 人", len(rows))


async def run(cfg: Config) -> None:
    store = Store(cfg.db_path)
    ck = cookie_dict(cfg.cookie)
    uid = int(ck.get("DedeUserID", 0))
    async with BiliApi(cfg.cookie) as api:
        info = await api.room_init(cfg.room_id)
        real_room, ruid = info["room_id"], info["uid"]
        log.info("房间 %s -> real_room=%s 主播 uid=%s 直播状态=%s", cfg.room_id, real_room, ruid,
                 info.get("live_status"))
        session_id = store.start_session(real_room)
        await snapshot_guards(api, store, real_room, ruid)

        backoff = 1
        try:
            while True:
                try:
                    dm = await api.danmu_info(real_room)
                    headers = {"User-Agent": UA, "Origin": "https://live.bilibili.com"}
                    if cfg.cookie:
                        headers["Cookie"] = cfg.cookie
                    if "buvid3" in ck:
                        headers["buvid"] = ck["buvid3"]
                    backoff = 1
                    async for msg in ws.stream(dm["host_list"], dm["token"], real_room, uid, headers):
                        r = normalize(msg)
                        if r is None:
                            continue
                        store.add_event(session_id, r["cmd"], r["uid"], r["uname"], coin=r["coin"],
                                        guard_level=r["guard_level"], medal_level=r["medal_level"],
                                        text=r["text"], raw=msg)
                        if r["cmd"] in ("GUARD_BUY", "SUPER_CHAT_MESSAGE") or r["coin"] >= 10000:
                            log.info("%s %s(%s) %s %.1f元", r["cmd"], r["uname"], r["uid"], r["text"],
                                     r["coin"] / 1000)
                        if r["cmd"] == "GUARD_BUY":
                            await snapshot_guards(api, store, real_room, ruid)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.warning("连接断开：%s，%ds 后重连", e, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            store.end_session(session_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(run(Config.load()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
