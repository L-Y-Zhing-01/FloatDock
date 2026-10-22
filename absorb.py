# -*- coding: utf-8 -*-
"""窗口吸附引擎：把别的进程的窗口"挂"到面板下，并能原样还回去。

原理是 Win32 的跨进程 SetParent：
  吸附 —— 取快照 -> ShowWindow(HIDE) -> 剥掉边框/标题栏 -> SetParent(面板)
         -> MoveWindow 到用户区 -> ShowWindow(SHOW)
  释放 —— SetParent(原父) -> 还原 style/exstyle -> SetWindowPos 回原位
快照（Tab）是这套机制的安全网：只要拿到快照，任何一步失败都能逐位还原，
绝不会把用户的窗口留在"看不见又关不掉"的状态。
"""
import ctypes
import time
from ctypes import wintypes as wt

from debug import dbg
from winapi import (u32, gdi32, GWL_STYLE, GWL_EXSTYLE, WS_CHILD, WS_POPUP,
                    WS_CAPTION, WS_THICKFRAME, WS_EX_APPWINDOW,
                    SW_HIDE, SW_SHOW, SW_RESTORE, SW_MINIMIZE, SW_MAXIMIZE,
                    SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE,
                    SWP_FRAMECHANGED, SWP_SHOWWINDOW, RDW_REPAINT_ALL)
from wndutil import (get_long, set_long, is_suitable_target, win_rect, win_text,
                     frame_companions)

# 吸附时要剥掉的样式：窗口边框与标题栏。
# 只剥这两样，别的一概不动 —— 剥掉之后窗口就是一个纯内容面，摆进用户区即可。
# 为什么连 WS_CAPTION 一起剥：文件夹（资源管理器）这类应用在客户区顶部固定
# 预留了一条"自定义标题栏"的位置，可它作为子窗口根本画不出那条标题栏，于是
# 留着 CAPTION 只会变成"系统标题栏 + 31px 空带"。空带既填不上也劝不动它重排
# （v1.7.2 已穷举 RDW / 样式循环 / 重挂 / 缩放），所以干脆剥掉、由 place_current
# 把那条空带裁出去，内容顶格。
STRIP_STYLE = WS_POPUP | WS_CAPTION | WS_THICKFRAME
# 扩展样式里只去掉 WS_EX_APPWINDOW：它会把窗口强行留在任务栏/Alt-Tab 上，
# 而子窗口不该在那里出现。
STRIP_EXSTYLE = WS_EX_APPWINDOW

# "包边层"（画在窗口外围的阴影/外框）被挪去的位置：屏幕外的坐标。
# 用挪走而不是 SW_HIDE，原因见 Absorber._park_companions 的说明。
SHADOW_PARK = -30000
SHADOW_OUTSIDE = -15000        # 横/纵坐标小于它就算"已在屏幕外"

# MoveWindow 不接受 0 尺寸；面板被拖到极小时用这两个值兜底。
PLACE_MIN_W, PLACE_MIN_H = 80, 60


def _park(hwnd):
    """把一个包边层挪到屏幕外；成功返回 True。

    带 SWP_NOSIZE，尺寸参数被系统忽略（保留它原来的大小），所以这里不必
    传宽高 —— 旧代码传了原矩形宽高，看着像"按原尺寸挪"，其实是空参数。
    """
    try:
        if not u32.IsWindow(hwnd):
            return False
        u32.SetWindowPos(hwnd, None, SHADOW_PARK, SHADOW_PARK, 0, 0,
                         SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        return True
    except Exception:
        return False


class Tab(object):
    """一个被吸附的窗口及其还原快照。"""

    __slots__ = ("hwnd", "title", "style", "exstyle", "parent", "rect",
                 "was_iconic", "was_zoomed", "companions", "blank", "rgn")

    def __init__(self, hwnd, was_iconic=False, was_zoomed=False):
        self.hwnd = hwnd
        self.title = win_text(hwnd)
        self.style = get_long(hwnd, GWL_STYLE)
        self.exstyle = get_long(hwnd, GWL_EXSTYLE)
        self.parent = u32.GetParent(hwnd)
        self.rect = win_rect(hwnd) or (100, 100, 900, 600)
        # 吸附前的窗口状态由调用方传进来，不能在这里读：构造 Tab 时窗口已经
        # SW_RESTORE 过，IsIconic/IsZoomed 恒为 False（实测 2026-10-21）。
        self.was_iconic = was_iconic
        self.was_zoomed = was_zoomed
        # 画在这个窗口外围的阴影/外框层 [(hwnd, 原矩形)]，吸附时挪走、释放时归位。
        # 必须在**吸附前**登记，两个原因：此时窗口还在原位，包边层与它位置匹配
        # 才认得出来；一旦把内容窗藏起来，浏览器会顺手把包边层也藏掉。
        self.companions = []
        for h in frame_companions(hwnd):
            rect = win_rect(h)
            if rect:
                self.companions.append((h, rect))
        # 客户区顶部那条"应用自己预留、却画不出来"的空白高度。
        # None = 还没量；首摆（MoveWindow 之后）量一次，之后一直沿用。
        self.blank = None
        # 已设过窗口区域的那个 (w, h, d)，避免每帧重设同一块区域
        self.rgn = None

    def measure_blank(self):
        """量客户区顶部那条空带有多少像素，没有则返回 0。

        文件夹（资源管理器）把标题栏高度烤进了布局：剥掉 WS_CAPTION 后，
        它的内容仍从"原标题栏高度"处开始排，顶部留一条画不出来的空带
        （实测 31px，2026-10-21）。测法：取"直接子窗口"里宽 >= 窗宽一半
        且高 >= 30 的最小 top（相对窗口外框）。

        必须**首摆之后**量：MoveWindow 跨进程同步送达 WM_SIZE，返回时应用
        已按新客户区重排完毕 —— 会自我修正的（记事本/Tk）这时归零，不修正的
        （资源管理器）保持 31，一刀就能分出来。
        """
        wr = wt.RECT()
        u32.GetWindowRect(self.hwnd, ctypes.byref(wr))
        w0 = wr.right - wr.left
        best = None
        proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def cb(h, _l):
            nonlocal best
            if u32.GetParent(h) == self.hwnd:
                r = wt.RECT()
                u32.GetWindowRect(h, ctypes.byref(r))
                if (r.right - r.left >= w0 * 0.5 and r.bottom - r.top >= 30):
                    top = r.top - wr.top
                    if best is None or top < best:
                        best = top
            return True

        u32.EnumChildWindows(self.hwnd, proc(cb), 0)
        if best is not None and 4 <= best <= 96:    # 标题栏高度的正常范围
            return best
        return 0


class Absorber(object):
    """维护"当前吸附的那一个窗口"，并负责吸附 / 释放。"""

    def __init__(self, panel_hwnd_getter, own_pid):
        self._panel_hwnd = panel_hwnd_getter   # callable -> 面板 HWND
        self.own_pid = own_pid
        self.tab = None         # 当前吸附的 Tab；None = 容器是空的
        self.last_stuck = []    # 上次释放没能还原的窗口标题
        self._last_place = None # (hwnd, rect) —— 判断本次摆放是否真的有变化

    # ================= 吸附 =================
    def absorb(self, target):
        """把 target 收进面板。返回 (Tab|None, 提示文案)。

        容器一次只放一个窗口：手里已经有别的窗口时，先把它们还回桌面，再吸
        新的。这条规则放在这里而不是调用方，是为了让"多窗口"在结构上不可能
        出现 —— 面板、托盘、测试都走同一个入口。
        """
        ok, info = is_suitable_target(target, self.own_pid)
        dbg("absorb 请求 target=%s ok=%s info=%r" % (target, ok, info))
        if not ok:
            return None, info
        if self.tab is not None:
            if self.tab.hwnd == target:
                return self.tab, "已在浮坞中"
            done = self.release_all()
            dbg("替换：先释放原窗口，成功 %d" % done)
            if not done:
                return None, "原窗口未能还原，已取消吸附"
        # 最小化/最大化的窗口必须先还原：最小化的窗口摆进去是空的，最大化的
        # 窗口 MoveWindow 只改“还原尺寸”、显示尺寸不动。两个状态都要在还原
        # **之前**取到 —— Tab 取快照时窗口已经被还原，IsIconic/IsZoomed 恒 False
        # （实测 2026-10-21：释放时还不回最小化）。
        was_iconic = bool(u32.IsIconic(target))
        was_zoomed = bool(u32.IsZoomed(target))
        if was_iconic or was_zoomed:
            u32.ShowWindow(target, SW_RESTORE)
            time.sleep(0.15)
        # 先取快照：之后任何一步失败都能逐位还原
        tab = Tab(target, was_iconic, was_zoomed)
        try:
            self._attach(tab)
        except Exception as e:
            dbg("吸附异常，回滚:", e)
            self._detach(tab)
            self._put_back(tab)
            self._restore_companions(tab)
            return None, "吸附失败已回滚：%s" % e
        return tab, "已吸附：%s" % (tab.title or info)

    def _attach(self, tab):
        """改挂到面板下（只换 popup→child）。失败时抛异常，由 absorb 回滚。"""
        u32.ShowWindow(tab.hwnd, SW_HIDE)
        set_long(tab.hwnd, GWL_STYLE,
                 (tab.style & ~STRIP_STYLE) | WS_CHILD)
        set_long(tab.hwnd, GWL_EXSTYLE, tab.exstyle & ~STRIP_EXSTYLE)
        panel = self._panel_hwnd()
        u32.SetParent(tab.hwnd, panel)
        if u32.GetParent(tab.hwnd) != panel:
            raise RuntimeError("该窗口拒绝被吸附（SetParent 失败）")
        u32.SetWindowPos(tab.hwnd, None, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                         | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        u32.ShowWindow(tab.hwnd, SW_SHOW)
        # 包边层必须在 SHOW **之后**处理：浏览器是跟着"窗口可见 + 位置变化"
        # 重画阴影层的，放在 HIDE 之后就等于白做。
        self._park_companions(tab)
        self.tab = tab
        self._last_place = None    # 新吸附的首摆必须强制整面重画（见 place_current）
        dbg("absorb 完成")

    # ================= 阴影 / 外框层 =================
    def _park_companions(self, tab):
        """把画在目标外围的"包边层"挪到屏幕外。

        这类窗口是独立的顶层分层窗口（实测 360 极速浏览器 X 的
        `Chrome_WidgetWin_0`：比内容窗每边大 21px、同进程、顶层、可见）。
        只搬走内容窗的话，它们会留在桌面原位 —— 看着就是一个空边框。

        **为什么是"挪走"而不是 `SW_HIDE`**（实测 2026-10-15）：
        浏览器只在窗口位置/尺寸变化时重画阴影层，而重画就是让它重新可见 ——
        隐藏完一摆放就被亮回来（0.5 秒内必现，反复隐藏只会拉锯闪烁）。
        挪到屏幕外则一劳永逸：重画只更新它的内容、不改位置，用户从此看不到它。
        """
        moved = [hwnd for hwnd, _rect in tab.companions if _park(hwnd)]
        if moved:
            dbg("外框/阴影层已挪到屏幕外：%s" % moved)

    def keep_parked(self):
        """兜底：把又跑回屏幕里的包边层再挪出去。

        名字里的"名单"是吸附时登记的，这里只做位置比对，不重新枚举窗口 ——
        摆放路径是高频的（拖动面板每帧都会走），比对开销必须可忽略。
        名单通常为空，此时一次 API 调用都不会发生。
        """
        if self.tab is None:
            return
        for hwnd, _rect in self.tab.companions:
            cur = win_rect(hwnd)
            if cur and (cur[0] > SHADOW_OUTSIDE or cur[1] > SHADOW_OUTSIDE):
                _park(hwnd)

    def _restore_companions(self, tab):
        """把挪走的包边层放回原位（内容窗回到原位之后再还）。

        名单里都是吸附前可见的窗口，所以这里无条件放回原位即为"还原原状"。
        """
        for hwnd, rect in tab.companions:
            try:
                if u32.IsWindow(hwnd):
                    u32.SetWindowPos(hwnd, None, rect[0], rect[1],
                                     rect[2], rect[3],
                                     SWP_NOZORDER | SWP_NOACTIVATE
                                     | SWP_SHOWWINDOW)
            except Exception:
                pass
        tab.companions = []

    # ================= 摆放 =================
    def place_current(self, x, y, w, h):
        """把当前 tab 的窗口摆进用户区 (x,y,w,h)。坐标是父窗口坐标。

        剥掉样式之后窗口就是一个纯内容面，但有的应用（文件夹）仍在客户区顶部
        给自己留了一条画不出来的空带。这里量出来、整体上移给它补掉，再用窗口
        区域把那一条裁到外面 —— 用户区里看到的只有内容，没有缝。
        """
        if self.tab is None or not u32.IsWindow(self.tab.hwnd):
            return
        tab = self.tab
        W, H = max(w, PLACE_MIN_W), max(h, PLACE_MIN_H)
        first = tab.blank is None
        if first:
            # 首摆：先按用户区原样摆一次，应用收到 WM_SIZE 后才会把内容排好，
            # 那时才量得准它自己在顶部留了多高一条空带。
            u32.MoveWindow(tab.hwnd, x, y, W, H, True)
            tab.blank = tab.measure_blank()
            dbg("空带测量 blank=%s title=%r" % (tab.blank, tab.title))
        d = tab.blank
        if d:
            # 空带在窗口顶部：窗口上移 d、高加 d，再把顶部 d 裁掉 ——
            # 可见部分正好落在用户区里（实测文件夹窗口 d=31）。
            if tab.rgn != (W, H, d):
                u32.SetWindowRgn(tab.hwnd, gdi32.CreateRectRgn(0, d, W, d + H),
                                 True)
                tab.rgn = (W, H, d)
            rect = (x, y - d, W, H + d)
        else:
            rect = (x, y, W, H)
        # 首摆且不需要补位时，上面那次 MoveWindow 已经是最终位置，不必重发
        if d or not first:
            u32.MoveWindow(tab.hwnd, rect[0], rect[1], rect[2], rect[3], True)
        # 关键：提到兄弟窗口（Tk 画布）之上，否则会被画布盖住
        u32.SetWindowPos(tab.hwnd, 0, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        # 几何一变就强制整面重画：只重画"自己认为变了"的区域的程序（浏览器
        # 外壳这类）会在缩放后把旧内容留在边上。尺寸没变就不打扰。
        if self._last_place != (tab.hwnd, rect):
            u32.RedrawWindow(tab.hwnd, None, None, RDW_REPAINT_ALL)
            self._last_place = (tab.hwnd, rect)
        # MoveWindow 会让浏览器重画它的阴影层，顺手确认它还躺在屏幕外
        self.keep_parked()

    # ================= 状态查询 =================
    def alive_title(self):
        """(标题, 是否还有效)；容器空着时返回 None。供绘制层与状态栏用。"""
        tab = self.tab
        if tab is None:
            return None
        if u32.IsWindow(tab.hwnd):
            return win_text(tab.hwnd) or "(未命名)", True
        return tab.title + "（已失效）", False

    def prune_dead(self):
        """窗口自己关掉了就从容器里清掉，返回是否真清了一个。

        窗口虽然没了，但它的外框层是独立 HWND，可能还活着 —— 顺手还原，
        别让它一直停在隐藏态。
        """
        tab = self.tab
        if tab is None or u32.IsWindow(tab.hwnd):
            return False
        self._restore_companions(tab)
        self.tab = None
        return True

    # ================= 释放 =================
    def release(self):
        """把当前窗口还回桌面。返回是否成功（容器空着时返回 False）。"""
        tab = self.tab
        if tab is None:
            return False
        self.tab = None
        return self._release(tab)

    def release_all(self, tries=2):
        """把当前窗口还回去，返回"成功还原"的个数（0 或 1）。

        名字保留"all"是为了与退出路径、托盘菜单的说法一致 —— 容器只有一个
        窗口，这里就是全部。

        退出路径也走这里，所以失败要重试：一次不成便整段放弃的话，没还回去
        的窗口会作为面板的子窗口被一起销毁（跨进程父子关系），那是真的把别人
        的窗口弄没了。窗口自己先关掉的，不算失败、也不计入。
        """
        tab = self.tab
        self.tab = None
        self.last_stuck = []
        if tab is None:
            return 0
        for _attempt in range(max(1, tries)):
            if self._release(tab):
                return 1
            if not u32.IsWindow(tab.hwnd):
                return 0            # 窗口自己已经没了，不需要还原
            time.sleep(0.12)
        if u32.IsWindow(tab.hwnd):
            self.last_stuck = [tab.title]
            dbg("警告：窗口未能还原：%s" % self.last_stuck)
        return 0

    def _release(self, tab):
        try:
            if not u32.IsWindow(tab.hwnd):
                return False
            u32.ShowWindow(tab.hwnd, SW_HIDE)
            if tab.rgn:
                # 先解除"空带裁剪"，否则还原后的窗口顶部少一条
                u32.SetWindowRgn(tab.hwnd, None, True)
                tab.rgn = None
            self._detach(tab)
            self._put_back(tab)
            self._restore_companions(tab)   # 内容窗回位后再亮出外围的框
            if tab.was_zoomed:      # 吸附前是最大化的，就还它一个最大化
                u32.ShowWindow(tab.hwnd, SW_MAXIMIZE)
            elif tab.was_iconic:    # 吸附前是最小化的，就还它一个最小化
                u32.ShowWindow(tab.hwnd, SW_MINIMIZE)
            return True
        except Exception:
            return False

    # ---- 还原的两个基本动作 ----
    def _detach(self, tab):
        """摘下父子关系并恢复原来的窗口样式。

        SetParent 在目标进程正忙、或对方拒绝改父时会失败。这时退一步把窗口
        挂到桌面：宁可它回不到原来的父窗口，也绝不能让别人的窗口继续挂在
        面板下 —— 面板一退出，还挂着的子窗口会被系统一起销毁。
        """
        u32.SetParent(tab.hwnd, tab.parent)
        if u32.GetParent(tab.hwnd) != tab.parent:
            dbg("回原父窗口失败，改挂桌面 hwnd=%s 原父=%s"
                % (tab.hwnd, tab.parent))
            u32.SetParent(tab.hwnd, None)
        set_long(tab.hwnd, GWL_STYLE, tab.style)
        set_long(tab.hwnd, GWL_EXSTYLE, tab.exstyle)

    @staticmethod
    def _put_back(tab):
        """放回桌面原来的位置并显示。"""
        u32.SetWindowPos(tab.hwnd, None, tab.rect[0], tab.rect[1],
                         tab.rect[2], tab.rect[3],
                         SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
