# -*- coding: utf-8 -*-
"""替换确认：吸附新窗口前，先讲清楚"当前那个会被还回桌面"。

浮坞一次只放一个窗口，换窗口就得先把旧的还回去。这件事第一次发生时必须
让用户知道（否则他会以为刚才那个窗口被吞了），之后由「不再提醒」接管。

返回值就是全部契约：(是否继续, 是否不再提醒)。关窗 / Esc 一律算取消。

为什么不用 messagebox：它带不了「不再提醒」这个勾选框，而"每次吸附都弹一次"
正是要靠这个勾选框才免掉的。
"""
import tkinter as tk

import appicon
import theme as T
from debug import dbg

PAD = 16
WRAP = 380                     # 说明文字的折行宽度（窗口宽度由内容决定）


def ask_replace(parent, panel_rect, old_title, new_title):
    """模态确认。返回 (继续?, 不再提醒?)。"""
    state = {"ok": False, "no_more": False}

    d = tk.Toplevel(parent)
    d.title(appicon.APP_TITLE)
    d.configure(bg=T.C_BG)
    d.resizable(False, False)
    d.attributes("-topmost", True)
    d.transient(parent)
    d.columnconfigure(0, weight=1)

    no_more = tk.BooleanVar(value=False)

    def finish(ok):
        state["ok"] = ok
        state["no_more"] = bool(no_more.get())
        d.destroy()

    tk.Label(d, text="浮坞一次只放一个窗口", bg=T.C_BG, fg=T.C_ACC,
             font=(T.FONT, -12, "bold"), anchor="w").grid(
        row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 6))
    tk.Label(d,
             text=("吸附「%s」会先把当前的「%s」原样还原回桌面。\n要继续吗？"
                   % (new_title or "新窗口", old_title or "当前窗口")),
             bg=T.C_BG, fg=T.C_FG, font=(T.FONT, -10), justify="left",
             anchor="w", wraplength=WRAP).grid(
        row=1, column=0, sticky="ew", padx=PAD)

    tk.Checkbutton(d, text="以后不再提醒（直接替换）", variable=no_more,
                   bg=T.C_BG, fg=T.C_DIM, selectcolor=T.C_BAR,
                   activebackground=T.C_BG, activeforeground=T.C_FG,
                   highlightthickness=0, bd=0, font=(T.FONT, -10)).grid(
        row=2, column=0, sticky="w", padx=PAD, pady=(12, 0))

    row = tk.Frame(d, bg=T.C_BG)
    row.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(16, PAD))
    tk.Button(row, text="先释放，再吸附", command=lambda: finish(True),
              bg=T.C_ACC, fg=T.C_ON_ACC, activebackground=T.C_ACC,
              activeforeground=T.C_ON_ACC, relief="flat", bd=0, padx=14,
              font=(T.FONT, -11, "bold")).pack(side="right")
    tk.Button(row, text="取消", command=lambda: finish(False),
              bg=T.C_BAR2, fg=T.C_FG, activebackground=T.C_BAR,
              activeforeground=T.C_FG, relief="flat", bd=0, padx=14,
              font=(T.FONT, -11)).pack(side="right", padx=(0, 8))

    d.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    d.bind("<Escape>", lambda _e: finish(False))
    d.bind("<Return>", lambda _e: finish(True))

    _place(d, panel_rect)
    try:
        d.grab_set()               # 模态：确认期间点不到面板
        d.focus_force()
    except Exception as e:
        dbg("确认窗聚焦失败", e)
    d.wait_window()
    dbg("替换确认 ok=%s no_more=%s" % (state["ok"], state["no_more"]))
    return state["ok"], state["no_more"]


def _place(d, panel_rect):
    """贴着面板放；越界就夹回屏幕内。"""
    px, py, pw, ph = panel_rect
    d.update_idletasks()
    dw, dh = d.winfo_reqwidth(), d.winfo_reqheight()
    x = px + (pw - dw) // 2
    y = py + (ph - dh) // 3
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    d.geometry("+%d+%d" % (max(8, min(x, sw - dw - 8)),
                           max(8, min(y, sh - dh - 48))))
    d.lift()
