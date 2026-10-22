# -*- coding: utf-8 -*-
"""调试输出：全项目共用的 dbg()。

默认静默（pythonw 下没有控制台，输出也无处可去）；
入口解析到 --debug 后调用 enable() 打开，输出带毫秒时间戳，
方便排查状态机、热键这类时序问题。
"""
import time

ENABLED = False


def enable():
    """打开调试输出。由入口在解析到 --debug 时调用。"""
    global ENABLED
    ENABLED = True


def dbg(*args):
    """带毫秒时间戳的调试输出；未开启调试时为空操作。"""
    if not ENABLED:
        return
    t = time.time()
    print("[浮坞 %s.%03d]" % (time.strftime("%H:%M:%S", time.localtime(t)),
                              int((t % 1) * 1000)), *args, flush=True)
