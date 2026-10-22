# -*- coding: utf-8 -*-
"""在进程内点清线程：浮坞自己到底起了几条线程。

为什么要专门在进程内点：从外部看进程的线程数会被环境干扰 —— 本机裸解释器
就有 9~10 条原生线程（运行时与沙箱注入），每建一个窗口环境还会再加一条，
所以"外部数出来 20 条"完全不能说明浮坞起了 20 条线程。
Python 自己的 threading 视图才是浮坞真实的线程账本。

输出（供 test_shutdown.py 解析）：
    THREADS_INIT <数量> <[名称, 是否守护]>
    THREADS_BUSY <数量> <[名称, 是否守护]>     打开设置窗口 / 显隐 / 改透明度之后
    THREADS_QUIT <数量> <[名称, 是否守护]>     进入 quit() 之前（此时辅助线程还在，
                                               它由 quit() 叫停，随后进程直接退出）
"""
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import winapi                                   # noqa: E402

winapi.enable_dpi_awareness()

from config import Config                       # noqa: E402
from panel import FloatDock                     # noqa: E402


def inventory():
    return sorted((t.name, bool(t.daemon)) for t in threading.enumerate())


def show(tag):
    print("%s %d %s" % (tag, threading.active_count(), inventory()), flush=True)


cfg_dir = tempfile.mkdtemp(prefix="fd_threadprobe_")
cfg_path = os.path.join(cfg_dir, "config.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump({"x": 200, "y": 120, "w": 470, "h": 620, "locked": True,
               "hotkey": {"ctrl": False, "alt": False, "shift": False,
                          "win": False, "key": "F14"}}, f)

fd = FloatDock(Config(cfg_path))
show("THREADS_INIT")


def busy():
    fd.hide()
    fd.show()
    fd._set_opacity(0.80)
    fd._toggle_lock()
    fd._open_settings()
    fd.root.after(800, after_busy)


def after_busy():
    if fd.settings:
        fd.settings.close()
    fd._draw()
    show("THREADS_BUSY")
    fd.root.after(300, do_quit)


def do_quit():
    show("THREADS_QUIT")
    fd.quit()


fd.root.after(1100, busy)
fd.run()                    # quit() 内部 os._exit，不会走到下一行
