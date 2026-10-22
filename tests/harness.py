# -*- coding: utf-8 -*-
"""测试共用工具：隔离启动、窗口查找、日志读取、消息级输入、断言。

两点说明：
1) 窗口枚举（EnumWindows）只有测试用得上，所以它住在测试侧；产品代码的
   winapi.py 只保留程序真正调用的那批绑定。
2) 测试实例一律用「独立 config.json + --allow-multiple」启动，因此可以和你
   正在用的浮坞并存，既不会碰你的配置，也不会被单实例检查挡住。

用法：用带 tkinter 的 Python 运行（本机为 C:\\Python314\\python.exe）。
"""
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import hotkey                                    # noqa: E402
import wndutil                                   # noqa: E402
from winapi import u32, HWND, LRESULT            # noqa: E402

APP = os.path.join(ROOT, "floatdock.pyw")
PY = sys.executable                              # 本测试进程自己（需有 tkinter）
USER_CFG = os.path.join(ROOT, "config.json")     # 用户自己那份配置，全程只读
ERR_HOTKEY_ALREADY_REGISTERED = 1409

# ---- 消息级输入用到的常量 ----
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_CLOSE, WM_COMMAND, WM_HOTKEY = 0x0010, 0x0111, 0x0312
EXTENDED_KEYS = {0xA3, 0xA5, 0x5B, 0x5C}         # 需带扩展位才能在 Tk 里区分左右

u32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM),
                            wt.LPARAM]
u32.EnumChildWindows.argtypes = [HWND, ctypes.c_void_p, wt.LPARAM]
u32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
u32.MapVirtualKeyW.restype = ctypes.c_uint
u32.PostMessageW.argtypes = [HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u32.RegisterHotKey.restype = wt.BOOL
u32.UnregisterHotKey.restype = wt.BOOL


# ================= 断言 =================
class Checker(object):
    """收集断言并统一汇报。"""

    def __init__(self, title):
        self.title = title
        self.passed, self.failed = [], []

    def ok(self, name, cond, detail=""):
        (self.passed if cond else self.failed).append(name)
        print("%s %s%s" % ("[OK]  " if cond else "[FAIL]", name,
                           ("   " + str(detail)) if detail else ""), flush=True)
        return bool(cond)

    def skip(self, name, why):
        print("[SKIP] %s   %s" % (name, why), flush=True)

    def report(self):
        print("\n%s：通过 %d 项，失败 %d 项"
              % (self.title, len(self.passed), len(self.failed)), flush=True)
        for name in self.failed:
            print("  - 失败：", name, flush=True)
        return 1 if self.failed else 0


# ================= 窗口 =================
def enum_windows():
    out = []
    proto = ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM)

    def cb(hwnd, _lparam):
        out.append(hwnd)
        return True

    u32.EnumWindows(proto(cb), 0)
    return out


def child_windows(hwnd):
    out = []
    proto = ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM)

    def cb(h, _lparam):
        out.append(h)
        return True

    u32.EnumChildWindows(hwnd, ctypes.cast(proto(cb), ctypes.c_void_p), 0)
    return out


def board_canvas(panel):
    """面板里真正接鼠标的那个画布窗口。

    Tk 的顶层窗口下面还有一层 wrapper（类名同为 TkChild），画布是 wrapper 的
    子窗口；EnumChildWindows 会把这两层一起列出来，直接取 kids[0] 会拿到
    wrapper —— 往它投鼠标消息，画布收不到，界面看起来"点了没反应"。
    所以这里按"父窗口不是面板"来挑真正的那一层。
    """
    kids = child_windows(panel)
    deep = [k for k in kids if u32.GetParent(k) != panel]
    if deep:
        return deep[-1]
    return kids[0] if kids else panel


def visible(hwnd):
    return bool(hwnd) and bool(u32.IsWindowVisible(hwnd))


def _top_levels(pid):
    return [h for h in enum_windows()
            if wndutil.window_pid(h) == pid and wndutil.root_of(h) == h]


def _wait(pred, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = pred()
        if found:
            return found
        time.sleep(0.15)
    return None


def find_panel(pid, timeout=15.0):
    """面板 = 该进程的 Tk 顶层窗口，标题是"浮坞 FloatDock"。"""
    def pred():
        for h in _top_levels(pid):
            title = wndutil.win_text(h)
            if wndutil.win_class(h) == "TkTopLevel" and "浮坞" in title \
                    and "设置" not in title:
                return h
        return None
    return _wait(pred, timeout)


def aux_class_name():
    """辅助窗口的类名 —— 向tray.py 要，别在这里另写一份。

    类名由 `tray.py` 用 `appicon.APP_TITLE + "AuxWnd"` 拼出来（品牌串只能
    出现在 appicon 一处）。测试若在这里写死字面量，就等于全项目多了一个
    品牌标识的定义点，而且产品一改名就静默失效 —— 所以宁可多一次 import。
    """
    import tray
    return tray.aux_class_name()


def find_aux(pid, timeout=8.0):
    """热键辅助窗口（类名向 tray.aux_class_name() 取，不写死）。"""
    want = aux_class_name()

    def pred():
        for h in enum_windows():
            if wndutil.window_pid(h) == pid and \
                    wndutil.win_class(h) == want:
                return h
        return None
    return _wait(pred, timeout)


def find_settings(pid, timeout=6.0):
    def pred():
        for h in _top_levels(pid):
            if visible(h) and "设置" in wndutil.win_text(h):
                return h
        return None
    return _wait(pred, timeout)


def find_popup_menu(pid):
    """系统菜单窗口（类名 #32768）是否属于该进程——用来判定托盘菜单已弹出。"""
    for h in enum_windows():
        if wndutil.window_pid(h) == pid and wndutil.win_class(h) == "#32768":
            return h
    return None


def wait_visible(hwnd, want, timeout=2.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if visible(hwnd) == want:
            return time.time() - t0
        time.sleep(0.02)
    return None


def wait_expr(pred, timeout=2.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return time.time() - t0
        time.sleep(0.02)
    return None


# ================= 图标读取（验证"全程序同一个图标文件"） =================
# 这一组只有测试用得上：产品代码从不读图标像素，所以绑定留在测试侧。
WM_GETICON = 0x007F
ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0, 1, 2
GCLP_HICON, GCLP_HICONSM = -14, -34

gdi = ctypes.WinDLL("gdi32", use_last_error=True)

# GDI 句柄（HDC/HBITMAP/HGDIOBJ）在 64 位 Windows 上是**指针宽**的，而 ctypes
# 对没声明 restype 的函数默认按 c_int（32 位有符号）解释返回值 —— 句柄值一旦
# 超过 2^31 就会在传参那一步炸 "OverflowError: int too long to convert"
# （v1.6.3 发布前 verify_app 就是这么失败的：标题栏取样必然崩）。
# 这几个是"按窗口自身取像素"要用的调用，成组补齐，别只补用到的那一个。
u32.GetWindowDC.argtypes = [HWND]
u32.GetWindowDC.restype = wt.HDC
u32.PrintWindow.argtypes = [HWND, wt.HDC, wt.UINT]
u32.PrintWindow.restype = wt.BOOL
gdi.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi.SelectObject.restype = wt.HGDIOBJ


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD),
                ("yHotspot", wt.DWORD), ("hbmMask", wt.HANDLE),
                ("hbmColor", wt.HANDLE)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                ("bmPlanes", wt.WORD), ("bmBitsPixel", wt.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


u32.SendMessageW.argtypes = [HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
u32.SendMessageW.restype = LRESULT
u32.GetDC.argtypes = [HWND]
u32.GetDC.restype = wt.HDC
u32.ReleaseDC.argtypes = [HWND, wt.HDC]
u32.ReleaseDC.restype = ctypes.c_int
u32.GetIconInfo.argtypes = [wt.HANDLE, ctypes.POINTER(ICONINFO)]   # user32，不是 gdi32
u32.GetIconInfo.restype = wt.BOOL
gdi.GetObjectW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p]
gdi.GetObjectW.restype = ctypes.c_int
gdi.GetDIBits.argtypes = [wt.HDC, wt.HANDLE, wt.UINT, wt.UINT, ctypes.c_void_p,
                          ctypes.c_void_p, wt.UINT]
gdi.GetDIBits.restype = ctypes.c_int
gdi.CreateCompatibleDC.argtypes = [wt.HDC]
gdi.CreateCompatibleDC.restype = wt.HDC
gdi.DeleteDC.argtypes = [wt.HDC]
gdi.DeleteDC.restype = wt.BOOL
gdi.DeleteObject.argtypes = [wt.HANDLE]
gdi.DeleteObject.restype = wt.BOOL


def window_icon(hwnd, big=True):
    """窗口当前实际使用的图标句柄。

    先问 WM_GETICON（Tk 的 iconbitmap 走的就是 WM_SETICON，能读到），
    读不到再退到窗口类的图标（GCLP_HICON），最后都没有就返回 None。
    """
    want = ICON_BIG if big else ICON_SMALL2
    hicon = u32.SendMessageW(hwnd, WM_GETICON, want, 0)
    if not hicon:
        hicon = u32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL, 0)
    if not hicon:
        hicon = u32.GetClassLongPtrW(hwnd, GCLP_HICON if big else GCLP_HICONSM)
    return hicon or None


def icon_pixels(hicon):
    """读一个 HICON 的像素，返回 (宽, 高, sha256)；读不到返回 None。

    走 GetIconInfo -> hbmColor -> GetDIBits 得到 32 位顶朝下的 DIB。
    GetIconInfo 返回的两个位图句柄是副本，必须自己 DeleteObject，
    否则每调用一次就漏两个 GDI 对象。
    """
    if not hicon:
        return None
    info = ICONINFO()
    if not u32.GetIconInfo(hicon, ctypes.byref(info)):
        return None
    hbm = info.hbmColor or info.hbmMask
    try:
        bm = BITMAP()
        if not gdi.GetObjectW(hbm, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            return None
        w, h = bm.bmWidth, bm.bmHeight
        hdc = u32.GetDC(None)
        mem = gdi.CreateCompatibleDC(hdc)
        bih = BITMAPINFOHEADER()
        bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bih.biWidth, bih.biHeight = w, -h       # 负高度 = 顶朝下
        bih.biPlanes, bih.biBitCount = 1, 32
        bih.biCompression = 0                   # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi.GetDIBits(mem, hbm, 0, h, buf, ctypes.byref(bih), 0)
        gdi.DeleteDC(mem)
        u32.ReleaseDC(None, hdc)
        if got != h:
            return None
        return w, h, hashlib.sha256(buf.raw).hexdigest()
    finally:
        if info.hbmColor:
            gdi.DeleteObject(info.hbmColor)
        if info.hbmMask:
            gdi.DeleteObject(info.hbmMask)


def load_icon_from(path, size=0):
    """从 .ico 文件载入图标句柄（size=0 走 LoadImage 默认尺寸）。

    用来给"某处显示的图标是否出自这个文件"提供基准：
    载入同一个文件的同一尺寸，像素应当一模一样。
    """
    hicon = u32.LoadImageW(None, path, 1, size, size, 0x10)   # IMAGE_ICON|LR_LOADFROMFILE
    return hicon or None


def icon_fingerprint(hwnd, big=True):
    """窗口图标的 (宽, 高, 哈希)。"""
    return icon_pixels(window_icon(hwnd, big))


# ================= 消息级输入（沙箱可用） =================
def post_key(hwnd, vk, hold=False):
    """把按键消息投递给窗口：走真实的 Win32 消息 -> Tk 事件链路。"""
    scan = u32.MapVirtualKeyW(vk, 0)
    lparam = 1 | (scan << 16) | (0x01000000 if vk in EXTENDED_KEYS else 0)
    u32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam)
    if not hold:
        time.sleep(0.05)
        u32.PostMessageW(hwnd, WM_KEYUP, vk, 0xC0000000 | lparam)
    time.sleep(0.30)


def release_key(hwnd, vk):
    scan = u32.MapVirtualKeyW(vk, 0)
    lparam = (0xC0000000 | 1 | (scan << 16)
              | (0x01000000 if vk in EXTENDED_KEYS else 0))
    u32.PostMessageW(hwnd, WM_KEYUP, vk, lparam)
    time.sleep(0.05)


def click_client(hwnd, x, y):
    lp = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    u32.PostMessageW(hwnd, WM_LBUTTONDOWN, 0x0001, lp)
    time.sleep(0.08)
    u32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)
    time.sleep(0.4)


# ================= 物理鼠标（沙箱可能拦截，需先探测） =================
def mouse_injection_available():
    """本环境是否允许物理鼠标注入。

    沙箱会把 SetCursorPos 变成空操作（光标停在 0,0），此时凡是要"真的移动
    鼠标"的测试都必须跳过，而不是假装失败。
    """
    before = wndutil.cursor_pos()
    u32.SetCursorPos(7, 7)
    time.sleep(0.05)
    moved = wndutil.cursor_pos() == (7, 7)
    u32.SetCursorPos(*before)
    return moved


def move_mouse(x, y, steps=14, delay=0.012):
    sx, sy = wndutil.cursor_pos()
    for i in range(1, steps + 1):
        u32.SetCursorPos(int(sx + (x - sx) * i / steps),
                         int(sy + (y - sy) * i / steps))
        time.sleep(delay)


def drag_mouse(x1, y1, x2, y2):
    """从 (x1,y1) 按住拖到 (x2,y2)。

    先真的把光标移到起点再按下 —— 少了这一步，按下点在"光标原来待的地方"，
    拖拽的起点就完全不是调用者以为的那个位置。
    """
    move_mouse(x1, y1, steps=12)
    time.sleep(0.18)
    u32.mouse_event(0x0002, 0, 0, 0, 0)              # LEFTDOWN
    time.sleep(0.15)
    move_mouse(x2, y2, steps=18)
    time.sleep(0.2)
    u32.mouse_event(0x0004, 0, 0, 0, 0)              # LEFTUP
    time.sleep(0.35)


def click_mouse(x, y):
    """真实左键单击（比 PostMessage 更贴近用户操作）。"""
    move_mouse(x, y, steps=10)
    time.sleep(0.15)
    u32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.09)
    u32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.45)


def menu_open(pid):
    """托盘菜单（TrackPopupMenu 建的 #32768 窗口）是否已弹出。"""
    return find_popup_menu(pid) is not None


def send_close(hwnd):
    u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(0.4)


def post_hotkey(aux_hwnd):
    """模拟系统投递 WM_HOTKEY：走辅助线程的真实消息处理链路。"""
    u32.PostMessageW(aux_hwnd, WM_HOTKEY, hotkey.HOTKEY_TOGGLE, 0)


def post_menu_command(aux_hwnd, cmd):
    """模拟托盘菜单被点选：辅助线程 -> actions 队列 -> 主线程执行。"""
    u32.PostMessageW(aux_hwnd, WM_COMMAND, cmd, 0)


# ================= 系统级：热键独占探测 =================
def try_register_hotkey(vk, mods=0, hwnd=None):
    """在测试进程里试着注册一个热键，返回 (是否成功, GetLastError)。

    用途：判定某个键是否"真的被目标实例装上并独占"—— 应用代码自己说注册
    成功不算证据，外部进程注册不到才算。
    """
    hid = 0x7FD0
    ctypes.set_last_error(0)
    ok = bool(u32.RegisterHotKey(hwnd, hid, mods, vk))
    err = ctypes.get_last_error()
    if ok:
        u32.UnregisterHotKey(hwnd, hid)
    return ok, err


# ================= 用户数据护栏 =================
def file_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return "(无法读取)"


def pythonw_pids():
    """当前所有 pythonw.exe 进程的 PID。用户自己那个实例就在里面。"""
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pythonw.exe",
                          "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, errors="replace")
    pids = []
    for line in out.stdout.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("pythonw"):
            pids.append(parts[1])
    return sorted(pids)


# ================= 找一块没人占的屏幕空域 =================
# 铺满全屏、永远"盖住"整个工作区的伪遮挡者：桌面本体、任务栏、输入法窗口。
# 它们不是别的应用，让它们参与遮挡计算会得出"屏幕上一寸空地都没有"。
_TRANSPARENT_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd",
    "Windows.UI.Core.CoreWindow", "EdgeUiInputTopWndClass",
}
# 桌面图标层（WorkerW 的子窗口 SysListView32）同样铺满全屏，但它不是应用：
# 落点压着桌面图标无所谓 —— 拾取器本来就会因为它没有标题栏而拒绝。
_DESKTOP_ICON_CLASSES = {"SysListView32", "FolderView", "SHELLDLL_DefView"}


def _opaque_at(x, y):
    """那个点上有没有"别的应用窗口"。返回 (bool, 说明)。"""
    under = u32.WindowFromPoint(wt.POINT(int(x), int(y)))
    if not under:
        return False, ""
    cls = wndutil.win_class(under)
    if cls in _TRANSPARENT_CLASSES or cls in _DESKTOP_ICON_CLASSES:
        return False, ""
    root = wndutil.root_of(under)
    if wndutil.win_class(root) in _TRANSPARENT_CLASSES:
        return False, ""
    return True, "%s %r %s pid=%s" % (cls, wndutil.win_text(under),
                                      wndutil.win_rect(under),
                                      wndutil.window_pid(under))


def free_spot(w, h, avoid_pids=(), step=40):
    """在屏幕上找一块 w*h 的空域，返回左上角 (x, y)；找不到返回 None。

    为什么需要它：吸附类测试必须用真实鼠标把窗口拖到目标上松开，拾取器
    认的是"光标底下那个窗口"。目标窗口的位置一旦被别的窗口盖住 —— 最常见
    的就是**用户自己正在用的那个浮坞面板**（实测它就在 (616,215)-(1404,941)，
    正好压住写死的测试落点）—— 拾取器抓到的就是那个窗口，后果严重。

    所以位置不该写死。实测记录：
      · 写死 (400,780,420,260) 时，用户面板一挪过来就整段测试失效，
        而且失败信息长得像产品缺陷（"拖放点不对"），误导排查方向；
      · 改为现找空域后，同一份代码在有面板/无面板两种环境下都能跑。

    判据是"逐点探测"而不是矩形相交：桌面上铺着 Progman / 图标层 / 输入法
    这些永远占满全屏的窗口，矩形相交法会得出"一寸空地都没有"。
    """
    screen_w = u32.GetSystemMetrics(0)
    screen_h = u32.GetSystemMetrics(1)
    for y in range(screen_h - h - step, 0, -step):
        for x in range(step, screen_w - w - step, step):
            probes = [(x + w // 2, y + h // 2),
                      (x + w // 8, y + h // 8), (x + w * 7 // 8, y + h // 8),
                      (x + w // 8, y + h * 7 // 8),
                      (x + w * 7 // 8, y + h * 7 // 8)]
            if not any(_opaque_at(px, py)[0] for px, py in probes):
                return x, y
    return None


class UserGuard(object):
    """记录用户实例与用户配置的状态，测试前后比对。

    本项目的铁律：任何测试都不许碰正在被用户使用的那个浮坞实例、
    也不许改动它的 config.json。这里就是那条铁律的执行者。
    """

    def __init__(self):
        self.pids = pythonw_pids()
        self.cfg = file_hash(USER_CFG)

    def unchanged(self):
        return (pythonw_pids() == self.pids) and file_hash(USER_CFG) == self.cfg

    def detail(self):
        return "pythonw=%s / config=%s" % (pythonw_pids(), file_hash(USER_CFG)[:16])


# ================= 隔离沙箱 =================
class Sandbox(object):
    """一个与用户实例并存的浮坞进程：独立配置、独立日志。"""

    def __init__(self, name, cfg=None):
        self.dir = os.path.join(HERE, "_sandbox", name)
        os.makedirs(self.dir, exist_ok=True)
        self.cfg_path = os.path.join(self.dir, "config.json")
        self.log_path = os.path.join(self.dir, "run.log")
        self.proc = None
        self._log = None
        self.write_cfg(cfg or {})

    # ---- 配置 ----
    def write_cfg(self, cfg):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)

    def read_cfg(self):
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ---- 进程 ----
    def start(self, debug=True):
        args = [PY, "-u", APP, "--config", self.cfg_path, "--allow-multiple"]
        if debug:
            args.append("--debug")
        self._log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(args, cwd=ROOT, stdout=self._log,
                                     stderr=subprocess.STDOUT)
        return self.proc

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=8)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    # ---- 日志 ----
    def lines(self):
        try:
            with open(self.log_path, "r", encoding="utf-8",
                      errors="replace") as f:
                return f.readlines()
        except Exception:
            return []

    def text(self):
        return "".join(self.lines())

    def wait_log(self, needle, since=0, timeout=5.0):
        """等日志里出现某个字符串，返回从 since 行开始的片段。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            chunk = "".join(self.lines()[since:])
            if needle in chunk:
                return chunk
            time.sleep(0.1)
        return "".join(self.lines()[since:])

    def line_count(self):
        return len(self.lines())

    # ---- 组合 ----
    def panel(self, timeout=15.0):
        return find_panel(self.proc.pid, timeout=timeout)

    def aux(self, timeout=8.0):
        return find_aux(self.proc.pid, timeout=timeout)

    def settings(self, timeout=6.0):
        return find_settings(self.proc.pid, timeout=timeout)
