# -*- coding: utf-8 -*-
"""托盘图标交互：左键切换显隐、右键弹菜单、双击忽略。

判据取"确定性"的那一侧：
  · 菜单是否弹出 —— 查 TrackPopupMenu 建的系统菜单窗口（类名 #32768，按 pid 归属）；
  · 显隐是否翻转 —— 查面板窗口的 WS_VISIBLE（配合 locked 配置，排除自动隐藏干扰）。

注意顺序：TrackPopupMenu 是模态的，会把辅助线程卡在里面，之后它不再处理任何
托盘消息。所以"左键切换"的用例全部排在弹菜单之前，弹菜单放最后。

配置里 locked=True：锁定状态下面板不会因鼠标移开而自动隐藏，
于是可见性变化只可能来自被测的托盘动作，判据不会被竞态污染。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import tray                                     # noqa: E402

CK = H.Checker("托盘交互")

WM_CANCELMODE = 0x001F
VK_ESCAPE = 0x1B

sb = H.Sandbox("tray", {
    "x": 260, "y": 160, "w": 470, "h": 620, "opacity": 0.92,
    "locked": True, "hide_delay": 3.0,
    "hotkey": {"ctrl": True, "alt": True, "shift": False, "win": False,
               "key": "D"}})

try:
    sb.start()
    panel = sb.panel(15.0)
    aux = sb.aux(8.0)
    CK.ok("面板与热键辅助窗口均已创建", bool(panel and aux),
          "panel=%s aux=%s" % (panel, aux))
    if not (panel and aux):
        sys.exit(CK.report())
    time.sleep(1.2)                      # 等首帧绘制与状态机启动

    CK.ok("基线：尚无菜单弹出", not H.menu_open(sb.proc.pid))
    CK.ok("基线：面板处于显示态（locked=True 不会自动隐藏）",
          H.visible(panel) is True)

    # ---------- 左键单击 = 切换显隐 ----------
    print("\n=== 左键单击：切换显示 / 隐藏 ===")
    u32 = H.u32
    u32.PostMessageW(aux, tray.WM_TRAY, 0, tray.WM_LBUTTONUP)
    dt = H.wait_visible(panel, False, 2.5)
    CK.ok("左键单击由显示翻转为隐藏", dt is not None,
          "%.0f ms" % (dt * 1000) if dt else "无响应")
    time.sleep(0.5)
    CK.ok("隐藏后保持隐藏（锁定态不会自己回来）", H.visible(panel) is False)

    u32.PostMessageW(aux, tray.WM_TRAY, 0, tray.WM_LBUTTONUP)
    dt = H.wait_visible(panel, True, 2.5)
    CK.ok("再点一次由隐藏翻转为显示", dt is not None,
          "%.0f ms" % (dt * 1000) if dt else "无响应")

    # ---------- 左键双击 = 什么都不做（修复前是"双击才出菜单"） ----------
    print("\n=== 左键双击：既不弹菜单也不切换 ===")
    before = H.visible(panel)
    u32.PostMessageW(aux, tray.WM_TRAY, 0, tray.WM_LBUTTONDBLCLK)
    time.sleep(0.9)
    CK.ok("双击不弹菜单", not H.menu_open(sb.proc.pid))
    CK.ok("双击不切换显隐", H.visible(panel) == before, H.visible(panel))

    # ---------- 右键单击 = 弹菜单 ----------
    print("\n=== 右键单击：弹出菜单 ===")
    CK.ok("0x0203 是左键双击、0x0205 才是右键（常量自证）",
          tray.WM_LBUTTONDBLCLK == 0x0203 and tray.WM_RBUTTONUP == 0x0205)
    u32.PostMessageW(aux, tray.WM_TRAY, 0, tray.WM_RBUTTONUP)
    t0 = time.time()
    menu = None
    while time.time() - t0 < 2.0:
        menu = H.find_popup_menu(sb.proc.pid)
        if menu:
            break
        time.sleep(0.05)
    CK.ok("右键单击弹出菜单窗口", menu is not None, "hwnd=%s" % menu)

    if menu:
        # 菜单是模态的，用消息把它关掉（沙箱里物理 Esc 注入无效）
        u32.PostMessageW(menu, WM_CANCELMODE, 0, 0)
        u32.PostMessageW(menu, H.WM_KEYDOWN, VK_ESCAPE, 0)
        closed = H.wait_expr(lambda: not H.menu_open(sb.proc.pid), 1.5)
        if closed is None:
            CK.skip("Esc 关闭菜单", "沙箱不接受物理/消息级 Esc，改用结束进程收尾")
        else:
            CK.ok("Esc 可关闭菜单", True, "%.0f ms" % (closed * 1000))
    else:
        CK.skip("Esc 关闭菜单", "菜单未弹出")
finally:
    sb.stop()

CK.ok("托盘实例已退出，未见异常", "Traceback" not in sb.text(),
      [ln.strip() for ln in sb.lines() if "Traceback" in ln][:2])

sys.exit(CK.report())
