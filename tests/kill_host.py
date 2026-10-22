# -*- coding: utf-8 -*-
"""一个"宿主窗口"：把目标窗口吸进去后原地待命，专供关停审计强杀。

用途只有一个 —— 测量"宿主进程被强制结束时，被吸附的第三方窗口会怎样"。
正常退出路径（✕ / 托盘退出）由浮坞自己负责逐位还原，这里只造异常场景：
进程被 TerminateProcess，没有任何清理代码有机会运行。

用法：kill_host.py
输出：HOST=<面板 hwnd> TARGET=<目标 hwnd> OK=<吸附结果>
"""
import os
import sys
import time
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import wndutil                                  # noqa: E402
from absorb import Absorber                     # noqa: E402

TITLE = "浮坞测试目标窗口"


def find_target():
    for h in H.enum_windows():
        if TITLE in wndutil.win_text(h):
            return h
    return None


target = find_target()
if not target:
    print("TARGET=None（目标窗口不存在）", flush=True)
    sys.exit(2)

root = tk.Tk()
root.overrideredirect(True)
root.geometry("440x320+200+120")
root.update()
host = wndutil.root_of(root.winfo_id())
print("HOST=%s TARGET=%s" % (host, target), flush=True)

ab = Absorber(lambda: host, os.getpid())
tab, msg = ab.absorb(target)
print("OK=%s" % msg, flush=True)

# 挂着不退出，等外部把本进程强杀
while True:
    try:
        root.update()
    except Exception:
        pass
    time.sleep(0.05)
