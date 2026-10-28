"""SQLite 存储：原始事件 + 舰长快照 + 直播场次。"""
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    room_id INTEGER NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    cmd TEXT NOT NULL,          -- DANMU_MSG / SEND_GIFT / GUARD_BUY / SUPER_CHAT_MESSAGE / INTERACT_WORD ...
    uid INTEGER,                -- 0 表示脱敏拿不到
    uname TEXT,
    coin INTEGER DEFAULT 0,     -- 金瓜子（1000 = 1 元），银瓜子不计
    guard_level INTEGER DEFAULT 0, -- 0 无 / 1 总督 / 2 提督 / 3 舰长
    medal_level INTEGER DEFAULT 0,
    text TEXT,                  -- 弹幕内容 / SC 内容 / 礼物名
    raw TEXT                    -- 原始 json
);
CREATE INDEX IF NOT EXISTS idx_events_uid_ts ON events(uid, ts);
CREATE INDEX IF NOT EXISTS idx_events_cmd ON events(cmd);

CREATE TABLE IF NOT EXISTS guard_snapshots (
    id INTEGER PRIMARY KEY,
    room_id INTEGER NOT NULL,
    taken_at REAL NOT NULL,
    uid INTEGER NOT NULL,
    uname TEXT,
    guard_level INTEGER NOT NULL,
    medal_level INTEGER,
    accompany_days INTEGER,     -- 接口给的「陪伴天数」，有就记
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_room_time ON guard_snapshots(room_id, taken_at);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    key TEXT NOT NULL,          -- watched / online_rank_count / likes
    value INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics ON metrics(session_id, key, ts);

CREATE TABLE IF NOT EXISTS official_gifts (
    id TEXT PRIMARY KEY,        -- 官方流水 id
    day TEXT NOT NULL,          -- YYYY-MM-DD（拉取时的 begin_time）
    ts REAL,
    uid INTEGER,
    uname TEXT,
    gift_id INTEGER,
    gift_name TEXT,
    gift_num INTEGER,
    coin INTEGER,               -- 金瓜子（normal_gold）
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_official_day ON official_gifts(day);

CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,         -- YYYY-MM-DD
    start TEXT,                 -- HH:MM
    title TEXT NOT NULL,
    note TEXT,
    done INTEGER DEFAULT 0
);
"""


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def start_session(self, room_id: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions(room_id, started_at) VALUES (?, ?)", (room_id, time.time())
        )
        self.conn.commit()
        return cur.lastrowid

    def end_session(self, session_id: int) -> None:
        self.conn.execute("UPDATE sessions SET ended_at=? WHERE id=?", (time.time(), session_id))
        self.conn.commit()

    def add_event(self, session_id: int, cmd: str, uid: int, uname: str, *, coin=0,
                  guard_level=0, medal_level=0, text="", raw=None, ts=None) -> int:
        cur = self.conn.execute(
            "INSERT INTO events(session_id, ts, cmd, uid, uname, coin, guard_level, medal_level, text, raw)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (session_id, ts or time.time(), cmd, uid, uname, coin, guard_level, medal_level, text,
             json.dumps(raw, ensure_ascii=False) if raw is not None else None),
        )
        self.conn.commit()
        return cur.lastrowid

    def upsert_official_gifts(self, day: str, items: list[dict]) -> int:
        rows = []
        for it in items:
            t = it.get("time")
            ts = None
            if isinstance(t, str):
                try:
                    ts = time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    ts = None
            elif isinstance(t, (int, float)):
                ts = float(t)
            rows.append((str(it.get("id")), day, ts, it.get("uid"), it.get("uname"), it.get("gift_id"),
                         it.get("gift_name"), it.get("gift_num"), it.get("normal_gold"),
                         json.dumps(it, ensure_ascii=False)))
        self.conn.executemany("INSERT OR REPLACE INTO official_gifts VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def add_metric(self, session_id: int, key: str, value: int) -> None:
        self.conn.execute("INSERT INTO metrics(session_id, ts, key, value) VALUES (?,?,?,?)",
                          (session_id, time.time(), key, value))
        self.conn.commit()

    def add_guard_snapshot(self, room_id: int, rows: list[dict]) -> None:
        now = time.time()
        self.conn.executemany(
            "INSERT INTO guard_snapshots(room_id, taken_at, uid, uname, guard_level, medal_level, accompany_days, raw)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [(room_id, now, r["uid"], r.get("uname"), r["guard_level"], r.get("medal_level"),
              r.get("accompany_days"), json.dumps(r.get("raw"), ensure_ascii=False)) for r in rows],
        )
        self.conn.commit()
