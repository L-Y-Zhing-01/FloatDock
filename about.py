# -*- coding: utf-8 -*-
"""「关于」框：版本、许可、源码、反馈与图标来源的唯一来源。

托盘右键「关于浮坞」与设置窗口底部的「许可与来源」都走这里，所以文案不会
出现两套。**任何需要改地址、改邮箱、改许可措辞的地方，只改本文件**。

为什么不用 messagebox：它的正文不能被选中、也不能放按钮，而"源码地址"和
"反馈邮箱"正是要让人复制走的。这里用自绘 Toplevel，值放在只读 Entry 里，
可以直接选中复制，另外给一个"复制邮箱"按钮兜底。

不设 transient：浮坞是 overrideredirect 的悬浮窗，一旦成为它的 owned window，
面板自动隐藏（withdraw）时关于框会跟着一起消失 —— 与 tip.py 踩过的是同一个坑。
"""
import tkinter as tk
import webbrowser

import appicon
import theme as T
from debug import dbg

PAD = 16
WRAP = 360

REPO_URL = "https://github.com/L-Y-Zhing-01/FloatDock"
FEEDBACK_MAIL = "906571651@qq.com"
LICENSE_NAME = "MIT"
AUTHOR = "难上南山"


def _copy(d, text, note=None):
    """把 text 写进剪贴板；note 是给调用方的可选回显控件。"""
    try:
        d.clipboard_clear()
        d.clipboard_append(text)
        d.update_idletasks()        # 让剪贴板立刻持有内容，不依赖后续事件
    except Exception as e:
        dbg("复制失败", e)
        return
    if note is not None:
        try:
            note.configure(text="已复制")
        except Exception:
            pass


def open_about(parent, version, hotkey_label=None, panel_rect=None,
               on_closed=None):
    """打开关于框（非模态）。返回 Toplevel 对象，由调用方记着它。"""
    d = tk.Toplevel(parent)
    d.title("关于 " + appicon.APP_TITLE)
    d.configure(bg=T.C_BG)
    d.resizable(False, False)
    d.attributes("-topmost", True)
    d.columnconfigure(0, weight=1)

    def close():
        try:
            d.destroy()
        except Exception:
            pass
        if on_closed is not None:
            on_closed()

    d.protocol("WM_DELETE_WINDOW", close)
    d.bind("<Escape>", lambda _e: close())

    # ---- 头：产品名 + 版本 ----
    head = tk.Frame(d, bg=T.C_BG)
    head.grid(row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))
    tk.Label(head, text=appicon.APP_NAME, bg=T.C_BG, fg=T.C_FG,
             font=(T.FONT, -18, "bold")).pack(side="left")
    tk.Label(head, text=appicon.SUBTITLE, bg=T.C_BG, fg=T.C_DIM,
             font=(T.FONT, -12)).pack(side="left", padx=(6, 0), pady=(4, 0))
    tk.Label(head, text=version, bg=T.C_BG, fg=T.C_ACC,
             font=(T.FONT, -11, "bold")).pack(side="right", pady=(4, 0))

    tk.Label(d, text="悬浮窗口容器：悬停显示 / 移开隐藏，把任意窗口拖进面板继续用。",
             bg=T.C_BG, fg=T.C_DIM, font=(T.FONT, -10), justify="left",
             anchor="w", wraplength=WRAP).grid(
        row=1, column=0, sticky="ew", padx=PAD)

    if hotkey_label:
        tk.Label(d, text="当前全局热键：%s（可在设置里改）" % hotkey_label,
                 bg=T.C_BG, fg=T.C_DIM, font=(T.FONT, -10), anchor="w").grid(
            row=2, column=0, sticky="ew", padx=PAD, pady=(4, 0))

    # ---- 分隔线 ----
    tk.Frame(d, bg=T.C_LINE, height=1).grid(
        row=3, column=0, sticky="ew", padx=PAD, pady=(12, 10))

    # ---- 许可 / 源码 / 反馈 / 图标来源 ----
    info = tk.Frame(d, bg=T.C_BG)
    info.grid(row=4, column=0, sticky="ew", padx=PAD)
    info.columnconfigure(1, weight=1)

    def line(row, name, value, copyable=False):
        tk.Label(info, text=name, bg=T.C_BG, fg=T.C_DIM, font=(T.FONT, -10),
                 anchor="w").grid(row=row, column=0, sticky="nw", pady=2)
        if copyable:
            var = tk.StringVar(master=d, value=value)
            ent = tk.Entry(info, textvariable=var, bg=T.C_BAR, fg=T.C_FG,
                           relief="flat", bd=0, readonlybackground=T.C_BAR,
                           state="readonly", font=(T.FONT, -10),
                           highlightthickness=0, width=len(value))
            ent.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=2,
                     ipady=2)
            ent.bind("<FocusIn>", lambda _e, w=ent: w.selection_range(0, "end"))
        else:
            tk.Label(info, text=value, bg=T.C_BG, fg=T.C_FG, font=(T.FONT, -10),
                     justify="left", anchor="w", wraplength=WRAP - 60).grid(
                row=row, column=1, sticky="ew", padx=(8, 0), pady=2)

    line(0, "许可", "代码 %s（可自由使用、修改、分发，保留版权与许可声明）；"
                    "图标、赞赏码与名称另附条款" % LICENSE_NAME)
    line(1, "源码", REPO_URL, copyable=True)
    line(2, "反馈", FEEDBACK_MAIL, copyable=True)
    line(3, "图标", "由 AI 绘图工具 WorkBuddy 生成，经作者定稿修订后使用")

    # ---- 版权与按钮 ----
    tk.Label(d, text="Copyright (c) 2026 %s" % AUTHOR, bg=T.C_BG, fg=T.C_DIM,
             font=(T.FONT, -9), anchor="w").grid(
        row=5, column=0, sticky="ew", padx=PAD, pady=(12, 0))

    foot = tk.Frame(d, bg=T.C_BG)
    foot.grid(row=6, column=0, sticky="ew", padx=PAD, pady=(12, PAD))
    hint = tk.Label(foot, text="", bg=T.C_BG, fg=T.C_ACC, font=(T.FONT, -9))
    hint.pack(side="left")

    tk.Button(foot, text="关闭", command=close, bg=T.C_BAR2, fg=T.C_FG,
              activebackground=T.C_BAR, activeforeground=T.C_FG, relief="flat",
              bd=0, padx=14, font=(T.FONT, -11)).pack(side="right")
    tk.Button(foot, text="复制邮箱",
              command=lambda: _copy(d, FEEDBACK_MAIL, hint),
              bg=T.C_BAR2, fg=T.C_FG, activebackground=T.C_BAR,
              activeforeground=T.C_FG, relief="flat", bd=0, padx=12,
              font=(T.FONT, -10)).pack(side="right", padx=(0, 8))
    tk.Button(foot, text="打开源码页", command=lambda: _open_url(d, REPO_URL),
              bg=T.C_ACC, fg=T.C_ON_ACC, activebackground=T.C_ACC,
              activeforeground=T.C_ON_ACC, relief="flat", bd=0, padx=12,
              font=(T.FONT, -10, "bold")).pack(side="right", padx=(0, 8))

    _place(d, panel_rect)
    try:
        d.focus_force()
    except Exception as e:
        dbg("关于框聚焦失败", e)
    return d


def _open_url(d, url):
    """交给系统默认浏览器；失败只记日志，不弹错框打扰用户。"""
    try:
        webbrowser.open(url)
    except Exception as e:
        dbg("打开链接失败", e)


def _place(d, panel_rect):
    """贴着面板居中放；没有面板矩形就落在屏幕中央，最后统一夹回屏幕内。"""
    d.update_idletasks()
    dw, dh = d.winfo_reqwidth(), d.winfo_reqheight()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    if panel_rect:
        px, py, pw, ph = panel_rect[:4]
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 3
    else:
        x = (sw - dw) // 2
        y = (sh - dh) // 3
    d.geometry("+%d+%d" % (max(8, min(x, sw - dw - 8)),
                           max(8, min(y, sh - dh - 48))))
    d.lift()
