"""把 B站杂乱的消息体归一化成 (cmd, uid, uname, coin, guard_level, medal_level, text)。
只处理和统计有关的几类，其余返回 None 丢掉。"""

KEEP = {"DANMU_MSG", "SEND_GIFT", "GUARD_BUY", "USER_TOAST_MSG", "SUPER_CHAT_MESSAGE",
        "INTERACT_WORD", "ENTRY_EFFECT", "LIKE_INFO_V3_CLICK"}


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
    elif base in ("INTERACT_WORD", "ENTRY_EFFECT", "LIKE_INFO_V3_CLICK"):
        r["uid"], r["uname"] = int(d.get("uid", 0)), d.get("uname", "")
        fm = d.get("fans_medal") or {}
        r["medal_level"] = int(fm.get("medal_level") or 0)
        r["guard_level"] = int(fm.get("guard_level") or d.get("privilege_type") or 0)
        r["text"] = {1: "进场", 2: "关注", 3: "分享"}.get(d.get("msg_type"), base)
    return r
