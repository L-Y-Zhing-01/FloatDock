# -*- coding: utf-8 -*-
"""赞赏：标题后 ♥ 的几何与命中优先级、图片加载与整数倍缩放、窗口开关。

全部在本进程的 Tk 里跑完 —— 不吸附真实窗口、不弹模态，因此可以随时单跑：

    python tests/test_tip.py

两条判据值得单独说：
  · ♥ 的命中必须排在标题拖拽区**前面**。它俩在同一个矩形里，顺序反了
    就是"点心形开始拖窗"，这种现象在自动测试之外很难被发现。
  · 缩放只允许整数倍，且基准是原图的 25%（`tip.SCALE`）。二维码一旦被
    插值，模块边界糊掉就扫不出来，所以这里断言的是"用 subsample + 倍数
    正确"，而不是"尺寸大致合适"。
"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import render                                   # noqa: E402
import theme as T                               # noqa: E402
import tip                                      # noqa: E402

CK = H.Checker("赞赏")

SIZES = (T.MIN_W, 420, 470, 560, 760)


def view(w, h):
    return render.View(w=w, h=h, opacity=1.0, locked=False, shown=True,
                       msg="", msg_is_err=False, hotkey_label="Ctrl+Alt+D",
                       tab=None, popup=None)


def widgets(w, kind):
    """递归收集某种控件（按钮埋在 Frame 里）。"""
    out = []
    for child in w.winfo_children():
        if isinstance(child, kind):
            out.append(child)
        out.extend(widgets(child, kind))
    return out


root = tk.Tk()
root.geometry("470x660+120+80")
root.update_idletasks()
root.update()

# ================= 1. 几何：给定左边界就得出标题栏内的一条命中区 =================
print("=== 1. ♥ 的形状 ===")
x1, y1, x2, y2 = T.tip_hit(100)
CK.ok("命中区从给定左边界起步、宽度 TIP_W", x1 == 100 and x2 == 100 + T.TIP_W,
      (x1, x2, T.TIP_W))
CK.ok("竖直在标题栏内", 0 <= y1 < y2 <= T.H_TITLE, (y1, y2, T.H_TITLE))
CK.ok("与右侧按钮竖向同高（同一条线）",
      (y1, y2) == (T.BTN_HIT_VPAD, T.H_TITLE - T.BTN_HIT_VPAD)
      and T.tip_rect(100)[1] == T.BTN_VPAD, (y1, y2))

# ================= 2. 绘制产出的命中区：♥ 优先于标题拖拽 =================
print("\n=== 2. 命中区与优先级 ===")
cv = tk.Canvas(root, width=470, height=660, bg=T.C_BG, highlightthickness=0)
cv.pack()
for w in SIZES:
    cv.configure(width=w)
    cv.update_idletasks()
    hits = render.draw(cv, view(w, 660))
    tips = [h for h in hits if h.kind == "btn" and h.payload == "tip"]
    titles = [h for h in hits if h.kind == "title"]
    CK.ok("w=%d：画出 ♥ 且只有一个" % w, len(tips) == 1, tips)
    CK.ok("w=%d：♥ 在标题栏内、不压右侧按钮集群" % w,
          tips[0].rect[0] >= 0 and tips[0].rect[2] <= T.cluster_left(w)
          and 0 <= tips[0].rect[1] < tips[0].rect[3] <= T.H_TITLE,
          (tips[0].rect, T.cluster_left(w)))
    CK.ok("w=%d：♥ 排在标题拖拽区之前" % w,
          bool(tips and titles) and hits.index(tips[0]) < hits.index(titles[0]),
          [h.kind for h in hits][:3])
    x1, y1, x2, y2 = tips[0].rect
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    got = next(h for h in hits if h.rect[0] <= cx <= h.rect[2]
               and h.rect[1] <= cy <= h.rect[3])
    CK.ok("w=%d：点心形中心命中 ♥（不是拖窗）" % w, got.payload == "tip", got)

# ================= 3. 窄面板：副标题让位，♥ 不能被挤掉 =================
print("\n=== 3. 窄面板下 ♥ 仍在标题文字后面 ===")
cv.configure(width=T.MIN_W)
cv.update_idletasks()
hits = render.draw(cv, view(T.MIN_W, 660))
tips = [h for h in hits if h.kind == "btn" and h.payload == "tip"]
CK.ok("最小宽度下 ♥ 仍在", len(tips) == 1, tips)
CK.ok("最小宽度下 ♥ 紧跟在主标题之后（副标题已撤掉）",
      tips[0].rect[0] < T.cluster_left(T.MIN_W) - 40, tips[0].rect)

# ================= 4. 固定 25%：只取整数倍，屏幕再小才继续缩 =================
print("\n=== 4. 显示比例为原图的 25%（1:4） ===")
CK.ok("1080 屏缩 4 倍（25%）", tip.fit_factor(658, 1080) == 4,
      tip.fit_factor(658, 1080))
CK.ok("768 屏也是 4 倍", tip.fit_factor(658, 768) == 4, tip.fit_factor(658, 768))
CK.ok("2160 屏不会放大回 1:1", tip.fit_factor(658, 2160) == 4,
      tip.fit_factor(658, 2160))
CK.ok("658 缩 4 倍 = 165px（Tk 的 subsample 向上取整）",
      -(-658 // 4) == 165, -(-658 // 4))
CK.ok("屏幕小到放不下 25% 时才继续缩（200px 高 → 5 倍）",
      tip.fit_factor(658, 200) == 5, tip.fit_factor(658, 200))
for h in (600, 720, 768, 900, 1080, 1440, 2160):
    f = tip.fit_factor(658, h)
    avail = max(160, int(h * tip.SCREEN_RATIO) - tip.CHROME_H)
    CK.ok("屏幕高 %d：%d 倍（%dpx）放得下且没有多余缩小" % (h, f, 658 // f),
          f >= tip.SCALE and 658 // f <= avail
          and (f == tip.SCALE or 658 // (f - 1) > avail),
          (f, avail))

# ================= 5. 图片本身 =================
print("\n=== 5. donation.png 能加载 ===")
CK.ok("图片文件在程序目录", os.path.exists(tip.PATH), tip.PATH)
if os.path.exists(tip.PATH):
    with open(tip.PATH, "rb") as f:
        CK.ok("是 PNG", f.read(8) == b"\x89PNG\r\n\x1a\n")
    img = tip._load(root)
    CK.ok("Tk 能解码这张 PNG", img is not None)
    if img is not None:
        f = tip.fit_factor(658, root.winfo_screenheight())
        # Tk 的 subsample 每 f 个像素取一个，尺寸是 px/f 向上取整（658/4 → 165）
        want = -(-658 // f)
        CK.ok("解码后是 1:%d 的整数倍图（%d×%d）" % (f, want, want),
              img.width() == want and img.height() == want,
              (img.width(), img.height(), f))

# ================= 6. 窗口：开、关、回调 =================
print("\n=== 6. 窗口开关与关闭回调 ===")
state = {"closed": 0}


def on_close():
    state["closed"] += 1


win = tip.show(root, on_close)
root.update()
CK.ok("窗口已建出来", isinstance(win, tk.Toplevel) and win.winfo_exists())
CK.ok("窗口标题带「赞赏」", "赞赏" in win.title(), win.title())

imgs = [w for w in widgets(win, tk.Label) if w.cget("image")]
CK.ok("窗口里放了赞赏码图片", len(imgs) == 1, len(imgs))

btns = [b for b in widgets(win, tk.Button)]
CK.ok("窗里没有「关闭」按钮（唯一入口是标题栏 ×）", btns == [],
      [b.cget("text") for b in btns])

# 标题栏 × 在 Tk 里就是 WM_DELETE_WINDOW，取到那条命令再执行，等价于点 ×。
close_cmd = win.protocol("WM_DELETE_WINDOW")
CK.ok("绑定了 WM_DELETE_WINDOW（标题栏 × 可用）", bool(close_cmd), close_cmd)
CK.ok("没有额外的 Esc 关闭入口", win.bind("<Escape>") == "", win.bind("<Escape>"))
if close_cmd:
    win.tk.call(close_cmd)
    root.update()
CK.ok("点 × 后窗口销毁", not win.winfo_exists())
CK.ok("关闭回调只触发一次", state["closed"] == 1, state["closed"])

cv.destroy()
root.destroy()
sys.exit(CK.report())
