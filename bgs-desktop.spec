# PyInstaller 配置：pyinstaller bgs-desktop.spec
# 产物在 dist/直播后台/ 目录（目录模式，启动快），Windows 下双击里面的 直播后台.exe
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    datas=[("bgs/static", "bgs/static")],
    hiddenimports=collect_submodules("bgs") + ["qrcode.image.pil"],
    excludes=["tkinter", "matplotlib", "numpy"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts,
    exclude_binaries=True,
    name="直播后台",
    console=True,          # 保留控制台窗口，能看日志、关窗口即退出
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="直播后台")
