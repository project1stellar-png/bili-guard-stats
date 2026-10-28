import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


def data_dir() -> Path:
    """配置和数据库放哪：BGS_HOME > 打包成 exe 时 exe 旁边的 data/ > 当前目录。"""
    if os.environ.get("BGS_HOME"):
        return Path(os.environ["BGS_HOME"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data"
    return Path(".")


@dataclass
class Config:
    room_id: int
    cookie: str
    db_path: str
    presence_gap_seconds: int
    commission_rate: float = 0.5  # 平台计提比例，官方口径 PC/安卓端 50%（税前）
    path: str = "config.toml"

    @staticmethod
    def load(path: str | None = None) -> "Config":
        path = path or os.environ.get("BGS_CONFIG") or str(data_dir() / "config.toml")
        p = Path(path)
        d = tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        default_db = str(Path(path).parent / "bgs.db") if Path(path).parent != Path(".") else "data/bgs.db"
        return Config(
            room_id=int(d.get("room_id", 0)),
            cookie=d.get("cookie", ""),
            db_path=d.get("db_path", default_db),
            presence_gap_seconds=int(d.get("presence_gap_seconds", 1800)),
            commission_rate=float(d.get("commission_rate", 0.5)),
            path=path,
        )

    def save(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(
            f'room_id = {self.room_id}\ncookie = "{self.cookie}"\ndb_path = "{self.db_path}"\n'
            f"presence_gap_seconds = {self.presence_gap_seconds}\ncommission_rate = {self.commission_rate}\n", encoding="utf-8")


def cookie_dict(cookie: str) -> dict[str, str]:
    out = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out
