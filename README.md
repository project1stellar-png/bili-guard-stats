# bili-guard-stats

B站直播间舰长 / 消费 / 在场时长统计工具（主播自用）。

## Windows 桌面版

解压 `bili-guard-stats-windows.zip`，双击 `直播后台.exe`：会弹一个控制台窗口并自动打开浏览器 http://127.0.0.1:8765 。
在「设置」页填直播间号、扫码登录、点「开始采集」即可；关掉控制台窗口就退出。
配置和数据库放在 exe 旁边的 `data/` 目录，换机器把这个目录一起拷走就行。

打包方式：

```bash
pip install -r requirements.txt pyinstaller
pyinstaller bgs-desktop.spec          # 产物在 dist/直播后台/
```

PyInstaller 只能在目标系统上打包，Windows 包要在 Windows 上打，或者推到 GitHub 打一个 `v*` 标签，
`.github/workflows/build.yml` 会在 Windows runner 上打包并挂到 Release。

## 命令行用法（开发）

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml   # 填 room_id
.venv/bin/python -m bgs.login        # 终端出二维码，B站 App 扫码，cookie 自动写入 config.toml
.venv/bin/python -m bgs.collect      # 开播前跑起来，Ctrl+C 结束
.venv/bin/python -m bgs.report       # 命令行报表；加 uid 看单人画像
.venv/bin/python -m bgs.web          # 本地网页后台 http://127.0.0.1:8765
```

想先看界面长什么样：`BGS_CONFIG=config.demo.toml .venv/bin/python -m bgs.demo` 造一份演示库，再用同样的环境变量起 `bgs.web`。

## 网页后台

| 页签 | 内容 |
| --- | --- |
| 场次 | 每场时长、弹幕数、互动人数、在线峰值、看过人数、点赞、收入 |
| 舰长 | 当前大航海名单（总督 / 提督 / 舰长），陪伴天数、出勤、估算在场时长、弹幕、消费；点名字看画像 |
| 流水 | 礼物 / 上舰 / SC 逐条流水，可按场次筛选 |
| 礼物榜 | 按人汇总消费排行 |
| 打卡 | 每人出勤场次、首末出现时间 |
| 感谢单 | 一键复制本场上舰 / SC / 礼物的感谢文案 |
| 记账 | 按月汇总收入（礼物 / SC / 大航海）和月度 Top 10 |
| 对账 | 拉主播后台的官方礼物流水（需主播本人登录），和本地采集按人比对，差值标红 |
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

## 登录

主播登录用的是 B站网页端的扫码登录接口（passport.bilibili.com 的 qrcode/generate + qrcode/poll），
和浏览器登录是同一套，不需要申请开放平台。`bgs.login` 扫完后把 SESSDATA / bili_jct / DedeUserID / buvid 写进 config.toml。
cookie 一般几个月有效，过期了重新扫一次。不要把 config.toml 发给别人，它等于你的登录态。

## 解析的消息

| 消息 | 处理 |
| --- | --- |
| DANMU_MSG | 弹幕，uid / 昵称 / 粉丝牌 / 舰长等级 |
| SEND_GIFT / SEND_GIFT_V2 | 礼物，只计金瓜子；V2 是 protobuf，解法参考 realtime_liushui |
| GUARD_BUY / USER_TOAST_MSG | 上舰 / 续费，金额只记 GUARD_BUY 一次 |
| SUPER_CHAT_MESSAGE | SC |
| INTERACT_WORD_V2 | 进场 / 关注 / 分享，protobuf，用 `bgs/pb.py` 的通用 wire 解码（字段布局是实测推的） |
| ENTRY_EFFECT / LIKE_INFO_V3_CLICK | 舰长进场特效 / 点赞，作在场信号 |
| ONLINE_RANK_V3 | 高能榜前几名（protobuf），作在场信号，同一人 5 分钟内只记一次 |
| WATCHED_CHANGE / ONLINE_RANK_COUNT / LIKE_INFO_V3_UPDATE | 房间指标，进 metrics 表，值变化才写 |

## 金额口径（参考 hefafafa/realtime_liushui 的实测）

- 1000 金瓜子 = 1 元；免费礼物（银瓜子）不计。
- 大航海回声：GUARD_BUY 之后 15 秒内同一人再来一条名字像「舰长 / 提督 / 总督」的礼物，是同一笔钱的回声，不重复计；回声价低于标价（打折舰长 168 / 138）时按回声价修正上舰金额。
- 人气红包（POPULARITY_RED_POCKET*）不计流水，中奖内容物被用掉时才作为礼物计。
- 顶栏「抽成后」开关：按设置里的计提比例（默认 50%）换算成实收，对账页不受影响。
- 官方流水接口 `giftStream/getReceivedGiftStreamNextList`（来自 boxie123/Bilibili_GetReceivedGiftStream）是主播后台的账，用来校对弹幕采集的漏记。

## 已知限制 / 待办

- 不带 cookie 实测：公开接口和弹幕流都能连，但服务器只下发极少量消息（几十万人在线的房间一分钟只给 1 条弹幕，还会推 LOG_IN_NOTICE），且 uid 为 0、昵称打码。**采集必须登录。**
- SEND_GIFT_V2 的字段映射按参考项目的实测写，本地只用合成报文验证过，登录后第一场跑完要在「流水」页核对礼物名和金额。
- 短时间反复请求 getDanmuInfo 会触发 -352 风控，几分钟后自然恢复。
- INTERACT_WORD_V2 的粉丝牌子消息（字段 9）布局没抓到带牌子的样本，按 v1 字段顺序推的，上线后核对一下。
