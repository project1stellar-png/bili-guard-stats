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
    record_dir: str = ""          # 录屏存放目录，空 = data/录屏
    audio_device: str = ""        # 录屏音频输入设备名
    ffmpeg_path: str = ""         # 留空自动找
    hotkey: str = "ctrl+alt+f9"   # 录屏开关全局快捷键（Windows）
    theme: str = "pink"
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
            record_dir=d.get("record_dir", ""), audio_device=d.get("audio_device", ""),
            ffmpeg_path=d.get("ffmpeg_path", ""), hotkey=d.get("hotkey", "ctrl+alt+f9"), theme=d.get("theme", "pink"),
            path=path,
        )

    def save(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(
            f'room_id = {self.room_id}\ncookie = "{self.cookie}"\ndb_path = "{self.db_path}"\n'
            f"presence_gap_seconds = {self.presence_gap_seconds}\ncommission_rate = {self.commission_rate}\n"
            f'record_dir = "{self.record_dir}"\naudio_device = "{self.audio_device}"\nffmpeg_path = "{self.ffmpeg_path}"\n'
            f'hotkey = "{self.hotkey}"\ntheme = "{self.theme}"\n', encoding="utf-8")

    def record_dir_path(self) -> str:
        return self.record_dir or str(Path(self.path).parent / "录屏")


def cookie_dict(cookie: str) -> dict[str, str]:
    out = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out
