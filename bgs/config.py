import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    room_id: int
    cookie: str
    db_path: str
    presence_gap_seconds: int

    @staticmethod
    def load(path: str | None = None) -> "Config":
        path = path or os.environ.get("BGS_CONFIG", "config.toml")
        p = Path(path)
        if not p.exists():
            raise SystemExit(f"找不到 {path}，先复制 config.example.toml 填好")
        d = tomllib.loads(p.read_text())
        return Config(
            room_id=int(d["room_id"]),
            cookie=d.get("cookie", ""),
            db_path=d.get("db_path", "data/bgs.db"),
            presence_gap_seconds=int(d.get("presence_gap_seconds", 1800)),
        )


def cookie_dict(cookie: str) -> dict[str, str]:
    out = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out
