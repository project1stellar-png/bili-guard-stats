"""统计报表：python -m bgs.report [uid]"""
import sqlite3
import sys
from collections import defaultdict

from .config import Config

GUARD_NAME = {1: "总督", 2: "提督", 3: "舰长"}


def presence_seconds(ts_list: list[float], gap: int) -> float:
    """按互动时间戳估算在场时长：相邻间隔 <= gap 的算连续在场。"""
    ts_list = sorted(ts_list)
    total, start, prev = 0.0, None, None
    for t in ts_list:
        if prev is None or t - prev > gap:
            if start is not None:
                total += prev - start
            start = t
        prev = t
    if start is not None:
        total += prev - start
    return total


def current_guards(conn: sqlite3.Connection, room_id: int) -> list[sqlite3.Row]:
    latest = conn.execute("SELECT MAX(taken_at) FROM guard_snapshots WHERE room_id=?", (room_id,)).fetchone()[0]
    if latest is None:
        return []
    return conn.execute(
        "SELECT uid, uname, guard_level, medal_level, accompany_days FROM guard_snapshots"
        " WHERE room_id=? AND taken_at=? ORDER BY guard_level, medal_level DESC", (room_id, latest)).fetchall()


def per_user(conn: sqlite3.Connection, gap: int) -> dict[int, dict]:
    users: dict[int, dict] = defaultdict(lambda: {"uname": "", "coin": 0, "danmu": 0, "sc": 0,
                                                  "sessions": set(), "ts": [], "guard_level": 0, "medal_level": 0})
    for row in conn.execute("SELECT uid, uname, cmd, coin, guard_level, medal_level, ts, session_id FROM events WHERE uid>0"):
        uid, uname, cmd, coin, gl, ml, ts, sid = row
        u = users[uid]
        u["uname"] = uname or u["uname"]
        u["coin"] += coin
        u["danmu"] += cmd == "DANMU_MSG"
        u["sc"] += cmd == "SUPER_CHAT_MESSAGE"
        u["sessions"].add(sid)
        u["ts"].append(ts)
        u["guard_level"] = gl or u["guard_level"]
        u["medal_level"] = max(u["medal_level"], ml)
    for u in users.values():
        u["presence_h"] = sum(presence_seconds([t for t in u["ts"]], gap) for _ in [0]) / 3600
    return users


def describe(u: dict, total_sessions: int) -> str:
    parts = []
    if u["guard_level"]:
        parts.append(GUARD_NAME[u["guard_level"]])
    if total_sessions:
        parts.append(f"出勤 {len(u['sessions'])}/{total_sessions} 场")
    parts.append(f"估算在场 {u['presence_h']:.1f} 小时")
    if u["coin"]:
        parts.append(f"消费 {u['coin']/1000:.0f} 元" + (f"（SC {u['sc']} 条）" if u["sc"] else ""))
    parts.append("弹幕 %d 条" % u["danmu"] if u["danmu"] else "基本不发弹幕")
    if u["medal_level"]:
        parts.append(f"粉丝牌 {u['medal_level']} 级")
    return "，".join(parts)


def main() -> None:
    cfg = Config.load()
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    room = conn.execute("SELECT room_id FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
    if not room:
        print("还没有数据"); return
    room_id = room[0]
    total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    users = per_user(conn, cfg.presence_gap_seconds)

    if len(sys.argv) > 1:
        uid = int(sys.argv[1])
        u = users.get(uid)
        print(f"{uid} {u['uname'] if u else '?'}：{describe(u, total_sessions) if u else '无记录'}")
        return

    guards = current_guards(conn, room_id)
    print(f"== 当前大航海 {len(guards)} 人 ==")
    for g in guards:
        u = users.get(g["uid"])
        desc = describe(u, total_sessions) if u else "本工具运行期间无互动记录"
        print(f"[{GUARD_NAME.get(g['guard_level'], '?')}] {g['uname']}({g['uid']}) 陪伴{g['accompany_days']}天 | {desc}")

    print("\n== 消费 Top 20（含非舰长）==")
    for uid, u in sorted(users.items(), key=lambda kv: -kv[1]["coin"])[:20]:
        if u["coin"] == 0:
            break
        print(f"{u['uname']}({uid}) {u['coin']/1000:.1f} 元 | {describe(u, total_sessions)}")

    print("\n== 直播内总计 ==")
    tot = conn.execute("SELECT cmd, COUNT(*), SUM(coin) FROM events GROUP BY cmd").fetchall()
    for cmd, n, coin in tot:
        print(f"{cmd:20s} {n:6d} 条  {(coin or 0)/1000:10.1f} 元")


if __name__ == "__main__":
    main()
