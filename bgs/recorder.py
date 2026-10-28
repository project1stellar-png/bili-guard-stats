"""屏幕录制：用 ffmpeg 录全屏 + 一路音频输入。Windows 用 gdigrab + dshow，macOS 用 avfoundation（开发测试用）。
ffmpeg 查找顺序：设置里指定的路径 > exe 旁边的 ffmpeg(.exe) > PATH。"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def find_ffmpeg(configured: str = "") -> str | None:
    cands = []
    if configured:
        cands.append(configured)
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")
    cands += [str(base / "ffmpeg.exe"), str(base / "ffmpeg"), str(base / "_internal" / "ffmpeg.exe")]
    for c in cands:
        if Path(c).is_file():
            return c
    return shutil.which("ffmpeg")


def list_audio_devices(ffmpeg: str) -> list[str]:
    """列出可用的音频输入设备名（Windows dshow / macOS avfoundation）。"""
    try:
        if sys.platform == "win32":
            out = subprocess.run([ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                                 capture_output=True, text=True, timeout=10, errors="replace").stderr
            names, audio = [], False
            for line in out.splitlines():
                if "(audio)" in line:
                    audio = True
                elif "(video)" in line:
                    audio = False
                if audio and '"' in line:
                    names.append(line.split('"')[1])
            return list(dict.fromkeys(names))
        if sys.platform == "darwin":
            out = subprocess.run([ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                                 capture_output=True, text=True, timeout=10, errors="replace").stderr
            names, audio = [], False
            for line in out.splitlines():
                if "audio devices" in line:
                    audio = True
                elif "video devices" in line:
                    audio = False
                elif audio and "] [" in line:
                    names.append(line.split("] ", 2)[-1].strip())
            return names
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


class Recorder:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.file: str = ""
        self.started_at: float = 0
        self.error: str = ""

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, ffmpeg: str, out_dir: str, audio_device: str = "", fps: int = 30) -> tuple[bool, str]:
        if self.running():
            return False, "已经在录了"
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        self.file = str(Path(out_dir) / time.strftime("录屏_%Y-%m-%d_%H%M%S.mp4"))
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        if sys.platform == "win32":
            cmd += ["-f", "gdigrab", "-framerate", str(fps), "-i", "desktop"]
            if audio_device:
                cmd += ["-f", "dshow", "-i", f"audio={audio_device}"]
        elif sys.platform == "darwin":
            # avfoundation 用 "视频索引:音频索引"，这里视频取 1（通常是屏幕），音频设备名用索引或名字都行
            cmd += ["-f", "avfoundation", "-framerate", str(fps), "-capture_cursor", "1",
                    "-i", f"1:{audio_device}" if audio_device else "1:none"]
        else:
            cmd += ["-f", "x11grab", "-framerate", str(fps), "-i", os.environ.get("DISPLAY", ":0")]
            if audio_device:
                cmd += ["-f", "pulse", "-i", audio_device]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", self.file]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            return False, str(e)
        self.started_at = time.time()
        self.error = ""
        time.sleep(1.0)
        if self.proc.poll() is not None:
            err = (self.proc.stderr.read() or b"").decode("utf-8", "replace").strip()
            self.error = err[-400:]
            self.proc = None
            return False, f"ffmpeg 启动失败：{self.error}"
        return True, self.file

    def stop(self) -> str:
        if not self.running():
            return ""
        try:
            self.proc.stdin.write(b"q")  # 让 ffmpeg 正常收尾，moov 才写得全
            self.proc.stdin.flush()
            self.proc.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.proc.kill()
        f, self.proc = self.file, None
        return f

    def status(self) -> dict:
        return {"recording": self.running(), "file": self.file if self.running() else "",
                "elapsed": int(time.time() - self.started_at) if self.running() else 0, "error": self.error}


def recent_files(out_dir: str, n: int = 8) -> list[dict]:
    p = Path(out_dir)
    if not p.is_dir():
        return []
    files = sorted(p.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)[:n]
    return [{"name": f.name, "size_mb": round(f.stat().st_size / 1048576, 1), "mtime": f.stat().st_mtime} for f in files]
