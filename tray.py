# -*- coding: utf-8 -*-
"""托盘图标与全局热键：跑在一条独立的 UI 线程里。

为什么要单独开线程：
  · 托盘图标需要一个能收消息的窗口过程，而 Tk 的主循环不给它这个机会；
  · 全局热键只会在"注册它的那个线程"的消息队列里收到 WM_HOTKEY。

线程只负责"系统交互"，不碰界面：它把要做的事丢进 actions 队列，
由 Tk 主线程轮询执行（见 panel._pump_aux），两边不共享任何界面状态。
"""
import ctypes
import queue
import threading
from ctypes import wintypes as wt

import appicon
import hotkey as hk
from debug import dbg
from winapi import (u32, k32, sh32, WNDCLASSW, WNDPROC, NOTIFYICONDATAW,
                    WM_APP, WM_NULL, WM_CLOSE, WM_COMMAND, WM_HOTKEY, WM_QUIT,
                    WS_EX_TOOLWINDOW)
from wndutil import cursor_pos

WM_TRAY = WM_APP + 0x5A1          # 托盘图标回调消息
WM_HOTKEY_SET = WM_APP + 0x5A2    # 请求改热键（发给辅助线程自己）

CMD_SHOWHIDE, CMD_LOCK, CMD_RELEASE_ALL = 0x1001, 0x1002, 0x1003
CMD_QUIT, CMD_ABOUT, CMD_SETTINGS = 0x1004, 0x1005, 0x1006
CMD_TIP = 0x1007                  # 赞赏支持

# 托盘回调消息的 lParam 携带鼠标消息。
# 注意 0x0203 是 WM_LBUTTONDBLCLK（左键双击）而不是右键——这正是
# "双击才出菜单"的根因；右键是 0x0205。
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0202, 0x0203, 0x0205

NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
MF_SEPARATOR, MF_CHECKED = 0x0800, 0x0008
TPM_RIGHTBUTTON = 0x0002

# 菜单项 id -> 交给主线程的动作名
_MENU_ACTIONS = {CMD_SHOWHIDE: "toggle", CMD_LOCK: "lock",
                 CMD_RELEASE_ALL: "release_all", CMD_SETTINGS: "settings",
                 CMD_TIP: "tip", CMD_ABOUT: "about", CMD_QUIT: "quit"}


def aux_class_name():
    """辅助窗口的类名。测试要按它找窗口，所以对外暴露一个取法。

    为什么要这么一根弦：品牌标识只有 `appicon` 一处定义，这个类名是从
    `APP_TITLE` 派生的。测试侧若写死字面量，就等于多了一个定义点，产品
    一改名就静默失效（而且失败信息是"窗口没找到"，极难定位）。
    """
    return appicon.APP_TITLE + "AuxWnd"


class AuxThread(threading.Thread):
    """承载托盘图标与全局热键的辅助线程。"""

    def __init__(self, app_title, locked_getter, hotkey_spec=None):
        super(AuxThread, self).__init__(daemon=True)
        self.app_title = app_title
        self.locked_getter = locked_getter
        self.actions = queue.Queue()        # -> 主线程执行的动作
        self.hk_results = queue.Queue()     # -> 主线程的热键注册结果 (ok, 文案)
        self._hk_req = queue.Queue()
        self.hwnd = None
        self.ready = threading.Event()      # 辅助窗口建好即置位
        self.hotkey_spec = dict(hotkey_spec if isinstance(hotkey_spec, dict)
                                else hk.DEFAULT_HOTKEY)
        self.hotkey_label = ""
        self._hk_registered = False
        self._nid = None
        self._own_icon = False              # 图标句柄是否由本程序创建（需自己销毁）
        self._menu = None
        self._wndproc_ref = None            # 保活，防止回调被 GC

    # ================= 线程体 =================
    def run(self):
        wc = WNDCLASSW()
        self._wndproc_ref = WNDPROC(self._wndproc)
        wc.lpfnWndProc = self._wndproc_ref
        # 窗口类名/窗口名从 appicon 派生，不要在这里另写一份品牌串——
        # 品牌标识只有 appicon 一处定义（见 tests/test_icon.py 的 A 段断言）。
        cls_name = aux_class_name()
        wc.lpszClassName = cls_name
        wc.hInstance = k32.GetModuleHandleW(None)
        if not u32.RegisterClassW(ctypes.byref(wc)):
            dbg("注册辅助窗口类失败，托盘与热键不可用")
            self.ready.set()
            return
        self.hwnd = u32.CreateWindowExW(WS_EX_TOOLWINDOW, wc.lpszClassName,
                                        appicon.APP_TITLE + "Aux",
                                        0, 0, 0, 0, 0,
                                        None, None, wc.hInstance, None)
        ok, text = self._apply_hotkey(self.hotkey_spec)
        dbg("初始热键:", ok, text)
        self._build_menu()
        self._add_tray()
        self.ready.set()
        msg = wt.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))

    # ================= 全局热键 =================
    # 只能在辅助线程里注册，这样 WM_HOTKEY 才会落到本线程的消息循环
    def _apply_hotkey(self, spec):
        """注册新的全局热键。失败时把旧的装回去，绝不留下"一个热键都没有"的状态。"""
        try:
            mods, vk, label = hk.hotkey_to_win(spec)
        except ValueError as e:
            return False, str(e)
        old_spec = dict(self.hotkey_spec)
        had_hotkey = self._hk_registered
        if had_hotkey:
            u32.UnregisterHotKey(self.hwnd, hk.HOTKEY_TOGGLE)
            self._hk_registered = False
        if u32.RegisterHotKey(self.hwnd, hk.HOTKEY_TOGGLE,
                              mods | hk.MOD_NOREPEAT, vk):
            self._hk_registered = True
            self.hotkey_spec = dict(spec)
            self.hotkey_label = label
            return True, label
        if had_hotkey:
            self._restore_hotkey(old_spec)
        return False, ("%s 注册失败（%s），已保留原快捷键 %s"
                       % (label, self._fail_reason(spec),
                          self.hotkey_label or "（无）"))

    def _restore_hotkey(self, spec):
        try:
            mods, vk, _label = hk.hotkey_to_win(spec)
        except ValueError:
            return
        if u32.RegisterHotKey(self.hwnd, hk.HOTKEY_TOGGLE,
                              mods | hk.MOD_NOREPEAT, vk):
            self._hk_registered = True

    @staticmethod
    def _fail_reason(spec):
        """归因注册失败。F12 是系统保留键，与"被别的程序占用"不是一回事。"""
        has_mod = any(spec.get(flag) for flag, _ in hk.MOD_NAMES)
        if not has_mod and hk.is_debugger_reserved(spec.get("key")):
            return "F12 被 Windows 保留给调试器，无法单独注册，请改用 F1–F11"
        return "可能已被其他程序占用"

    def set_hotkey(self, spec):
        """主线程调用：把注册请求投递到辅助线程，结果走 hk_results。"""
        if not self.hwnd:
            self.hk_results.put((False, "辅助窗口未就绪，请稍后重试"))
            return
        self._hk_req.put(dict(spec))
        u32.PostMessageW(self.hwnd, WM_HOTKEY_SET, 0, 0)

    # ================= 消息处理 =================
    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            return self._on_tray_msg(lparam)
        if msg == WM_HOTKEY_SET:
            self._on_hotkey_set()
            return 0
        if msg == WM_HOTKEY and wparam == hk.HOTKEY_TOGGLE:
            self.actions.put(("toggle", None))
            return 0
        if msg == WM_COMMAND:
            action = _MENU_ACTIONS.get(wparam & 0xFFFF)
            if action:
                self.actions.put((action, None))
            return 0
        if msg == WM_CLOSE:
            u32.DestroyWindow(hwnd)
            return 0
        return u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _on_tray_msg(self, lparam):
        """托盘鼠标消息路由：右键弹菜单，左键切换显隐，双击忽略。"""
        if lparam == WM_RBUTTONUP:
            self._popup_menu(self.hwnd)
        elif lparam == WM_LBUTTONUP:
            self.actions.put(("toggle", None))
        return 0

    def _on_hotkey_set(self):
        try:
            spec = self._hk_req.get_nowait()
        except queue.Empty:
            return
        ok, text = self._apply_hotkey(spec)
        self.hk_results.put((ok, text))
        if ok:
            self._build_menu()

    # ================= 托盘 =================
    def _add_tray(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        # 图标向 appicon 要，本线程不管它长什么样；第二个返回值说明句柄是不是
        # 本程序创建的 —— 只有自己 LoadImage 出来的才该在退出时 DestroyIcon。
        nid.hIcon, self._own_icon = appicon.load_hicon()
        nid.szTip = self.app_title
        self._nid = nid
        sh32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _build_menu(self):
        if self._menu:
            u32.DestroyMenu(self._menu)
        menu = u32.CreatePopupMenu()
        suffix = ("\t" + self.hotkey_label) if self.hotkey_label else ""
        u32.AppendMenuW(menu, 0, CMD_SHOWHIDE, "显示 / 隐藏浮坞" + suffix)
        u32.AppendMenuW(menu, 0, CMD_LOCK, "锁定（停用自动隐藏）")
        u32.AppendMenuW(menu, 0, CMD_RELEASE_ALL, "释放窗口")
        u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u32.AppendMenuW(menu, 0, CMD_SETTINGS, "设置…")
        u32.AppendMenuW(menu, 0, CMD_TIP, "赞赏支持…")
        u32.AppendMenuW(menu, 0, CMD_ABOUT, "关于浮坞")
        u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u32.AppendMenuW(menu, 0, CMD_QUIT, "退出浮坞")
        self._menu = menu

    def _popup_menu(self, hwnd):
        if not self._menu:
            return
        x, y = cursor_pos()
        u32.SetForegroundWindow(hwnd)
        u32.CheckMenuItem(self._menu, CMD_LOCK,
                          MF_CHECKED if self.locked_getter() else 0)
        u32.TrackPopupMenu(self._menu, TPM_RIGHTBUTTON, x, y, 0, hwnd, None)
        u32.PostMessageW(hwnd, WM_NULL, 0, 0)   # 让菜单退出模态

    def remove_tray(self):
        """退出前把辅助线程持有的系统资源逐样交还，并让线程结束。

        顺序是有讲究的，四步都不能省、也不能换位：
          1) 删托盘图标   —— 图标挂在通知区，不删就会留一个"僵尸图标"，
                            点它还会往一个已经消失的窗口发消息；
          2) 注销热键     —— 否则该组合在系统里被占着（进程退出虽然也会释放，
                            但退出路径上主动交还才叫"同步清理"）；
          3) 销毁图标句柄 —— 自己 LoadImage 出来的 HICON 属于本进程的 GDI 对象；
          4) 结束消息循环 —— 关键一步：删掉窗口并不会让 GetMessageW 返回，
                            线程会永远挂在它上面。必须投递 WM_QUIT，
                            run() 的循环才会退出、线程才真的结束。
        """
        if self._nid:
            sh32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            if getattr(self._nid, "hIcon", None) and self._own_icon:
                try:
                    u32.DestroyIcon(self._nid.hIcon)
                except Exception:
                    pass
            self._nid = None
        self._own_icon = False
        if self.hwnd:
            u32.UnregisterHotKey(self.hwnd, hk.HOTKEY_TOGGLE)
            self._hk_registered = False
            u32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self.ident:
            # 消息队列在创建窗口时就已存在，所以这里一定能投递成功
            u32.PostThreadMessageW(self.ident, WM_QUIT, 0, 0)
