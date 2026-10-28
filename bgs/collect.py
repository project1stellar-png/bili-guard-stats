"""采集主程序：python -m bgs.collect"""
import asyncio
import logging

from .api import BiliApi, UA
from .config import Config, cookie_dict
import time

from .parse import normalize, metric, online_rank
from .store import Store
from . import ws

log = logging.getLogger("bgs")


async def snapshot_guards(api: BiliApi, store: Store, room_id: int, ruid: int) -> None:
    rows = await api.guard_list(room_id, ruid)
    store.add_guard_snapshot(room_id, rows)
    log.info("舰长快照：%d 人", len(rows))


async def run(cfg: Config, status: dict | None = None) -> None:
    """采集主循环。status 可选，用来给网页汇报状态。"""
    status = status if status is not None else {}
    if not cfg.room_id:
        raise SystemExit("config.toml 里还没填 room_id")
    store = Store(cfg.db_path)
    ck = cookie_dict(cfg.cookie)
    uid = int(ck.get("DedeUserID", 0))
    async with BiliApi(cfg.cookie) as api:
        info = await api.room_init(cfg.room_id)
        real_room, ruid = info["room_id"], info["uid"]
        log.info("房间 %s -> real_room=%s 主播 uid=%s 直播状态=%s", cfg.room_id, real_room, ruid,
                 info.get("live_status"))
        status.update(real_room=real_room, live_status=info.get("live_status"), events=0, connected=False, error="")
        session_id = store.start_session(real_room)
        await snapshot_guards(api, store, real_room, ruid)

        backoff = 1
        last_metric: dict[str, int] = {}
        last_rank_seen: dict[int, float] = {}
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
                    status["connected"] = True
                    async for msg in ws.stream(dm["host_list"], dm["token"], real_room, uid, headers):
                        mt = metric(msg)
                        if mt and last_metric.get(mt[0]) != mt[1]:
                            last_metric[mt[0]] = mt[1]
                            store.add_metric(session_id, *mt)
                            continue
                        now = time.time()
                        for item in online_rank(msg):  # 同一人 5 分钟内只记一次
                            if now - last_rank_seen.get(item["uid"], 0) > 300:
                                last_rank_seen[item["uid"]] = now
                                store.add_event(session_id, item["cmd"], item["uid"], item["uname"],
                                                guard_level=item["guard_level"], text=item["text"])
                        r = normalize(msg)
                        if r is None:
                            continue
                        status["events"] = status.get("events", 0) + 1
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
                    status.update(connected=False, error=str(e))
                    log.warning("连接断开：%s，%ds 后重连", e, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        finally:
            store.end_session(session_id)


async def _main(cfg: Config) -> None:
    import signal
    task = asyncio.ensure_future(run(cfg))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: task.cancel())
    try:
        await task
    except asyncio.CancelledError:
        log.info("已停止")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_main(Config.load()))


if __name__ == "__main__":
    main()
