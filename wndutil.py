# -*- coding: utf-8 -*-
"""窗口查询与操作：矩形/类名/标题/进程号/根窗口、鼠标拾取、可吸附性判定。

这里放的是"跟窗口打交道"的通用操作，不含浮坞自身的业务状态。
"""
import ctypes
from ctypes import wintypes as wt

from winapi import (u32, dwm, ENUMWINDOWSPROC, GA_ROOT, GWL_EXSTYLE,
                    GWL_STYLE, DWMWA_CLOAKED, VK_LBUTTON, WS_CLIPSIBLINGS,
                    WS_EX_LAYERED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER,
                    SWP_NOACTIVATE, SWP_FRAMECHANGED)

# 不允许吸附的系统窗口类名（类名大小写敏感，别写成 Tooltips_class32）
FORBIDDEN_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow", "SysListView32", "SysHeader32",
    "MSO_TASKPANE", "tooltips_class32", "FloatingPreviewHost",
}

# "包边层"判定：阴影/外框层每边最多外扩这么多像素。窗口阴影通常在 8–32px，
# 留到 64 是给高 DPI 下的圆角外框留余量；再大就不像"包自己一圈"了。
MAX_FRAME_PAD = 64


# ---------------- 基本读取 ----------------
def get_long(hwnd, index):
    """读取窗口的长整型属性（样式等）。"""
    try:
        return u32.GetWindowLongPtrW(hwnd, index)
    except Exception:
        return u32.GetWindowLongW(hwnd, index)


def set_long(hwnd, index, value):
    try:
        return u32.SetWindowLongPtrW(hwnd, index, value)
    except Exception:
        return u32.SetWindowLongW(hwnd, index, value)


def root_of(hwnd):
    """所在顶层窗口。"""
    return u32.GetAncestor(hwnd, GA_ROOT)


def win_text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, buf, 512)
    return buf.value or ""


def win_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def win_rect(hwnd):
    """(x, y, w, h)；窗口失效时返回 None。"""
    r = wt.RECT()
    if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def window_pid(hwnd) -> int:
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def cursor_pos():
    p = wt.POINT()
    u32.GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


def point_window():
    """鼠标指向的顶层窗口；没有则 None。"""
    p = wt.POINT()
    u32.GetCursorPos(ctypes.byref(p))
    h = u32.WindowFromPoint(p)
    return root_of(h) if h else None


def lbutton_up():
    """左键是否已经松开（拾取时用它判断拖拽结束）。"""
    return not (u32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def invalidate(hwnd):
    """强制重画窗口，让画布收回被腾出的那块区域。"""
    u32.InvalidateRect(hwnd, None, True)


def add_clipsiblings(hwnd):
    """给窗口补上 WS_CLIPSIBLINGS（幂等）。

    否则画布重绘时会直接盖掉被吸附窗口的像素，而对方并不知道自己被覆盖、
    不会重绘，表现就是"吸附后一片空白"。
    """
    style = get_long(hwnd, GWL_STYLE)
    if style & WS_CLIPSIBLINGS:
        return
    set_long(hwnd, GWL_STYLE, style | WS_CLIPSIBLINGS)
    u32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                     | SWP_FRAMECHANGED | SWP_NOACTIVATE)


# ---------------- 窗口枚举与"包边层" ----------------
def top_level_windows(pid=None):
    """枚举当前可见的顶层窗口；pid 给定时只取该进程的。

    不可见的窗口一律略过：吸附与"包边层"判定都只关心屏幕上看得见的东西。
    """
    out = []

    def _collect(hwnd, _lparam):
        try:
            if not u32.IsWindowVisible(hwnd):
                return True
            if pid is None or window_pid(hwnd) == pid:
                out.append(hwnd)
        except Exception:
            pass
        return True

    u32.EnumWindows(ENUMWINDOWSPROC(_collect), 0)
    return out


def frame_pads(outer, inner):
    """outer 比 inner 每边各外扩多少像素；outer 不包含 inner 时返回 None。"""
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    pads = (ix - ox, iy - oy, ox + ow - (ix + iw), oy + oh - (iy + ih))
    return None if min(pads) < 0 else pads


def _pads_around(outer, inner):
    """outer 是不是"正好包了 inner 一圈"：四周都有外扩，且不超出上限。"""
    pads = frame_pads(outer, inner)
    return pads is not None and 0 < max(pads) <= MAX_FRAME_PAD


def frame_companions(target):
    """包在 target 外围的"框窗"（阴影 / 外框层）。

    有些浏览器不把阴影与圆角外框交给 DWM，而是画在一个独立的**分层窗口**里
    （实测 360 极速浏览器 X：`Chrome_WidgetWin_0` 比内容窗 `Chrome_WidgetWin_1`
    每边大 21px，同进程、顶层、可见、带 WS_EX_LAYERED）。只搬走内容窗的话，
    这个包边会留在桌面原位 —— 用户看到的就是"吸附完剩下一个空边框"。
    """
    rect = win_rect(target)
    if not rect:
        return []
    out = []
    for hwnd in top_level_windows(pid=window_pid(target)):
        if hwnd == target:
            continue
        if not (get_long(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED):
            continue                     # 不是分层窗口，就不可能是阴影层
        outer = win_rect(hwnd)
        if outer and _pads_around(outer, rect):
            out.append(hwnd)
    return out


def is_frame_layer(hwnd):
    """hwnd 是不是"画在别的窗口外围"的阴影 / 外框层。

    拾取器有可能点在窗口外圈那 21px 上 —— 那时光标底下是包边层而不是窗口
    本身。吸附它只会得到一个空框子，所以要先把它认出来、拒掉。
    """
    if not (get_long(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED):
        return False
    outer = win_rect(hwnd)
    if not outer:
        return False
    for other in top_level_windows(pid=window_pid(hwnd)):
        if other == hwnd:
            continue
        inner = win_rect(other)
        if inner and _pads_around(outer, inner):
            return True
    return False


def is_cloaked(hwnd):
    """UWP/商店应用被 DWM 斗篷化时不适合吸附。"""
    if dwm is None:
        return False
    val = wt.DWORD(0)
    try:
        dwm.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val),
                                  ctypes.sizeof(val))
    except Exception:
        return False
    return val.value != 0


def is_suitable_target(hwnd, own_pid):
    """判断一个顶层窗口是否允许吸附。返回 (是否允许, 说明或标题)。"""
    if not hwnd or not u32.IsWindow(hwnd):
        return False, "窗口已失效"
    if not u32.IsWindowVisible(hwnd):
        return False, "目标窗口不可见"
    if window_pid(hwnd) == own_pid:
        return False, "不能吸附浮坞自己"
    cls = win_class(hwnd)
    if cls in FORBIDDEN_CLASSES:
        return False, "系统窗口（%s）不允许吸附" % cls
    if is_cloaked(hwnd):
        return False, "该窗口是隐藏的 UWP 宿主，不支持吸附"
    if is_frame_layer(hwnd):
        return False, "这是窗口的阴影/外框层，请吸附它包住的窗口"
    title = win_text(hwnd).strip()
    if not title and cls == "ApplicationFrameWindow":
        return False, "未命名的应用宿主窗口"
    return True, title or cls
