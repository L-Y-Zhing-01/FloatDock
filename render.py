# -*- coding: utf-8 -*-
"""面板绘制：把一帧状态画成 chrome，并返回可点击区域。

刻意与 FloatDock 解耦 —— 只吃一个只读的 View，产出 (类型, 矩形, 载荷) 列表。
于是改界面不必碰状态机，改状态机也不必碰画法；命中区由绘制顺带产出，
不会出现"画了但点不到"的错位。
"""
from collections import namedtuple

import appicon
import theme as T

# 一帧绘制需要的全部状态（只读）
# tab 是"当前嵌入的窗口"：(标题, 是否还有效)，没有窗口时为 None。
# tab 与 popup 给默认值：绘制层之外（如测试）构造 View 时不必逐个关心。
View = namedtuple("View", (
    "w h opacity locked shown msg msg_is_err hotkey_label tab popup"),
    defaults=(None, None))

# 一个可点击区域：kind 决定怎么响应，payload 是给响应方的参数
Hit = namedtuple("Hit", "kind rect payload")

STATUS_TAG = "status"       # 状态栏图元的画布标签，供局部重画


def draw(cv, view):
    """重画面板，返回命中区列表（列表顺序即命中优先级）。"""
    cv.delete("all")
    hits = []
    _background(cv, view)
    _titlebar(cv, view, hits)
    if view.tab is None:
        _empty_hint(cv, view)
    # 状态栏最后画：引导文案在窄面板里会折行变高，让状态栏压住它的下沿，
    # 而不是被它盖住。
    _status(cv, view)
    _corners(cv, view)
    if view.popup == "opacity":
        # 最后画：要压住标题文字，也压住左上角的收角线
        _popup(cv, view, hits)
    return hits


def draw_status(cv, view):
    """只重画状态栏。

    状态文案变得很频繁（拾取目标跟踪时每 30ms 一次），整帧重画会闪，
    所以状态栏的图元单独打 "status" 标签、单独擦除。
    """
    cv.delete(STATUS_TAG)
    _status(cv, view)


# ================= 背景 =================
def _background(cv, view):
    cv.create_rectangle(0, 0, view.w, view.h, fill=T.C_BG, outline=T.C_LINE)


def _titlebar(cv, view, hits):
    w, mid = view.w, T.H_TITLE // 2
    cv.create_rectangle(0, 0, w, T.H_TITLE, fill=T.C_BAR, outline=T.C_LINE)
    # 主标识：直接贴图标文件里的 32px 位图（与托盘/任务栏/设置窗同一来源、
    # 同一像素，这才是"统一"）；取不到位图时退回 GLYPH 字形，绝不开天窗。
    # 主文字与副标题都取自 appicon（全程序唯一来源）；副标题按主文字的实际
    # 像素宽度排，于是换图标或改产品名都不会和副标题压在一起。
    x = T.PAD_X
    img = appicon.photo(cv)
    if img is not None:
        cv.create_image(x, mid, image=img, anchor="w")
        x += img.width() + T.GAP_TEXT
    main = cv.create_text(x, mid, anchor="w",
                          text=(appicon.APP_NAME if img is not None
                                else appicon.title_text()),
                          fill=T.C_FG, font=(T.FONT, -12, "bold"))
    box = cv.bbox(main)
    main_right = box[2] if box else x
    sub = cv.create_text(main_right + T.GAP_TEXT, mid, anchor="w",
                         text=appicon.SUBTITLE, fill=T.C_DIM,
                         font=(T.FONT, -10))
    sbox = cv.bbox(sub)
    # 副标题只是装饰，赞赏按钮才是入口：先按"按钮一定放得下"算出上限，
    # 副标题超出就整块撤掉。顺序不能反 —— 先画副标题、再被按钮挤出去，
    # 就会在两者之间反复（窄面板下副标题忽隐忽现）。
    limit = T.cluster_left(w) - T.PAD_X - T.TIP_W - T.TIP_GAP
    if sbox is None or sbox[2] > limit:
        cv.delete(sub)
        sbox = None
    tail = sbox[2] if sbox else main_right
    _tip_button(cv, hits, tail + T.TIP_GAP)
    # 命中区顺序 = 优先级：标题拖拽区盖住整条空白，赞赏按钮必须先入表，
    # 否则点在 ♥ 上会被判成"拖窗"。
    hits.append(Hit("title", T.title_hit(w), None))

    for name, glyph, bx in T.title_buttons(w):
        _title_button(cv, view, hits, name, glyph, bx)


def _tip_button(cv, hits, bx):
    """标题后面的赞赏按钮：只展示赞赏码，不操作窗口。

    与右侧集群用不同颜色区分开 —— 那一排每个字形都对应一个窗口动作，
    这一颗不对应。没有底色：它不该比 ✥ 更显眼。
    """
    x1, _y1, x2, _y2 = T.tip_rect(bx)
    cv.create_text((x1 + x2) // 2, T.H_TITLE // 2, text=T.TIP_GLYPH,
                   fill=T.C_TIP, font=(T.FONT, -14, "bold"))
    hits.append(Hit("btn", T.tip_hit(bx), "tip"))


def _title_button(cv, view, hits, name, glyph, bx):
    """标题栏里的一个按钮。✥ 是主操作，保留实心蓝底以便一眼找到。"""
    enabled = name != "release" or view.tab is not None
    if name == "close":
        color = T.C_DANGER
    elif name == "grab":
        color = T.C_ON_ACC               # 蓝底上的深色字形
    elif name == "lock" and view.locked:
        color = T.C_ACC
    elif name == "opacity" and view.popup:
        color = T.C_ACC                 # 浮层开着时高亮 ◐
    else:
        color = T.C_DIM
    cv.create_rectangle(bx, T.BTN_VPAD, bx + T.BTN_W,
                        T.H_TITLE - T.BTN_VPAD,
                        fill=T.C_ACC if name == "grab" else T.C_BAR,
                        outline="")
    cv.create_text(bx + T.BTN_W // 2, T.H_TITLE // 2, text=glyph, fill=color,
                   font=(T.FONT, -12, "bold"))
    if enabled:
        hits.append(Hit("btn", (bx, T.BTN_HIT_VPAD, bx + T.BTN_W,
                                T.H_TITLE - T.BTN_HIT_VPAD), name))


def _popup(cv, view, hits):
    """透明度浮层：画在标题栏内、按钮集群左侧。

    命中区插到列表最前 —— 浮层压在标题的拖拽区之上，点的应该是滑块而不是
    拖窗。插入顺序必须是 slider 在前、popup 在后；反过来浮层底会先吃掉点击，
    滑块就再也拖不动了。
    """
    x1, y1, x2, y2 = T.popup_rect(view.w)
    T.rrect(cv, x1, y1, x2, y2, r=6, fill=T.C_BAR2, outline=T.C_LINE)

    sx1, sy, sx2, _ = T.slider_geo(view.w)
    ratio = (view.opacity - T.OP_MIN) / (T.OP_MAX - T.OP_MIN)
    knob = sx1 + ratio * (sx2 - sx1)
    cv.create_line(sx1, sy, sx2, sy, fill=T.C_GRIP, width=3)
    cv.create_line(sx1, sy, knob, sy, fill=T.C_ACC, width=3)
    cv.create_oval(knob - 6, sy - 6, knob + 6, sy + 6, fill=T.C_FG, outline="")
    cv.create_text(x2 - T.POPUP_PCT_W + 6, sy,
                   text="%d%%" % round(view.opacity * 100),
                   fill=T.C_FG, font=(T.FONT, -10), anchor="w")
    hits[0:0] = [Hit("slider", (sx1 - 8, sy - 13, sx2 + 8, sy + 13), None),
                 Hit("popup", (x1, y1, x2, y2), None)]


def _status(cv, view):
    """状态栏：右侧状态文字定宽，左侧提示语吃掉剩下的全部宽度。"""
    y0 = view.h - T.H_STATUS
    mid = y0 + T.H_STATUS // 2
    cv.create_rectangle(0, y0, view.w, view.h, fill=T.C_BAR2, outline="",
                        tags=STATUS_TAG)
    cv.create_line(0, y0, view.w, y0, fill=T.C_LINE, tags=STATUS_TAG)
    if view.locked:
        state = "已锁定（不自动隐藏）"
    elif view.shown:
        state = "已显示"
    else:
        state = "已隐藏（按 %s 唤出）" % view.hotkey_label
    right = cv.create_text(view.w - T.PAD_X, mid, anchor="e", text=state,
                           fill=T.C_ACC if view.shown else T.C_DIM,
                           font=(T.FONT, -10), tags=STATUS_TAG)
    left_w = view.w - 2 * T.PAD_X
    box = cv.bbox(right)
    if box:
        left_w = box[0] - T.GAP_TEXT - T.PAD_X     # 让出状态文字占的那一段
    cv.create_text(T.PAD_X, mid, anchor="w", text=view.msg,
                   fill=T.C_DANGER if view.msg_is_err else T.C_DIM,
                   font=(T.FONT, -10), width=max(40, left_w), tags=STATUS_TAG)


def _empty_hint(cv, view):
    """没吸附任何窗口时的引导文案：先按内容区宽度折行，再整块垂直居中。

    每一段的高度由 bbox 实测累加，不按"行数 × 固定行高"估算 —— 面板变窄时
    文案会折行，估算出来的居中必然偏（这正是旧版窄面板下文案压到状态栏的
    原因）。折行宽度取内容区宽度，于是文案永远填满可用空间、不写死。
    """
    cx, cy, cw, ch = T.content_rect(view.w, view.h)
    center_x = cx + cw // 2
    max_w = max(120, cw - 2 * T.PAD_X)
    lines = [
        ("还没有嵌入任何窗口", T.C_FG, -13, "bold"),
        ("", None, 0, ""),
        ("① 按住标题栏的「✥」，拖到任意程序窗口上松开", T.C_DIM, -11, ""),
        ("② 该窗口会被收进浮坞，功能照常使用", T.C_DIM, -11, ""),
        ("③ 点标题栏的「⤴」原样还原到桌面", T.C_DIM, -11, ""),
        ("", None, 0, ""),
        ("鼠标移开自动隐藏 · 双击标题栏隐藏 · 按快捷键或点托盘唤出",
         T.C_DIM, -10, ""),
        ("托盘图标右键出菜单；%s 随时切换" % view.hotkey_label, T.C_DIM, -10, ""),
        ("「◐」调透明度，四边四角都能拖动改变大小", T.C_DIM, -10, ""),
    ]
    items, y = [], cy
    for text, color, size, weight in lines:
        if not text:
            y += T.HINT_GAP          # 空串 = 一段留白
            continue
        item = cv.create_text(center_x, y, text=text, fill=color,
                              width=max_w, anchor="n",
                              font=(T.FONT, size, weight) if weight
                              else (T.FONT, size))
        box = cv.bbox(item)
        if box is None:
            continue
        items.append(item)
        y = box[3] + T.HINT_LEAD
    if items:
        block = y - T.HINT_LEAD - cy
        dy = max(0, (ch - block) // 2)     # 装不下就顶格排，溢出部分交给状态栏压住
        if dy:
            for item in items:
                cv.move(item, 0, dy)


def _corners(cv, view):
    """四角收角线：提示四边/四角都能拖拽缩放。"""
    w, h = view.w, view.h
    for cx, cy, sx, sy in ((0, 0, 1, 1), (w, 0, -1, 1),
                           (0, h, 1, -1), (w, h, -1, -1)):
        for k in range(3):
            o = 3 + k * 4
            cv.create_line(cx + sx * o, cy + sy * (o + 5),
                           cx + sx * (o + 5), cy + sy * o,
                           fill=T.C_GRIP, width=1)
