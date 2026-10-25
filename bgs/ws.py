"""最小弹幕 WebSocket 客户端。协议：16 字节头 + body，brotli 压缩包里嵌套多个子包。"""
import asyncio
import json
import logging
import struct
from typing import AsyncIterator

import aiohttp
import brotli

log = logging.getLogger("bgs.ws")

HEADER = struct.Struct(">IHHII")  # packet_len, header_len, ver, op, seq
OP_HEARTBEAT, OP_HEARTBEAT_REPLY, OP_MESSAGE, OP_AUTH, OP_AUTH_REPLY = 2, 3, 5, 7, 8
VER_JSON, VER_INT, VER_ZLIB, VER_BROTLI = 0, 1, 2, 3


def pack(op: int, body: bytes, ver: int = 1) -> bytes:
    return HEADER.pack(HEADER.size + len(body), HEADER.size, ver, op, 1) + body


def unpack(data: bytes):
    """递归展开一个 WS 帧里的所有子包，yield (op, body_json_or_None)。"""
    off = 0
    while off < len(data):
        plen, hlen, ver, op, _ = HEADER.unpack_from(data, off)
        body = data[off + hlen: off + plen]
        off += plen
        if ver == VER_BROTLI:
            yield from unpack(brotli.decompress(body))
        elif ver == VER_ZLIB:
            import zlib
            yield from unpack(zlib.decompress(body))
        elif op == OP_MESSAGE:
            try:
                yield op, json.loads(body)
            except json.JSONDecodeError:
                log.warning("bad json: %r", body[:80])
        else:
            yield op, None


async def stream(host_list: list[dict], token: str, real_room_id: int, uid: int,
                 headers: dict) -> AsyncIterator[dict]:
    """连一台弹幕服务器，持续 yield 消息 dict。断开则抛异常，由上层重连。"""
    host = host_list[0]
    url = f"wss://{host['host']}:{host['wss_port']}/sub"
    auth = {"uid": uid, "roomid": real_room_id, "protover": 3, "platform": "web", "type": 2,
            "key": token}
    if "buvid" in headers:
        auth["buvid"] = headers.pop("buvid")
    async with aiohttp.ClientSession(headers=headers) as s, s.ws_connect(url, heartbeat=None) as ws:
        await ws.send_bytes(pack(OP_AUTH, json.dumps(auth).encode(), VER_JSON))

        async def heartbeat():
            while True:
                await ws.send_bytes(pack(OP_HEARTBEAT, b"[object Object]"))
                await asyncio.sleep(30)

        hb = asyncio.create_task(heartbeat())
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.BINARY:
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                for op, body in unpack(msg.data):
                    if op == OP_AUTH_REPLY:
                        log.info("auth reply: %s", body)
                    elif op == OP_MESSAGE and body:
                        yield body
        finally:
            hb.cancel()
    raise ConnectionError("ws closed")
