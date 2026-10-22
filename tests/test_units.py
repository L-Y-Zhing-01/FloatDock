# -*- coding: utf-8 -*-
"""纯逻辑单元测试：热键映射、按键解析、缩放几何、托盘路由、配置读写。

不含任何界面 —— 需要 Tk 的测试在 test_ui.py，走真实系统调用的在
test_hotkey_register.py，整机流程在 test_e2e_app.py。
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import config as cfg_mod                        # noqa: E402
import hotkey                                   # noqa: E402
import theme                                    # noqa: E402
import tray                                     # noqa: E402

CK = H.Checker("单元测试")


# ================= 1. 热键映射 =================
print("=== 1. 热键 spec -> Win32 ===")
mods, vk, label = hotkey.hotkey_to_win({"ctrl": True, "alt": True, "key": "d"})
CK.ok("默认 Ctrl+Alt+D", (mods, vk, label) == (0x3, ord("D"), "Ctrl+Alt+D"),
      "%s %s %s" % (hex(mods), hex(vk), label))

mods, vk, label = hotkey.hotkey_to_win({"ctrl": True, "shift": True, "key": "F9"})
CK.ok("Ctrl+Shift+F9", (mods, vk, label) == (0x2 | 0x4, 0x78, "Ctrl+Shift+F9"),
      "%s %s %s" % (hex(mods), hex(vk), label))

mods, vk, label = hotkey.hotkey_to_win({"ctrl": True, "alt": True,
                                        "shift": True, "win": True, "key": "3"})
CK.ok("四修饰键 + 3", (mods, vk, label) == (0xF, ord("3"), "Ctrl+Alt+Shift+Win+3"),
      label)

mods, vk, label = hotkey.hotkey_to_win({"ctrl": True, "key": "NUMPAD7"})
CK.ok("小键盘注册 VK_NUMPAD7 而非主键盘 7",
      vk == 0x67 and mods == hotkey.MOD_CONTROL, "vk=0x%X" % vk)
CK.ok("小键盘显示名可区分", label == "Ctrl+小键盘7", label)

for bad in ({"key": "A"}, {"ctrl": True, "key": "F25"}, {"ctrl": True, "key": ""},
            {"ctrl": True, "key": "@"}, {"alt": True, "key": "Enter"}, None):
    try:
        hotkey.hotkey_to_win(bad)
        CK.ok("非法配置应报错 %r" % (bad,), False, "未抛异常")
    except ValueError as e:
        CK.ok("非法配置应报错 %r" % (bad,), True, str(e)[:30])


# ================= 2. 无修饰键策略 =================
print("\n=== 2. 哪些键可以单独使用 ===")
for key, want in (("F1", True), ("F11", True), ("F12", True), ("F24", True),
                  ("f9", True), ("F0", False), ("F25", False), ("F99", False),
                  ("A", False), ("0", False), ("NUMPAD7", False),
                  ("", False), ("Ctrl", False), ("FK", False)):
    got = hotkey.is_standalone_ok(key)
    CK.ok("is_standalone_ok(%r) == %s" % (key, want), got is want, "实际=%s" % got)

mods, vk, label = hotkey.hotkey_to_win({"ctrl": False, "alt": False,
                                        "shift": False, "win": False,
                                        "key": "F9"})
CK.ok("裸 F9 -> mods=0 / VK_F9 / 显示名无加号",
      mods == 0 and vk == 0x78 and label == "F9", "%s %s" % (mods, label))

for bad in ("A", "0", "NUMPAD7"):
    try:
        hotkey.hotkey_to_win({"ctrl": False, "alt": False, "shift": False,
                              "win": False, "key": bad})
        CK.ok("裸 %s 被拒" % bad, False, "未抛 ValueError")
    except ValueError as e:
        CK.ok("裸 %s 被拒且提示可用范围" % bad, "F1–F11" in str(e), str(e))

try:
    hotkey.hotkey_to_win({"ctrl": False, "alt": False, "shift": False,
                          "win": False, "key": "F12"})
    CK.ok("裸 F12 通过策略校验（成败交给系统判定）", True)
except ValueError as e:
    CK.ok("裸 F12 通过策略校验（成败交给系统判定）", False, str(e))
CK.ok("F12 被识别为系统保留键", hotkey.is_debugger_reserved("f12") is True)
CK.ok("其他功能键不算保留键", hotkey.is_debugger_reserved("F11") is False)


# ================= 3. 按键解析（真机退化场景） =================
print("\n=== 3. 一次按键 -> 修饰键 / 主键 ===")
for vk, want in ((0xA2, "ctrl"), (0xA3, "ctrl"), (0xA4, "alt"), (0xA5, "alt"),
                 (0xA0, "shift"), (0xA1, "shift"), (0x5B, "win"), (0x5C, "win")):
    CK.ok("vk=0x%02X -> %s" % (vk, want),
          hotkey.mod_of(vk, "??") == want, hotkey.mod_of(vk, "??"))
for keysym, want in (("Control_L", "ctrl"), ("Alt_R", "alt"),
                     ("Shift_L", "shift"), ("Super_L", "win"),
                     ("Win_L", "win"), ("Meta_L", "win")):
    CK.ok("keysym=%s -> %s（keycode 缺失时的兜底）" % (keysym, want),
          hotkey.mod_of(0, keysym) == want)

CK.ok("小键盘 7（keysym 与主键盘相同，靠 VK 区分）"
      "-> NUMPAD7", hotkey.key_of(0x67, "7") == "NUMPAD7")
CK.ok("主键盘 7 -> '7'", hotkey.key_of(0x37, "7") == "7")
CK.ok("F9（vk=0x78）-> F9", hotkey.key_of(0x78, "F9") == "F9")
CK.ok("NumLock 关闭时的 KP_Home -> NUMPAD7",
      hotkey.key_of(0, "KP_Home") == "NUMPAD7")
CK.ok("NumLock 打开时的 KP_7 -> NUMPAD7", hotkey.key_of(0, "KP_7") == "NUMPAD7")
CK.ok("F25 不被接受", hotkey.key_of(0, "F25") is None)
CK.ok("Home 不被接受", hotkey.key_of(0, "Home") is None)
CK.ok("小写字母归一成大写", hotkey.key_of(0, "d") == "D")


# ================= 4. sanitize =================
print("\n=== 4. 配置里的坏热键要被修掉 ===")
CK.ok("合法 spec 原样保留",
      hotkey.sanitize({"ctrl": True, "key": "f9"}) ==
      {"ctrl": True, "alt": False, "shift": False, "win": False, "key": "F9"},
      hotkey.sanitize({"ctrl": True, "key": "f9"}))
CK.ok("非法 spec 退回默认", hotkey.sanitize({"key": "A"}) == hotkey.DEFAULT_HOTKEY)
CK.ok("None 退回默认", hotkey.sanitize(None) == hotkey.DEFAULT_HOTKEY)


# ================= 5. 缩放几何 =================
print("\n=== 5. 拖拽缩放的几何运算 ===")
from_rect = (1000, 200, 470, 660)
cases = [
    ("右边右拖 +130", from_rect, "r", (130, 0), (1000, 200, 600, 660)),
    ("上边下拖 +50", from_rect, "t", (0, 50), (1000, 250, 470, 610)),
    ("下边上拖 -80", from_rect, "b", (0, -80), (1000, 200, 470, 580)),
    ("左上角 (+40,+30)", from_rect, "tl", (40, 30), (1040, 230, 430, 630)),
    ("右下角 (+60,+40)", from_rect, "br", (60, 40), (1000, 200, 530, 700)),
    ("右上角 (+100,+60)", from_rect, "tr", (100, 60), (1000, 260, 570, 600)),
    ("左边右拖 +100（起始 600 宽）", (1000, 200, 600, 660), "l", (100, 0),
     (1100, 200, 500, 660)),
]
for name, rect, zone, delta, want in cases:
    got = theme.resized_rect(rect, delta, zone)
    CK.ok(name, got == want, got)

got = theme.resized_rect(from_rect, (900, 0), "l")
CK.ok("左边超拖钳制到 MIN_W 且右边不动",
      got == (1000 + 470 - theme.MIN_W, 200, theme.MIN_W, 660), got)
got = theme.resized_rect(from_rect, (0, 900), "t")
CK.ok("上边超拖钳制到 MIN_H 且下边不动",
      got == (1000, 200 + 660 - theme.MIN_H, 470, theme.MIN_H), got)

z = lambda x, y: theme.resize_zone(470, 660, x, y)
CK.ok("角区/边区/内部判定",
      z(2, 2) == "tl" and z(468, 2) == "tr" and z(2, 658) == "bl"
      and z(468, 658) == "br" and z(2, 300) == "l" and z(468, 300) == "r"
      and z(200, 2) == "t" and z(200, 658) == "b" and z(200, 300) is None
      and z(30, 30) is None,
      "%s %s" % (z(2, 2), z(200, 300)))

CK.ok("工具栏行已删除，客户区矩形从四边 chrome 反推",
      not hasattr(theme, "H_TOOL")
      and theme.content_rect(470, 660) == (6, theme.H_TITLE + 2, 458,
                                           660 - theme.H_TITLE - 32),
      theme.content_rect(470, 660))
CK.ok("标签栏（多窗口时代的那一行）已随单窗口容器删除",
      not hasattr(theme, "H_TAB") and not hasattr(theme, "tabbar_visible"))

# ================= 5b. 标题栏按钮集群与透明度浮层 =================
print("\n=== 5b. 标题栏按钮集群与透明度浮层 ===")
btns = dict((n, bx) for n, _g, bx in theme.title_buttons(470))
CK.ok("七个标题按钮、右端留 6、间距 4",
      len(btns) == 7 and btns["close"] == 470 - 34
      and btns["grab"] == 470 - 226 and btns["opacity"] == 470 - 162,
      btns)
order = [bx for _n, _g, bx in theme.title_buttons(470)]     # 右 -> 左，递减
CK.ok("按钮从右往左步距 32",
      all(b1 - b2 == theme.BTN_STEP for b1, b2 in zip(order, order[1:])), order)
CK.ok("标题拖拽区止于集群左侧 4px",
      theme.title_hit(470) == (0, 0, 470 - 230, theme.H_TITLE),
      theme.title_hit(470))
for w in (380, 470, 930):
    px1, py1, px2, py2 = theme.popup_rect(w)
    sx1, sy, sx2, _ = theme.slider_geo(w)
    grab_left = dict((n, bx) for n, _g, bx in theme.title_buttons(w))["grab"]
    CK.ok("浮层在标题栏内、按钮左侧、滑块可拖 w=%d" % w,
          px1 >= 4 and px2 <= grab_left - 4 and 0 < py1 and py2 < theme.H_TITLE
          and sx1 >= px1 and sx2 <= px2 - 30 and abs(sy - theme.H_TITLE // 2) <= 1,
          (theme.popup_rect(w), theme.slider_geo(w)))


# ================= 6. 托盘鼠标消息路由 =================
print("\n=== 6. 托盘消息路由 ===")
CK.ok("0x0203 是左键双击、0x0205 才是右键",
      tray.WM_LBUTTONDBLCLK == 0x0203 and tray.WM_RBUTTONUP == 0x0205)

aux = tray.AuxThread("test", lambda: False)
popups = []
aux._popup_menu = lambda hwnd: popups.append(hwnd)   # 桩：只记录是否弹菜单
aux._on_tray_msg(tray.WM_RBUTTONUP)
CK.ok("右键单击 -> 弹菜单，不切换显隐",
      len(popups) == 1 and aux.actions.empty())
aux._on_tray_msg(tray.WM_LBUTTONUP)
CK.ok("左键单击 -> 切换显隐",
      aux.actions.qsize() == 1 and aux.actions.get()[0] == "toggle")
aux._on_tray_msg(tray.WM_LBUTTONDBLCLK)
CK.ok("左键双击 -> 既不弹菜单也不切换（修复前的行为）",
      len(popups) == 1 and aux.actions.empty())


# ================= 7. 热键注册与回滚 =================
print("\n=== 7. 动态注册与失败回滚 ===")


class StubU32(object):
    """拦截 RegisterHotKey：带 Shift 的组合一律模拟"已被占用"。"""

    def __init__(self, real):
        self._real = real
        self.tried = []

    def RegisterHotKey(self, hwnd, hid, mods, vk):
        self.tried.append((mods, vk))
        if mods & hotkey.MOD_SHIFT:
            return 0
        return self._real.RegisterHotKey(hwnd, hid, mods, vk)

    def __getattr__(self, name):
        return getattr(self._real, name)


aux2 = tray.AuxThread("test", lambda: False,
                      {"ctrl": True, "alt": True, "key": "D"})
aux2.start()
aux2.ready.wait(3)
CK.ok("辅助窗口已创建", bool(aux2.hwnd), "hwnd=%s" % aux2.hwnd)
time.sleep(0.2)
CK.ok("初始热键已注册", aux2._hk_registered and aux2.hotkey_label == "Ctrl+Alt+D",
      aux2.hotkey_label)

real_u32 = tray.u32
tray.u32 = StubU32(real_u32)


def hk_result(timeout=3.0):
    try:
        return aux2.hk_results.get(timeout=timeout)
    except Exception:
        return None, "（超时）"


try:
    # 走真实消息投递：set_hotkey -> PostMessage -> 辅助线程注册
    aux2.set_hotkey({"ctrl": True, "alt": True, "shift": True, "key": "F9"})
    res = hk_result()
    CK.ok("被占用的组合应失败并保留原键",
          res[0] is False and aux2.hotkey_label == "Ctrl+Alt+D",
          "%r / 现用=%s" % (res, aux2.hotkey_label))

    aux2.set_hotkey({"ctrl": True, "alt": True, "key": "F9"})
    res = hk_result()
    CK.ok("合法组合应生效",
          res[0] is True and aux2.hotkey_label == "Ctrl+Alt+F9", res)

    aux2.set_hotkey({"ctrl": True, "key": "Enter"})
    res = hk_result()
    CK.ok("非法按键被拒绝且不影响现用键",
          res[0] is False and aux2.hotkey_label == "Ctrl+Alt+F9", res)

    aux2.set_hotkey({"key": "A"})
    res = hk_result()
    CK.ok("裸字母被策略拒绝，提示必须搭配修饰键",
          res[0] is False and "必须搭配" in res[1], res)
finally:
    tray.u32 = real_u32
    aux2.remove_tray()
    time.sleep(0.3)


# ================= 8. 配置读写 =================
print("\n=== 8. 配置读写与容错 ===")
tmp = tempfile.mkdtemp(prefix="fd_cfg_")
path = os.path.join(tmp, "config.json")

cfg = cfg_mod.Config(path)
CK.ok("缺文件时用默认值",
      (cfg.w, cfg.h) == (cfg_mod.DEFAULT_W, cfg_mod.DEFAULT_H)
      and cfg.x is None and cfg.hotkey == hotkey.DEFAULT_HOTKEY,
      "%s %s" % (cfg.w, cfg.h))

with open(path, "w", encoding="utf-8") as f:
    json.dump({"x": 100, "y": 120, "w": 5000, "h": 10, "opacity": 9.9,
               "hide_delay": 99, "locked": True,
               "hotkey": {"key": "A"}, "my_own_field": "保留我"}, f)
cfg = cfg_mod.Config(path)
CK.ok("超范围尺寸被夹到合法区间",
      cfg.w == 3000 and cfg.h == theme.MIN_H, "%s %s" % (cfg.w, cfg.h))
CK.ok("超范围透明度被夹到合法区间",
      cfg.opacity == theme.OP_MAX, cfg.opacity)
CK.ok("超范围隐藏延迟被夹到合法区间",
      cfg.hide_delay == cfg_mod.HIDE_DELAY_MAX, cfg.hide_delay)
CK.ok("坏热键退回默认", cfg.hotkey == hotkey.DEFAULT_HOTKEY, cfg.hotkey)
CK.ok("position 与 locked 正常读入",
      (cfg.x, cfg.y) == (100, 120) and cfg.locked is True)

cfg.save()
with open(path, "r", encoding="utf-8") as f:
    saved = json.load(f)
CK.ok("保存后仍保留未知字段", saved.get("my_own_field") == "保留我", saved.keys())
CK.ok("保存的尺寸是夹过的值", saved["w"] == 3000 and saved["h"] == theme.MIN_H)

with open(path, "w", encoding="utf-8") as f:
    f.write("{ 这不是 JSON")
cfg = cfg_mod.Config(path)
CK.ok("配置文件损坏也能起来（退回默认）",
      cfg.w == cfg_mod.DEFAULT_W and cfg.hotkey == hotkey.DEFAULT_HOTKEY)

sys.exit(CK.report())
