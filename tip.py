# -*- coding: utf-8 -*-
"""赞赏码窗口：把 donation.png 按原图 25% 显示出来。

入口只有一个 —— 标题栏标题后面的 ♥（托盘菜单也有一项）。做成非模态的
独立窗口，理由和设置窗一样：它不改变浮坞的任何状态，没有"必须回答"
的问题，拦着用户反而碍事。

图不重采样，只按整数倍 subsample（逐像素抽取）。二维码最怕插值：一旦
像素被混色，模块边界糊掉，手机就扫不出来。

显示比例固定为原图的 1/4（25%）：赞赏码分辨率远高于扫码所需，缩到 25%
仍然清晰可扫，而弹窗能小很多，不占半屏。
"""
import base64
import os
import pathlib
import tkinter as tk

import appicon
import theme as T
from debug import dbg

PAD = 16
PATH = os.path.join(appicon.APP_DIR, "donation.png")

# 显示比例：原图的 1/4（25%）。658px 的赞赏码缩到 165px 仍好扫，
# 弹窗却只有原图四分之一的面积 —— 赞赏是顺手的事，不该占掉半屏。
SCALE = 4

# 兜底：屏幕小到连 25% 都放不下时，再往下整数倍缩。图片最多占屏幕
# 高度的 78%，再扣掉标题/说明/按钮大约这么高。
CHROME_H = 150
SCREEN_RATIO = 0.78

MISSING = ("找不到赞赏码图片（donation.png）\n"
           "请把图片放回程序目录后重新打开。")


def show(parent, on_close=None):
    """打开赞赏窗，返回 Toplevel。重复调用由调用方（panel）去重。"""
    d = tk.Toplevel(parent)
    d.title(appicon.APP_NAME + " · 赞赏")
    d.configure(bg=T.C_BG)
    d.resizable(False, False)
    d.attributes("-topmost", True)
    # 不设 transient：Win32 的 owned window 会随 owner 一起隐藏，而托盘的
    # 「赞赏支持」可以在面板收起时点开（设置窗也是同样的做法）。
    d.columnconfigure(0, weight=1)

    closed = {"done": False}

    def finish():
        if closed["done"]:
            return
        closed["done"] = True
        if on_close is not None:
            try:
                on_close()
            except Exception as e:
                dbg("赞赏窗关闭回调异常", e)
        d.destroy()

    tk.Label(d, text="赞赏支持", bg=T.C_BG, fg=T.C_TIP,
             font=(T.FONT, -13, "bold"), anchor="w").grid(
        row=0, column=0, sticky="ew", padx=PAD, pady=(PAD, 4))
    tk.Label(d,
             text=("浮坞开源、免费，赞赏完全自愿，不影响任何功能。\n"
                   "如果觉得还不错，可以扫码请我喝杯咖啡。"),
             bg=T.C_BG, fg=T.C_FG, font=(T.FONT, -13), justify="left",
             anchor="w").grid(row=1, column=0, sticky="ew", padx=PAD)

    img = _load(d)
    if img is None:
        tk.Label(d, text=MISSING, bg=T.C_BG, fg=T.C_DIM, justify="left",
                 anchor="w", font=(T.FONT, -10)).grid(
            row=2, column=0, sticky="ew", padx=PAD, pady=(PAD, 0))
    else:
        # 白底图放在深色弹窗里像一块贴纸：给一圈细边，让它看起来是"一张卡片"。
        # 图片引用挂在 Label 上，否则被回收后窗口只剩空白。
        holder = tk.Frame(d, bg=T.C_LINE, bd=0)
        holder.grid(row=2, column=0, padx=PAD, pady=(PAD, 0))
        lbl = tk.Label(holder, image=img, bg="#ffffff", bd=0)
        lbl.image = img
        lbl.pack(padx=1, pady=1)

    # 不放「关闭」按钮：这个窗没有要"确认"的东西，系统标题栏的 × 就够了。
    # 窗里多一个按钮，本来就很小的弹窗又要高一截。
    tk.Label(d, text="用微信扫码", bg=T.C_BG, fg=T.C_DIM,
             font=(T.FONT, -13), anchor="center").grid(
        row=3, column=0, sticky="ew", padx=PAD, pady=(10, PAD))

    # 唯一的关窗入口：标题栏 ×。它照样走 finish()，关闭回调不会漏。
    d.protocol("WM_DELETE_WINDOW", finish)
    _place(d, parent)
    try:
        d.focus_force()
    except Exception as e:
        dbg("赞赏窗聚焦失败", e)
    return d


def fit_factor(px, screen_h):
    """缩小几倍。基准就是 SCALE（25%），只有屏幕放不下才继续往下缩。"""
    avail = max(160, int(screen_h * SCREEN_RATIO) - CHROME_H)
    factor = SCALE
    while px // factor > avail:
        factor += 1
    return factor


def _load(master):
    """读图并缩小；读不到 / 解不开都返回 None，由调用方显示兜底文案。

    走 base64 的 data= 而不是 file=：安装目录可能带中文（本机就是
    ``.../浮坞-FloatDock/``），Tk 对 file= 的路径编码依赖平台设置；
    交给 Python 读字节再递进去，路径就与 Tk 无关了。
    """
    try:
        blob = pathlib.Path(PATH).read_bytes()
    except OSError as e:
        dbg("赞赏码读取失败：%s" % PATH, e)
        return None
    try:
        img = tk.PhotoImage(master=master,
                            data=base64.b64encode(blob).decode("ascii"))
    except Exception as e:
        dbg("赞赏码解码失败", e)
        return None
    factor = fit_factor(img.height(), master.winfo_screenheight())
    return img.subsample(factor, factor)


def _place(d, parent):
    """放在面板旁边（先左后右），两边都放不下才居中夹回屏幕。

    不压在面板上：面板常驻屏幕右侧，它左边几乎总是空的；而盖住面板只会
    让人看不清这个窗口是从哪冒出来的。多显示器时面板可能在负坐标，所以
    最后一律夹回当前屏幕。
    """
    d.update_idletasks()
    dw, dh = d.winfo_reqwidth(), d.winfo_reqheight()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
    except Exception:
        px, py, pw, ph = 0, 0, 0, 0
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    gap = 12
    x = px - dw - gap
    if x < 8:
        x = px + pw + gap
    if x + dw > sw - 8:
        x = px + (pw - dw) // 2
    y = py + (ph - dh) // 3
    d.geometry("+%d+%d" % (max(8, min(x, sw - dw - 8)),
                           max(8, min(y, sh - dh - 56))))
    d.lift()
