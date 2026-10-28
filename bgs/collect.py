"""采集主程序：python -m bgs.collect"""
import asyncio
import logging

from .api import BiliApi, UA
from .config import Config, cookie_dict
import re
import time

from .parse import normalize, metric, online_rank
from .store import Store
from . import ws

log = logging.getLogger("bgs")
GUARD_WORD = re.compile(r"舰长|提督|总督|大航海")


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
        # 大航海回声：GUARD_BUY 之后 15 秒内，同一人再来一条名字像「舰长/提督/总督」的礼物，
        # 是同一笔钱的回声，不重复计；回声价低于标价（打折舰长 168/138）时，按回声价修正上舰金额。
        # 口径来自 hefafafa/realtime_liushui 的实测。
        guard_echo: dict[int, dict] = {}   # uid -> {"ts", "coin", "event_id", "left"}
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
                        now = time.time()
                        if r["cmd"] == "GUARD_BUY" and r["uid"]:
                            guard_echo[r["uid"]] = {"ts": now, "coin": r["coin"], "left": 4, "row": None}
                        elif r["cmd"] == "USER_TOAST_MSG" and r["uid"] in guard_echo:
                            # 实付价来自上舰通知：低于 GUARD_BUY 的标价就修正（打折舰长）
                            e = guard_echo[r["uid"]]
                            pay = r.get("pay_coin", 0)
                            if e["row"] and 0 < pay < e["coin"]:
                                store.conn.execute("UPDATE events SET coin=? WHERE id=?", (pay, e["row"]))
                                store.conn.commit()
                                log.info("打折舰长：%s 上舰 %.0f -> 实付 %.0f 元", r["uname"], e["coin"] / 1000, pay / 1000)
                                e["coin"] = pay
                            if r.get("payflow_id"):
                                # 同一笔 payflow 的 V1 / V2 通知只留一条
                                if e.get("payflow") == r["payflow_id"]:
                                    continue
                                e["payflow"] = r["payflow_id"]
                        elif r["cmd"] == "SEND_GIFT" and r["uid"] in guard_echo:
                            e = guard_echo[r["uid"]]
                            if now - e["ts"] <= 15 and e["left"] > 0 and GUARD_WORD.search(r["text"] or ""):
                                e["left"] -= 1
                                if 100_000 <= r["coin"] < e["coin"] and e["row"]:
                                    store.conn.execute("UPDATE events SET coin=? WHERE id=?", (r["coin"], e["row"]))
                                    store.conn.commit()
                                    log.info("打折舰长：%s 上舰金额 %.0f -> %.0f 元", r["uname"], e["coin"] / 1000, r["coin"] / 1000)
                                    e["coin"] = r["coin"]
                                r["coin"] = 0
                                r["text"] = "（上舰回声）" + r["text"]
                            elif now - e["ts"] > 15:
                                del guard_echo[r["uid"]]
                        row_id = store.add_event(session_id, r["cmd"], r["uid"], r["uname"], coin=r["coin"],
                                                 guard_level=r["guard_level"], medal_level=r["medal_level"],
                                                 text=r["text"], raw=msg)
                        if r["cmd"] == "GUARD_BUY" and r["uid"] in guard_echo:
                            guard_echo[r["uid"]]["row"] = row_id
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
