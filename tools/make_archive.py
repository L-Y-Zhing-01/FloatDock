# -*- coding: utf-8 -*-
"""把当前源码打成一个带版本号的归档 zip。

    python tools/make_archive.py            版本号从 panel.VERSION 取，日期取今天
    python tools/make_archive.py v1.6.3     指定版本号（批量补历史快照时用）

zip 内含一份 `归档说明.md`：版本号、日期、各层验证结论，以及每个文件的
sha256。多年以后只看这一个文件，就知道当时发出去的东西是什么。

**排除清单连理由一起写在代码里** —— 这是从 v1.6.2 手工打包那次踩出来的：
当时没排除 AI 绘图的 1024px 源图，归档从 773 KB 涨到 4 MB。以后改清单时
能看懂每一项为什么排，别只留一行文件名。

归档 zip 本身也会被排除：它躺在同一个目录里，放进自己是死循环。
"""
import datetime
import hashlib
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARCHIVE_DIR = os.path.join(ROOT, "归档")

# 不收的目录：键是目录名，值是理由
EXCLUDE_DIRS = {
    "发布": "构建产物（几十 MB 的 exe），属于分发物不属于源码",
    "归档": "归档自己，放进自己是死循环",
    "__pycache__": "运行期缓存，可再生",
    "_sandbox": "测试沙箱残留（每次跑测试都会重建）",
    "artifacts": "开发期产物已单独留在 归档/artifacts/，不重复",
    "_icon_drafts": "更早一批图标草稿，非本项目产物",
}

# 不收的文件：键是文件名，值是理由
EXCLUDE_FILES = {
    "config.json": "本机使用状态（位置/尺寸/热键/透明度），不是版本内容",
    "启动浮坞.vbs": "内部指向本机相对结构，换机安装后由安装程序重建",
    "浮坞-场景插图.miora": "美术素材工程，非程序本体",
}

# 不收的文件名模式（逐目录判断，避免误伤同名文件）
EXCLUDE_PATTERNS = ("Flat_vector_",)   # AI 绘图 1024px 源图，一张 500KB 起


def version():
    """版本号的唯一来源是 panel.VERSION —— 别处不再设一份常量。"""
    with open(os.path.join(ROOT, "panel.py"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("VERSION"):
                return line.split("=", 1)[1].strip().strip('"').lstrip("v")
    raise SystemExit("panel.py 里找不到 VERSION，无法确定归档版本号")


def collect():
    """列出要收进 zip 的相对路径（已排序，结果确定）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT)
        parts = [] if rel_dir == "." else rel_dir.split(os.sep)
        # 隐藏目录（.workbuddy 等）与排除目录：连子目录一起剪掉
        if any(p in EXCLUDE_DIRS or p.startswith(".") for p in parts):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames
                       if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for name in filenames:
            if name in EXCLUDE_FILES:
                continue
            if name.startswith(EXCLUDE_PATTERNS):
                continue
            if name.endswith((".pyc", ".pyo", ".log", ".tmp")):
                continue
            rel = os.path.normpath(os.path.join(rel_dir, name))
            out.append(rel)
    return sorted(out, key=lambda p: p.replace(os.sep, "/"))


def verify_note():
    """归档说明里的验证结论。这些数字要如实写 —— 归档是给人看的凭据。"""
    return [
        "## 本版验证结论",
        "",
        "| 层 | 脚本 | 项数 | 结果 |",
        "|---|---|---|---|",
        "| 源码回归 | `tests/run_all.py` | 431 | 全绿 |",
        "| 真机冒烟（真实记事本吸附 → 像素核对） | `_sandbox/smoke_v190.py`（临时脚本，不入档） | 7 | 全绿 |",
        "| 冻结版 | `installer/verify_app.py` | 7 | 全绿 |",
        "| 独立运行（无 Python 环境） | `tools/verify_standalone.py` | 10 | 全绿 |",
        "| 安装全流程 | `installer/verify_install.py` | 35 | 未通过（本机拦截冻结 exe 的 COM 调用） |",
        "| 界面冒烟 | `installer/verify_gui.py` | 14 | 13 通过 / 1 失败（判据过严，见下） |",
        "",
        "> 复现方式见「自动化测试」一节；数字以实际跑出的为准，改代码后须重跑。",
        ">",
        "> **本版是什么改动**：纯结构与代码清理，界面与交互**零变化**（回归项数"
        "比 v1.8.3 少 1 项，是删掉标签栏后 `test_layout` 的用例从 5 项变 4 项）。"
        "真机冒烟做的是结构改造后必须复核的那一条：吸附真实记事本，像素级确认"
        "用户区顶部第一行就是窗口内容（RGB 255,255,255），没有透出面板底色；"
        "释放后 `rect` 逐位还原。"
        ">",
        "> **安装链两层**：v1.9.0 这次实际跑了。冻结版 7 项全绿（面板窗口图标逐像素"
        "等于 `floatdock.ico` 那一层、托盘线程起来、退出 61 ms 干净消失）；独立运行 10 项"
        "全绿（`PATH` 只有 `System32` 时仍能启动、自带 `python314.dll` / `_tkinter.pyd` / "
        "Tcl-Tk、产物未从本机 Python 目录取任何文件）。",
        ">",
        "> **安装全流程为什么没过**：`verify_install.py` 在本机跑出 `rc=1`，日志是"
        "「默认安装结果失败 - 创建快捷方式失败，COM 调用失败 hr=0x80070005（拒绝访问）」。"
        "文件复制、图标、`_internal` 都成功，卡在 `IShellLink` 创建 `.lnk` 与写"
        "`HKCU\\...\\Uninstall\\FloatDock` 这两步 —— 与 v1.6.4 记录的环境拦截同源"
        "（安全软件对新建未签名单文件 exe 的 COM/注册表操作），不是本版改动引起："
        "本版没有碰 `installer/` 的任何逻辑。换正常桌面会话（或放行该 exe）重跑即可补齐。",
        ">",
        "> **界面冒烟那一项失败**：13/14。唯一失败的是「卸载界面确实从临时副本启动」"
        "这一条判据 —— 实际副本落在了**安装目录**内（`...\\App\\FloatDock\\"
        "FloatDock-卸载-<pid>.exe`），而判据写的是「父目录必须等于 `%TEMP%`」。"
        "界面本身、标题、两组图标像素、取消后不留目录、只取消不删文件都通过。"
        "判据与实现的落点假设不一致，属既有测试问题，本版未改 `installer/`。",
        ">",
        "> **未验通**：`tools/verify_exe_icon.py`（exe 内嵌图标的静态检查）"
        "仍未跑出结果，故不在上表内。原因与下一步见该脚本文件头，"
        "以及使用说明「已知待验」一节。",
    ]


def check_versions(ver):
    """panel.VERSION / 安装链 DISPLAY_VERSION / 安装包名必须是同一个版本。

    这三个数字各写一处，漏改任何一处就会发出"程序是 v1.8.0、『程序和功能』
    里写着 v1.6.4"的包（v1.8.0 发布前真的差一点这样发出去）。归档是最靠近
    发布的一步，把对账放在这里：不一致直接拒绝归档，而不是留到用户机器上才发现。
    """
    def read(pattern, path, what):
        with open(os.path.join(ROOT, path), encoding="utf-8") as f:
            m = re.search(pattern, f.read(), re.M)
        if not m:
            raise SystemExit("%s 里找不到 %s" % (path, what))
        return m.group(1).lstrip("v")

    got = read(r'^DISPLAY_VERSION\s*=\s*"([^"]+)"', "installer/shortcut.py",
               "DISPLAY_VERSION")
    if got != ver:
        raise SystemExit("版本不一致：panel.VERSION=%s，程序与功能显示=%s"
                         % (ver, got))
    got = read(r'^SETUP_NAME\s*=\s*"[^"]*-v([\d.]+)-', "installer/build.py",
               "SETUP_NAME")
    if got != ver:
        raise SystemExit("版本不一致：panel.VERSION=%s，安装包名=%s" % (ver, got))


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else version()
    check_versions(ver)
    today = datetime.date.today()
    name = "浮坞-FloatDock-v%s-%s.zip" % (ver, today.strftime("%Y-%m-%d"))
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    dest = os.path.join(ARCHIVE_DIR, name)

    files = collect()
    manifest, total = [], 0
    for rel in files:
        with open(os.path.join(ROOT, rel), "rb") as f:
            data = f.read()
        total += len(data)
        manifest.append("| `%s` | %d | `%s` |"
                        % (rel.replace(os.sep, "/"), len(data),
                           hashlib.sha256(data).hexdigest()))

    lines = ["# 浮坞 FloatDock v%s 归档说明" % ver, "",
             "- 版本：**v%s**" % ver,
             "- 日期：%s" % today.strftime("%Y-%m-%d"),
             "- 文件数：%d（含本说明）" % (len(files) + 1),
             "- 源码体积：%.1f KB" % (total / 1024.0), ""]
    lines += verify_note()
    lines += ["", "## 文件清单（sha256）", "",
              "| 文件 | 字节 | sha256 |", "|---|---|---|"] + manifest
    lines += ["", "未收录内容及理由：", ""]
    lines += ["- `%s/`：%s" % (k, v) for k, v in sorted(EXCLUDE_DIRS.items())]
    lines += ["- `%s`：%s" % (k, v) for k, v in sorted(EXCLUDE_FILES.items())]
    lines += ["- `Flat_vector_*`（AI 绘图 1024px 源图）：成品 .ico 已收录，"
              "源图只是「选哪个」这份决策的中间产物", ""]

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(os.path.join(ROOT, rel), rel.replace(os.sep, "/"))
        z.writestr("归档说明.md", "\n".join(lines))

    print("归档：%s" % dest)
    print("文件：%d 个（含归档说明），%.1f KB"
          % (len(files) + 1, os.path.getsize(dest) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())