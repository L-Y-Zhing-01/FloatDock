# -*- coding: utf-8 -*-
"""阴影 / 外框层（"包边层"）：吸附时不能把包边留在桌面上。

背景（实测 2026-10-15）：360 极速浏览器 X 不把窗口阴影与圆角外框交给 DWM，
而是画在一个**独立的分层窗口**里 —— `Chrome_WidgetWin_0` 比内容窗
`Chrome_WidgetWin_1` 每边大 21px，同进程、顶层、可见、带 WS_EX_LAYERED。
只搬走内容窗的话，这个包边留在桌面原位，用户看到的就是"吸附完剩下一个空边框"。

这里就地造一对"内容窗 + 包边窗"（同进程、真实 HWND、真实 layered 扩展样式），
覆盖三件事：

  1. 认得出 —— 包边层被 frame_companions 找到，且不会被当成吸附目标；
  2. 挪得走 —— 吸附时包边层被挪到屏幕外（用"隐藏"会被浏览器重画覆盖，
     实测摆放进客户区后 0.5 秒内必被亮回来）；
  3. 还得回 —— 释放后包边层放回原位（本来就藏着的，我们不碰）。

不依赖物理鼠标，也不碰任何外部程序。
"""
import ctypes
import os
import sys
import time
import tkinter as tk
from ctypes import wintypes as wt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                                 # noqa: E402
import absorb as A                                  # noqa: E402
import winapi                                       # noqa: E402
import wndutil                                      # noqa: E402
from winapi import GWL_EXSTYLE, GWL_STYLE, WS_EX_LAYERED      # noqa: E402

winapi.enable_dpi_awareness()
CK = H.Checker("阴影/外框层")

PAD = 21                                # 包边厚度：与实测的 360 浏览器一致
IN_W, IN_H = 400, 300
OUT_W, OUT_H = IN_W + 2 * PAD, IN_H + 2 * PAD
IN_X, IN_Y = 300, 300                   # 屏幕左上，避开右侧的面板
OUT_X, OUT_Y = IN_X - PAD, IN_Y - PAD
PANEL_GEOM = (470, 620, 760, 80)

root = tk.Tk()
root.withdraw()
root.update()


def make_window(geom, color):
    """一个无边框顶层窗口，返回其顶层 HWND。"""
    w = tk.Toplevel(root)
    w.overrideredirect(True)
    w.geometry("%dx%d+%d+%d" % geom)
    w.configure(bg=color)
    w.update()
    return w, wndutil.root_of(w.winfo_id())


def region_box(hwnd):
    """窗口区域的外接矩形；没有设置区域（整窗可见）时返回 None。"""
    u32 = winapi.u32
    u32.GetWindowRgn.restype = ctypes.c_int
    u32.GetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    winapi.gdi32.CreateRectRgn.restype = ctypes.c_void_p
    winapi.gdi32.CreateRectRgn.argtypes = [ctypes.c_int] * 4
    winapi.gdi32.GetRgnBox.restype = ctypes.c_int
    winapi.gdi32.GetRgnBox.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
    winapi.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    hrgn = winapi.gdi32.CreateRectRgn(0, 0, 0, 0)
    try:
        if not u32.GetWindowRgn(hwnd, hrgn):
            return None                      # ERROR：没有区域
        r = wt.RECT()
        if not winapi.gdi32.GetRgnBox(hrgn, ctypes.byref(r)):
            return None
        return (r.left, r.top, r.right, r.bottom)
    finally:
        winapi.gdi32.DeleteObject(hrgn)


def set_visible(hwnd, visible):
    u32 = winapi.u32
    u32.ShowWindow(hwnd, winapi.SW_SHOW if visible else winapi.SW_HIDE)


panel_w, panel_h = make_window((PANEL_GEOM[0], PANEL_GEOM[1],
                                PANEL_GEOM[2], PANEL_GEOM[3]), "#202020")


def new_pair(tag):
    """造一对"内容窗 + 包边窗"，包边窗带 WS_EX_LAYERED。"""
    inner_w, inner_h = make_window((IN_W, IN_H, IN_X, IN_Y), "#123456")
    outer_w, outer_h = make_window((OUT_W, OUT_H, OUT_X, OUT_Y), "#000000")
    ex = wndutil.get_long(outer_h, GWL_EXSTYLE)
    wndutil.set_long(outer_h, GWL_EXSTYLE, ex | WS_EX_LAYERED)
    print("    [%s] 内容窗 hwnd=%s rect=%s" % (tag, inner_h, wndutil.win_rect(inner_h)))
    print("    [%s] 包边窗 hwnd=%s rect=%s 外扩=%s"
          % (tag, outer_h, wndutil.win_rect(outer_h),
             wndutil.frame_pads(wndutil.win_rect(outer_h),
                                wndutil.win_rect(inner_h))))
    return inner_w, inner_h, outer_w, outer_h


# ================= 1. 认得出 =================
print("\n=== 1. 包边层的识别（不改变任何状态）===")
inner_w, inner_h, outer_w, outer_h = new_pair("认得出")

CK.ok("包边窗带 WS_EX_LAYERED（造得和真实阴影层同构）",
      bool(wndutil.get_long(outer_h, GWL_EXSTYLE) & WS_EX_LAYERED),
      hex(wndutil.get_long(outer_h, GWL_EXSTYLE)))
CK.ok("frame_companions 精确找到包边窗",
      wndutil.frame_companions(inner_h) == [outer_h],
      wndutil.frame_companions(inner_h))
CK.ok("包边窗被认成包边层", wndutil.is_frame_layer(outer_h) is True)
CK.ok("内容窗不会被误认成包边层", wndutil.is_frame_layer(inner_h) is False)
ck_ok, why = wndutil.is_suitable_target(outer_h, 0)
CK.ok("包边窗被拒绝吸附（不会吸到一个空框子）", ck_ok is False, why)
ck_ok2, _ = wndutil.is_suitable_target(inner_h, 0)
CK.ok("内容窗仍可正常吸附", ck_ok2 is True)

# ================= 2. 收得走 =================
print("\n=== 2. 吸附：包边层被一起收走 ===")
panel_root = wndutil.root_of(panel_w.winfo_id())
absorber = A.Absorber(lambda: panel_root, -1)       # -1：本进程窗口也算"外部"

before = {
    "rect": wndutil.win_rect(inner_h),
    "style": wndutil.get_long(inner_h, GWL_STYLE),
    "exstyle": wndutil.get_long(inner_h, GWL_EXSTYLE),
    "parent": winapi.u32.GetParent(inner_h),
}

tab, msg = absorber.absorb(inner_h)
CK.ok("吸附成功", tab is not None, msg)
parked = wndutil.win_rect(outer_h)
CK.ok("包边层已被挪出屏幕（桌面不再留边框）",
      parked and parked[0] <= A.SHADOW_OUTSIDE and parked[1] <= A.SHADOW_OUTSIDE,
      parked)
CK.ok("包边层原位记进了快照（释放时才知道该还到哪）",
      (tab.companions if tab else None) == [(outer_h, (OUT_X, OUT_Y, OUT_W, OUT_H))],
      tab.companions if tab else None)
CK.ok("内容窗已挂到面板下",
      winapi.u32.GetParent(inner_h) == panel_root,
      "parent=%s" % winapi.u32.GetParent(inner_h))
CK.ok("内容窗仍在面板内可见", bool(winapi.u32.IsWindowVisible(inner_h)))
# 吸附前"包边层不可被拾取"已由第 1 段覆盖；这里它已被挪出屏幕，
# is_frame_layer 自然为假（不再包住任何窗口），无需重复断言。

# ---------- 2.5 兜底：包边层若又跑回屏幕里，必须能再次挪出去 ----------
print("\n--- 2.5 兜底 keep_parked() ---")
winapi.u32.SetWindowPos(outer_h, None, OUT_X, OUT_Y, OUT_W, OUT_H,
                        0x0001 | 0x0004 | 0x0010)     # 手工搬回屏幕内
time.sleep(0.2)
CK.ok("先手工把包边层搬回屏幕内（模拟被浏览器拉回）",
      wndutil.win_rect(outer_h)[0] > A.SHADOW_OUTSIDE, wndutil.win_rect(outer_h))
absorber.keep_parked()
time.sleep(0.2)
CK.ok("keep_parked() 又把它挪出屏幕",
      wndutil.win_rect(outer_h)[0] <= A.SHADOW_OUTSIDE, wndutil.win_rect(outer_h))

# ================= 3. 还得回 =================
print("\n=== 3. 释放：包边层原样还回 ===")
n = absorber.release_all()
CK.ok("释放成功（1 个窗口）", n == 1, n)
CK.ok("包边层放回原位（位置逐位还原）",
      all(abs(a - b) <= 2 for a, b in
          zip(wndutil.win_rect(outer_h), (OUT_X, OUT_Y, OUT_W, OUT_H))),
      "%s 期望 %s" % (wndutil.win_rect(outer_h),
                      (OUT_X, OUT_Y, OUT_W, OUT_H)))
CK.ok("包边层恢复可见", bool(winapi.u32.IsWindowVisible(outer_h)),
      "visible=%s" % bool(winapi.u32.IsWindowVisible(outer_h)))
CK.ok("内容窗样式逐位还原",
      wndutil.get_long(inner_h, GWL_STYLE) == before["style"],
      "0x%08X → 0x%08X" % (before["style"], wndutil.get_long(inner_h, GWL_STYLE)))
CK.ok("内容窗扩展样式逐位还原",
      wndutil.get_long(inner_h, GWL_EXSTYLE) == before["exstyle"],
      "0x%08X → 0x%08X" % (before["exstyle"],
                           wndutil.get_long(inner_h, GWL_EXSTYLE)))
CK.ok("内容窗几何还原",
      all(abs(a - b) <= 2 for a, b in
          zip(wndutil.win_rect(inner_h), before["rect"])),
      "%s → %s" % (before["rect"], wndutil.win_rect(inner_h)))
CK.ok("内容窗父窗口还原（重新是独立顶层窗口）",
      winapi.u32.GetParent(inner_h) == before["parent"],
      "%s → %s" % (before["parent"], winapi.u32.GetParent(inner_h)))
CK.ok("快照已清空（不留悬挂引用）", tab.companions == [], tab.companions)

inner_w.destroy()
outer_w.destroy()

# ================= 4. 本来就藏着的包边层，不该被碰、更不该被点亮 =================
print("\n=== 4. 原本隐藏的包边层：不碰它，也不点亮它 ===")
i2, i2_h, o2, o2_h = new_pair("原本隐藏")
set_visible(o2_h, False)
CK.ok("先把包边层藏起来", not winapi.u32.IsWindowVisible(o2_h))

absorber2 = A.Absorber(lambda: panel_root, -1)
tab2, msg2 = absorber2.absorb(i2_h)
CK.ok("吸附仍成功", tab2 is not None, msg2)
CK.ok("快照为空（只认可见的包边层，藏着的本来就不留边框）",
      tab2 is not None and tab2.companions == [],
      tab2.companions if tab2 else None)
absorber2.release_all()
CK.ok("释放后包边层仍然隐藏（没被我们动过）",
      not winapi.u32.IsWindowVisible(o2_h),
      "visible=%s" % bool(winapi.u32.IsWindowVisible(o2_h)))
i2.destroy()
o2.destroy()

# ================= 5. 窗口自己关掉：包边层不能一直停在被隐藏的状态 =================
print("\n=== 5. 吸附中窗口自己关掉（prune_dead 要顺手还原包边层）===")
i3, i3_h, o3, o3_h = new_pair("自己关掉")
absorber3 = A.Absorber(lambda: panel_root, -1)
tab3, msg3 = absorber3.absorb(i3_h)
CK.ok("吸附成功", tab3 is not None, msg3)
CK.ok("包边层此刻已被挪出屏幕",
      wndutil.win_rect(o3_h)[0] <= A.SHADOW_OUTSIDE, wndutil.win_rect(o3_h))
i3.destroy()                                     # 用户把窗口关掉了
time.sleep(0.4)
absorber3.prune_dead()
CK.ok("死窗口已从容器清掉", absorber3.tab is None, absorber3.tab)
CK.ok("包边层被顺手放回原位（不会留在屏幕外）",
      all(abs(a - b) <= 2 for a, b in
          zip(wndutil.win_rect(o3_h), (OUT_X, OUT_Y, OUT_W, OUT_H))),
      wndutil.win_rect(o3_h))
o3.destroy()

# ================= 6. 真实的 360 极速浏览器（只读，若在运行）=================
print("\n=== 6. 现场窗口：若 360 极速浏览器正在运行，核对真实结构 ===")
real = None
for h in wndutil.top_level_windows():
    if "360极速浏览器" in (wndutil.win_text(h) or ""):
        real = h
        break
if real is None:
    CK.skip("真实浏览器结构核对", "360 极速浏览器当前未运行")
else:
    CK.ok("真实内容窗仍可吸附",
          wndutil.is_suitable_target(real, 0)[0] is True,
          wndutil.win_text(real))
    # 包边层是浏览器按"可见 + 有位置"自己画的，窗口最小化或还没渲染时为 0 个。
    # 那是环境状态，不是产品缺陷 —— 记 SKIP，别让它长得像吸附坏了。
    comp = wndutil.frame_companions(real)
    if not comp:
        CK.skip("真实浏览器结构核对",
                "窗口在运行但没有挂包边层（未渲染 / 已最小化）")
    else:
        CK.ok("真实浏览器也能定位到它的包边层", len(comp) >= 1,
              [(h, wndutil.win_class(h), wndutil.win_rect(h)) for h in comp])
        CK.ok("真实包边层同样被拒绝吸附",
              all(wndutil.is_suitable_target(h, 0)[0] is False for h in comp))

# ================= 7. 客户区顶部空带：量得准、裁得掉、释放时解除 =================
# 文件夹（资源管理器）把标题栏高度烤进了布局：剥掉 WS_CAPTION 后内容仍从
# 31px 处开始排，顶部留一条它自己画不出来的空带，且劝不动它重排
# （v1.7.2 已穷举 RDW / 样式循环 / 重挂 / 缩放）。所以 place_current 把它量出来，
# 窗口整体上移、加高，再用窗口区域把那一条裁到可视区之外 —— 用户区里只有内容。
print("\n=== 7. 客户区顶部空带：量得准、裁得掉、释放时解除 ===")
cap_w, cap_h = make_window((360, 260, 640, 320), "#204020")
cap_w.update()
kids = [h for h in H.child_windows(cap_h)
        if winapi.u32.GetParent(h) == cap_h]
CK.ok("造出带客户区子窗口的窗口", len(kids) == 1,
      [(h, wndutil.win_class(h)) for h in kids])
# 7a 判据：直接子窗口不贴顶（31）就是空带高度；贴顶则为 0
winapi.u32.SetWindowPos(kids[0], None, 0, 31, 360, 260 - 31,
                        0x0004 | 0x0010)        # NOZORDER | NOACTIVATE
CK.ok("子窗口不贴顶 -> 量出空带 31",
      A.Tab(cap_h).measure_blank() == 31, wndutil.win_rect(kids[0]))
winapi.u32.SetWindowPos(kids[0], None, 0, 0, 360, 260, 0x0004 | 0x0010)
CK.ok("子窗口贴顶 -> 空带为 0",
      A.Tab(cap_h).measure_blank() == 0, wndutil.win_rect(kids[0]))

# 7b 动作：吸附后剥掉边框/标题栏；空白非零时上移 + 加高 + 裁剪
style_before = wndutil.get_long(cap_h, GWL_STYLE)
ex_before = wndutil.get_long(cap_h, GWL_EXSTYLE)
CK.ok("夹具是无边框窗口（判据只看空带，不看窗口样式）",
      not (style_before & winapi.WS_CAPTION), hex(style_before))
absorber4 = A.Absorber(lambda: panel_root, -1)
tab4, msg4 = absorber4.absorb(cap_h)
CK.ok("该类窗口也能吸附", tab4 is not None, msg4)
style_in = wndutil.get_long(cap_h, GWL_STYLE)
CK.ok("吸附后标题栏与边框已剥掉（纯内容面）",
      not (style_in & winapi.WS_CAPTION)
      and not (style_in & winapi.WS_THICKFRAME)
      and not (style_in & winapi.WS_POPUP)
      and bool(style_in & winapi.WS_CHILD), hex(style_in))
# 真机由 measure_blank 量出 31；这里注入，省去造一个"客户区子窗口不贴顶"
# 的原生窗口（Tk 在 WM_SIZE 后会把子窗口拉回 0，造不出来）
tab4.blank = 31
absorber4.place_current(6, 38, 458, 592)
time.sleep(0.2)
px, py, _pw, _ph = wndutil.win_rect(panel_h)
wx, wy, ww, wh = wndutil.win_rect(cap_h)
CK.ok("窗口上移 31、加高 31（可见部分仍落在用户区）",
      abs(wx - (px + 6)) <= 1 and abs(wy - (py + 38 - 31)) <= 1
      and abs(ww - 458) <= 2 and abs(wh - 623) <= 2,
      "窗口 %s / 面板 %s" % ((wx, wy, ww, wh), (px, py)))
CK.ok("窗口区域已裁掉顶部那 31px",
      region_box(cap_h) == (0, 31, 458, 623), region_box(cap_h))
CK.ok("窗口仍挂在面板下",
      winapi.u32.GetParent(cap_h) == panel_root,
      winapi.u32.GetParent(cap_h))
absorber4.release_all()
CK.ok("释放后解除裁剪（区域已清除）", region_box(cap_h) is None,
      region_box(cap_h))
CK.ok("释放后样式逐位还原",
      wndutil.get_long(cap_h, GWL_STYLE) == style_before,
      "0x%08X -> 0x%08X" % (style_before, wndutil.get_long(cap_h, GWL_STYLE)))
CK.ok("释放后扩展样式逐位还原",
      wndutil.get_long(cap_h, GWL_EXSTYLE) == ex_before,
      "0x%08X -> 0x%08X" % (ex_before, wndutil.get_long(cap_h, GWL_EXSTYLE)))
cap_w.destroy()

panel_w.destroy()
root.destroy()
sys.exit(CK.report())
