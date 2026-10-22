# -*- coding: utf-8 -*-
"""吸附与释放（另一端到端）：把真实窗口拖进面板，再原样还回去。

这是浮坞的核心功能，也是最危险的一段 —— 它跨进程改别人的窗口样式与父窗口。
所以判据不取"应用说成功了"，而是直接查窗口本身的 Win32 状态：

  吸附后：GetParent == 面板、WS_CHILD 置上、标题/边框样式剥掉、
          几何落在面板客户区内、窗口可见；
  释放后：父窗口回到原样、style/exstyle 逐位还原、几何还原、窗口可见。

目标窗口由 absorb_target.py 现造，位置放在屏幕左下空域，
既避开沙箱面板也避开用户正在用的那个浮坞 —— 万一拾取器抓错，后果很严重。

吸附要用真实鼠标（拾取器靠 GetCursorPos 判定目标），
沙箱拦截物理输入时整段 SKIP。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import theme as T                               # noqa: E402
import tray                                     # noqa: E402
import wndutil                                  # noqa: E402
from winapi import (u32, GWL_STYLE, GWL_EXSTYLE, WS_CHILD, WS_CAPTION,   # noqa: E402
                    WS_POPUP, WS_THICKFRAME)

CK = H.Checker("吸附与释放")

PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 200, 120, 470, 620
TARGET_TITLE = "浮坞测试目标窗口"
TARGET_W, TARGET_H = 420, 260
# 目标窗口的位置现找空域，不写死（见 harness.free_spot 的实测记录）：
# 用户正在用的那个浮坞面板实测在 (616,215)-(1404,941)，正好压住写死的
# (400,780) —— 而拾取器认的是"光标底下那个窗口"，被压住就会去抓用户面板。
TARGET_GEOM = (lambda p: (p[0], p[1], TARGET_W, TARGET_H))(
    H.free_spot(TARGET_W, TARGET_H) or (400, 780))
print("目标窗口落点：%s（现找空域，避开你正在用的浮坞面板）" % (TARGET_GEOM,))

# 面板上的按钮中心（从 theme 的标题栏布局反查，别再硬编码坐标）
_BTN = dict((n, bx) for n, _g, bx in T.title_buttons(PANEL_W))
GRAB_BTN = (_BTN["grab"] + 14, T.H_TITLE // 2)          # ✥ 吸附
RELEASE_BTN = (_BTN["release"] + 14, T.H_TITLE // 2)    # ⤴ 释放


SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0010, 0x0040
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
VK_ESCAPE = 0x1B


def bring_to_front(hwnd):
    """把目标窗口抬到最前，保证光标落下去时它真的在最上面。

    这一步不能省：沙箱环境里别的窗口（编辑器、资源管理器）随时可能盖在这块
    区域上，拾取器认的是"光标底下那个窗口"，会误抓无关窗口。
    """
    try:
        u32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    u32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    time.sleep(0.25)
    u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    time.sleep(0.15)


def find_target(pid, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        for h in H.enum_windows():
            if wndutil.window_pid(h) == pid and \
                    TARGET_TITLE in wndutil.win_text(h):
                return h
        time.sleep(0.15)
    return None


if not H.mouse_injection_available():
    CK.skip("吸附与释放", "沙箱拦截物理鼠标注入，拾取器无法定位目标")
    sys.exit(CK.report())

tgt_proc = subprocess.Popen(
    [H.PY, "-u", os.path.join(HERE, "absorb_target.py"),
     str(TARGET_GEOM[0]), str(TARGET_GEOM[1]),
     str(TARGET_GEOM[2]), str(TARGET_GEOM[3])],
    cwd=HERE)
sb = H.Sandbox("absorb", {
    "x": PANEL_X, "y": PANEL_Y, "w": PANEL_W, "h": PANEL_H, "opacity": 0.92,
    "locked": True, "hide_delay": 3.0,
    "hotkey": {"ctrl": True, "alt": True, "shift": False, "win": False,
               "key": "D"}})

try:
    target = find_target(tgt_proc.pid)
    CK.ok("目标窗口已创建", bool(target),
          "hwnd=%s pid=%s" % (target, tgt_proc.pid))
    sb.start()
    panel = sb.panel(15.0)
    CK.ok("浮坞实例已启动", bool(panel), "hwnd=%s" % panel)
    if not (target and panel):
        sys.exit(CK.report())
    time.sleep(1.4)

    # 吸附前的原始状态
    before = {
        "rect": wndutil.win_rect(target),
        "style": wndutil.get_long(target, GWL_STYLE),
        "exstyle": wndutil.get_long(target, GWL_EXSTYLE),
        "parent": u32.GetParent(target),
    }
    print("    吸附前 rect=%s style=0x%08X exstyle=0x%08X parent=%s"
          % (before["rect"], before["style"], before["exstyle"],
             before["parent"]))
    CK.ok("目标窗口可被吸附（可吸附性判定通过）",
          wndutil.is_suitable_target(target, sb.proc.pid)[0] is True,
          wndutil.is_suitable_target(target, sb.proc.pid)[1])
    CK.ok("目标窗口原本是顶层窗口（无父窗口）",
          not before["parent"], before["parent"])
    CK.ok("目标窗口原本带标题栏边框",
          bool(before["style"] & WS_CAPTION) and bool(before["style"] & WS_THICKFRAME),
          hex(before["style"]))

    # ---------- 1. 按住「✥ 吸附窗口」拖到目标上松开 ----------
    print("\n--- 1. 拖拽吸附 ---")
    tx, ty, tw, th = before["rect"]
    center = (tx + tw // 2, ty + th // 2)

    # 先确认光标底下真的是目标窗口。不是就整段跳过 —— 绝不能在没确认的情况下
    # 松开鼠标：拾取器会把当时压在光标上的那个窗口吸进来（可能与你无关）。
    #
    # 判据的顺序很重要：这是**环境前置条件**，不是产品行为。落点被别的窗口压住
    # 时该记 SKIP（诚实说明"这段没跑成、为什么"），记成 FAIL 会让人误以为是
    # 吸附逻辑坏了 —— v1.6.3 发布前就踩过这个：用户面板一挪过来，失败信息长得
    # 像产品缺陷，排查方向被带偏。
    bring_to_front(target)
    H.move_mouse(*center, steps=16)
    time.sleep(0.3)
    under = wndutil.point_window()
    if under != target:
        CK.skip("拖拽吸附",
                "落点 (%.0f,%.0f) 上是 %s %r 而非目标（多半被别的窗口压住），"
                "已放弃：未吸附任何窗口" % (center[0], center[1],
                                          wndutil.win_class(under),
                                          wndutil.win_text(under)))
        sys.exit(CK.report())
    CK.ok("拖放点上确实是目标窗口（确认后才敢松鼠标）", True,
          "(%.0f,%.0f) -> %r" % (center[0], center[1], wndutil.win_text(under)))

    px, py, pw, ph = wndutil.win_rect(panel)
    H.move_mouse(px + GRAB_BTN[0], py + GRAB_BTN[1])
    time.sleep(0.2)
    u32.mouse_event(0x0002, 0, 0, 0, 0)                # 按住
    time.sleep(0.3)
    H.move_mouse(*center, steps=24)
    time.sleep(0.4)
    picked = wndutil.point_window()
    if picked != target:                                # 途中被盖住 -> 取消拾取
        u32.PostMessageW(panel, H.WM_KEYDOWN, VK_ESCAPE, 0)
        time.sleep(0.3)
        CK.skip("拖拽吸附", "松开前目标被遮挡（%r），已 Esc 取消"
                % wndutil.win_text(picked))
        sys.exit(CK.report())
    u32.mouse_event(0x0004, 0, 0, 0, 0)                 # 松开
    time.sleep(0.9)

    attached = H.wait_expr(lambda: u32.GetParent(target) == panel, 4.0)
    CK.ok("目标窗口已被挂到面板下（GetParent == 面板）",
          attached is not None, "parent=%s" % u32.GetParent(target))

    style = wndutil.get_long(target, GWL_STYLE)
    exstyle = wndutil.get_long(target, GWL_EXSTYLE)
    CK.ok("WS_CHILD 已置上（真的变成子窗口）", bool(style & WS_CHILD),
          hex(style))
    CK.ok("标题栏 / 边框样式已剥掉（吸附后是纯内容面）",
          not (style & WS_CAPTION) and not (style & WS_THICKFRAME)
          and not (style & WS_POPUP) and bool(style & WS_CHILD), hex(style))
    CK.ok("任务栏/Alt-Tab 相关扩展样式已剥掉",
          not (exstyle & 0x00040000), hex(exstyle))   # WS_EX_APPWINDOW

    r = wndutil.win_rect(target)
    cx, cy, cw, ch = T.content_rect(PANEL_W, PANEL_H)
    inside = (abs(r[0] - (px + cx)) <= 3 and abs(r[1] - (py + cy)) <= 3
              and abs(r[2] - cw) <= 3 and abs(r[3] - ch) <= 3)
    CK.ok("窗口被摆进面板客户区（含状态栏留白）", inside,
          "%s 期望≈%s" % (r, (px + cx, py + cy, cw, ch)))
    CK.ok("窗口在面板内可见", H.visible(target) is True)
    CK.ok("日志确认吸附完成", "absorb 完成" in sb.text(),
          [ln.strip() for ln in sb.lines() if "absorb" in ln][-2:])

    # ---------- 2. 点「⤴ 释放」 ----------
    print("\n--- 2. 点释放还原 ---")
    px, py, pw, ph = wndutil.win_rect(panel)
    u32.SetForegroundWindow(panel)                   # 面板置顶，确保按钮点得到
    time.sleep(0.25)
    H.move_mouse(px + RELEASE_BTN[0], py + RELEASE_BTN[1], steps=12)
    time.sleep(0.25)
    CK.ok("释放按钮在光标下（面板未被遮挡）",
          wndutil.point_window() == panel, wndutil.point_window())
    u32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.09)
    u32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.45)
    restored = H.wait_expr(lambda: u32.GetParent(target) != panel, 4.0)
    CK.ok("已摘下父子关系（不再是面板的子窗口）",
          restored is not None, "parent=%s" % u32.GetParent(target))

    CK.ok("样式逐位还原（标题栏 / 边框都回来了）",
          wndutil.get_long(target, GWL_STYLE) == before["style"],
          "0x%08X → 0x%08X" % (before["style"],
                               wndutil.get_long(target, GWL_STYLE)))
    CK.ok("扩展样式逐位还原",
          wndutil.get_long(target, GWL_EXSTYLE) == before["exstyle"],
          "0x%08X → 0x%08X" % (before["exstyle"],
                               wndutil.get_long(target, GWL_EXSTYLE)))
    CK.ok("父窗口还原",
          u32.GetParent(target) == before["parent"],
          "%s → %s" % (before["parent"], u32.GetParent(target)))
    now = wndutil.win_rect(target)
    CK.ok("几何还原到原位",
          now and all(abs(a - b) <= 3 for a, b in zip(now, before["rect"])),
          "%s → %s" % (before["rect"], now))
    CK.ok("窗口仍然可见可用", H.visible(target) is True)
    CK.ok("重新成为独立的顶层窗口",
          wndutil.root_of(target) == target, wndutil.root_of(target))
    CK.ok("面板已清空（没有残留子窗口）",
          H.child_windows(panel) == [] or
          all(wndutil.win_class(c) != "TkTopLevel"
              for c in H.child_windows(panel)),
          [wndutil.win_class(c) for c in H.child_windows(panel)])

    CK.ok("运行期无异常", "Traceback" not in sb.text(),
          [ln.strip() for ln in sb.lines() if "Traceback" in ln][:3])

    # ---------- 3. 托盘「释放窗口」：文案必须如实 ----------
    # 这条路径单独测：release_all() 曾经返回布尔值而文案按数量格式化，
    # 于是不管释放几个都显示"已释放 1 个窗口"（重构前就有的历史 bug）。
    # 现在容器只有一个窗口，文案也随之收敛成"已释放窗口"。
    print("\n--- 3. 托盘「释放窗口」（真实拖拽吸附后再释放）---")
    bring_to_front(target)
    H.move_mouse(*center, steps=16)
    time.sleep(0.3)
    if wndutil.point_window() != target:
        CK.skip("托盘释放全部", "目标窗口被遮挡，未再次吸附")
    else:
        px, py, pw, ph = wndutil.win_rect(panel)
        H.move_mouse(px + GRAB_BTN[0], py + GRAB_BTN[1])
        time.sleep(0.2)
        u32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.3)
        H.move_mouse(*center, steps=24)
        time.sleep(0.4)
        if wndutil.point_window() != target:
            u32.PostMessageW(panel, H.WM_KEYDOWN, VK_ESCAPE, 0)
            time.sleep(0.3)
            u32.mouse_event(0x0004, 0, 0, 0, 0)
            CK.skip("托盘释放全部", "松开前目标被遮挡，已 Esc 取消")
        else:
            u32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.9)
            CK.ok("再次吸附成功", u32.GetParent(target) == panel,
                  "parent=%s" % u32.GetParent(target))
            n0 = sb.line_count()
            H.post_menu_command(sb.aux(8.0), tray.CMD_RELEASE_ALL)
            seg = sb.wait_log("托盘释放全部", since=n0, timeout=4.0)
            CK.ok("文案如实报告已释放", "已释放窗口" in seg,
                  [ln.strip() for ln in sb.lines()[n0:] if "释放全部" in ln][-1:])
            CK.ok("窗口确实被还原（不再是面板子窗口）",
                  H.wait_expr(lambda: u32.GetParent(target) != panel, 4.0)
                  is not None, "parent=%s" % u32.GetParent(target))
            CK.ok("窗口样式与几何仍逐位还原",
                  wndutil.get_long(target, GWL_STYLE) == before["style"]
                  and wndutil.get_long(target, GWL_EXSTYLE) == before["exstyle"]
                  and all(abs(a - b) <= 3 for a, b in
                          zip(wndutil.win_rect(target), before["rect"])),
                  "style=0x%08X rect=%s"
                  % (wndutil.get_long(target, GWL_STYLE),
                     wndutil.win_rect(target)))
finally:
    sb.stop()
    try:
        tgt_proc.terminate()
        tgt_proc.wait(timeout=5)
    except Exception:
        try:
            tgt_proc.kill()
        except Exception:
            pass

sys.exit(CK.report())
