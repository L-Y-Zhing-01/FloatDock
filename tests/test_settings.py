# -*- coding: utf-8 -*-
"""设置窗口（Tk 层）测试：按键捕获、校验、修饰键同步、灵敏度滑块。

为什么必须在真 Tk 里跑、而不是直接调函数：最初的问题"F1–F12 无法键入"
本身就是 Tk 事件分发行为造成的 —— 功能键不产生 event.char，普通 Entry
的默认绑定根本不会写入。所以这里用 event_generate 造真实按键分发。

只在 Tk 合成器认得的 keysym 上走 event_generate；小键盘、右 Ctrl 这类
合成器会退化成 "??" 的取值，用 SimpleNamespace 直接喂给 _key_capture，
其真机取值由 test_e2e_app.py 的消息注入覆盖。
"""
import os
import sys
import types
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import hotkey                                   # noqa: E402
import theme as T                               # noqa: E402
from config import HIDE_DELAY_MAX, HIDE_DELAY_MIN   # noqa: E402
from settings import SettingsDialog             # noqa: E402

CK = H.Checker("设置窗口")


class HooksStub(object):
    """记下设置窗口对外发出的每一次调用。"""

    def __init__(self):
        self.applied = []
        self.delays = []
        self.closed_count = 0

    def apply_hotkey(self, spec):
        self.applied.append(dict(spec))

    def delay_changed(self, seconds):
        self.delays.append(seconds)

    def closed(self):
        self.closed_count += 1


root = tk.Tk()
root.title("设置窗口测试宿主")
root.withdraw()
root.update()


def new_dialog(spec=None, label=None, delay=0.05):
    spec = dict(spec or {"ctrl": True, "alt": True, "shift": False,
                         "win": False, "key": "D"})
    hooks = HooksStub()
    dlg = SettingsDialog(root, (100, 100, 470), spec,
                         label or hotkey.hotkey_to_win(spec)[2], delay, hooks)
    root.update()
    return dlg, hooks


def key_entry(dlg):
    return dlg._key_entry


def press(dlg, keysym):
    """合成一次真实按键分发；合成器不认识的名字返回 False。"""
    try:
        key_entry(dlg).event_generate("<KeyPress-%s>" % keysym)
    except tk.TclError:
        return False
    root.update()
    return True


def feed(dlg, keysym, keycode=0):
    """直接喂一个按键事件对象（用于合成器造不出来的 keysym）。"""
    dlg._key_capture(types.SimpleNamespace(keysym=keysym, keycode=keycode))
    root.update()


def showed(dlg):
    return key_entry(dlg).get()


def hint(dlg):
    return (dlg._hint.cget("text"), str(dlg._hint.cget("fg")))


# ================= 0. 对照实验：普通 Entry 的老 bug =================
print("=== 0. 对照：为什么必须做捕获 ===")
plain = tk.Entry(root)
plain.pack()
plain.focus_force()
root.update()
plain.event_generate("<KeyPress-F9>")
root.update()
CK.ok("普通 Entry 按 F9 后内容仍为空（当初的 bug）",
      plain.get() == "" and plain.index("end") == 0, "内容=%r" % plain.get())
plain.destroy()


# ================= 1. 只读输入框 =================
print("\n=== 1. 按键框只读，禁止手输乱填 ===")
dlg, hooks = new_dialog()
CK.ok("input 为 readonly", str(key_entry(dlg).cget("state")) == "readonly")
try:
    key_entry(dlg).insert(0, "X")
except tk.TclError:
    pass
CK.ok("只读状态拒绝直接写入", showed(dlg) == "D", showed(dlg))
CK.ok("初始回填配置里的主键",
      dlg._mods["ctrl"].get() is True and dlg._mods["alt"].get() is True)
CK.ok("初始提示行显示当前热键", "Ctrl+Alt+D" in dlg._hint.cget("text"),
      dlg._hint.cget("text"))

key_entry(dlg).focus_force()
root.update()
press(dlg, "a")
CK.ok("按键被当作主键捕获而不是落进文本框", showed(dlg) == "A", showed(dlg))
dlg.close()


# ================= 2. 功能键（原问题） =================
print("\n=== 2. F1–F24 全部可捕获 ===")
dlg, hooks = new_dialog()
bad = []
for n in list(range(1, 25)):
    press(dlg, "F%d" % n)
    if showed(dlg) != "F%d" % n:
        bad.append((n, showed(dlg)))
CK.ok("F1–F24 逐个按下都能写入", not bad, str(bad))

press(dlg, "F25")
CK.ok("F25 不写入且给出提示",
      showed(dlg) == "F24" and "不支持" in dlg._hint.cget("text"),
      "%s / %s" % (showed(dlg), dlg._hint.cget("text")))


# ================= 3. 字母 / 数字 =================
print("\n=== 3. 字母与数字 ===")
for ks, want in (("d", "D"), ("z", "Z"), ("0", "0"), ("5", "5"), ("A", "A")):
    press(dlg, ks)
    CK.ok("keysym %s -> %s" % (ks, want), showed(dlg) == want, showed(dlg))


# ================= 4. 小键盘（VK 与主键盘不同） =================
print("\n=== 4. 小键盘数字必须与主键盘分开 ===")
for ks, want in (("KP_7", "NUMPAD7"), ("KP_0", "NUMPAD0"),
                 ("KP_Home", "NUMPAD7"), ("KP_End", "NUMPAD1"),
                 ("KP_Begin", "NUMPAD5"), ("KP_Prior", "NUMPAD9")):
    feed(dlg, ks)
    CK.ok("keysym %s -> %s（NumLock 开/关都一样）" % (ks, want),
          showed(dlg) == want, showed(dlg))
feed(dlg, "7", keycode=0x67)
CK.ok("NumLock 开：keysym=7 + vk=0x67 -> NUMPAD7", showed(dlg) == "NUMPAD7",
      showed(dlg))
feed(dlg, "7", keycode=0x37)
CK.ok("主键盘：keysym=7 + vk=0x37 -> 7", showed(dlg) == "7", showed(dlg))


# ================= 5. 修饰键同步 =================
print("\n=== 5. 修饰键：VK 优先、keysym 兜底 ===")
for keysym, mod in (("Control_L", "ctrl"), ("Control_R", "ctrl"),
                    ("Alt_L", "alt"), ("Alt_R", "alt"),
                    ("Shift_L", "shift"), ("Shift_R", "shift"),
                    ("Super_L", "win"), ("Super_R", "win"),
                    ("Meta_L", "win"), ("Win_L", "win")):
    for var in dlg._mods.values():
        var.set(False)
    feed(dlg, keysym)
    CK.ok("keysym=%s 勾上 %s" % (keysym, mod), dlg._mods[mod].get() is True)
    CK.ok("keysym=%s 不改动主键" % keysym, showed(dlg) == "7", showed(dlg))

# 真机实测：右 Ctrl 的 keysym 会退化成 "??"，只能靠 VK 判定
for vk, mod in ((0xA2, "ctrl"), (0xA3, "ctrl"), (0xA4, "alt"), (0xA5, "alt"),
                (0xA0, "shift"), (0xA1, "shift"), (0x5B, "win"), (0x5C, "win")):
    for var in dlg._mods.values():
        var.set(False)
    feed(dlg, "??", keycode=vk)
    CK.ok("vk=0x%02X keysym=? -> %s" % (vk, mod), dlg._mods[mod].get() is True)
    CK.ok("vk=0x%02X 不改动主键" % vk, showed(dlg) == "7", showed(dlg))


# ================= 6. 不支持的键 / Tab =================
print("\n=== 6. 不支持的键与 Tab 导航 ===")
for ks in ("Home", "End", "Escape", "space", "Up", "Insert", "Menu", "F26"):
    before = showed(dlg)
    press(dlg, ks)
    CK.ok("%s 不写入且给出提示" % ks,
          showed(dlg) == before and "不支持" in dlg._hint.cget("text"),
          "%s / %s" % (showed(dlg), dlg._hint.cget("text")))

ret = dlg._key_capture(types.SimpleNamespace(keysym="Tab", keycode=0))
CK.ok("Tab 返回 None（放行，保留控件间导航）", ret is None, repr(ret))
ret = dlg._key_capture(types.SimpleNamespace(keysym="F9", keycode=0x78))
CK.ok("普通键返回 'break'（阻止类绑定继续冒泡）", ret == "break", repr(ret))


# ================= 7. 提示文案（v1.3 无修饰键策略） =================
print("\n=== 7. 捕获后立刻讲清「能不能用」 ===")
dlg, hooks = new_dialog()
for var in dlg._mods.values():
    var.set(False)
press(dlg, "F9")
text, fg = hint(dlg)
CK.ok("裸 F9 提示【单独使用】", "单独使用" in text, text)
CK.ok("裸 F9 不用错误色", fg != T.C_DANGER, fg)

for var in dlg._mods.values():
    var.set(False)
press(dlg, "F12")
text, fg = hint(dlg)
CK.ok("裸 F12 提示【调试器保留】", "调试器" in text, text)
CK.ok("裸 F12 用错误色", fg == T.C_DANGER, fg)

for var in dlg._mods.values():
    var.set(False)
press(dlg, "k")
text, fg = hint(dlg)
CK.ok("裸字母当场报错，不必等点应用",
      "必须搭配" in text and fg == T.C_DANGER, text)

for var in dlg._mods.values():
    var.set(False)
dlg._mods["ctrl"].set(True)
press(dlg, "F9")
hint_text = dlg._hint.cget("text")
CK.ok("带修饰键时提示组合键", "Ctrl+F9" in hint_text, hint_text)


# ================= 8. 清空修饰键 =================
print("\n=== 8. 「清空修饰键」按钮 ===")
for var in dlg._mods.values():
    var.set(True)
dlg._set_key_text("F9")
dlg._clear_mods()
CK.ok("清空后所有修饰键均未勾选",
      all(not v.get() for v in dlg._mods.values()))
CK.ok("清空后提示 F9 将单独生效", "单独生效" in dlg._hint.cget("text"),
      dlg._hint.cget("text"))

dlg._set_key_text("F12")
dlg._mods["ctrl"].set(True)
dlg._clear_mods()
CK.ok("F12 清空后提示调试器保留（错误色）",
      "调试器" in dlg._hint.cget("text")
      and str(dlg._hint.cget("fg")) == T.C_DANGER, dlg._hint.cget("text"))

dlg._set_key_text("K")
dlg._clear_mods()
CK.ok("字母清空后提示必须搭配修饰键",
      "必须搭配" in dlg._hint.cget("text"), dlg._hint.cget("text"))

# 清空后直接按功能键：应能捕获并以裸键通过校验
dlg._mods["ctrl"].set(True)
dlg._clear_mods()
press(dlg, "F7")
CK.ok("清空修饰键后按 F7，主键为 F7 且修饰键全空",
      showed(dlg) == "F7" and not any(v.get() for v in dlg._mods.values()),
      "%s %s" % (showed(dlg), {k: v.get() for k, v in dlg._mods.items()}))
dlg.close()


# ================= 9. 应用 / 回车 / 拦截 =================
print("\n=== 9. 应用快捷键 ===")
dlg, hooks = new_dialog()
dlg._set_key_text("F5")
dlg._apply_hotkey()
CK.ok("「应用快捷键」把 spec 投给后台注册",
      len(hooks.applied) == 1 and hooks.applied[0]["key"] == "F5"
      and hooks.applied[0]["ctrl"] is True, str(hooks.applied))
CK.ok("投递期间提示【正在注册…】", "正在注册" in dlg._hint.cget("text"),
      dlg._hint.cget("text"))

# 功能键 + 无修饰键：合法，应当投递
dlg._set_key_text("F6")
for var in dlg._mods.values():
    var.set(False)
dlg._apply_hotkey()
CK.ok("功能键无修饰键可投递（单独使用）",
      len(hooks.applied) == 2 and hooks.applied[1]["key"] == "F6"
      and not any(hooks.applied[1][k] for k in ("ctrl", "alt", "shift", "win")),
      str(hooks.applied))

# 字母 + 无修饰键：应被本地校验拦下，不打扰后台线程
dlg._set_key_text("K")
dlg._apply_hotkey()
CK.ok("字母无修饰键被本地拦下且不投递",
      len(hooks.applied) == 2 and "必须搭配" in dlg._hint.cget("text"),
      dlg._hint.cget("text"))

# 回车 = 点应用
dlg._set_key_text("F8")
n = len(hooks.applied)
key_entry(dlg).event_generate("<Return>")
root.update()
CK.ok("回车触发应用", len(hooks.applied) == n + 1
      and hooks.applied[-1]["key"] == "F8", str(hooks.applied))


# ================= 10. 回写结果 =================
print("\n=== 10. 后台注册结果回写提示行 ===")
dlg.show_hotkey_result(True, "Ctrl+Alt+F8")
CK.ok("成功：提示【已生效】且用强调色",
      "已生效" in dlg._hint.cget("text")
      and str(dlg._hint.cget("fg")) == T.C_ACC, dlg._hint.cget("text"))
dlg.show_hotkey_result(False, "该组合已被其他程序占用")
CK.ok("失败：原样显示原因且用错误色",
      dlg._hint.cget("text") == "该组合已被其他程序占用"
      and str(dlg._hint.cget("fg")) == T.C_DANGER, dlg._hint.cget("text"))


# ================= 11. 灵敏度滑块 =================
print("\n=== 11. 隐藏延迟滑块 ===")
dlg, hooks = new_dialog(delay=0.05)
dlg._on_delay_changed("0.12")
CK.ok("滑块回调同步 hide_delay 并通知面板", dlg.hide_delay == 0.12
      and hooks.delays == [0.12], "%s / %s" % (dlg.hide_delay, hooks.delays))
CK.ok("读数已刷新", "0.12" in dlg._delay_txt.cget("text"),
      dlg._delay_txt.cget("text"))
dlg._on_delay_changed("9")
CK.ok("超上限被夹到 HIDE_DELAY_MAX", dlg.hide_delay == HIDE_DELAY_MAX,
      dlg.hide_delay)
dlg._on_delay_changed("-5")
CK.ok("低于下限被夹到 HIDE_DELAY_MIN", dlg.hide_delay == HIDE_DELAY_MIN,
      dlg.hide_delay)
dlg._on_delay_changed("不是数字")
CK.ok("非法输入不改动现值", isinstance(dlg.hide_delay, float), dlg.hide_delay)


# ================= 12. 关闭 =================
print("\n=== 12. 关闭与生命周期 ===")
dlg.close()
CK.ok("关闭后 is_open 为假", dlg.is_open is False)
CK.ok("关闭回调只触发一次", hooks.closed_count == 1, hooks.closed_count)
dlg.show_hotkey_result(True, "迟到结果")
CK.ok("窗口已关时回写结果不抛异常", True)
dlg.close()
CK.ok("重复关闭不会二次触发回调", hooks.closed_count == 1, hooks.closed_count)

root.destroy()
sys.exit(CK.report())
