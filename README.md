# bili-guard-stats

B站直播间舰长 / 消费 / 在场时长统计工具（主播自用）。

## 用法

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml   # 填 room_id 和 cookie
.venv/bin/python -m bgs.collect      # 开播前跑起来，Ctrl+C 结束
.venv/bin/python -m bgs.report       # 命令行报表；加 uid 看单人画像
.venv/bin/python -m bgs.web          # 本地网页后台 http://127.0.0.1:8765
```

想先看界面长什么样：`BGS_CONFIG=config.demo.toml .venv/bin/python -m bgs.demo` 造一份演示库，再用同样的环境变量起 `bgs.web`。

## 网页后台

| 页签 | 内容 |
| --- | --- |
| 舰长 | 当前大航海名单（总督 / 提督 / 舰长），陪伴天数、出勤、估算在场时长、弹幕、消费；点名字看画像 |
| 流水 | 礼物 / 上舰 / SC 逐条流水，可按场次筛选 |
| 礼物榜 | 按人汇总消费排行 |
| 打卡 | 每人出勤场次、首末出现时间 |
| 感谢单 | 一键复制本场上舰 / SC / 礼物的感谢文案 |
| 记账 | 按月汇总收入（礼物 / SC / 大航海）和月度 Top 10 |
| 排播 | 简单的排播清单，本地保存 |

用户画像弹窗：一句话描述 + 消费 / 出勤 / 在场 / 弹幕 / 粉丝牌 + 24 小时活跃分布 + 最近记录。

## 不做的功能

- 房管机器人 / 自动谢礼：要用自己的号自动发弹幕，风控风险高，暂不做。
- 私信群发：违反 B站规则，不做。

## 结构

- `bgs/api.py` HTTP 接口：room_init、getDanmuInfo、大航海列表（topList 翻页）
- `bgs/ws.py` 最小弹幕 WebSocket 客户端（brotli 协议 v3，30s 心跳）
- `bgs/parse.py` 消息归一化，只保留弹幕 / 礼物 / 上舰 / SC / 进场 / 点赞
- `bgs/store.py` SQLite：events（原始事件）、guard_snapshots（舰长快照）、sessions（场次）
- `bgs/collect.py` 采集主循环，断线指数退避重连，GUARD_BUY 时重拍舰长快照
- `bgs/report.py` 命令行报表 + 在场时长估算 + 画像一句话
- `bgs/queries.py` 网页用的查询（舰长 / 流水 / 礼物榜 / 打卡 / 感谢单 / 月度 / 排播）
- `bgs/web.py` + `bgs/static/index.html` 本地网页后台（aiohttp，仅监听 127.0.0.1）
- `bgs/demo.py` 演示数据

## 已知限制

- 在场时长是按互动时间戳估算的（相邻互动间隔 ≤ `presence_gap_seconds` 视为连续在场），不是真实观看时长。
- 不登录 cookie 时弹幕 uid 会脱敏成 0，这类事件不计入个人统计。
- 非官方接口，B站改协议时需要跟进。

## 待办

- 进场消息已改为 `INTERACT_WORD_V2`（protobuf，字段 `pb`），当前未解析，在场时长估算暂只靠弹幕 / 礼物 / 点赞。
- `ONLINE_RANK_V3` 带高能榜前几名的 uid，可以作为在场信号补充。
- 不带 cookie 实测：公开接口和弹幕流都能连，但弹幕 uid 大多为 0、昵称打码。
