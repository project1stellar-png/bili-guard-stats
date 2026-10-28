"""本地网页后台：python -m bgs.web，浏览器开 http://127.0.0.1:8765"""
import json
from pathlib import Path

from aiohttp import web

from . import queries as q
from .config import Config

STATIC = Path(__file__).parent / "static"


def make_app(cfg: Config) -> web.Application:
    app = web.Application()

    from .store import Store
    Store(cfg.db_path)  # 建表

    def conn():
        return q.connect(cfg.db_path)

    def js(data):
        return web.Response(text=json.dumps(data, ensure_ascii=False), content_type="application/json")

    def sid(req):
        v = req.query.get("session")
        return int(v) if v else None

    async def index(_):
        return web.FileResponse(STATIC / "index.html")

    async def sessions(_):
        return js(q.sessions(conn()))

    async def guards(_):
        c = conn()
        room = c.execute("SELECT room_id FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        return js(q.guards(c, room[0], cfg.presence_gap_seconds) if room else [])

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
        return js(q.attendance(conn(), cfg.presence_gap_seconds))

    async def user(req):
        p = q.user_profile(conn(), int(req.match_info["uid"]), cfg.presence_gap_seconds)
        return js(p) if p else web.json_response({"error": "no data"}, status=404)

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

    app.add_routes([
        web.get("/api/monthly", monthly), web.get("/api/schedule", schedule_get),
        web.post("/api/schedule", schedule_post), web.post("/api/schedule/{id}/toggle", schedule_toggle),
        web.delete("/api/schedule/{id}", schedule_delete),
        web.get("/", index), web.get("/api/sessions", sessions), web.get("/api/guards", guards),
        web.get("/api/flow", flow), web.get("/api/gifts", gifts), web.get("/api/thanks", thanks),
        web.get("/api/attendance", attendance), web.get("/api/user/{uid}", user),
        web.static("/static", STATIC),
    ])
    return app


def main() -> None:
    cfg = Config.load()
    web.run_app(make_app(cfg), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
