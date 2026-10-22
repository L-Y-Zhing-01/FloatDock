# -*- coding: utf-8 -*-
"""Win32 绑定层：DLL 句柄、常量与 ctypes 函数签名。

本模块只做"定义"，不含任何业务逻辑；窗口的查询与操作见 wndutil.py。

所有用到的函数都显式声明 argtypes/restype —— 64 位下 HWND/HANDLE 若按
ctypes 默认的 c_int 传递会被截断，是这类代码最常见的隐性 bug 来源。
"""
import ctypes
from ctypes import wintypes as wt

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
sh32 = ctypes.WinDLL("shell32")
gdi32 = ctypes.WinDLL("gdi32")
try:
    dwm = ctypes.WinDLL("dwmapi")
except Exception:                      # 极老的系统没有 dwmapi
    dwm = None

LRESULT = ctypes.c_ssize_t
HWND = wt.HWND
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM)
ENUMWINDOWSPROC = ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM)

# ================= 窗口样式 =================
# 只列程序真正用到的位。多写一个"也许将来有用"的常量，下次读代码就得
# 多查一处"它到底有没有被用过" —— 要加再按需加。
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_CLIPSIBLINGS = 0x04000000

WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

# ================= SetWindowPos =================
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x0001, 0x0002, 0x0004
SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0010, 0x0020, 0x0040

# ================= ShowWindow =================
SW_HIDE, SW_SHOW, SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 0, 5, 6, 3, 9

# ================= 其它常量 =================
GA_ROOT = 2
DWMWA_CLOAKED = 14
VK_LBUTTON = 0x01
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
IDI_APPLICATION = 32512

# 窗口类图标槽位（SetClassLongPtrW / GetClassLongPtrW 的 nIndex）
GCLP_HICON, GCLP_HICONSM = -14, -34

# GetSystemMetrics 索引
SM_CXICON, SM_CYICON = 11, 12
SM_CXSMICON, SM_CYSMICON = 49, 50

# ================= 消息 =================
WM_NULL = 0x0000
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_COMMAND = 0x0111
WM_GETICON = 0x007F
WM_SETICON = 0x0080
WM_HOTKEY = 0x0312
WM_APP = 0x8000

# WM_SETICON 的 wParam
ICON_SMALL, ICON_BIG = 0, 1

# ================= 结构体 =================


class WNDCLASSW(ctypes.Structure):
    """ctypes.wintypes 在 Python 3.13+ 移除了 WNDCLASSW，这里自定义。"""
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HANDLE),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HANDLE),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    """Shell_NotifyIconW 用的托盘图标结构（取常用的前段字段）。"""
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", HWND), ("uID", wt.UINT),
                ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT),
                ("hIcon", wt.HANDLE), ("szTip", wt.WCHAR * 128),
                ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
                ("szInfo", wt.WCHAR * 256), ("uVersion", wt.UINT),
                ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD)]


# ================= 函数签名 =================
def _sig(func, restype=None, argtypes=None):
    if restype is not None:
        func.restype = restype
    if argtypes is not None:
        func.argtypes = argtypes


_sig(u32.GetWindowLongPtrW, LRESULT, [HWND, ctypes.c_int])
_sig(u32.SetWindowLongPtrW, LRESULT, [HWND, ctypes.c_int, LRESULT])
_sig(u32.SetClassLongPtrW, LRESULT, [HWND, ctypes.c_int, LRESULT])
_sig(u32.SendMessageW, LRESULT,
     [HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM])
_sig(u32.GetSystemMetrics, ctypes.c_int, [ctypes.c_int])
_sig(u32.GetWindowLongW, ctypes.c_long, [HWND, ctypes.c_int])
_sig(u32.SetWindowLongW, ctypes.c_long, [HWND, ctypes.c_int, ctypes.c_long])
_sig(u32.SetParent, HWND, [HWND, HWND])
_sig(u32.GetParent, HWND, [HWND])
_sig(u32.GetAncestor, HWND, [HWND, ctypes.c_uint])
_sig(u32.SetWindowPos, wt.BOOL,
     [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      ctypes.c_uint])
_sig(u32.MoveWindow, wt.BOOL,
     [HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.BOOL])
_sig(u32.ShowWindow, wt.BOOL, [HWND, ctypes.c_int])
_sig(u32.IsWindow, wt.BOOL, [HWND])
_sig(u32.IsWindowVisible, wt.BOOL, [HWND])
_sig(u32.IsIconic, wt.BOOL, [HWND])
_sig(u32.IsZoomed, wt.BOOL, [HWND])
_sig(u32.GetWindowRect, wt.BOOL, [HWND, ctypes.POINTER(wt.RECT)])
_sig(u32.GetWindowThreadProcessId, wt.DWORD, [HWND, ctypes.POINTER(wt.DWORD)])
_sig(u32.GetClassNameW, ctypes.c_int, [HWND, wt.LPWSTR, ctypes.c_int])
_sig(u32.GetWindowTextW, ctypes.c_int, [HWND, wt.LPWSTR, ctypes.c_int])
_sig(u32.WindowFromPoint, HWND, [wt.POINT])
_sig(u32.GetCursorPos, wt.BOOL, [ctypes.POINTER(wt.POINT)])
_sig(u32.GetAsyncKeyState, ctypes.c_short, [ctypes.c_int])
_sig(u32.SetForegroundWindow, wt.BOOL, [HWND])
_sig(u32.PostMessageW, wt.BOOL, [HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM])
_sig(u32.InvalidateRect, wt.BOOL, [HWND, ctypes.c_void_p, wt.BOOL])
# RedrawWindow：强制子窗口整面重画。吸附后必须调它 —— 见 absorb.place_current。
_sig(u32.RedrawWindow, wt.BOOL,
     [HWND, ctypes.c_void_p, wt.HANDLE, ctypes.c_uint])
# RDW_*：RedrawWindow 的标志位（0x585 = 整面失效 + 擦背景 + 连框 + 连子窗口 + 立即重画）
RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_ALLCHILDREN = 0x0080
RDW_UPDATENOW = 0x0100
RDW_FRAME = 0x0400
RDW_REPAINT_ALL = (RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN
                   | RDW_UPDATENOW | RDW_FRAME)
# SetWindowRgn + CreateRectRgn：裁掉嵌入窗口顶部那条画不出来的空带。
# 见 absorb.place_current —— 文件夹这类应用的空白劝不动，只能裁掉再上移补位。
_sig(u32.SetWindowRgn, wt.BOOL, [HWND, wt.HANDLE, wt.BOOL])
_sig(gdi32.CreateRectRgn, wt.HANDLE,
     [ctypes.c_long, ctypes.c_long, ctypes.c_long, ctypes.c_long])
_sig(u32.DestroyWindow, wt.BOOL, [HWND])
_sig(u32.SetProcessDPIAware, wt.BOOL, [])
_sig(u32.LoadImageW, wt.HANDLE,
     [wt.HINSTANCE, wt.LPCWSTR, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
      ctypes.c_uint])
_sig(u32.LoadIconW, wt.HANDLE, [wt.HINSTANCE, ctypes.c_void_p])
_sig(u32.DestroyIcon, wt.BOOL, [wt.HANDLE])
_sig(u32.PostThreadMessageW, wt.BOOL,
     [wt.DWORD, ctypes.c_uint, wt.WPARAM, wt.LPARAM])
_sig(u32.EnumWindows, wt.BOOL, [ENUMWINDOWSPROC, wt.LPARAM])

# ---- 全局热键 ----
_sig(u32.RegisterHotKey, wt.BOOL, [HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint])
_sig(u32.UnregisterHotKey, wt.BOOL, [HWND, ctypes.c_int])
_sig(u32.RegisterClassW, wt.ATOM, [ctypes.POINTER(WNDCLASSW)])
_sig(u32.CreateWindowExW, HWND,
     [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      HWND, wt.HANDLE, wt.HINSTANCE, wt.LPVOID])
_sig(u32.DefWindowProcW, LRESULT, [HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM])
_sig(u32.GetMessageW, ctypes.c_int,
     [ctypes.POINTER(wt.MSG), HWND, ctypes.c_uint, ctypes.c_uint])
_sig(u32.TranslateMessage, wt.BOOL, [ctypes.POINTER(wt.MSG)])
_sig(u32.DispatchMessageW, LRESULT, [ctypes.POINTER(wt.MSG)])

# ---- 托盘菜单 ----
_sig(u32.CreatePopupMenu, wt.HANDLE, [])
_sig(u32.DestroyMenu, wt.BOOL, [wt.HANDLE])
_sig(u32.AppendMenuW, wt.BOOL,
     [wt.HANDLE, ctypes.c_uint, ctypes.c_size_t, wt.LPCWSTR])
_sig(u32.TrackPopupMenu, wt.BOOL,
     [wt.HANDLE, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      HWND, ctypes.c_void_p])
_sig(u32.CheckMenuItem, wt.BOOL, [wt.HANDLE, ctypes.c_uint, ctypes.c_uint])
_sig(sh32.Shell_NotifyIconW, wt.BOOL, [wt.DWORD, ctypes.c_void_p])

_sig(k32.GetModuleHandleW, wt.HANDLE, [wt.LPCWSTR])

if dwm is not None:
    _sig(dwm.DwmGetWindowAttribute, ctypes.c_long,
         [HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint])


def enable_dpi_awareness():
    """必须在 Tk 初始化前调用：保证坐标是物理像素，吸附才不会错位。"""
    try:
        if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "PER_MONITOR_AWARE_V2"
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return "PER_MONITOR_AWARE"
    except Exception:
        pass
    u32.SetProcessDPIAware()
    return "SYSTEM_AWARE"


def make_int_resource(res_id):
    """MAKEINTRESOURCE：把整型资源 ID 包成指针，供 LoadIconW 等使用。"""
    return ctypes.c_void_p(res_id)
