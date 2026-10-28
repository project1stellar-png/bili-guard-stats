"""直播软件清单：登记程序路径，一键启动，查是否在运行，打开所在文件夹。"""
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

GROUPS = ["直播推流", "虚拟形象", "音频声卡", "唱歌音乐", "其他"]


def _running_exes() -> dict[str, list[int]]:
    """当前所有进程的可执行文件路径（小写）-> pid 列表。"""
    out: dict[str, list[int]] = {}
    for p in psutil.process_iter(["pid", "exe", "name"]):
        try:
            exe = (p.info.get("exe") or "").lower()
            name = (p.info.get("name") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if exe:
            out.setdefault(exe, []).append(p.info["pid"])
        if name:
            out.setdefault("name:" + name, []).append(p.info["pid"])
    return out


def _is_running(path: str, table: dict[str, list[int]]) -> bool:
    low = path.lower()
    if low in table:
        return True
    base = os.path.basename(low)
    # 兜底：有些进程拿不到 exe（权限），按进程名比
    if "name:" + base in table:
        return True
    # macOS .app：里面的主程序
    if low.endswith(".app"):
        stem = os.path.basename(low)[:-4]
        if "name:" + stem in table:
            return True
        for exe in table:
            if exe.startswith(low + "/contents/macos/"):
                return True
    return False


def list_programs(conn) -> list[dict]:
    table = _running_exes()
    rows = [dict(r) for r in conn.execute("SELECT * FROM programs ORDER BY grp, sort, id")]
    for r in rows:
        r["running"] = _is_running(r["path"], table)
        r["exists"] = Path(r["path"]).exists()
    return rows


def add_program(conn, name: str, path: str, grp: str, args: str = "") -> int:
    path = path.strip().strip('"')
    name = name.strip() or Path(path).stem
    cur = conn.execute("INSERT INTO programs(name, path, args, grp) VALUES (?,?,?,?)", (name, path, args, grp or "其他"))
    conn.commit()
    return cur.lastrowid


def update_program(conn, pid: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items() if k in ("name", "path", "args", "grp", "checked", "sort")}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    conn.execute(f"UPDATE programs SET {sets} WHERE id=?", (*allowed.values(), pid))
    conn.commit()


def delete_program(conn, pid: int) -> None:
    conn.execute("DELETE FROM programs WHERE id=?", (pid,))
    conn.commit()


def launch(path: str, args: str = "") -> tuple[bool, str]:
    """启动一个程序，不等待。Windows 用 startfile 风格（能带参数就用 Popen）。"""
    p = Path(path)
    if not p.exists():
        return False, "文件不存在"
    try:
        if sys.platform == "darwin" and path.endswith(".app"):
            subprocess.Popen(["open", "-a", path] + (args.split() if args else []))
        elif sys.platform == "win32":
            subprocess.Popen([path] + (args.split() if args else []), cwd=str(p.parent),
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            subprocess.Popen([path] + (args.split() if args else []), cwd=str(p.parent), start_new_session=True)
        return True, ""
    except OSError as e:
        return False, str(e)


def checked_programs(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM programs WHERE checked=1 ORDER BY grp, sort, id")]


def launch_checked(rows: list[dict], skip_running: bool = True) -> list[dict]:
    """一键启动给定清单（可在线程里跑，不碰数据库），返回每项结果。"""
    results = []
    table = _running_exes()
    for r in rows:
        if skip_running and _is_running(r["path"], table):
            results.append({"id": r["id"], "name": r["name"], "ok": True, "skipped": True})
            continue
        ok, err = launch(r["path"], r["args"])
        results.append({"id": r["id"], "name": r["name"], "ok": ok, "error": err})
        time.sleep(0.5)  # 别一口气把十几个程序同时拉起来
    return results


def open_folder(path: str) -> None:
    p = Path(path)
    target = p if p.is_dir() else p.parent
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)] if p.exists() else ["explorer", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)] if p.exists() else ["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
