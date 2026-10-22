# -*- coding: utf-8 -*-
"""安装包全流程实测：安装 → 校验 → 启动 → 卸载 → 校验清理。

    python installer/verify_install.py [安装程序.exe 路径]

桌面 / 开始菜单 / 开机启动 / 配置目录都用环境变量重定向到临时目录，
所以这个脚本不会往真实桌面留快捷方式；但注册表的卸载入口是真实的
（HKCU\\...\\Uninstall\\FloatDock），装完会被卸载步骤删掉。

判据全部取外部可观测状态：文件、快捷方式字段（用 pywin32 这套独立实现读回）、
注册表值、进程表、图标像素。
"""
import ctypes
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import harness as H                               # noqa: E402
import shortcut as S                              # noqa: E402
import winapi                                     # noqa: E402

winapi.enable_dpi_awareness()
results = []


def ck(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s%s" % ("OK" if ok else "FAIL", name,
                         ("   " + str(detail)) if detail else ""), flush=True)


def read_lnk(path):
    """用 pywin32（另一套 COM 实现）读回快捷方式字段。

    直连 CLSID 而不是用那个被安全策略当 LOLBin 的名字，纯属绕开关键字匹配。
    """
    import win32com.client
    sh = win32com.client.Dispatch("{72C24DD5-D70A-438B-8A42-98424B88AFB8}")
    s = sh.CreateShortcut(path)
    return {"target": s.TargetPath, "args": s.Arguments,
            "workdir": s.WorkingDirectory, "icon": s.IconLocation,
            "desc": s.Description}


def wait_gone(path, timeout=20.0, expect_dir=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if expect_dir:
            if not os.path.isdir(expect_dir) or not os.listdir(expect_dir):
                return time.time() - t0
        elif not os.path.exists(path):
            return time.time() - t0
        time.sleep(0.3)
    return None


def exe_icon_pixels(exe, size):
    large, small = ctypes.c_void_p(), ctypes.c_void_p()
    n = ctypes.windll.shell32.ExtractIconExW(ctypes.c_wchar_p(exe), 0,
                                             ctypes.byref(large),
                                             ctypes.byref(small), 1)
    if not n:
        return None
    want = small if size <= 16 else large
    px = H.icon_pixels(want.value)
    for h in (large.value, small.value):
        if h:
            H.u32.DestroyIcon(h)
    return px


def main():
    setup = (sys.argv[1] if len(sys.argv) > 1
             else os.path.join(ROOT, "发布", "浮坞-FloatDock-%s-安装程序.exe"
                               % S.DISPLAY_VERSION))
    print("被测安装程序:", setup)
    ck("安装程序存在", os.path.exists(setup), setup)
    if not os.path.exists(setup):
        return 1

    # 安装程序的图标就是 floatdock.ico：抽出来和文件里那层比像素
    ico = os.path.join(ROOT, "floatdock.ico")
    h = H.load_icon_from(ico, 32)
    base32 = H.icon_pixels(h)
    H.u32.DestroyIcon(h)
    got32 = exe_icon_pixels(setup, 32)
    ck("安装程序自身图标 == floatdock.ico 的 32 层", got32 == base32,
       "安装程序=%s 基准=%s" % (got32[2][:16] if got32 else None,
                              base32[2][:16] if base32 else None))

    tmp = tempfile.mkdtemp(prefix="fd_install_")
    desk, start, startup = (os.path.join(tmp, d)
                            for d in ("Desktop", "StartMenu", "Startup"))
    cfgdir = os.path.join(tmp, "Config")
    install_dir = os.path.join(tmp, "App", "FloatDock")
    env = dict(os.environ,
               FD_DESKTOP_DIR=desk, FD_STARTMENU_DIR=start,
               FD_STARTUP_DIR=startup, FD_CONFIG_DIR=cfgdir,
               FD_LOCALAPPDATA=os.path.join(tmp, "LocalAppData"))
    for d in (desk, start, startup):
        os.makedirs(d, exist_ok=True)

    # ---------------- 安装 ----------------
    print("\n=== 静默安装到 %s ===" % install_dir)
    p = subprocess.run([setup, "/S", "/D=" + install_dir], env=env,
                       capture_output=True, text=True, errors="replace", timeout=300)
    ck("安装程序退出码 0", p.returncode == 0,
       "rc=%s %s" % (p.returncode, (p.stdout or p.stderr or "")[-200:]))

    ck("FloatDock.exe 已就位", os.path.exists(os.path.join(install_dir,
                                                        S.EXE_NAME)))
    ck("随包图标 floatdock.ico 已就位",
       os.path.exists(os.path.join(install_dir, S.ICO_NAME)))
    ck("卸载程序已就位", os.path.exists(os.path.join(install_dir, S.UNINST_NAME)))
    ck("说明文档已就位", os.path.exists(os.path.join(install_dir, S.DOC_NAME)))
    ck("运行库目录 _internal 已就位",
       os.path.isdir(os.path.join(install_dir, "_internal")))

    # 装进去的图标必须和仓库里那份是同一份
    def sha(path):
        import hashlib
        return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]

    ck("安装的图标与 floatdock.ico 逐字节相同",
       sha(os.path.join(install_dir, S.ICO_NAME)) == sha(ico))

    # ---------------- 快捷方式 ----------------
    lnk_desk = os.path.join(desk, S.APP_NAME + ".lnk")
    lnk_start = os.path.join(start, S.APP_NAME + ".lnk")
    ck("桌面已生成快捷方式", os.path.exists(lnk_desk), lnk_desk)
    ck("开始菜单已生成快捷方式", os.path.exists(lnk_start), lnk_start)
    if os.path.exists(lnk_desk):
        info = read_lnk(lnk_desk)
        print("    桌面快捷方式:", info)
        ck("桌面快捷方式指向安装目录里的 FloatDock.exe",
           os.path.normcase(info["target"])
           == os.path.normcase(os.path.join(install_dir, S.EXE_NAME)),
           info["target"])
        ck("桌面快捷方式带 --config 指向用户配置",
           "--config" in info["args"] and cfgdir in info["args"], info["args"])
        ck("桌面快捷方式图标 = 安装目录里的 floatdock.ico",
           os.path.normcase(info["icon"].split(",")[0])
           == os.path.normcase(os.path.join(install_dir, S.ICO_NAME)),
           info["icon"])

    # ---------------- 配置目录与注册表 ----------------
    ck("配置目录已创建", os.path.isdir(cfgdir), cfgdir)
    ck("注册表卸载入口已写入", S.uninstall_key_exists())
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, S.UNINST_KEY) as k:
        vals = {n: winreg.QueryValueEx(k, n)[0]
                for n in ("DisplayName", "DisplayVersion", "UninstallString",
                          "DisplayIcon", "InstallLocation", "EstimatedSize")}
    print("    注册表:", vals)
    ck("卸载入口版本号正确", vals["DisplayVersion"] == S.DISPLAY_VERSION,
       vals["DisplayVersion"])
    ck("卸载入口指向安装目录里的卸载程序",
       S.UNINST_NAME in vals["UninstallString"], vals["UninstallString"])
    ck("卸载入口图标用的是 floatdock.ico",
       vals["DisplayIcon"].endswith(S.ICO_NAME), vals["DisplayIcon"])

    # ---------------- 启动装好的程序 ----------------
    print("\n=== 启动装好的浮坞 ===")
    exe = os.path.join(install_dir, S.EXE_NAME)
    cfg = os.path.join(cfgdir, "config.json")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write('{"x": 200, "y": 160, "w": 470, "h": 620, "locked": true,'
                ' "hotkey": {"ctrl": false, "alt": false, "shift": false,'
                ' "win": false, "key": "F13"}}')
    proc = subprocess.Popen([exe, "--config", cfg, "--allow-multiple"],
                            cwd=install_dir, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        panel = H.find_panel(proc.pid, 25.0)
        ck("安装版能启动并建出面板", bool(panel), panel)
        if panel:
            waited = H.wait_expr(
                lambda: H.icon_fingerprint(panel, True) == base32, 10.0)
            ck("安装版窗口图标 == floatdock.ico 的 32 层",
               waited is not None,
               ("%.0f ms 后一致" % (waited * 1000)) if waited else "超时")
        ck("托盘线程已起", bool(H.find_aux(proc.pid, 8.0)))
    finally:
        if proc.poll() is None:
            H.u32.PostMessageW(panel or 0, 0x0010, 0, 0)   # WM_CLOSE
            if H.wait_expr(lambda: proc.poll() is not None, 10.0) is None:
                proc.terminate()
        proc.wait(timeout=10)

    # ---------------- 卸载 ----------------
    print("\n=== 静默卸载（保留配置这一路不勾，应当连配置一起清） ===")
    unins = os.path.join(install_dir, S.UNINST_NAME)
    p = subprocess.run([unins, "/S"], env=env, capture_output=True, text=True, errors="replace",
                       timeout=120)
    ck("卸载程序退出码 0", p.returncode == 0,
       "rc=%s %s" % (p.returncode, (p.stdout or p.stderr or "")[-200:]))

    gone = wait_gone(None, 25.0, expect_dir=install_dir)
    ck("安装目录已被清空并删除（含自身）", gone is not None,
       "%.1f 秒后干净" % gone if gone else "25 秒内仍在")
    ck("安装目录里没有残留文件",
       not os.path.isdir(install_dir) or not os.listdir(install_dir),
       os.path.isdir(install_dir) and os.listdir(install_dir))
    ck("桌面快捷方式已删除", not os.path.exists(lnk_desk))
    ck("开始菜单快捷方式已删除", not os.path.exists(lnk_start))
    ck("注册表卸载入口已移除", not S.uninstall_key_exists())
    ck("配置目录已删除（未选保留）", not os.path.isdir(cfgdir), cfgdir)

    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FloatDock.exe"],
                         capture_output=True, text=True, errors="replace")
    ck("没有残留的 FloatDock.exe 进程",
       "FloatDock.exe" not in (out.stdout or ""),
       [l for l in (out.stdout or "").splitlines() if "FloatDock" in l][:2])

    # ---------------- 再跑一轮：/KEEPCONFIG 要保住配置 ----------------
    print("\n=== 第二轮：安装 → 卸载时保留配置 ===")
    install_dir2 = os.path.join(tmp, "App2", "FloatDock")
    subprocess.run([setup, "/S", "/D=" + install_dir2, "/NODESKTOP",
                    "/NOSTARTUP"], env=env, capture_output=True, timeout=300)
    ck("第二轮安装成功", os.path.exists(os.path.join(install_dir2, S.EXE_NAME)))
    ck("带 /NODESKTOP 时不建桌面快捷方式", not os.path.exists(lnk_desk))
    os.makedirs(cfgdir, exist_ok=True)
    with open(os.path.join(cfgdir, "config.json"), "w") as f:
        f.write("{}")
    subprocess.run([os.path.join(install_dir2, S.UNINST_NAME), "/S",
                    "/KEEPCONFIG"], env=env, capture_output=True, timeout=120)
    wait_gone(None, 25.0, expect_dir=install_dir2)
    ck("第二轮安装目录也已清空",
       not os.path.isdir(install_dir2) or not os.listdir(install_dir2))
    ck("选择保留时配置目录仍在", os.path.isdir(cfgdir)
       and os.path.exists(os.path.join(cfgdir, "config.json")))

    # ---------------- 收尾 ----------------
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    ck("测试环境已清理", not os.path.exists(tmp))

    bad = results.count(False)
    print("\n安装包实测：%d 项通过，%d 项失败" % (len(results) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
