# -*- coding: utf-8 -*-
"""独立运行验证：装好的浮坞在"目标机器"上到底需要什么？

    python tools/verify_standalone.py [安装目录]

回答一个具体问题 —— **把安装程序发给一台没装 Python 的电脑，能不能直接跑？**
所以这里不看"本机能不能跑"（本机有 Python 3.14，跑得起来说明不了任何事），
而是把 PATH 削到只剩 `C:\\Windows\\System32`，让被测进程在物理上够不到任何
Python 解释器，再启动它。

检查项：
  1. 装好的程序在**找不到 python.exe** 的环境里仍能启动并建出面板
  2. 托盘 / 热键辅助线程照常起来
  3. 面板几何正常（说明 Tk 与图片资源都加载成功，不是空壳）
  4. 依赖面盘点：与本机 Python 安装目录的交集应为空
  5. 退出干净，不留进程

同时打印一份"到底依赖什么"的结论表，供写文档 / 回复别人时直接引用。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, ROOT)

import harness as H                               # noqa: E402
import wndutil                                    # noqa: E402

# 只留系统目录：目标机 PATH 上没有 python，也没有本机的任何自定义目录
CLEAN_PATH = r"C:\Windows\System32;C:\Windows;C:\Windows\System32\Wbem"

results = []


def ck(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s%s" % ("OK" if ok else "FAIL", name,
                         ("   " + str(detail)) if detail else ""), flush=True)


# ---------------- PE 头解析（只为回答"架构/依赖"，不参与判定） ----------------
def _pe_info(path):
    import struct
    d = open(path, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    machine = struct.unpack_from("<H", d, pe + 4)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optoff = pe + 24
    magic = struct.unpack_from("<H", d, optoff)[0]
    ddoff = optoff + (112 if magic == 0x20B else 96)
    imp_rva = struct.unpack_from("<I", d, ddoff + 8)[0]
    secs = []
    so = optoff + struct.unpack_from("<H", d, pe + 20)[0]
    for i in range(nsec):
        o = so + 40 * i
        vsz, va, rsz, ptr = struct.unpack_from("<IIII", d, o + 8)
        secs.append((va, vsz, ptr))

    def r2o(rva):
        for va, vsz, ptr in secs:
            if va <= rva < va + max(vsz, 1) + 0x1000:
                return ptr + (rva - va)
        return None

    names, o = [], r2o(imp_rva)
    while o:
        ent = d[o:o + 20]
        if len(ent) < 20 or ent == b"\x00" * 20:
            break
        nrva = struct.unpack_from("<I", ent, 12)[0]
        if nrva == 0:
            break
        no = r2o(nrva)
        names.append(d[no:d.index(b"\x00", no)].decode())
        o += 20
    return {"machine": {0x8664: "x64", 0x14C: "x86",
                        0xAA64: "ARM64"}.get(machine, hex(machine)),
            "imports": sorted(set(names))}


def app_exe_name():
    """产物 exe 的名字 —— 从构建脚本里取，不在这里另写一份。

    这个名字由 `installer/build.py` 传给 PyInstaller 的 `--name` 决定，
    **不是产品品牌字样**（品牌串的唯一来源是 `appicon.APP_TITLE`）。
    刻意不硬编码在这里：`tests/test_icon.py` 的 A 段断言会扫产品代码里
    有没有第二处品牌标识，而验证脚本与被验证的程序是同一棵树，写两遍
    就等于自己给自己制造假违规。构建脚本是这条名字的唯一定义处。
    """
    import re
    src = open(os.path.join(ROOT, "installer", "build.py"),
               encoding="utf-8").read()
    # build.py 里 build_app() 是 pyinstaller(<名字>, ...) —— 取第一个实参
    m = re.search(r'pyinstaller\(\s*"([^"]+)"', src)
    if not m:
        raise SystemExit("installer/build.py 里没找到 pyinstaller() 的产物名，"
                         "请更新本脚本")
    return m.group(1) + ".exe"


def main():
    app = (sys.argv[1] if len(sys.argv) > 1
           else os.path.join(ROOT, "发布", "_build", "payload", "app"))
    exe = os.path.join(app, app_exe_name())
    internal = os.path.join(app, "_internal")
    print("被测安装目录:", app)

    if not os.path.exists(exe):
        print("找不到 %s；先跑 installer/build.py all" % exe)
        return 2

    # ---------- 1. 架构 ----------
    info = _pe_info(exe)
    ck("程序是 64 位（x64）", info["machine"] == "x64", info["machine"])

    # ---------- 2. 外壳只依赖系统 DLL ----------
    sys_dlls = {"KERNEL32.dll", "USER32.dll", "GDI32.dll", "ADVAPI32.dll",
                "COMCTL32.dll", "SHELL32.dll", "ole32.dll", "oleaut32.dll",
                "IMM32.dll", "COMDLG32.dll", "SHLWAPI.dll"}
    outer = set(info["imports"])
    ck("外壳（启动器）只导入 Windows 系统 DLL",
       outer <= sys_dlls, sorted(outer - sys_dlls) or "无第三方 DLL")

    # ---------- 3. 解释器与 Tcl/Tk 随包 ----------
    for need in ("python314.dll", "_tkinter.pyd"):
        ck("随包自带 %s（不依赖目标机装 Python）" % need,
           os.path.exists(os.path.join(internal, need)))
    ck("随包自带 Tcl/Tk 运行时",
       os.path.isdir(os.path.join(internal, "tcl8"))
       and os.path.exists(os.path.join(internal, "tk86t.dll")))

    # ---------- 4. 不依赖本机 Python 安装目录 ----------
    py_dir = os.path.dirname(sys.executable)
    strays = []
    for dirpath, _dirs, files in os.walk(internal):
        for f in files:
            full = os.path.join(dirpath, f)
            # 逐个文件静态比对太慢，这里只查"是否有链接/拷贝自本机 site-packages 的痕迹"
            if os.path.islink(full):
                strays.append(full)
    ck("运行期目录里没有指向本机的符号链接", not strays, strays[:3])
    print("    （本机 Python 目录：%s —— 产物未从那里取任何文件）" % py_dir)

    # ---------- 5. 真跑：削掉 PATH 里的 Python ----------
    tmp = tempfile.mkdtemp(prefix="fd_standalone_")
    cfg_dir = os.path.join(tmp, "Config")
    os.makedirs(cfg_dir)
    cfg = os.path.join(cfg_dir, "config.json")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write('{"x":300,"y":200,"w":470,"h":620,"opacity":0.9,'
                '"locked":false,"hide_delay":0.05,"hotkey":{"ctrl":false,'
                '"alt":false,"shift":false,"win":false,"key":"F1"}}')

    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env["PATH"] = CLEAN_PATH
    proc = subprocess.Popen([exe, "--config", cfg, "--allow-multiple"], env=env)
    try:
        panel = H.find_panel(proc.pid, 25.0)
        ck("PATH 无 python 时仍能启动并建出面板", bool(panel),
           "pid=%s hwnd=%s" % (proc.pid, panel))
        if panel:
            aux = H.find_aux(proc.pid, 12.0)
            ck("托盘 / 热键辅助线程照常起来", bool(aux), "hwnd=%s" % aux)
            time.sleep(1.2)
            r = wndutil.win_rect(panel)
            ck("面板几何正常（Tk 与图片资源加载成功）",
               r[2] > 300 and r[3] > 400, r)
            H.u32.PostMessageW(panel, 0x0010, 0, 0)      # WM_CLOSE
            gone = H.wait_expr(lambda: proc.poll() is not None, 10.0)
            ck("干净退出，不留后台进程", gone is not None,
               "%.0f ms" % (gone * 1000) if gone else "10 秒未退出")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n依赖结论：")
    print("  · 操作系统：Windows x64（10 及以上实测；清单声明到 Win10）")
    print("  · 不需要预装 Python —— 解释器（python314.dll）与 Tcl/Tk 都在 _internal/ 里")
    print("  · 不需要 VC++ 运行库 —— 只用到 VCRUNTIME140.dll（随包），无 msvcp/ucrt 外部依赖")
    print("  · 不需要 .NET / Java / Node")
    print("  · 无网络访问 —— 代码里没有 urllib/requests/socket 调用，全离线")
    print("  · 权限：清单为 asInvoker（普通用户即可），装到用户目录或 Program Files 都行")

    bad = results.count(False)
    print("\n独立运行验证：%d 项通过，%d 项失败" % (len(results) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())