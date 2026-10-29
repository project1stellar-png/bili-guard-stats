"""流失分析：谁不来了、他们现在的主场在哪、整体流向。
「主场」= 当前佩戴的牌子；没戴就取等级最高的非本直播间牌子。数据来自 B站公开的粉丝勋章墙。"""
import asyncio
import logging
import sqlite3
import time
from collections import Counter, defaultdict

from .api import BiliApi
from .store import Store

log = logging.getLogger("bgs.churn")
RECENT_SESSIONS = 3        # 最近几场算「现在」
PRIOR_MIN_ATTEND = 2       # 之前至少出勤几场才算常客


def churn_list(conn: sqlite3.Connection, recent_n: int = RECENT_SESSIONS, prior_min: int = PRIOR_MIN_ATTEND) -> dict:
    sessions = [r[0] for r in conn.execute("SELECT id FROM sessions ORDER BY id DESC")]
    if len(sessions) <= recent_n:
        return {"recent": [], "prior": [], "churned": [], "regulars": 0, "enough": False}
    recent, prior = sessions[:recent_n], sessions[recent_n:recent_n + 12]
    ph = ",".join("?" * len(prior)); rh = ",".join("?" * len(recent))
    prior_users = {}
    for uid, uname, n, danmu, coin, gl in conn.execute(
            f"SELECT uid, MAX(uname), COUNT(DISTINCT session_id), SUM(cmd='DANMU_MSG'), SUM(coin), MAX(guard_level)"
            f" FROM events WHERE uid>0 AND session_id IN ({ph}) GROUP BY uid HAVING COUNT(DISTINCT session_id)>=?",
            (*prior, prior_min)):
        prior_users[uid] = {"uid": uid, "uname": uname, "prior_attend": n, "danmu": danmu, "coin": coin, "guard_level": gl}
    recent_users = {r[0] for r in conn.execute(f"SELECT DISTINCT uid FROM events WHERE uid>0 AND session_id IN ({rh})", recent)}
    churned = [u for uid, u in prior_users.items() if uid not in recent_users]
    churned.sort(key=lambda u: (-u["coin"], -u["prior_attend"]))
    return {"recent": recent, "prior": prior, "churned": churned, "regulars": len(prior_users), "enough": True}


def _latest_two_rounds(conn) -> list[float]:
    return [r[0] for r in conn.execute("SELECT DISTINCT taken_at FROM medal_snapshots ORDER BY taken_at DESC LIMIT 2")]


def home_of(medals: list[dict], own_target: int) -> dict | None:
    others = [m for m in medals if m["target_id"] != own_target]
    worn = [m for m in others if m["wearing"]]
    if worn:
        return worn[0]
    return max(others, key=lambda m: (m["guard_level"] > 0, m["level"], m["intimacy"]), default=None)


def analysis(conn: sqlite3.Connection, own_target: int) -> dict:
    base = churn_list(conn)
    rounds = _latest_two_rounds(conn)
    latest, prev = (rounds + [None, None])[:2]
    by_uid: dict[int, list[dict]] = defaultdict(list)
    prev_by: dict[tuple[int, int], dict] = {}
    if latest:
        for r in conn.execute("SELECT * FROM medal_snapshots WHERE taken_at=?", (latest,)):
            by_uid[r["uid"]].append(dict(r))
    if prev:
        for r in conn.execute("SELECT * FROM medal_snapshots WHERE taken_at=?", (prev,)):
            prev_by[(r["uid"], r["target_id"])] = dict(r)
    flow = Counter(); flow_names = {}
    for u in base["churned"]:
        medals = by_uid.get(u["uid"], [])
        u["snapshot"] = bool(medals)
        own = next((m for m in medals if m["target_id"] == own_target), None)
        u["own_level"] = own["level"] if own else None
        h = home_of(medals, own_target)
        if h:
            pv = prev_by.get((u["uid"], h["target_id"]))
            u["home"] = {"target_id": h["target_id"], "target_name": h["target_name"], "medal_name": h["medal_name"],
                         "level": h["level"], "guard_level": h["guard_level"], "wearing": h["wearing"],
                         "level_gain": (h["level"] - pv["level"]) if pv else None}
            flow[h["target_id"]] += 1; flow_names[h["target_id"]] = h["target_name"]
        else:
            u["home"] = None
        # 在别处涨得最快的牌子
        gains = [(m["level"] - prev_by[(u["uid"], m["target_id"])]["level"], m) for m in medals
                 if (u["uid"], m["target_id"]) in prev_by and m["target_id"] != own_target]
        gains = [g for g in gains if g[0] > 0]
        u["rising"] = max(gains, key=lambda g: g[0])[1]["target_name"] if gains else None
    base["flow"] = [{"target_id": t, "target_name": flow_names[t], "n": n} for t, n in flow.most_common(15)]
    base["latest_round"] = latest; base["prev_round"] = prev
    base["snapshot_users"] = len(by_uid)
    return base


def snapshot_targets(conn: sqlite3.Connection, limit: int = 300) -> list[int]:
    """要拉勋章墙的人：流失名单 + 当前舰长 + 最近最活跃的人，去重后最多 limit 个。"""
    uids: list[int] = [u["uid"] for u in churn_list(conn)["churned"]]
    latest = conn.execute("SELECT MAX(taken_at) FROM guard_snapshots").fetchone()[0]
    if latest:
        uids += [r[0] for r in conn.execute("SELECT uid FROM guard_snapshots WHERE taken_at=?", (latest,))]
    uids += [r[0] for r in conn.execute(
        "SELECT uid FROM events WHERE uid>0 AND ts>? GROUP BY uid ORDER BY COUNT(*) DESC LIMIT 200", (time.time() - 45 * 86400,))]
    seen, out = set(), []
    for u in uids:
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out[:limit]


async def run_snapshot(cfg, progress: dict) -> None:
    """拉一轮勋章墙快照。progress 给网页看进度。接口有频率限制，每人间隔 0.7 秒。"""
    store = Store(cfg.db_path)
    conn = store.conn; conn.row_factory = sqlite3.Row
    targets = snapshot_targets(conn)
    progress.update(total=len(targets), done=0, errors=0, running=True, error="")
    taken_at = time.time()
    async with BiliApi(cfg.cookie) as api:
        try:
            info = await api.room_init(cfg.room_id)
            store.set_meta("own_target", str(info["uid"]))
        except Exception as e:  # noqa: BLE001
            log.warning("room_init 失败：%s", e)
        for uid in targets:
            try:
                medals = await api.medal_wall(uid)
                store.add_medal_snapshot(taken_at, uid, medals)
            except Exception as e:  # noqa: BLE001
                progress["errors"] += 1
                progress["error"] = str(e)[:120]
                if "412" in str(e) or "-412" in str(e) or "频繁" in str(e):
                    await asyncio.sleep(20)
            progress["done"] += 1
            await asyncio.sleep(0.7)
    store.set_meta("last_medal_snapshot", str(taken_at))
    progress["running"] = False
