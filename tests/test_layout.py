# -*- coding: utf-8 -*-
"""界面布局：排布靠"实测 + 填充"，不靠写死的像素。

这一层专门盯三件容易回归的事：
  1. 任何尺寸下都没有图元越出画布（文案折行、长标题、浮层打开都算）；
  2. 版式是"抢剩余空间"而不是"各占固定宽度"——状态栏提示语必须让位于
     右侧状态文字，引导文案在内容区居中；
  3. 设置窗口宽度一变，折行宽度与滑块长度一起跟着变（旧版这两处写死
     wraplength=380 / length=210，窗口缩放后就对不齐）。

不需要真窗口、不碰系统状态，所以在任何环境里都能跑。
"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import render                                   # noqa: E402
import theme as T                               # noqa: E402
from settings import SettingsDialog             # noqa: E402

CK = H.Checker("界面布局")

root = tk.Tk()
root.withdraw()

SIZES = ((380, 240), (380, 420), (470, 660), (900, 500), (1340, 665))
MSG = "把窗口拖到标题栏的「✥」上即可嵌入"
LONG_TITLE = "很长的窗口标题示例：一个足以压到按钮集群的标题"


def view(w, h, title=None, popup=None):
    return render.View(w=w, h=h, opacity=0.9, locked=False, shown=True,
                       msg=MSG, msg_is_err=False, hotkey_label="Ctrl+Alt+D",
                       tab=(title, True) if title else None, popup=popup)


def draw(w, h, title=None, popup=None):
    cv = tk.Canvas(root, width=w, height=h)
    hits = render.draw(cv, view(w, h, title, popup))
    return cv, hits


def status_texts(cv):
    """状态栏里的 (左, 右) 两段文字。"""
    items = [i for i in cv.find_all()
             if cv.type(i) == "text" and render.STATUS_TAG in cv.gettags(i)]
    left = [i for i in items if cv.itemcget(i, "anchor") == "w"]
    right = [i for i in items if cv.itemcget(i, "anchor") == "e"]
    return left, right


# ================= 1. 不越界 =================
print("=== 1. 任何尺寸都不越出画布 ===")
bad = []
for w, h in SIZES:
    for popup in (None, "opacity"):
        for title in (None, LONG_TITLE):
            cv, _hits = draw(w, h, title, popup)
            for item in cv.find_all():
                box = cv.bbox(item)
                if box and (box[0] < -2 or box[1] < -2
                            or box[2] > w + 2 or box[3] > h + 2):
                    bad.append((w, h, popup, title, cv.type(item), box))
            cv.destroy()
CK.ok("%d 个尺寸 × 浮层开关 × 有无窗口，均无图元越界" % len(SIZES),
      not bad, bad[:3])


# ================= 2. 状态栏：提示语让位于状态文字 =================
print("\n=== 2. 状态栏两段文字互不侵占 ===")
for w, h in SIZES:
    cv, _hits = draw(w, h)
    left, right = status_texts(cv)
    ok = bool(left) and bool(right)
    if ok:
        lb, rb = cv.bbox(left[0]), cv.bbox(right[0])
        ok = lb[2] <= rb[0] - T.GAP_TEXT + 1 and lb[0] >= T.PAD_X - 1
    CK.ok("w=%d：长提示语在状态文字左侧收住" % w, ok,
          (cv.bbox(left[0]), cv.bbox(right[0])) if left and right else "缺文字")
    cv.destroy()


# ================= 3. 标签栏已随单窗口容器删除 =================
print("\n=== 3. 标签栏已删除：单窗口下不再有 tab 命中区 ===")
for w, h in SIZES:
    cv, hits = draw(w, h, LONG_TITLE)
    tabs = [hit for hit in hits if hit.kind == "tab"]
    CK.ok("w=%d：长标题也不产生 tab 命中" % w, tabs == [], tabs)
    cv.destroy()


# ================= 4. 空面板引导文案：按内容区居中 =================
print("\n=== 4. 空面板文案按实测尺寸居中 ===")
for w, h in ((470, 660), (900, 500)):
    cv, _hits = draw(w, h)
    cx, cy, cw, ch = T.content_rect(w, h)
    boxes = [cv.bbox(i) for i in cv.find_all()
             if cv.type(i) == "text"
             and render.STATUS_TAG not in cv.gettags(i)
             and cv.bbox(i) and cv.bbox(i)[1] >= T.H_TITLE]
    centers = [(b[0] + b[2]) / 2.0 for b in boxes]
    top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
    CK.ok("%dx%d：各行对齐内容区中线" % (w, h),
          max(centers) - min(centers) <= 1.5, (min(centers), max(centers)))
    CK.ok("%dx%d：整块垂直居中（±2px）" % (w, h),
          abs((top + bottom) / 2.0 - (cy + ch / 2.0)) <= 2,
          ((top, bottom), (cy, cy + ch)))
    cv.destroy()


# ================= 5. 设置窗口：填满而非写死 =================
print("\n=== 5. 设置窗口跟随宽度 ===")


class HooksStub(object):
    def apply_hotkey(self, spec):
        pass

    def delay_changed(self, seconds):
        pass

    def closed(self):
        pass


spec = {"ctrl": True, "alt": True, "shift": False, "win": False, "key": "D"}
dlg = SettingsDialog(root, (100, 100, 470), spec, "Ctrl+Alt+D", 0.05,
                     HooksStub())
root.update()
d = dlg.window
PAD = 14                                     # 与 settings.PAD 一致
wrap0 = int(dlg._hints[0].cget("wraplength"))
CK.ok("设置窗口可缩放（不再锁死尺寸）", tuple(d.resizable()) == (1, 1),
      d.resizable())
CK.ok("说明文字折行宽度 = 窗宽 - 两侧留白",
      abs(wrap0 - (d.winfo_width() - 2 * PAD)) <= 2,
      (d.winfo_width(), wrap0))
CK.ok("最小尺寸等于自然尺寸（拖不小、也裁不掉字）",
      tuple(d.minsize()) == (d.winfo_reqwidth(), d.winfo_reqheight()),
      (d.minsize(), d.winfo_reqwidth(), d.winfo_reqheight()))

scale = dlg._delay_txt.master.grid_slaves(row=0, column=0)[0]
sw0 = scale.winfo_width()
d.geometry("1000x%d" % d.winfo_height())
root.update()
CK.ok("窗口拉宽后滑块跟着变宽（长度不是写死的）",
      scale.winfo_width() > sw0 + 100, (sw0, scale.winfo_width()))
CK.ok("窗口拉宽后说明文字按新宽度折行",
      int(dlg._hints[0].cget("wraplength")) > wrap0 + 100,
      (wrap0, dlg._hints[0].cget("wraplength")))
dlg.close()
CK.ok("关闭后窗口句柄已释放", dlg.is_open is False)

root.destroy()
sys.exit(CK.report())
