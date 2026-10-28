"""报表用的查询，web 和命令行共用。"""
import sqlite3
from collections import defaultdict

from .report import GUARD_NAME, presence_seconds, current_guards


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def sessions(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT s.id, s.room_id, s.started_at, s.ended_at,"
        " (SELECT COUNT(*) FROM events e WHERE e.session_id=s.id AND e.cmd='DANMU_MSG') AS danmu,"
        " (SELECT COALESCE(SUM(coin),0) FROM events e WHERE e.session_id=s.id) AS coin,"
        " (SELECT COUNT(DISTINCT uid) FROM events e WHERE e.session_id=s.id AND e.uid>0) AS users"
        " FROM sessions s ORDER BY s.id DESC").fetchall()
    return [dict(r) for r in rows]


def guards(conn, room_id: int, gap: int) -> list[dict]:
    users = per_user(conn, gap)
    total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    out = []
    for g in current_guards(conn, room_id):
        u = users.get(g["uid"], {})
        out.append({
            "uid": g["uid"], "uname": g["uname"], "guard_level": g["guard_level"],
            "guard_name": GUARD_NAME.get(g["guard_level"], "?"),
            "medal_level": g["medal_level"], "accompany_days": g["accompany_days"],
            "attend": len(u.get("sessions", ())), "total_sessions": total,
            "coin": u.get("coin", 0), "danmu": u.get("danmu", 0),
            "presence_h": round(u.get("presence_h", 0), 1),
        })
    return out


def flow(conn, session_id: int | None, limit: int = 300) -> list[dict]:
    where = "WHERE cmd IN ('SEND_GIFT','GUARD_BUY','SUPER_CHAT_MESSAGE') AND coin>0"
    args: tuple = ()
    if session_id:
        where += " AND session_id=?"; args = (session_id,)
    rows = conn.execute(f"SELECT ts, cmd, uid, uname, coin, guard_level, text FROM events {where}"
                        f" ORDER BY ts DESC LIMIT {int(limit)}", args).fetchall()
    return [dict(r) for r in rows]


def gift_rank(conn, session_id: int | None, limit: int = 50) -> list[dict]:
    where, args = "WHERE uid>0", ()
    if session_id:
        where += " AND session_id=?"; args = (session_id,)
    rows = conn.execute(
        f"SELECT uid, MAX(uname) uname, SUM(coin) coin, MAX(guard_level) guard_level,"
        f" SUM(cmd='SUPER_CHAT_MESSAGE') sc, SUM(cmd='GUARD_BUY') guard_buy, COUNT(*) n"
        f" FROM events {where} GROUP BY uid HAVING SUM(coin)>0 ORDER BY SUM(coin) DESC LIMIT {int(limit)}", args).fetchall()
    return [dict(r) for r in rows]


def thanks(conn, session_id: int) -> dict:
    """感谢单：本场上舰 / SC / 礼物（按人合并）。"""
    out = {"guard": [], "sc": [], "gift": []}
    for r in conn.execute("SELECT uname, uid, guard_level, text, coin FROM events WHERE session_id=? AND cmd='GUARD_BUY'", (session_id,)):
        out["guard"].append(dict(r))
    for r in conn.execute("SELECT uname, uid, coin, text FROM events WHERE session_id=? AND cmd='SUPER_CHAT_MESSAGE' ORDER BY coin DESC", (session_id,)):
        out["sc"].append(dict(r))
    for r in conn.execute("SELECT uid, MAX(uname) uname, SUM(coin) coin, GROUP_CONCAT(text, '、') gifts FROM events"
                          " WHERE session_id=? AND cmd='SEND_GIFT' AND coin>0 GROUP BY uid ORDER BY coin DESC", (session_id,)):
        out["gift"].append(dict(r))
    return out


def attendance(conn, gap: int, limit: int = 100) -> list[dict]:
    """打卡：每人出勤场次、首末出现。"""
    users = per_user(conn, gap)
    total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    rows = sorted(users.items(), key=lambda kv: (-len(kv[1]["sessions"]), -kv[1]["danmu"]))[:limit]
    return [{"uid": uid, "uname": u["uname"], "attend": len(u["sessions"]), "total_sessions": total,
             "danmu": u["danmu"], "presence_h": round(u["presence_h"], 1), "guard_level": u["guard_level"],
             "first_seen": min(u["ts"]), "last_seen": max(u["ts"])} for uid, u in rows]


def per_user(conn, gap: int) -> dict[int, dict]:
    users: dict[int, dict] = defaultdict(lambda: {"uname": "", "coin": 0, "danmu": 0, "sc": 0,
                                                  "sessions": set(), "ts": [], "guard_level": 0, "medal_level": 0})
    for uid, uname, cmd, coin, gl, ml, ts, sid in conn.execute(
            "SELECT uid, uname, cmd, coin, guard_level, medal_level, ts, session_id FROM events WHERE uid>0"):
        u = users[uid]
        u["uname"] = uname or u["uname"]; u["coin"] += coin
        u["danmu"] += cmd == "DANMU_MSG"; u["sc"] += cmd == "SUPER_CHAT_MESSAGE"
        u["sessions"].add(sid); u["ts"].append(ts)
        u["guard_level"] = gl or u["guard_level"]; u["medal_level"] = max(u["medal_level"], ml)
    for u in users.values():
        u["presence_h"] = presence_seconds(u["ts"], gap) / 3600
    return users


def user_profile(conn, uid: int, gap: int) -> dict | None:
    from .report import describe
    u = per_user(conn, gap).get(uid)
    if not u:
        return None
    total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    hours = defaultdict(int)
    from datetime import datetime
    for t in u["ts"]:
        hours[datetime.fromtimestamp(t).hour] += 1
    recent = [dict(r) for r in conn.execute(
        "SELECT ts, cmd, coin, text FROM events WHERE uid=? ORDER BY ts DESC LIMIT 50", (uid,))]
    snap = conn.execute("SELECT MIN(taken_at) first_seen, MAX(guard_level) gl FROM guard_snapshots WHERE uid=?", (uid,)).fetchone()
    return {"uid": uid, "uname": u["uname"], "guard_level": u["guard_level"], "medal_level": u["medal_level"],
            "coin": u["coin"], "danmu": u["danmu"], "sc": u["sc"], "attend": len(u["sessions"]),
            "total_sessions": total, "presence_h": round(u["presence_h"], 1),
            "active_hours": dict(sorted(hours.items())), "recent": recent,
            "guard_since": snap["first_seen"], "description": describe(u, total)}


def monthly(conn) -> list[dict]:
    """记账 / 月度礼物：按自然月汇总。"""
    rows = conn.execute(
        "SELECT strftime('%Y-%m', ts, 'unixepoch', 'localtime') AS month,"
        " SUM(CASE WHEN cmd='SEND_GIFT' THEN coin ELSE 0 END) gift,"
        " SUM(CASE WHEN cmd='SUPER_CHAT_MESSAGE' THEN coin ELSE 0 END) sc,"
        " SUM(CASE WHEN cmd='GUARD_BUY' THEN coin ELSE 0 END) guard,"
        " SUM(coin) total, COUNT(DISTINCT session_id) sessions, COUNT(DISTINCT CASE WHEN coin>0 THEN uid END) payers"
        " FROM events GROUP BY month ORDER BY month DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["top"] = [dict(x) for x in conn.execute(
            "SELECT uid, MAX(uname) uname, SUM(coin) coin FROM events"
            " WHERE strftime('%Y-%m', ts, 'unixepoch', 'localtime')=? AND uid>0 GROUP BY uid"
            " HAVING SUM(coin)>0 ORDER BY SUM(coin) DESC LIMIT 10", (d["month"],))]
        out.append(d)
    return out


def schedule_list(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM schedule ORDER BY date, start")]


def schedule_add(conn, date: str, start: str, title: str, note: str) -> int:
    cur = conn.execute("INSERT INTO schedule(date, start, title, note) VALUES (?,?,?,?)", (date, start, title, note))
    conn.commit(); return cur.lastrowid


def schedule_toggle(conn, sid: int) -> None:
    conn.execute("UPDATE schedule SET done = 1 - done WHERE id=?", (sid,)); conn.commit()


def schedule_delete(conn, sid: int) -> None:
    conn.execute("DELETE FROM schedule WHERE id=?", (sid,)); conn.commit()
