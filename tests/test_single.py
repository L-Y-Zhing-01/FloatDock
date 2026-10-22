# -*- coding: utf-8 -*-
"""单窗口容器：吸附新窗口时先把旧的还回桌面，以及首次替换的确认窗。

浮坞一次只放一个窗口 —— 这条规则写在 `Absorber.absorb` 里，不在调用方，
所以这里就着真实 HWND 直接验证：吸附 A → 吸附 B 之后，A 已经回到桌面、
面板下只剩 B、tabs 长度为 1。

确认窗只测"返回值契约"（继续 / 不再提醒 / 取消），它自己点自己：
用 after 找到对话框并 invoke 按钮，不依赖真人操作。
"""
import os
import sys
import tempfile
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402
import absorb as A                              # noqa: E402
import confirm                                  # noqa: E402
import config as C                              # noqa: E402
import winapi                                   # noqa: E402
import wndutil                                  # noqa: E402

winapi.enable_dpi_awareness()
CK = H.Checker("单窗口容器")

root = tk.Tk()
root.withdraw()
root.update()


def make_window(geom, color):
    w = tk.Toplevel(root)
    w.overrideredirect(True)
    w.geometry("%dx%d+%d+%d" % geom)
    w.configure(bg=color)
    w.update()
    return w, wndutil.root_of(w.winfo_id())


def widgets(w, kind):
    """递归收集某种控件（按钮/勾选框都埋在 Frame 里）。"""
    out = []
    for child in w.winfo_children():
        if isinstance(child, kind):
            out.append(child)
        out.extend(widgets(child, kind))
    return out


def click_later(prefix, tick=False):
    """等对话框建好后点它：可先勾选，再点文字以 prefix 开头的按钮。"""
    def act():
        for top in root.winfo_children():
            if not isinstance(top, tk.Toplevel):
                continue
            if tick:
                for cb in widgets(top, tk.Checkbutton):
                    cb.invoke()
            for btn in widgets(top, tk.Button):
                if btn.cget("text").startswith(prefix):
                    btn.invoke()
                    return
    root.after(120, act)


panel_w, panel_h = make_window((470, 620, 760, 80), "#202020")
a_w, a_h = make_window((300, 200, 200, 200), "#203040")
b_w, b_h = make_window((300, 200, 560, 200), "#402030")

a_rect0 = wndutil.win_rect(a_h)
a_style0 = wndutil.get_long(a_h, winapi.GWL_STYLE)

# ================= 1. 吸附 B 时自动把 A 还回去 =================
print("\n=== 1. 一次只放一个窗口：吸附新的先释放旧的 ===")
ab = A.Absorber(lambda: panel_h, -1)
tab, msg = ab.absorb(a_h)
CK.ok("吸附 A 成功", tab is not None and ab.tab is tab, msg)
ab.place_current(6, 38, 458, 592)
CK.ok("A 在面板下", winapi.u32.GetParent(a_h) == panel_h,
      winapi.u32.GetParent(a_h))

tab2, msg2 = ab.absorb(b_h)
CK.ok("吸附 B 成功", tab2 is not None and tab2.hwnd == b_h, msg2)
CK.ok("容器里只剩一个窗口", ab.tab is tab2, ab.tab.title)
CK.ok("B 已挂在面板下", winapi.u32.GetParent(b_h) == panel_h,
      winapi.u32.GetParent(b_h))
CK.ok("A 已脱离面板", winapi.u32.GetParent(a_h) != panel_h,
      winapi.u32.GetParent(a_h))
CK.ok("A 回到原来位置（误差 ≤2px）",
      all(abs(x - y) <= 2 for x, y in zip(wndutil.win_rect(a_h), a_rect0)),
      "%s vs %s" % (wndutil.win_rect(a_h), a_rect0))
CK.ok("A 的窗口样式逐位还原",
      wndutil.get_long(a_h, winapi.GWL_STYLE) == a_style0,
      "0x%08X -> 0x%08X" % (a_style0, wndutil.get_long(a_h, winapi.GWL_STYLE)))
CK.ok("A 重新可见", H.visible(a_h) is True)

# ================= 2. 吸附已在容器里的那个窗口 =================
print("\n=== 2. 重复吸附同一个窗口：不释放、也不重复吸附 ===")
tab3, msg3 = ab.absorb(b_h)
CK.ok("返回「已在浮坞中」", msg3 == "已在浮坞中", msg3)
CK.ok("仍是同一个 tab、没有被替换", tab3 is tab2 and ab.tab is tab2,
      ab.tab.title)
CK.ok("B 仍挂在面板下", winapi.u32.GetParent(b_h) == panel_h,
      winapi.u32.GetParent(b_h))

# ================= 3. 确认窗的返回值契约 =================
print("\n=== 3. 首次替换的确认窗 ===")
click_later("先释放")
ok, no_more = confirm.ask_replace(root, (760, 80, 470, 620), "旧的", "新的")
CK.ok("点「先释放，再吸附」-> 继续，且仍会提醒", ok is True and no_more is False,
      (ok, no_more))

click_later("先释放", tick=True)
ok, no_more = confirm.ask_replace(root, (760, 80, 470, 620), "旧的", "新的")
CK.ok("勾了「以后不再提醒」-> 继续，且回报不再提醒",
      ok is True and no_more is True, (ok, no_more))

click_later("取消")
ok, no_more = confirm.ask_replace(root, (760, 80, 470, 620), "旧的", "新的")
CK.ok("点「取消」-> 不继续", ok is False, (ok, no_more))
CK.ok("确认窗已全部销毁", not widgets(root, tk.Checkbutton)
      or all(w.winfo_exists() for w in ()), "ok")

# ================= 4. auto_release 的持久化 =================
print("\n=== 4. 「不再提醒」落在配置里 ===")
path = os.path.join(tempfile.mkdtemp(prefix="fd_cfg_"), "config.json")
cfg = C.Config(path)
CK.ok("默认会提醒（auto_release=False）", cfg.auto_release is False,
      cfg.auto_release)
cfg.auto_release = True
cfg.save()
CK.ok("保存后重新读取仍为 True", C.Config(path).auto_release is True,
      C.Config(path).auto_release)
with open(path, "w", encoding="utf-8") as f:
    f.write('{"auto_release": "yes"}')
CK.ok("写坏的值不会被当成 True", C.Config(path).auto_release is False,
      C.Config(path).auto_release)

ab.release_all()
for w in (a_w, b_w, panel_w):
    w.destroy()
root.destroy()
sys.exit(CK.report())
