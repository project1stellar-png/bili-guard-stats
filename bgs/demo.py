"""造演示数据：BGS_CONFIG=config.demo.toml python -m bgs.demo"""
import random
import time

from .config import Config
from .store import Store

NAMES = ["然然唱歌好听", "企鹅树", "乙醇丶", "伯乐咚咚糖", "西行妖", "深夜食堂", "路过的咸鱼", "打卡机器", "SC狂魔", "小花花批发"]


def main() -> None:
    cfg = Config.load()
    import os
    if os.path.exists(cfg.db_path):
        os.remove(cfg.db_path)
    st = Store(cfg.db_path)
    rng = random.Random(7)
    users = [{"uid": 1000 + i, "uname": n, "gl": rng.choice([0, 0, 0, 3, 3, 2, 1]) if i else 1,
              "medal": rng.randint(5, 30), "spend": rng.choice([0, 5, 30, 200, 1000])} for i, n in enumerate(NAMES)]
    st.add_guard_snapshot(1, [{"uid": u["uid"], "uname": u["uname"], "guard_level": u["gl"], "medal_level": u["medal"],
                               "accompany_days": rng.randint(30, 1500), "raw": {}} for u in users if u["gl"]])
    now = time.time()
    for s in range(6):  # 6 场，跨两个月
        start = now - (40 - s * 7) * 86400 + 20 * 3600
        sid = st.start_session(1)
        st.conn.execute("UPDATE sessions SET started_at=?, ended_at=? WHERE id=?", (start, start + 3 * 3600, sid))
        for u in users:
            if rng.random() < 0.3:
                continue
            t = start + rng.randint(0, 1800)
            st.add_event(sid, "INTERACT_WORD", u["uid"], u["uname"], guard_level=u["gl"], medal_level=u["medal"], text="进场", ts=t)
            for _ in range(rng.randint(0, 25)):
                t += rng.randint(60, 900)
                st.add_event(sid, "DANMU_MSG", u["uid"], u["uname"], guard_level=u["gl"], medal_level=u["medal"],
                             text=rng.choice(["哈哈哈", "晚上好", "唱歌！", "?", "好可爱", "打卡"]), ts=t)
            if u["spend"] and rng.random() < 0.8:
                coin = u["spend"] * 1000 * rng.choice([1, 1, 2, 5])
                kind = rng.choice(["SEND_GIFT", "SEND_GIFT", "SUPER_CHAT_MESSAGE"])
                st.add_event(sid, kind, u["uid"], u["uname"], coin=coin, guard_level=u["gl"], medal_level=u["medal"],
                             text="小花花 x%d" % (coin // 1000) if kind == "SEND_GIFT" else "今天也要加油！", ts=t + 100)
            if u["gl"] and s % 4 == 0:
                st.add_event(sid, "GUARD_BUY", u["uid"], u["uname"], coin={1: 19998000, 2: 1998000, 3: 198000}[u["gl"]],
                             guard_level=u["gl"], text={1: "总督", 2: "提督", 3: "舰长"}[u["gl"]], ts=t + 200)
    st.conn.commit()
    print("demo 数据已写入", cfg.db_path)


if __name__ == "__main__":
    main()
