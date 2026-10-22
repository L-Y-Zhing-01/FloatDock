# -*- coding: utf-8 -*-
"""按钮悬停提示：鼠标停在按钮上，就在它正下方弹出一条小字。

为什么必须是个独立顶层窗，而不是画在画布上：标题栏下方就是内容区，那一片
被 SetParent 进来的原生子窗口占着，画布上的图元会被它整块盖住 —— 透明度
浮层因此只能待在标题栏内，提示条没法照办（它天生要跨到按钮下面去）。
于是做成 overrideredirect + topmost 的小窗：不进任务栏、不抢焦点、不拦
鼠标（鼠标还停在按钮上，光标并没有跑进这条提示里）。

为什么自己写而不是引第三方：Tk 没有内建 tooltip，装一个库就要在安装程序
里多拆一份包；而这里只需要"显示一段字 + 夹回屏幕"，三十行足够。
"""
import tkinter as tk

import theme as T
import wndutil
from debug import dbg
from winapi import (GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
                    WS_EX_TRANSPARENT)

# 悬停多久才出现。太短会在掠过按钮时一路闪；太长像没反应。
DELAY_MS = 380
GAP = 6                     # 提示条顶边与按钮底边的间距
PAD_X, PAD_Y = 8, 4         # 文字与边框的内边距，也是"气泡"的胖瘦


def _click_through(win):
    """让提示条"看得见、点不到"：鼠标消息穿透到它下面的窗口去。

    提示条挂在按钮下方 6px，那一带已经是内容区 —— 面板自己占的空白，或者
    被 SetParent 进来的那个程序。它要是接收鼠标，用户想点内容区顶部就会先
    点在一条 26px 高的提示上，第一下被白白吃掉，像"点了没反应"。

    WS_EX_TRANSPARENT 就是"画出来但不参与命中测试"；TOOLWINDOW 让它不进
    任务栏与 Alt-Tab，NOACTIVATE 保证出来时焦点不跳。设不上也不影响显示，
    只是会重新吃那一下点击 —— 所以这里只记日志，不往外抛。
    """
    try:
        win.update_idletasks()
        hwnd = wndutil.root_of(win.winfo_id())
        style = wndutil.get_long(hwnd, GWL_EXSTYLE)
        wndutil.set_long(hwnd, GWL_EXSTYLE,
                         style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
                         | WS_EX_NOACTIVATE)
    except Exception as e:
        dbg("提示条设为点击穿透失败", e)


class Hint(object):
    """一次只显示一条提示。调用方每次鼠标移动都喂它当前该显示什么。"""

    def __init__(self, root):
        self._root = root
        self._win = None        # 正在显示的 Toplevel
        self._text = None       # 它上面写的字（None = 没显示）
        self._pending = None    # 已排上延迟、还没到点的文案
        self._job = None        # 延迟定时器
        self._at = (0, 0)       # 提示条顶边中点要对准的屏幕坐标

    # ================= 对外 =================
    def schedule(self, text, x, y):
        """请求显示 text，顶边中点对准屏幕坐标 (x, y)。

        同一个按钮上移动鼠标会反复调到这里：文案没变就只挪位置，不重新
        计时 —— 否则手一抖，提示就永远出不来。
        """
        self._at = (x, y)
        if text == self._text:
            if self._win is not None:
                self._place()
            return
        if text == self._pending:
            return
        self.hide()
        self._pending = text
        self._job = self._root.after(DELAY_MS, self._reveal)

    def hide(self):
        """收起提示，并取消还没到点的显示。重复调用无副作用。"""
        if self._job is not None:
            try:
                self._root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self._pending = None
        self._text = None
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None

    # ================= 内部 =================
    def _reveal(self):
        self._job = None
        text, self._pending = self._pending, None
        if not text:
            return
        win = tk.Toplevel(self._root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        # 不用 Frame 描边：底色铺满、Label 内缩 1px，露出来的那一圈就是边。
        win.configure(bg=T.C_HINT_LINE)
        tk.Label(win, text=text, bg=T.C_HINT_BG, fg=T.C_FG, bd=0,
                 font=(T.FONT, -10), padx=PAD_X, pady=PAD_Y).pack(padx=1, pady=1)
        self._win, self._text = win, text
        _click_through(win)
        self._place()

    def _place(self):
        """顶边中点对准目标；越出屏幕就夹回来（面板可能贴着屏幕边缘）。"""
        win = self._win
        if win is None:
            return
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x, y = self._at
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        left = max(4, min(x - w // 2, sw - w - 4))
        top = max(4, min(y, sh - h - 4))
        win.geometry("+%d+%d" % (left, top))
