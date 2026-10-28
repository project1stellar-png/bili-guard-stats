"""本地网页后台：python -m bgs.web，浏览器开 http://127.0.0.1:8765
同时承担桌面版的控制面：设置房间号、扫码登录、开关采集。"""
import asyncio
import base64
import io
import json
import logging
from pathlib import Path

import qrcode
from aiohttp import web

from . import launcher, queries as q, recorder as rec
from .collect import run as collect_run
from .config import Config
from .login import QrLogin
from .store import Store

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("bgs.web")


def make_app(cfg: Config) -> web.Application:
    app = web.Application()
    Store(cfg.db_path)  # 建表
    state = {"cfg": cfg, "task": None, "status": {}, "qr": None, "recorder": rec.Recorder()}

    def conn():
        return q.connect(state["cfg"].db_path)

    def js(data, status=200):
        return web.Response(text=json.dumps(data, ensure_ascii=False), content_type="application/json", status=status)

    def sid(req):
        v = req.query.get("session")
        return int(v) if v else None

    def gap():
        return state["cfg"].presence_gap_seconds

    # ---------- 数据 ----------
    async def index(_):
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def sessions(_):
        return js(q.sessions(conn()))

    async def guards(_):
        c = conn()
        room = c.execute("SELECT room_id FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        return js(q.guards(c, room[0], gap()) if room else [])

    async def flow(req):
        return js(q.flow(conn(), sid(req)))

    async def gifts(req):
        return js(q.gift_rank(conn(), sid(req)))

    async def thanks(req):
        s = sid(req)
        if not s:
            row = conn().execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
            s = row[0] if row else 0
        return js(q.thanks(conn(), s))

    async def attendance(_):
        return js(q.attendance(conn(), gap()))

    async def user(req):
        p = q.user_profile(conn(), int(req.match_info["uid"]), gap())
        return js(p) if p else js({"error": "no data"}, 404)

    async def monthly(_):
        return js(q.monthly(conn()))

    async def schedule_get(_):
        return js(q.schedule_list(conn()))

    async def schedule_post(req):
        d = await req.json()
        return js({"id": q.schedule_add(conn(), d["date"], d.get("start", ""), d["title"], d.get("note", ""))})

    async def schedule_toggle(req):
        q.schedule_toggle(conn(), int(req.match_info["id"])); return js({"ok": True})

    async def schedule_delete(req):
        q.schedule_delete(conn(), int(req.match_info["id"])); return js({"ok": True})

    # ---------- 控制面 ----------
    def collecting() -> bool:
        t = state["task"]
        return t is not None and not t.done()

    async def status(_):
        c = state["cfg"]
        from .config import cookie_dict
        uid = cookie_dict(c.cookie).get("DedeUserID", "")
        return js({"room_id": c.room_id, "logged_in": bool(uid), "uid": uid, "collecting": collecting(),
                   "commission_rate": c.commission_rate, "theme": c.theme, "hotkey": c.hotkey,
                   "record_dir": c.record_dir, "audio_device": c.audio_device, "ffmpeg_path": c.ffmpeg_path,
                   "platform": __import__("sys").platform,
                   "collect": state["status"], "config_path": str(c.path), "db_path": c.db_path})

    async def settings_post(req):
        d = await req.json()
        c = state["cfg"]
        if "room_id" in d:
            c.room_id = int(d["room_id"] or 0)
        if "presence_gap_seconds" in d:
            c.presence_gap_seconds = int(d["presence_gap_seconds"])
        if "commission_rate" in d:
            c.commission_rate = max(0.0, min(1.0, float(d["commission_rate"])))
        for k in ("record_dir", "audio_device", "ffmpeg_path", "hotkey", "theme"):
            if k in d:
                setattr(c, k, str(d[k]).strip())
        c.save()
        return js({"ok": True})

    async def logout(_):
        state["cfg"].cookie = ""
        state["cfg"].save()
        return js({"ok": True})

    async def login_qr(_):
        if state["qr"]:
            await state["qr"].close()
        state["qr"] = QrLogin()
        url = await state["qr"].start()
        img = qrcode.make(url)
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return js({"png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()})

    async def login_poll(_):
        if not state["qr"]:
            return js({"code": -1})
        code, cookie = await state["qr"].poll()
        if code == 0:
            state["cfg"].cookie = cookie
            state["cfg"].save()
            await state["qr"].close(); state["qr"] = None
        elif code == 86038:
            await state["qr"].close(); state["qr"] = None
        return js({"code": code})

    async def reconcile_get(req):
        day = req.query.get("day") or __import__("datetime").date.today().isoformat()
        return js(q.reconcile(conn(), day))

    async def reconcile_fetch(req):
        """从主播后台拉某天的官方流水入库。"""
        from .api import BiliApi
        d = await req.json()
        day = d["day"]
        c = state["cfg"]
        if not c.cookie:
            return js({"error": "先扫码登录（必须是主播本人的账号）"}, 400)
        try:
            async with BiliApi(c.cookie) as api:
                items = await api.received_gift_stream(day)
        except Exception as e:  # noqa: BLE001
            return js({"error": str(e)}, 400)
        n = Store(c.db_path).upsert_official_gifts(day, items)
        return js({"ok": True, "n": n})

    async def official_days(_):
        return js(q.official_days(conn()))

    # ---------- 直播软件 ----------
    async def programs_get(_):
        return js({"groups": launcher.GROUPS, "items": launcher.list_programs(conn())})

    async def programs_post(req):
        d = await req.json()
        return js({"id": launcher.add_program(conn(), d.get("name", ""), d["path"], d.get("grp", "其他"), d.get("args", ""))})

    async def programs_patch(req):
        launcher.update_program(conn(), int(req.match_info["id"]), **(await req.json())); return js({"ok": True})

    async def programs_delete(req):
        launcher.delete_program(conn(), int(req.match_info["id"])); return js({"ok": True})

    async def programs_launch_one(req):
        row = conn().execute("SELECT * FROM programs WHERE id=?", (int(req.match_info["id"]),)).fetchone()
        if not row:
            return js({"error": "没有这个程序"}, 404)
        ok, err = launcher.launch(row["path"], row["args"])
        return js({"ok": ok, "error": err})

    async def programs_launch_all(req):
        d = await req.json() if req.can_read_body else {}
        loop = asyncio.get_running_loop()
        rows = launcher.checked_programs(conn())
        results = await loop.run_in_executor(None, launcher.launch_checked, rows, bool(d.get("skip_running", True)))
        return js({"results": results})

    async def programs_folder(req):
        row = conn().execute("SELECT path FROM programs WHERE id=?", (int(req.match_info["id"]),)).fetchone()
        if row:
            launcher.open_folder(row["path"])
        return js({"ok": bool(row)})

    # ---------- 录屏 ----------
    def rec_info():
        c = state["cfg"]
        ff = rec.find_ffmpeg(c.ffmpeg_path)
        st = state["recorder"].status()
        st.update(ffmpeg=ff or "", record_dir=c.record_dir_path(), audio_device=c.audio_device,
                  recent=rec.recent_files(c.record_dir_path()))
        return st

    async def record_status(_):
        return js(rec_info())

    async def record_devices(_):
        ff = rec.find_ffmpeg(state["cfg"].ffmpeg_path)
        if not ff:
            return js({"error": "没找到 ffmpeg"}, 400)
        loop = asyncio.get_running_loop()
        return js({"devices": await loop.run_in_executor(None, rec.list_audio_devices, ff)})

    async def record_start(_):
        c = state["cfg"]
        ff = rec.find_ffmpeg(c.ffmpeg_path)
        if not ff:
            return js({"error": "没找到 ffmpeg：把 ffmpeg.exe 放到程序旁边，或在设置里填路径"}, 400)
        loop = asyncio.get_running_loop()
        ok, msg = await loop.run_in_executor(None, state["recorder"].start, ff, c.record_dir_path(), c.audio_device)
        return js({"ok": ok, "file" if ok else "error": msg}, 200 if ok else 400)

    async def record_stop(_):
        loop = asyncio.get_running_loop()
        f = await loop.run_in_executor(None, state["recorder"].stop)
        return js({"ok": True, "file": f})

    async def record_folder(_):
        launcher.open_folder(state["cfg"].record_dir_path() + "/"); return js({"ok": True})

    async def quit_app(_):
        async def _bye():
            await asyncio.sleep(0.3)
            raise web.GracefulExit()
        asyncio.create_task(_bye())
        return js({"ok": True})

    async def collect_start(_):
        if collecting():
            return js({"ok": True, "already": True})
        if not state["cfg"].room_id:
            return js({"error": "先填房间号"}, 400)
        state["status"] = {}

        async def runner():
            try:
                await collect_run(state["cfg"], state["status"])
            except asyncio.CancelledError:
                pass
            except BaseException as e:  # noqa: BLE001
                state["status"]["error"] = str(e)
                log.exception("采集异常退出")

        state["task"] = asyncio.create_task(runner())
        return js({"ok": True})

    async def collect_stop(_):
        if collecting():
            state["task"].cancel()
            try:
                await state["task"]
            except BaseException:  # noqa: BLE001
                pass
        return js({"ok": True})

    async def on_shutdown(_):
        await collect_stop(None)
        state["recorder"].stop()
        if state["qr"]:
            await state["qr"].close()

    app.on_shutdown.append(on_shutdown)
    app["state"] = state
    app.add_routes([
        web.get("/", index),
        web.get("/api/sessions", sessions), web.get("/api/guards", guards), web.get("/api/flow", flow),
        web.get("/api/gifts", gifts), web.get("/api/thanks", thanks), web.get("/api/attendance", attendance),
        web.get("/api/user/{uid}", user), web.get("/api/monthly", monthly),
        web.get("/api/schedule", schedule_get), web.post("/api/schedule", schedule_post),
        web.post("/api/schedule/{id}/toggle", schedule_toggle), web.delete("/api/schedule/{id}", schedule_delete),
        web.get("/api/reconcile", reconcile_get), web.post("/api/reconcile/fetch", reconcile_fetch),
        web.get("/api/official/days", official_days),
        web.get("/api/programs", programs_get), web.post("/api/programs", programs_post),
        web.patch("/api/programs/{id}", programs_patch), web.delete("/api/programs/{id}", programs_delete),
        web.post("/api/programs/{id}/launch", programs_launch_one), web.post("/api/programs/{id}/folder", programs_folder),
        web.post("/api/programs/launch", programs_launch_all),
        web.get("/api/record", record_status), web.get("/api/record/devices", record_devices),
        web.post("/api/record/start", record_start), web.post("/api/record/stop", record_stop),
        web.post("/api/record/folder", record_folder),
        web.post("/api/quit", quit_app),
        web.get("/api/status", status), web.post("/api/settings", settings_post), web.post("/api/logout", logout),
        web.post("/api/login/qr", login_qr), web.get("/api/login/poll", login_poll),
        web.post("/api/collect/start", collect_start), web.post("/api/collect/stop", collect_stop),
        web.static("/static", STATIC),
    ])
    return app


def _install_hotkey(app: web.Application) -> None:
    """Windows 上注册全局快捷键切换录屏。keyboard 库不可用就跳过。"""
    import sys
    if sys.platform != "win32":
        return
    try:
        import keyboard  # type: ignore
    except ImportError:
        return
    state = app["state"]

    def toggle():
        c, r = state["cfg"], state["recorder"]
        if r.running():
            r.stop()
        else:
            ff = rec.find_ffmpeg(c.ffmpeg_path)
            if ff:
                r.start(ff, c.record_dir_path(), c.audio_device)

    try:
        keyboard.add_hotkey(state["cfg"].hotkey or "ctrl+alt+f9", toggle)
        log.info("录屏快捷键：%s", state["cfg"].hotkey)
    except Exception as e:  # noqa: BLE001
        log.warning("注册快捷键失败：%s", e)


def main(port: int = 8765, open_browser: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config.load()
    app = make_app(cfg)
    _install_hotkey(app)
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    web.run_app(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
