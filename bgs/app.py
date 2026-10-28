"""桌面版入口（PyInstaller 打包的就是它）：起后台服务并打开浏览器。
数据和配置放在 exe 旁边的 data/ 目录。"""
import sys

from .web import main


def entry() -> None:
    port = 8765
    for a in sys.argv[1:]:
        if a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    print(f"直播后台已启动：http://127.0.0.1:{port}  （关掉这个窗口即退出）")
    main(port=port, open_browser=True)


if __name__ == "__main__":
    entry()
