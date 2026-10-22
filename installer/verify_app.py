# -*- coding: utf-8 -*-
"""验证打包出来的 FloatDock.exe —— 免 Python 的冻结版本是否与源码版等价。

    python installer/verify_app.py [FloatDock.exe 路径]

检查项（都用外部可观测的系统状态判定，不看日志自述）：
  1. 进程能起来，并建出面板窗口
  2. 面板窗口的图标像素 == floatdock.ico 里那一层（证明 frozen 后
     appicon.PATH 仍然指向随包带走的图标，而不是回退成系统默认图标）
  3. 托盘线程也起来了（辅助窗口存在）
  4. 标题栏上真的画出了图标位图（按窗口自身取像素，找图标底色/琥珀像素）
  5. WM_CLOSE 退出后进程干净消失，不留后台

不动用户那份 config.json：全程用临时配置文件与 --allow-multiple。
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
sys.path.insert(0, ROOT)

import harness as H                               # noqa: E402
import theme as T                                 # noqa: E402
import winapi                                     # noqa: E402
import wndutil                                    # noqa: E402

winapi.enable_dpi_awareness()
SM_CXICON, SM_CYICON = 11, 12

results = []


def ck(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s%s" % ("OK" if ok else "FAIL", name,
                         ("   " + str(detail)) if detail else ""), flush=True)


def main():
    exe = (sys.argv[1] if len(sys.argv) > 1
           else os.path.join(ROOT, "发布", "_build", "dist", "FloatDock",
                             "FloatDock.exe"))
    ico = os.path.join(ROOT, "floatdock.ico")
    print("被测程序:", exe)
    ck("FloatDock.exe 存在", os.path.exists(exe), exe)
    if not os.path.exists(exe):
        return 1

    # ---- exe 文件里嵌的图标（资源管理器里那个文件长什么样）----
    # 与下面那两项的区别：它们只证明"程序自己会 LoadImage"，
    # 证明不了"编译期把图标嵌进 exe 了"。这条链要静态读 PE 资源，
    # 但实现尚未在真实环境验证过（见 tools/verify_exe_icon.py），
    # 所以这里只提示不判定 —— 发布链路上不能挂一个会误报的红灯。
    print("    提示：exe 内嵌图标的静态检查请单独跑 tools/verify_exe_icon.py"
          "（本项尚未验证，不计入判定）")

    big = H.u32.GetSystemMetrics(SM_CXICON)
    h = H.load_icon_from(ico, big)
    base = H.icon_pixels(h)
    H.u32.DestroyIcon(h)

    tmp = tempfile.mkdtemp(prefix="fd_frozen_")
    cfg = os.path.join(tmp, "config.json")
    # locked=true 让它常显：面板默认"鼠标移开 0.05 秒就隐藏"，等待期间会自己藏起来
    # 导致截屏什么都取不到（这不是缺陷，是设计）。
    with open(cfg, "w", encoding="utf-8") as f:
        f.write('{"x": 200, "y": 160, "w": 470, "h": 620, "locked": true,'
                ' "hotkey": {"ctrl": false, "alt": false, "shift": false,'
                ' "win": false, "key": "F13"}}')
    proc = subprocess.Popen([exe, "--config", cfg, "--debug",
                             "--allow-multiple"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        panel = H.find_panel(proc.pid, 25.0)
        ck("冻结版能启动并建出面板窗口", bool(panel),
           "hwnd=%s 用时 %.1fs" % (panel, time.time() - t0))
        if not panel:
            return 1

        # 面板是"先建窗、后补图标"，拿到句柄时图标可能还没挂上 —— 等它生效
        waited = H.wait_expr(
            lambda: H.icon_fingerprint(panel, True) == base, 10.0)
        got = H.icon_fingerprint(panel, True)
        ck("面板窗口图标 == floatdock.ico 的那一层（逐像素）", waited is not None,
           ("%.0f ms 后一致" % (waited * 1000)) if waited
           else "超时，实际=%s 基准=%s" % (got[2][:16] if got else None,
                                        base[2][:16] if base else None))

        aux = H.find_aux(proc.pid, 8.0)
        ck("托盘/热键线程已起（辅助窗口存在）", bool(aux), aux)

        # 标题栏位图：等首帧画完，按窗口自身取像素（PrintWindow，不依赖抓屏
        # —— 沙箱/非交互会话里 ImageGrab 直接 "screen grab failed"），再在
        # 标题栏区域找图标里的琥珀色像素
        try:
            from ctypes import wintypes as wtx
            from PIL import Image
            time.sleep(1.5)                        # 首帧含中文字体预热
            _x, _y, w, h = wndutil.win_rect(panel)
            wbar, hbar = min(w, 300), min(T.H_TITLE, h)
            u = H.u32
            g = H.gdi
            hdc = u.GetWindowDC(panel)
            mdc = g.CreateCompatibleDC(hdc)
            bmp = g.CreateCompatibleBitmap(hdc, wbar, hbar)
            old = g.SelectObject(mdc, bmp)
            try:
                u.PrintWindow(panel, mdc, 2)       # PW_RENDERFULLCONTENT

                class BMIH(ctypes.Structure):
                    _fields_ = [("biSize", wtx.DWORD),
                                ("biWidth", ctypes.c_long),
                                ("biHeight", ctypes.c_long),
                                ("biPlanes", wtx.WORD),
                                ("biBitCount", wtx.WORD),
                                ("biCompression", wtx.DWORD),
                                ("biSizeImage", wtx.DWORD),
                                ("biXPelsPerMeter", ctypes.c_long),
                                ("biYPelsPerMeter", ctypes.c_long),
                                ("biClrUsed", wtx.DWORD),
                                ("biClrImportant", wtx.DWORD)]

                bi = BMIH()
                bi.biSize = ctypes.sizeof(BMIH)
                bi.biWidth, bi.biHeight = wbar, -hbar
                bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
                buf = ctypes.create_string_buffer(wbar * hbar * 4)
                g.GetDIBits(mdc, bmp, 0, hbar, buf, ctypes.byref(bi), 0)
            finally:
                g.SelectObject(mdc, old)
                g.DeleteObject(bmp)
                g.DeleteDC(mdc)
                u.ReleaseDC(panel, hdc)
            img = Image.frombuffer("RGBA", (wbar, hbar), buf,
                                   "raw", "BGRA", 0, 1).convert("RGB")
            warm = sum(1 for r, g2, b in img.getdata()
                       if r > 150 and 90 < g2 < 220 and b < 150)
            ck("自绘标题栏画出了图标位图（取样到琥珀像素）", warm >= 12,
               "暖色像素 %d 个" % warm)
        except ImportError as e:                   # 确实没装 Pillow 才跳过
            ck("标题栏位图取样（无 Pillow，跳过）", True, str(e)[:60])
        except Exception as e:                     # 其它失败是真的失败，别吞掉
            ck("自绘标题栏画出了图标位图（取样到琥珀像素）", False,
               "%s: %s" % (type(e).__name__, str(e)[:80]))

        # 退出：投 WM_CLOSE（不用物理鼠标，免得打扰正在用电脑的人）
        H.u32.PostMessageW(panel, 0x0010, 0, 0)     # WM_CLOSE
        gone = H.wait_expr(lambda: proc.poll() is not None, 10.0)
        ck("关闭后进程干净退出", gone is not None,
           "%.0f ms" % (gone * 1000) if gone else "10 秒未退出")
        if gone is None:
            proc.terminate()
        time.sleep(0.5)
        ck("退出后窗口已销毁（IsWindow = 0）",
           not H.u32.IsWindow(panel))
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        for name in os.listdir(tmp):
            try:
                os.remove(os.path.join(tmp, name))
            except OSError:
                pass
        os.rmdir(tmp)

    bad = results.count(False)
    print("\n冻结版验证：%d 项通过，%d 项失败" % (len(results) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
