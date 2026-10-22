# -*- coding: utf-8 -*-
"""图形安装/卸载界面的冒烟测试：真起窗口、真截图，然后取消退出。

这一层不做安装动作，只确认"用户双击后会看到什么"：窗口能出来、
标题/文案/控件在位、图标是 floatdock.ico。截图存到 发布/_build/gui-*.png。
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
import wndutil                                    # noqa: E402

winapi.enable_dpi_awareness()
OUT = os.path.join(ROOT, "发布", "_build")
ICO = os.path.join(ROOT, "floatdock.ico")
results = []


def ck(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s%s" % ("OK" if ok else "FAIL", name,
                         ("   " + str(detail)) if detail else ""), flush=True)


def _base_icon(size):
    """基准：把 floatdock.ico 按指定尺寸载入后的像素指纹。"""
    h = H.load_icon_from(ICO, size)
    px = H.icon_pixels(h)
    H.u32.DestroyIcon(h)
    return px


def check_icon(hwnd, name):
    """窗口大/小图标都应与 floatdock.ico 对应层逐像素一致。

    安装/卸载程序与主程序同走 appicon.apply：大图标取系统 SM_CXICON 尺寸，
    小图标取 SM_CXSMICON 尺寸，各能从文件里找到原像素那一层。
    """
    u32 = H.u32
    big = u32.GetSystemMetrics(11)          # SM_CXICON
    small = u32.GetSystemMetrics(49)        # SM_CXSMICON
    got_big = H.icon_fingerprint(hwnd, True)
    got_small = H.icon_fingerprint(hwnd, False)
    ck("%s：大图标 = floatdock.ico 的 %dpx 层" % (name, big),
       got_big == _base_icon(big),
       "实际 %s" % (got_big[2][:12] if got_big else "读不到"))
    ck("%s：小图标 = floatdock.ico 的 %dpx 层" % (name, small),
       got_small == _base_icon(small),
       "实际 %s" % (got_small[2][:12] if got_small else "读不到"))


def _running_exe(pid):
    """取某个进程的可执行文件完整路径（靠内核 API，不看命令行字符串）。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    PROCESS_QUERY_LIMITED = 0x1000
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        fn = k32.QueryFullProcessImageNameW
        fn.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                       ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        if fn(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        k32.CloseHandle(h)


def find_window(title_part, timeout=20.0):
    """按标题找一个 Tk 顶层窗口。

    不能用"按启动进程的 pid 找"：PyInstaller 单文件模式的父进程只负责解包，
    真正建窗口的是它拉起来的子进程，pid 不是同一个。
    """
    box = []

    def scan():
        for hwnd in H.enum_windows():
            if wndutil.win_class(hwnd) != "TkTopLevel":
                continue
            if title_part in wndutil.win_text(hwnd):
                box.append(hwnd)
                return True
        return False

    H.wait_expr(scan, timeout)          # 它只回时间，窗口得自己接出来
    return box[0] if box else None


def kill_tree(hwnd, popen):
    """关掉界面进程：先给窗口发 WM_CLOSE，再按窗口所属 pid 收尾。"""
    pid = wndutil.window_pid(hwnd) if hwnd else 0
    if hwnd:
        H.u32.PostMessageW(hwnd, 0x0010, 0, 0)      # WM_CLOSE → 取消退出
    time.sleep(0.8)
    for target in {pid, popen.pid}:
        if target:
            subprocess.run(["taskkill", "/PID", str(target), "/F"],
                           capture_output=True)
    try:
        popen.wait(timeout=8)
    except Exception:
        pass


def shot(hwnd, path):
    """按窗口自身取像素（PrintWindow），不依赖"抓屏"。

    这一条是必需的：在无人值守/非当前会话里 ImageGrab 直接报 screen grab
    failed，而 PrintWindow 让窗口自己把界面画到我们给的内存位图上。
    """
    from ctypes import wintypes as wt
    from PIL import Image
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    g32 = ctypes.WinDLL("gdi32", use_last_error=True)

    r = wndutil.win_rect(hwnd)
    if not r:                                       # 返回的是 (x, y, w, h)
        raise OSError("窗口已失效")
    _x, _y, w, h = r
    if w <= 0 or h <= 0:
        raise OSError("窗口尺寸异常 %r" % (r,))

    hdc = u32.GetWindowDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    old = g32.SelectObject(mdc, bmp)
    try:
        u32.PrintWindow(hwnd, mdc, 2)               # PW_RENDERFULLCONTENT

        class BMIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wt.DWORD),
                        ("biClrImportant", wt.DWORD)]

        bi = BMIH()
        bi.biSize = ctypes.sizeof(BMIH)
        bi.biWidth = w
        bi.biHeight = -h                            # 负值 = 自上而下
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = 0                        # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
        img.convert("RGB").save(path)
    finally:
        g32.SelectObject(mdc, old)
        g32.DeleteObject(bmp)
        g32.DeleteDC(mdc)
        u32.ReleaseDC(hwnd, hdc)
    print("    截图:", os.path.basename(path), (w, h))


def safe_shot(hwnd, name):
    """截图 + 顺手看一眼它到底画没画东西（纯白一片说明界面没渲染）。"""
    path = os.path.join(OUT, name)
    try:
        shot(hwnd, path)
        from PIL import Image
        im = Image.open(path).convert("RGB")
        colors = len(set(im.getdata()))
        ck("%s 已渲染（不是空白）" % name, colors > 8, "%d 种颜色" % colors)
    except Exception as e:
        ck("%s 截图失败" % name, False, "%s: %s" % (type(e).__name__, e))


def title_of(hwnd):
    return wndutil.win_text(hwnd)


def main():
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="fd_gui_")
    env = dict(os.environ,
               FD_DESKTOP_DIR=os.path.join(tmp, "Desktop"),
               FD_STARTMENU_DIR=os.path.join(tmp, "StartMenu"),
               FD_STARTUP_DIR=os.path.join(tmp, "Startup"),
               FD_CONFIG_DIR=os.path.join(tmp, "Config"),
               FD_LOCALAPPDATA=os.path.join(tmp, "LocalAppData"))
    install_dir = os.path.join(tmp, "App", "FloatDock")

    # ---- 安装程序界面 ----
    setup = os.path.join(ROOT, "发布",
                         "浮坞-FloatDock-%s-安装程序.exe" % S.DISPLAY_VERSION)
    print("=== 安装程序界面 ===")
    p = subprocess.Popen([setup], env=env, cwd=tmp)
    hwnd = None
    try:
        hwnd = find_window("安装程序", 25.0)
        ck("安装界面已打开", bool(hwnd), "hwnd=%s" % hwnd)
        if hwnd:
            time.sleep(2.0)
            ck("标题正确", "安装程序" in title_of(hwnd), title_of(hwnd))
            safe_shot(hwnd, "gui-安装程序.png")
            check_icon(hwnd, "安装界面")
    finally:
        kill_tree(hwnd, p)
    time.sleep(1.0)
    ck("取消安装后没有留下任何目录",
       not os.path.exists(install_dir) and not os.path.exists(
           os.path.join(tmp, "Config")))

    # ---- 真的装一份，再验卸载界面 ----
    print("\n=== 先静默装一份，再看卸载界面 ===")
    subprocess.run([setup, "/S", "/D=" + install_dir], env=env,
                   capture_output=True, timeout=300)
    ck("已装到测试目录", os.path.exists(os.path.join(install_dir, S.EXE_NAME)))

    unins = os.path.join(install_dir, S.UNINST_NAME)
    p = subprocess.Popen([unins], env=env, cwd=install_dir)
    hwnd = None
    try:
        hwnd = find_window("卸载", 25.0)
        ck("卸载界面已打开", bool(hwnd), "hwnd=%s" % hwnd)
        if hwnd:
            time.sleep(2.0)
            ck("标题正确", "卸载" in title_of(hwnd), title_of(hwnd))
            safe_shot(hwnd, "gui-卸载程序.png")
            check_icon(hwnd, "卸载界面")
            # 界面是从临时副本起来的：说明自删除那条路走通了
            exe = _running_exe(wndutil.window_pid(hwnd))
            ck("卸载界面确实从临时副本启动（自删除链路生效）",
               exe and os.path.normcase(os.path.dirname(exe))
               == os.path.normcase(tempfile.gettempdir()),
               "pid=%s exe=%s" % (wndutil.window_pid(hwnd), exe))
    finally:
        kill_tree(hwnd, p)

    time.sleep(1.0)
    ck("只取消、没确认卸载时，程序文件仍在",
       os.path.exists(os.path.join(install_dir, S.EXE_NAME)))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    bad = results.count(False)
    print("\n界面冒烟：%d 项通过，%d 项失败" % (len(results) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
