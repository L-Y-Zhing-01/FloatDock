# -*- coding: utf-8 -*-
"""把浮坞打包成免 Python 的独立程序与安装包。

    python installer/build.py app    只打应用本体（FloatDock.exe）
    python installer/build.py all    应用 + 卸载程序 + 待安装内容 + 安装程序 + 发布文件

为什么用 PyInstaller 的 onedir 装应用、onefile 装安装器：
  · 浮坞是常驻托盘的，onedir 启动快、也更不容易被误报；onefile 每次要解包，
    启动多花 1–2 秒，对常驻程序不划算。
  · 安装程序/卸载程序是"用完即走"的，onefile 的单文件形态最适合传播。

资源与路径：`--add-data` 把 floatdock.ico 与 donation.png 放进程序包根
（PyInstaller 6 的 onedir 里就是 `_internal/`），打包后模块的 `__file__` 也
落在同一目录，所以 appicon.PATH / tip.PATH 那两条"资源就在我旁边"的路径在
冻结后依然成立 —— 全程序只有这两处声明资源在哪，打包不需要第二套逻辑。
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "发布")
BUILD = os.path.join(OUT, "_build")
PYI = os.path.join(os.path.dirname(sys.executable), "Scripts", "pyinstaller.exe")
ICO = os.path.join(ROOT, "floatdock.ico")
DONATION = os.path.join(ROOT, "donation.png")
# 随安装包铺到安装目录的文档。许可文件是合规必需项 —— 缺了就不许构建，
# 免得再次出现"装完的目录里没有 LICENSE"这种事后才发现的问题。
DOCS = ("使用说明.md", "README.md", "LICENSE", "LICENSE-ASSETS", "NOTICE")
SETUP_NAME = "浮坞-FloatDock-v1.10.0-安装程序"


def run(cmd):
    print(">", " ".join(cmd[1:]), flush=True)
    p = subprocess.run(cmd, cwd=ROOT)
    if p.returncode != 0:
        raise SystemExit("构建失败，退出码 %d" % p.returncode)


def clean_dir(path):
    """用原生命令删目录，绕开 Python 侧的"先送回收站"。

    本机把 `shutil.rmtree` 换成了"移入回收站"，而回收站在某些盘符（映射盘/
    网络盘）上会直接失败（实测 SHFileOperationW 返回 0x2），PyInstaller 清理
    上一次的产物时就会半途而废。构建产物本来就该直接删，走 `rmdir /s /q`
    最稳、也不误伤别处。
    """
    if not os.path.exists(path):
        return
    subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", path],
                   capture_output=True)


def pyinstaller(name, script, onefile, extra=()):
    # 每个产物开工前先自己清干净（见 clean_dir 的说明）
    clean_dir(os.path.join(BUILD, "dist", name))
    clean_dir(os.path.join(BUILD, "dist", name + ".exe"))
    clean_dir(os.path.join(BUILD, "work", name))
    args = [PYI, "--noconfirm", "--clean", "--noconsole",
            "--name", name, "--icon", ICO, "--paths", ROOT,
            "--distpath", os.path.join(BUILD, "dist"),
            "--workpath", os.path.join(BUILD, "work", name),
            "--specpath", os.path.join(BUILD, "spec"),
            "--onefile" if onefile else "--onedir"]
    args += list(extra) + [script]
    run(args)
    return os.path.join(BUILD, "dist", name + (".exe" if onefile else ""))


def build_app():
    for path in (ICO, DONATION):
        if not os.path.exists(path):
            raise SystemExit("缺少资源：%s" % path)
    exe = pyinstaller("FloatDock", os.path.join(ROOT, "floatdock.pyw"), False,
                      ["--add-data", ICO + os.pathsep + ".",
                       "--add-data", DONATION + os.pathsep + "."])
    print("应用产物:", exe)
    return exe


def build_uninstaller():
    exe = pyinstaller("卸载程序", os.path.join(HERE, "uninstall_app.py"), True)
    print("卸载程序:", exe)
    return exe


def stage(app_dir, unins_exe):
    """待安装内容：安装程序会把这些原样铺到用户选的目录里。"""
    payload = os.path.join(BUILD, "payload")
    clean_dir(payload)
    os.makedirs(payload)
    shutil.copytree(app_dir, os.path.join(payload, "app"))
    shutil.copy2(unins_exe, os.path.join(payload, "卸载程序.exe"))
    shutil.copy2(ICO, os.path.join(payload, "floatdock.ico"))
    for name in DOCS:
        src = os.path.join(ROOT, name)
        if not os.path.exists(src):
            raise SystemExit("缺少文档：%s（安装包须随附许可与说明）" % src)
        shutil.copy2(src, os.path.join(payload, name))
    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _d, fs in os.walk(payload) for f in fs)
    print("待安装内容: %s (%.1f MB)" % (payload, size / 1048576))
    return payload


def build_setup(payload):
    exe = pyinstaller(SETUP_NAME, os.path.join(HERE, "setup_app.py"), True,
                      ["--add-data", payload + os.pathsep + "payload"])
    print("安装程序:", exe)
    return exe


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.makedirs(BUILD, exist_ok=True)
    if what == "setup":
        # 只重做「待安装内容」与安装程序：改文档、换图标、动 payload 清单时用这个，
        # 不必重新分析依赖、重编 app 与卸载程序（那两步占掉全部时间的九成）。
        app_dir = os.path.join(BUILD, "dist", "FloatDock")
        unins = os.path.join(BUILD, "dist", "卸载程序.exe")
        for path in (app_dir, unins):
            if not os.path.exists(path):
                raise SystemExit("缺少上次构建产物：%s（先跑一次 all）" % path)
        setup = build_setup(stage(app_dir, unins))
        final = os.path.join(OUT, os.path.basename(setup))
        shutil.copy2(setup, final)
        print("安装程序:", final)
        return
    app = build_app()
    if what == "app":
        return
    unins = build_uninstaller()
    payload = stage(app, unins)
    setup = build_setup(payload)
    final = os.path.join(OUT, os.path.basename(setup))
    shutil.copy2(setup, final)
    print("\n发布文件：%s" % final)
    print("体积：%.1f MB" % (os.path.getsize(final) / 1048576))


if __name__ == "__main__":
    main()
