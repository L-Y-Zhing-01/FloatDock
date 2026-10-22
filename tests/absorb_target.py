# -*- coding: utf-8 -*-
"""被吸附用的目标窗口：一个位于屏幕左下空域的普通顶层窗口。

为什么要专门造一个而不借记事本：
  · 位置可控 —— 必须完全避开用户正在用的浮坞面板所在区域，
    否则拾取器会把用户的面板当成目标（那就闯祸了）；
  · 颜色醒目 —— 便于人工看截图确认它真的被嵌进面板且渲染正常；
  · 用完即杀，不留下任何痕迹。

用法：absorb_target.py X Y [W H]
"""
import sys
import tkinter as tk

x, y, w, h = 400, 780, 420, 260
if len(sys.argv) >= 3:
    x, y = int(sys.argv[1]), int(sys.argv[2])
if len(sys.argv) >= 5:
    w, h = int(sys.argv[3]), int(sys.argv[4])

TITLE = "浮坞测试目标窗口"

root = tk.Tk()
root.title(TITLE)
root.geometry("%dx%d+%d+%d" % (w, h, x, y))
root.configure(bg="#00e07a")
tk.Label(root, text="TARGET-OK", font=("Segoe UI", 34, "bold"),
         bg="#00e07a", fg="#00226b").place(relx=0.5, rely=0.45, anchor="center")
tk.Label(root, text="这个窗口应当能被吸附、继续使用、并原样还原",
         font=("Microsoft YaHei UI", 11), bg="#00e07a", fg="#0b3d24"
         ).place(relx=0.5, rely=0.72, anchor="center")
root.mainloop()
