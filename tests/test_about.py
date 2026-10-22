# -*- coding: utf-8 -*-
"""关于框：文案来源、可复制性、窗口行为，以及"只有一处入口"的静态核查。

全部在本进程的 Tk 里跑完，可以随时单跑：

    python tests/test_about.py

三条判据值得单独说：
  · **地址与邮箱必须出现在只读 Entry 里**，而不是 Label。Label 的文字选不中，
    用户看到源码地址却复制不走，等于没给。所以断言的是"有 Entry 且值相等"。
  · **不设 transient**。浮坞是 overrideredirect 悬浮窗，一旦关于框成为它的
    owned window，面板自动隐藏（withdraw）时关于框会跟着一起消失 ——
    tip.py 已经踩过这个坑，这里用 `win.transient()` 为空来锁住。
  · **panel.py 里不能再出现 messagebox**。原「关于浮坞」是 messagebox，
    正文不可选中也不能放按钮；改走 about.py 之后若又冒出来一个，
    就等于同一条信息有两个来源，迟早不一致。这是静态核查，不是运行时断言。
"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import harness as H                             # noqa: E402

import about                                    # noqa: E402
import settings as S                            # noqa: E402

CK = H.Checker("关于")


def texts(widget, acc=None):
    """收集一棵控件树里所有可见文字（Label 的 text 与 Entry 的 get）。"""
    acc = [] if acc is None else acc
    for opt in ("text",):
        try:
            acc.append(str(widget.cget(opt)))
        except Exception:
            pass
    if widget.winfo_class() in ("Entry", "TEntry"):
        try:
            acc.append(str(widget.get()))
        except Exception:
            pass
    for child in widget.winfo_children():
        texts(child, acc)
    return acc


def entries(widget, acc=None):
    """收集所有 Entry 的 (类型, 当前值)。"""
    acc = [] if acc is None else acc
    if widget.winfo_class() in ("Entry", "TEntry"):
        try:
            acc.append((widget.winfo_class(), str(widget.get()),
                        str(widget.cget("state"))))
        except Exception:
            pass
    for child in widget.winfo_children():
        entries(child, acc)
    return acc


# ================= 常量 =================
CK.ok("源码地址是 https 的仓库地址",
      about.REPO_URL.startswith("https://github.com/")
      and about.REPO_URL.rstrip("/").endswith("FloatDock"), about.REPO_URL)
CK.ok("反馈邮箱形如 xxx@qq.com",
      "@" in about.FEEDBACK_MAIL and about.FEEDBACK_MAIL.endswith("@qq.com"),
      about.FEEDBACK_MAIL)
CK.ok("许可写的是 MIT", about.LICENSE_NAME == "MIT", about.LICENSE_NAME)
CK.ok("作者署名非空", bool(about.AUTHOR.strip()), about.AUTHOR)

# ================= 窗口 =================
root = tk.Tk()
root.withdraw()
root.update()

win = about.open_about(root, "v1.10.0", "Ctrl+Alt+D", (100, 100, 600, 700))
root.update()
root.update_idletasks()

CK.ok("窗口已创建", win is not None and bool(win.winfo_exists()))
CK.ok("尺寸固定（不许拉坏版式）", tuple(win.resizable()) == (0, 0),
      win.resizable())
CK.ok("不设 transient（否则随面板隐藏一起消失）", win.transient() in ("", None),
      win.transient())
CK.ok("置顶", bool(win.attributes("-topmost")), win.attributes("-topmost"))

body = " ".join(texts(win))
CK.ok("显示版本号", "v1.10.0" in body)
CK.ok("显示当前热键", "Ctrl+Alt+D" in body)
CK.ok("显示 MIT", "MIT" in body)
CK.ok("显示源码地址", about.REPO_URL in body)
CK.ok("显示反馈邮箱", about.FEEDBACK_MAIL in body)
CK.ok("显示图标来源 WorkBuddy", "WorkBuddy" in body)
CK.ok("显示版权年与作者", "2026" in body and about.AUTHOR in body)

# 地址与邮箱必须是可选中复制的 Entry
rows = entries(win)
CK.ok("邮编与地址放在只读 Entry 里（可选中复制）",
      any(v == about.FEEDBACK_MAIL and st == "readonly" for _c, v, st in rows)
      and any(v == about.REPO_URL and st == "readonly" for _c, v, st in rows),
      rows)

# ================= 关闭 =================
win.event_generate("<Escape>")
root.update()
CK.ok("Esc 可关闭", not win.winfo_exists())

closed = {"n": 0}
win2 = about.open_about(root, "v1.10.0", "F1", None,
                        lambda: closed.__setitem__("n", closed["n"] + 1))
root.update()
CK.ok("无面板矩形时也能定位（不抛异常）", win2.winfo_width() > 100,
      win2.winfo_width())
win2.protocol("WM_DELETE_WINDOW")
try:
    win2.tk.call("wm", "protocol", str(win2), "WM_DELETE_WINDOW")
except Exception:
    pass
win2.destroy()
root.update()
CK.ok("destroy 后回调未被误触（由 WM_DELETE_WINDOW 显式调用）",
      closed["n"] == 0, closed["n"])

# ================= 设置窗口入口 =================
def lines_of(path):
    import io
    return io.open(path, encoding="utf-8").read()


class Stub(object):
    def apply_hotkey(self, spec):
        pass

    def delay_changed(self, s):
        pass

    def closed(self):
        pass


spec = {"ctrl": True, "alt": True, "shift": False, "win": False, "key": "D"}
dlg = S.SettingsDialog(root, (100, 100, 470), spec, "Ctrl+Alt+D", 0.05,
                       Stub())
root.update()
CK.ok("不传 about 时没有「许可与来源」入口",
      "许可与来源" not in " ".join(texts(dlg.window)))
dlg.close()
root.update()

hit = {"n": 0}
dlg2 = S.SettingsDialog(root, (100, 100, 470), spec, "Ctrl+Alt+D", 0.05,
                        Stub(), about=lambda: hit.__setitem__("n", 1))
root.update()
CK.ok("传了 about 就有入口",
      "许可与来源" in " ".join(texts(dlg2.window)))
dlg2.close()
root.update()

# ================= 静态核查：唯一入口 =================
panel_src = lines_of(os.path.join(ROOT, "panel.py"))
CK.ok("panel.py 不再使用 messagebox", "messagebox" not in panel_src)
CK.ok("panel.py 的 about 动作走 about 模块",
      'about.open_about' in panel_src)

CK.report()
root.destroy()
