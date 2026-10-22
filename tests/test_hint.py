# -*- coding: utf-8 -*-
"""悬停提示：哪一个按钮说什么、什么时候出现、出现在哪。

全部在本进程的 Tk 里跑完 —— 不启动浮坞、不碰托盘线程、不动你的 config：

    python tests/test_hint.py

三条判据值得单独说：
  · **延迟**不能靠"睡够 380ms 就一定在"来验，反过来要验"不到点一定不在"，
    否则这个测试只能证明定时器没崩，证明不了它有延迟。
  · **同一文案反复 schedule 不能重置计时**。鼠标在按钮上抖一像素就重排一次
    的话，手一停反而永远不出提示 —— 这个缺陷肉眼很难复现，只能在这里锁住。
  · **位置**要验"顶边中点在按钮中心线上"，不是"大致在下面"：提示条长得
    比按钮宽得多，偏移 3px 看不出来，偏 30px 就像指错了按钮。
"""
import os
import sys
import time
import tkinter as tk
from ctypes import wintypes as wt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import hint                                     # noqa: E402
import panel                                    # noqa: E402
import render                                   # noqa: E402
import theme as T                               # noqa: E402
import wndutil                                  # noqa: E402
from winapi import (GWL_EXSTYLE, WS_EX_NOACTIVATE,   # noqa: E402
                    WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT, u32)

CK = H.Checker("悬停提示")

root = tk.Tk()
root.withdraw()                                 # 不占桌面，Toplevel 照样能建


def pump(ms):
    """让 Tk 处理事件与 after 定时器，持续 ms 毫秒（含真实的时钟流逝）。"""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        root.update()
        time.sleep(0.01)


class Fake(object):
    """只借 `_hint_text` 用：它除 self.locked 之外不碰面板的任何状态。"""

    def __init__(self, locked=False):
        self.locked = locked


hint_text = panel.FloatDock._hint_text

# ================= 1. 每个按钮都要有话说 =================
print("=== 1. 每个按钮都有提示文案 ===")
cv = tk.Canvas(root, width=470, height=660, bg=T.C_BG, highlightthickness=0)
hits = render.draw(cv, render.View(w=470, h=660, opacity=1.0, locked=False,
                                  shown=True, msg="", msg_is_err=False,
                                  hotkey_label="Ctrl+Alt+D", tab=None,
                                  popup=None))
payloads = sorted({h.payload for h in hits if h.kind == "btn"})
print("  画出来的按钮:", payloads)
for name in payloads:
    text = hint_text(Fake(), render.Hit("btn", (0, 0, 1, 1), name))
    CK.ok("按钮 %-8s 有提示：%r" % (name, text), bool(text))

# release 只在有窗口时可点（render 那时才产出命中区），文案仍在表里
CK.ok("release 有提示（有窗口时才会画出来）",
      bool(hint_text(Fake(), render.Hit("btn", (0, 0, 1, 1), "release"))),
      panel.BTN_HINTS.get("release"))

# ================= 2. 锁定按钮的文案随状态走 =================
print("\n=== 2. 锁 / 解锁文案 ===")
lock_hit = render.Hit("btn", (0, 0, 1, 1), "lock")
CK.ok("未锁定时说「锁定」", "锁定" in hint_text(Fake(False), lock_hit),
      hint_text(Fake(False), lock_hit))
CK.ok("已锁定时说「解锁」", "解锁" in hint_text(Fake(True), lock_hit),
      hint_text(Fake(True), lock_hit))
CK.ok("两句话不相同", hint_text(Fake(False), lock_hit)
      != hint_text(Fake(True), lock_hit))

# ================= 3. 不该有提示的地方就没有 =================
print("\n=== 3. 非按钮不给提示 ===")
CK.ok("标题拖拽区没有提示",
      hint_text(Fake(), render.Hit("title", (0, 0, 1, 1), None)) is None)
CK.ok("浮层没有提示",
      hint_text(Fake(), render.Hit("popup", (0, 0, 1, 1), None)) is None)
CK.ok("滑块没有提示",
      hint_text(Fake(), render.Hit("slider", (0, 0, 1, 1), None)) is None)
CK.ok("未知按钮名没有提示",
      hint_text(Fake(), render.Hit("btn", (0, 0, 1, 1), "nope")) is None)
CK.ok("没有命中就没有提示", hint_text(Fake(), None) is None)

# ================= 4. 延迟：不到点不出现 =================
print("\n=== 4. 悬停延迟 ===")
h = hint.Hint(root)
h.schedule("甲", 400, 300)
pump(140)
CK.ok("%dms 内不出现（%dms 延迟）" % (hint.DELAY_MS, hint.DELAY_MS),
      h._win is None, hint.DELAY_MS)
pump(400)
CK.ok("过了延迟就出现", h._win is not None)
CK.ok("文案就是喂进去的那句", h._text == "甲", h._text)

# ================= 5. 位置：顶边中点对准按钮中心 =================
print("\n=== 5. 位置与出屏夹回 ===")
w = h._win
w.update_idletasks()
cx = w.winfo_rootx() + w.winfo_width() // 2
CK.ok("顶边中点在给定的 x 上（±2px）", abs(cx - 400) <= 2, (cx, 400))
CK.ok("顶边落在给定的 y 上（±2px）", abs(w.winfo_rooty() - 300) <= 2,
      (w.winfo_rooty(), 300))

sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
h.hide()
h.schedule("乙", 0, 0)
pump(hint.DELAY_MS + 160)
CK.ok("贴左上角时不出屏", bool(h._win)
      and h._win.winfo_rootx() >= 4 and h._win.winfo_rooty() >= 4,
      (h._win.winfo_rootx(), h._win.winfo_rooty()) if h._win else None)

h.hide()
h.schedule("丙", sw, sh)
pump(hint.DELAY_MS + 160)
CK.ok("贴右下角时不出屏", bool(h._win)
      and h._win.winfo_rootx() + h._win.winfo_width() <= sw - 3
      and h._win.winfo_rooty() + h._win.winfo_height() <= sh - 3,
      (h._win.geometry() if h._win else None, sw, sh))

# ================= 5b. 它只是"画上去"，不该参与鼠标命中 =================
print("\n=== 5b. 点击穿透 ===")
hwnd = wndutil.root_of(h._win.winfo_id())
ex = wndutil.get_long(hwnd, GWL_EXSTYLE)
CK.ok("带 WS_EX_TRANSPARENT（点击落到下面的窗口）",
      bool(ex & WS_EX_TRANSPARENT), hex(ex))
CK.ok("带 WS_EX_TOOLWINDOW（不进任务栏 / Alt-Tab）",
      bool(ex & WS_EX_TOOLWINDOW), hex(ex))
CK.ok("带 WS_EX_NOACTIVATE（出来时不抢焦点）",
      bool(ex & WS_EX_NOACTIVATE), hex(ex))


def window_at(x, y):
    """这一屏幕坐标命中的窗口（会跳过 TRANSPARENT 层）。"""
    u32.WindowFromPoint.restype = wt.HWND
    u32.WindowFromPoint.argtypes = [wt.POINT]
    return u32.WindowFromPoint(wt.POINT(x, y))


cx = h._win.winfo_rootx() + h._win.winfo_width() // 2
cy = h._win.winfo_rooty() + h._win.winfo_height() // 2
CK.ok("提示条正中央的点不落在它自己身上", window_at(cx, cy) != hwnd,
      (window_at(cx, cy), hwnd))

# ================= 6. 同一文案不重置计时 =================
print("\n=== 6. 鼠标抖动不重置计时 ===")
h.hide()
h.schedule("丁", 400, 300)
for _ in range(6):                   # 每 60ms 喂一次同样的文案，累计 360ms
    pump(60)
    h.schedule("丁", 400, 300)
pump(120)                            # 总 480ms：若每次重置，这里距上次才 120ms
CK.ok("在同一按钮上反复移动，提示照样按时出现", h._win is not None, h._text)
CK.ok("显示的还是同一句", h._text == "丁", h._text)

# ================= 7. 换按钮 = 换内容，旧的立刻收 =================
print("\n=== 7. 换按钮 / 收起 ===")
h.schedule("戊", 500, 320)
pump(60)
CK.ok("换文案时先把旧的收掉（此刻不显示）", h._win is None, h._text)
pump(hint.DELAY_MS + 160)
CK.ok("新文案按时出现", h._text == "戊", h._text)

h.hide()
CK.ok("hide 之后窗口没了", h._win is None)
pump(hint.DELAY_MS + 120)
CK.ok("hide 也取消了还没到点的显示", h._win is None)

h.schedule("己", 400, 300)
h.hide()                             # 排上之后立刻收
pump(hint.DELAY_MS + 120)
CK.ok("排上又被收掉，不会再冒出来", h._win is None)

cv.destroy()
root.destroy()
sys.exit(CK.report())
