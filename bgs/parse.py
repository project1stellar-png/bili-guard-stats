"""把 B站杂乱的消息体归一化成 (cmd, uid, uname, coin, guard_level, medal_level, text)。
只处理和统计有关的几类，其余返回 None 丢掉。"""

import base64

from . import pb

KEEP = {"DANMU_MSG", "SEND_GIFT", "SEND_GIFT_V2", "GUARD_BUY", "USER_TOAST_MSG", "SUPER_CHAT_MESSAGE",
        "INTERACT_WORD", "INTERACT_WORD_V2", "ENTRY_EFFECT", "LIKE_INFO_V3_CLICK"}


def _find_gift_item(d: dict, depth: int = 0) -> dict | None:
    """SEND_GIFT_V2 的礼物子消息：有 1 gift_id(int) / 2 name(str) / 3 num / 5 price / 7 total_coin / 14 combo_total_coin。
    不信任固定路径，递归找第一个长得像的子消息。字段号来自 hefafafa/realtime_liushui 的实测。"""
    if depth > 4:
        return None
    if isinstance(d.get(2, [None])[0], bytes) and d.get(1) and not isinstance(d[1][0], bytes) and d.get(5) \
            and not isinstance(d[5][0], bytes):
        try:
            d[2][0].decode("utf-8")
            return d
        except UnicodeDecodeError:
            pass
    for vals in d.values():
        for v in vals:
            if isinstance(v, bytes) and len(v) > 4:
                try:
                    sub = pb.decode(v)
                except Exception:  # noqa: BLE001
                    continue
                hit = _find_gift_item(sub, depth + 1)
                if hit:
                    return hit
    return None

# 房间级指标（不是某个人的行为）：cmd -> (指标名, 取值函数)
METRICS = {
    "WATCHED_CHANGE": ("watched", lambda d: d.get("num")),
    "ONLINE_RANK_COUNT": ("online_rank_count", lambda d: d.get("online_count") or d.get("count")),
    "LIKE_INFO_V3_UPDATE": ("likes", lambda d: d.get("click_count")),
}


def metric(msg: dict) -> tuple[str, int] | None:
    """返回 (指标名, 值)，不是指标消息则 None。"""
    m = METRICS.get(msg.get("cmd", ""))
    if not m:
        return None
    v = m[1](msg.get("data") or {})
    return (m[0], int(v)) if v is not None else None


def online_rank(msg: dict) -> list[dict]:
    """ONLINE_RANK_V3（protobuf）：高能榜前几名，作为在场信号。
    布局（实测）：3 = 榜单项 repeated { 1 uid, 2 头像, 3{6 score}, 4 uname, 5 rank, 6 guard_level }"""
    if msg.get("cmd") != "ONLINE_RANK_V3":
        return []
    try:
        d = pb.decode(base64.b64decode(msg["data"]["pb"]))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for raw in d.get(3, []):
        it = pb.decode(raw)
        uid = pb.i(it, 1)
        if uid:
            out.append({"cmd": "ONLINE_RANK", "uid": uid, "uname": pb.s(it, 4), "coin": 0,
                        "guard_level": pb.i(it, 6), "medal_level": 0, "text": f"高能榜第{pb.i(it, 5)}"})
    return out


def normalize(msg: dict) -> dict | None:
    cmd = msg.get("cmd", "")
    base = cmd.split(":")[0]  # DANMU_MSG:4:0:2:2:2:0 这种
    if base not in KEEP:
        return None
    d = msg.get("data") or {}
    r = {"cmd": base, "uid": 0, "uname": "", "coin": 0, "guard_level": 0, "medal_level": 0, "text": ""}

    if base == "DANMU_MSG":
        info = msg.get("info") or []
        try:
            r["text"] = info[1]
            r["uid"], r["uname"] = int(info[2][0]), info[2][1]
            medal = info[3] or []
            r["medal_level"] = int(medal[0]) if medal else 0
            r["guard_level"] = int(info[7]) if len(info) > 7 else 0
        except (IndexError, TypeError, ValueError):
            return None
    elif base == "SEND_GIFT_V2":
        # protobuf：顶层 1 uid / 2 uname（实测核对），礼物内容在嵌套子消息里
        try:
            m = pb.decode(base64.b64decode(d["pb"]))
        except Exception:  # noqa: BLE001
            return None
        item = _find_gift_item(m)
        if not item:
            return None
        r["cmd"] = "SEND_GIFT"
        r["uid"], r["uname"] = pb.i(m, 1), pb.s(m, 2)
        num = pb.i(item, 3) or 1
        name = pb.s(item, 2)
        r["text"] = f"{name} x{num}"
        # 金额：本条实付 total_coin(7) 优先，没有就 price(5)×num；免费礼物 coin_type 不在结构里，
        # 用 price 是否为 0 判断（免费礼物 price=0）
        coin = pb.i(item, 7) or pb.i(item, 5) * num
        r["coin"] = int(coin) if pb.i(item, 5) > 0 else 0
    elif base == "SEND_GIFT":
        r["uid"], r["uname"] = int(d.get("uid", 0)), d.get("uname", "")
        r["text"] = f"{d.get('giftName')} x{d.get('num', 1)}"
        if d.get("coin_type") == "gold":
            r["coin"] = int(d.get("total_coin") or d.get("price", 0) * d.get("num", 1))
        r["guard_level"] = int(d.get("guard_level", 0))
        r["medal_level"] = int(((d.get("medal_info") or {}).get("medal_level")) or 0)
    elif base == "GUARD_BUY":
        r["uid"], r["uname"] = int(d.get("uid", 0)), d.get("username", "")
        r["guard_level"] = int(d.get("guard_level", 0))
        r["coin"] = int(d.get("price", 0)) * int(d.get("num", 1))
        r["text"] = d.get("gift_name", "")
    elif base == "USER_TOAST_MSG":
        # 上舰/续费的另一条通知，带 unit（月/年）；GUARD_BUY 已记金额，这里 coin 置 0 避免重复计
        r["uid"], r["uname"] = int(d.get("uid", 0)), d.get("username", "")
        r["guard_level"] = int(d.get("guard_level", 0))
        r["text"] = f"{d.get('role_name')} {d.get('num')}{d.get('unit')} {d.get('op_type')}"
    elif base == "SUPER_CHAT_MESSAGE":
        ui = d.get("user_info") or {}
        r["uid"], r["uname"] = int(d.get("uid", 0)), ui.get("uname", "")
        r["coin"] = int(d.get("price", 0)) * 1000
        r["guard_level"] = int(ui.get("guard_level", 0))
        r["medal_level"] = int(((d.get("medal_info") or {}).get("medal_level")) or 0)
        r["text"] = d.get("message", "")
    elif base == "INTERACT_WORD_V2":
        # protobuf，布局（实测 + 对照 v1 字段）：1 uid, 2 uname, 4 identities, 5 msg_type, 6 roomid, 7 ts, 9 fans_medal
        try:
            m = pb.decode(base64.b64decode(d["pb"]))
        except Exception:  # noqa: BLE001
            return None
        r["uid"], r["uname"] = pb.i(m, 1), pb.s(m, 2)
        fm = pb.m(m, 9)
        r["medal_level"], r["guard_level"] = pb.i(fm, 2), pb.i(fm, 9)
        r["text"] = {1: "进场", 2: "关注", 3: "分享"}.get(pb.i(m, 5), "进场")
        r["cmd"] = "INTERACT_WORD"
    elif base in ("INTERACT_WORD", "ENTRY_EFFECT", "LIKE_INFO_V3_CLICK"):
        r["uid"], r["uname"] = int(d.get("uid", 0)), d.get("uname", "")
        fm = d.get("fans_medal") or {}
        r["medal_level"] = int(fm.get("medal_level") or 0)
        r["guard_level"] = int(fm.get("guard_level") or d.get("privilege_type") or 0)
        r["text"] = {1: "进场", 2: "关注", 3: "分享"}.get(d.get("msg_type"), base)
    return r
