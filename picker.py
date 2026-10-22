# -*- coding: utf-8 -*-
"""拖拽拾取器：在全屏跟随鼠标高亮一个目标窗口，松开左键后交回它的句柄。

用轮询而不是鼠标钩子：目标会随鼠标移动不停变化，轮询简单可靠，
而且拾取只在用户按住按钮的短短几秒内运行，开销可以忽略。
"""
import tkinter as tk

from debug import dbg
from winapi import (GWL_EXSTYLE, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE,
                    WS_EX_TOPMOST)
from wndutil import get_long, set_long, root_of, point_window, win_rect, \
    win_text, win_class, lbutton_up

HIGHLIGHT_COLOR = "#ff4d4d"     # 目标窗口的描边色
POLL_MS = 30
_KEY_COLOR = "#010101"          # 用 transparentcolor 抠掉的背景色


class WindowPicker(object):
    """「按住拖动到目标窗口上松开」这套交互的实现。"""

    def __init__(self, root, on_target, on_done):
        self.root = root
        self._on_target = on_target     # (标题) -> None，用来更新状态栏提示
        self._on_done = on_done         # (hwnd 或 None) -> None
        self.active = False
        self.target = None
        self._win = None
        self._cv = None

    # ================= 生命周期 =================
    def start(self):
        if self.active:
            return
        self.active = True
        self.target = None
        self._make_overlay()
        self.root.after(POLL_MS, self._poll)

    def cancel(self):
        """用户按 Esc：放弃这次拾取。"""
        if self.active:
            self._finish(None)

    # ================= 内部 =================
    def _make_overlay(self):
        """建一个点不透、不抢焦点、永远置顶的高亮层。"""
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", _KEY_COLOR)
        cv = tk.Canvas(win, bg=_KEY_COLOR, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True)
        win.update_idletasks()
        hwnd = root_of(win.winfo_id())
        ex = get_long(hwnd, GWL_EXSTYLE)
        set_long(hwnd, GWL_EXSTYLE,
                 ex | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
        self._win, self._cv = win, cv

    def _poll(self):
        if not self.active:
            return
        target = point_window()
        if target != self.target:
            self.target = target
            dbg("拾取目标变更:", target, win_text(target))
            self._highlight(target)
        if lbutton_up():
            self._finish(self.target)
            return
        self.root.after(POLL_MS, self._poll)

    def _highlight(self, target):
        rect = win_rect(target) if target else None
        if rect:
            x, y, w, h = rect
            self._win.geometry("%dx%d+%d+%d" % (w, h, x, y))
            self._cv.delete("all")
            self._cv.create_rectangle(1, 1, w - 2, h - 2,
                                      outline=HIGHLIGHT_COLOR, width=3)
            self._on_target(win_text(target) or win_class(target))
        self._win.deiconify()

    def _finish(self, target):
        self.active = False
        self.target = None
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = self._cv = None
        self._on_done(target)
