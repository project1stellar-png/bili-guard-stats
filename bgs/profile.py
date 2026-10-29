"""用户近况：本直播间轨迹 + 主场 + B站公开名片 + 一句话总结（规则模板，或可选 Claude 生成）。"""
import json
import logging
import sqlite3
import time
from datetime import datetime

from .api import BiliApi
from .churn import home_of
from .report import GUARD_NAME, presence_seconds

log = logging.getLogger("bgs.profile")
CARD_TTL = 7 * 86400


def _fmt_yuan(coin: int) -> str:
    return f"{coin / 1000:.0f} 元" if coin >= 1000 else f"{coin / 1000:.1f} 元"


def trajectory(conn: sqlite3.Connection, uid: int, gap: int) -> dict | None:
    rows = conn.execute("SELECT ts, cmd, coin, guard_level, medal_level, medal_target, medal_name, session_id, text, uname"
                        " FROM events WHERE uid=? ORDER BY ts", (uid,)).fetchall()
    if not rows:
        return None
    sessions_all = [r[0] for r in conn.execute("SELECT id FROM sessions ORDER BY id DESC")]
    attended = sorted({r["session_id"] for r in rows}, reverse=True)
    recent3 = set(sessions_all[:3]); prior = set(sessions_all[3:15])
    by_session: dict[int, list] = {}
    for r in rows:
        by_session.setdefault(r["session_id"], []).append(r)
    t = {
        "uname": rows[-1]["uname"], "first_seen": rows[0]["ts"], "last_seen": rows[-1]["ts"],
        "attend": len(attended), "total_sessions": len(sessions_all),
        "attend_recent3": len(recent3 & set(attended)), "attend_prior": len(prior & set(attended)), "prior_n": len(prior),
        "danmu": sum(r["cmd"] == "DANMU_MSG" for r in rows), "coin": sum(r["coin"] for r in rows),
        "sc": sum(r["cmd"] == "SUPER_CHAT_MESSAGE" for r in rows),
        "guard_buys": [(r["ts"], r["guard_level"], r["coin"]) for r in rows if r["cmd"] == "GUARD_BUY"],
        "guard_level": max((r["guard_level"] for r in rows), default=0),
        "presence_h": presence_seconds([r["ts"] for r in rows], gap) / 3600,
        "medal_first": next((r["medal_level"] for r in rows if r["medal_level"]), 0),
        "medal_last": next((r["medal_level"] for r in reversed(rows) if r["medal_level"]), 0),
        "coin_recent3": sum(r["coin"] for r in rows if r["session_id"] in recent3),
        "coin_prior": sum(r["coin"] for r in rows if r["session_id"] in prior),
    }
    # 最近一次来戴的别家牌子
    worn = next((r for r in reversed(rows) if r["medal_target"]), None)
    t["last_worn"] = {"target_id": worn["medal_target"], "medal_name": worn["medal_name"], "level": worn["medal_level"]} if worn else None
    # 常用词（弹幕前 5）
    from collections import Counter
    words = Counter(r["text"] for r in rows if r["cmd"] == "DANMU_MSG" and r["text"] and len(r["text"]) <= 12)
    t["top_words"] = [w for w, _ in words.most_common(5)]
    # 常来的时段
    hours = Counter(datetime.fromtimestamp(r["ts"]).hour for r in rows)
    t["peak_hour"] = hours.most_common(1)[0][0] if hours else None
    return t


def medals(conn: sqlite3.Connection, uid: int, own_target: int) -> dict:
    latest = conn.execute("SELECT MAX(taken_at) FROM medal_snapshots WHERE uid=?", (uid,)).fetchone()[0]
    if not latest:
        return {"snapshot": False, "home": None, "own": None, "count": 0}
    ms = [dict(r) for r in conn.execute("SELECT * FROM medal_snapshots WHERE uid=? AND taken_at=?", (uid, latest))]
    own = next((m for m in ms if m["target_id"] == own_target), None)
    h = home_of(ms, own_target)
    return {"snapshot": True, "taken_at": latest, "count": len(ms), "own": own, "home": h,
            "guard_elsewhere": [m for m in ms if m["guard_level"] and m["target_id"] != own_target]}


async def card(conn: sqlite3.Connection, uid: int, cookie: str, force: bool = False) -> dict | None:
    row = conn.execute("SELECT fetched_at, json FROM user_cards WHERE uid=?", (uid,)).fetchone()
    if row and not force and time.time() - row[0] < CARD_TTL:
        return json.loads(row[1])
    try:
        async with BiliApi(cookie) as api:
            c = await api.user_card(uid)
    except Exception as e:  # noqa: BLE001
        log.warning("user_card %s: %s", uid, e)
        return json.loads(row[1]) if row else None
    conn.execute("INSERT OR REPLACE INTO user_cards VALUES (?,?,?)", (uid, time.time(), json.dumps(c, ensure_ascii=False)))
    conn.commit()
    return c


def rule_summary(t: dict, m: dict, c: dict | None) -> str:
    """不用模型也能出的一段话。"""
    parts = []
    days_since = (time.time() - t["last_seen"]) / 86400
    ident = GUARD_NAME.get(t["guard_level"], "") or ("老观众" if t["attend"] >= 5 else "观众")
    since = datetime.fromtimestamp(t["first_seen"]).strftime("%Y年%m月")
    parts.append(f"{since}起出现的{ident}，共出勤 {t['attend']}/{t['total_sessions']} 场")
    if t["prior_n"] and t["attend_prior"] >= 2:
        if t["attend_recent3"] == 0:
            parts.append(f"之前 {t['prior_n']} 场来了 {t['attend_prior']} 场，最近 3 场没出现，已有 {days_since:.0f} 天没来")
        elif t["attend_recent3"] < 2 and t["attend_prior"] >= t["prior_n"] * 0.6:
            parts.append("出勤在下滑")
        else:
            parts.append("出勤稳定")
    elif days_since > 14:
        parts.append(f"已有 {days_since:.0f} 天没来")
    if t["coin"]:
        trend = ""
        if t["coin_prior"] and t["coin_recent3"] < t["coin_prior"] * 0.3:
            trend = "，最近明显减少"
        elif t["coin_prior"] and t["coin_recent3"] > t["coin_prior"] * 1.5:
            trend = "，最近在增加"
        parts.append(f"累计消费 {_fmt_yuan(t['coin'])}" + (f"（SC {t['sc']} 条）" if t["sc"] else "") + trend)
    else:
        parts.append("没有付费记录")
    parts.append(f"弹幕 {t['danmu']} 条" if t["danmu"] >= 5 else "基本不发弹幕")
    if t["medal_last"] and t["medal_first"] and t["medal_last"] > t["medal_first"]:
        parts.append(f"你家牌子从 {t['medal_first']} 级涨到 {t['medal_last']} 级")
    elif t["medal_last"]:
        parts.append(f"你家牌子 {t['medal_last']} 级")
    h = m.get("home")
    if h:
        parts.append(f"现在主场在「{h['target_name']}」（{h['medal_name']} {h['level']} 级{'，那边上了' + GUARD_NAME[h['guard_level']] if h.get('guard_level') else ''}）")
    elif t.get("last_worn"):
        parts.append(f"最近来时戴的是「{t['last_worn']['medal_name']}」牌子")
    if c and c.get("official"):
        parts.append(f"B站认证：{c['official']}")
    return "，".join(parts) + "。"


def build_context(t: dict, m: dict, c: dict | None) -> dict:
    """喂给模型的结构化数据，不含弹幕原文，只有统计。"""
    return {
        "身份": GUARD_NAME.get(t["guard_level"], "普通观众"), "首次出现": datetime.fromtimestamp(t["first_seen"]).strftime("%Y-%m-%d"),
        "最近出现": datetime.fromtimestamp(t["last_seen"]).strftime("%Y-%m-%d"),
        "出勤": f"{t['attend']}/{t['total_sessions']}", "之前出勤": f"{t['attend_prior']}/{t['prior_n']}", "最近3场出勤": t["attend_recent3"],
        "估算在场小时": round(t["presence_h"], 1), "弹幕条数": t["danmu"], "常发的弹幕": t["top_words"], "常来的时段": t["peak_hour"],
        "累计消费元": round(t["coin"] / 1000, 1), "之前消费元": round(t["coin_prior"] / 1000, 1), "最近3场消费元": round(t["coin_recent3"] / 1000, 1),
        "SC条数": t["sc"], "上舰记录": [(datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), GUARD_NAME.get(g, "")) for ts, g, _ in t["guard_buys"]],
        "本直播间牌子等级": f"{t['medal_first']} -> {t['medal_last']}",
        "勋章墙": ({"牌子数": m["count"], "主场": m["home"] and {"主播": m["home"]["target_name"], "等级": m["home"]["level"], "佩戴": bool(m["home"]["wearing"]), "舰长": m["home"]["guard_level"]},
                   "别处上舰": [x["target_name"] for x in m.get("guard_elsewhere", [])]} if m.get("snapshot") else "未公开或未拉取"),
        "最近来时戴的牌子": t.get("last_worn") and t["last_worn"]["medal_name"],
        "公开资料": c and {"等级": c["level"], "粉丝": c["fans"], "关注": c["attention"], "认证": c["official"], "大会员": bool(c["vip"]), "签名": c["sign"][:60]},
    }


SYSTEM = ("你是直播间主播的运营助手。根据给你的一名观众在本直播间的统计数据和公开资料，用中文写一段 2 到 4 句的「用户近况」，"
          "给主播自己看。要点：他是谁（身份、来了多久）、最近活跃度和消费的变化趋势、他现在的主场在哪（如果有）、一条可操作的建议。"
          "只依据给定数据，不要编造，不要评价他的人品，不要使用夸张措辞。直接输出正文，不要标题。")


async def claude_summary(api_key: str, ctx: dict) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    resp = await client.beta.messages.create(
        model="claude-opus-5", max_tokens=512,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        output_config={"effort": "low"},
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
    )
    if resp.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in resp.content if b.type == "text").strip()
