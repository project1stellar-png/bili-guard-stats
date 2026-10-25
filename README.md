# bili-guard-stats

B站直播间舰长 / 消费 / 在场时长统计工具（主播自用）。

## 用法

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml   # 填 room_id 和 cookie
.venv/bin/python -m bgs.collect      # 开播前跑起来，Ctrl+C 结束
.venv/bin/python -m bgs.report       # 看报表；加 uid 看单人画像
```

## 结构

- `bgs/api.py` HTTP 接口：room_init、getDanmuInfo、大航海列表（topList 翻页）
- `bgs/ws.py` 最小弹幕 WebSocket 客户端（brotli 协议 v3，30s 心跳）
- `bgs/parse.py` 消息归一化，只保留弹幕 / 礼物 / 上舰 / SC / 进场 / 点赞
- `bgs/store.py` SQLite：events（原始事件）、guard_snapshots（舰长快照）、sessions（场次）
- `bgs/collect.py` 采集主循环，断线指数退避重连，GUARD_BUY 时重拍舰长快照
- `bgs/report.py` 报表：当前在舰名单 + 画像一句话、消费 Top、事件总计

## 已知限制

- 在场时长是按互动时间戳估算的（相邻互动间隔 ≤ `presence_gap_seconds` 视为连续在场），不是真实观看时长。
- 不登录 cookie 时弹幕 uid 会脱敏成 0，这类事件不计入个人统计。
- 非官方接口，B站改协议时需要跟进。

## 待办

- 进场消息已改为 `INTERACT_WORD_V2`（protobuf，字段 `pb`），当前未解析，在场时长估算暂只靠弹幕 / 礼物 / 点赞。
- `ONLINE_RANK_V3` 带高能榜前几名的 uid，可以作为在场信号补充。
- 不带 cookie 实测：公开接口和弹幕流都能连，但弹幕 uid 大多为 0、昵称打码。
