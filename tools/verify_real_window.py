# -*- coding: utf-8 -*-
"""真机验收：对真实运行中的窗口做一次「吸附 → 观察 → 释放」，核对桌面不留边框。

    python tools/verify_real_window.py [标题关键字]

这是 v1.6.3 那次修复的**验收手段** —— 单元测试造的是"符合我们定义的包边层"，
而真实浏览器（360 极速浏览器 X）的阴影窗口是厂商自己的实现，只有对着真程序
跑一次才算数。判据取自 Win32 真实状态，不看程序自述。

安全约束（不能破）：
  · 用隔离沙箱浮坞（独立 config + --allow-multiple），**不碰用户正在用的实例**；
  · 默认挑一个"无关紧要"的窗口（记事本 / 计算器 / 浏览器），
    用标题关键字可以指定；
  · 末尾**无条件还原**目标窗口（摘父子关系 + 逐位还样式 + 还几何），
    任何异常路径都不许把别人的窗口留在面板下。

通过标准：释放后目标窗口 rect / style / exstyle / parent 与吸附前逐位一致，
且吸附期间桌面像素上不再有残留的边框（后者靠枚举包边层的位置判定）。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, ROOT)

import harness as H                               # noqa: E402
import theme as T                                 # noqa: E402
import wndutil                                    # noqa: E402
from absorb import Absorber                       # noqa: E402
from winapi import u32, GWL_STYLE, GWL_EXSTYLE    # noqa: E402

# 沙箱面板放屏幕左上一角，避开用户面板与任务栏
PANEL = {"x": 200, "y": 120, "w": 470, "h": 620, "opacity": 0.92,
         "locked": True, "hide_delay": 3.0,
         "hotkey": {"ctrl": True, "alt": True, "shift": False,
                    "win": False, "key": "D"}}

results = []


def ck(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s%s" % ("OK" if ok else "FAIL", name,
                         ("   " + str(detail)) if detail else ""), flush=True)


def snapshot(hwnd):
    return {"rect": wndutil.win_rect(hwnd),
            "style": wndutil.get_long(hwnd, GWL_STYLE),
            "exstyle": wndutil.get_long(hwnd, GWL_EXSTYLE),
            "parent": u32.GetParent(hwnd),
            "companions": wndutil.frame_companions(hwnd)}


def pick_window(keyword):
    """按标题关键字找一个合适的第三方窗口（跳过自己人）。"""
    own = H.pythonw_pids()
    fallback = []
    for h in H.enum_windows():
        if not H.visible(h):
            continue
        title = wndutil.win_text(h)
        if not title:
            continue
        pid = wndutil.window_pid(h)
        if pid in own or pid == os.getpid():
            continue
        if wndutil.root_of(h) != h:
            continue
        # 最小化的窗口不能当靶子：它的 rect 是 (-32000,-32000,160,28) 这种占位值，
        # 而吸附/释放会顺手清掉 WS_MINIMIZE，于是「还原后与吸附前一致」拿一个本就
        # 不可比的基线去比，报出假失败（v1.6.4 实测踩到过）。
        if u32.IsIconic(h):
            continue
        ok, why = wndutil.is_suitable_target(h, os.getpid())
        if not ok:
            continue
        if keyword:
            if keyword in title:
                return h, title
        else:
            fallback.append((h, title))
    if keyword:
        return None, ""
    # 没指定关键字：优先挑浏览器（那是包边层问题的主要受害者）
    for h, t in fallback:
        if wndutil.frame_companions(h):
            return h, t
    return fallback[0] if fallback else (None, "")


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else None
    target, title = pick_window(keyword)
    print("目标窗口:", title or "(未找到)", "hwnd=%s" % target)
    if not target:
        print("没找到合适的第三方窗口；可以带标题关键字跑，例如：")
        print("  python tools/verify_real_window.py 记事本")
        return 2

    before = snapshot(target)
    print("吸附前 rect=%s style=0x%08X exstyle=0x%08X parent=%s"
          % (before["rect"], before["style"], before["exstyle"],
             before["parent"]))
    print("识别到的包边/阴影层：%s" % ([hex(h) for h in before["companions"]]
                                       or "无（这个窗口不自带包边层）"))

    sb = H.Sandbox("realwin", PANEL)
    sb.start()
    panel = sb.panel(20.0)
    if not panel:
        ck("沙箱浮坞已启动", False)
        return 1
    ck("沙箱浮坞已启动（未碰用户实例）", True, "hwnd=%s pid=%s" % (panel, sb.proc.pid))

    ab = Absorber(lambda: panel, sb.proc.pid)
    tab = None
    try:
        tab, msg = ab.absorb(target)
        ck("目标窗口已吸附进面板", tab is not None, msg)
        if tab is None:
            return 1

        time.sleep(1.0)
        # 关键判据：包边层必须已挪到屏幕外（坐标 ≪ 0）
        # companions 是 [(hwnd, 原矩形)]，别只解出 hwnd 就当窗口句柄用
        for ch, _orig in tab.companions:
            r = wndutil.win_rect(ch)
            parked = bool(r) and (r[0] < -1000 or r[1] < -1000)
            ck("包边层 %s 已挪出屏幕（原位置会被留下空框）" % hex(ch), parked, r)

        # 兜底路径：走产品的摆放路径，触发 keep_parked，确认包边层不会跑回来
        ab.place_current(*panel_content_rect(sb, panel))
        time.sleep(0.8)
        back = [hex(ch) for ch, _r in tab.companions
                if wndutil.win_rect(ch) and wndutil.win_rect(ch)[0] > -1000]
        ck("摆放面板后包边层没有跑回桌面", not back, back or "全部仍在屏幕外")
    finally:
        # ---- 无条件还原 ----
        ok = ab.release() if ab.tab is not None and ab.tab.hwnd == target else False
        ck("已释放目标窗口", ok, "容器里的窗口=%s" % (ab.tab and ab.tab.title))
        time.sleep(0.6)

    after = snapshot(target)
    for key in ("parent", "style", "exstyle", "rect"):
        ck("还原后 %s 与吸附前一致" % key, before[key] == after[key],
           "%s → %s" % (before[key], after[key]))
    ck("目标窗口仍可见可用", H.visible(target))
    sb.stop()
    return 0 if results.count(False) == 0 else 1


def panel_content_rect(sb, panel):
    """把目标摆在面板客户区正中（走产品的摆放路径，触发 keep_parked 兜底）。"""
    px, py, pw, ph = wndutil.win_rect(panel)
    x, y, w, h = T.content_rect(pw, ph)
    return px + x, py + y, w, h


if __name__ == "__main__":
    sys.exit(main())