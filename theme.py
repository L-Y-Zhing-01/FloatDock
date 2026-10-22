# -*- coding: utf-8 -*-
"""外观与布局：配色、字体、尺寸度量、以及共用的小块几何计算。

界面要改样子，改这一个文件即可；绘制细节见 render.py。
"""

# ================= 配色 =================
C_BG = "#14181f"        # 面板底
C_BAR = "#1b2230"       # 标题栏
C_BAR2 = "#171d28"      # 工具/状态栏
C_LINE = "#2a3342"      # 分割线/边框
C_FG = "#dfe6f2"        # 主文字
C_DIM = "#8a95a8"       # 次文字
C_ACC = "#4da3ff"       # 主题蓝
C_DANGER = "#ff6b6b"    # 警示
C_ON_ACC = "#0d1117"    # 铺在主题蓝上的字形/文字
C_GRIP = "#39445a"      # 手柄/刻度
C_TIP = "#ffb454"       # 赞赏：暖橙，与图标的烛光同色系
# 悬停提示：底比面板更黑一档、边框比 C_LINE 亮一档。提示条会跨在面板边缘
# 上（按钮在标题栏，条子在标题栏下方），底太接近 C_BAR 就成了"贴在面板上
# 的一道横杠"，看不出它是个独立的气泡。
C_HINT_BG = "#0b0e14"
C_HINT_LINE = "#3d4a61"

FONT = "Microsoft YaHei UI"

# ================= 尺寸 =================
# 面板只剩标题栏 36 与状态栏 24 两行 chrome。原先那条 42px 的工具栏
# （吸附 / 释放 / 透明度滑块）已整体并入标题栏，内容区因此永久多出 42px，
# 且不随鼠标悬停反复改变高度 —— 内容区高度就是 MoveWindow 的参数，
# 一变就让被嵌入的程序收一次 WM_SIZE，抖动是治不掉的。
# 标签栏（多窗口时代的那一行）随 v1.8.3「容器只放一个窗口」一起删除：
# 只有一个窗口就没有"切换"，那一行永远不会出现，留着只是死代码。
H_TITLE, H_STATUS = 36, 24
MARGIN = 6                  # 内容区四边留白
GAP = 2                     # 内容区与上下 chrome 之间的细缝
PAD_X = 10                  # 标题栏/状态栏的左右留白
GAP_TEXT = 8                # 同一行里两段文字之间的间距
MIN_W, MIN_H = 380, 240     # 下限的由来见文件末尾
OP_MIN, OP_MAX = 0.35, 1.0  # 面板透明度可调范围
EDGE = 5                    # 边缘缩放的感应宽度
CORNER = 11                 # 角部缩放的感应宽度（角比边更好抓）

# 标题栏按钮：28 宽、右端留 6、相邻间隔 4。增删或换序只改这一张表 ——
# 绘制、命中区、标题拖拽区、浮层避让全部由它算出来，不会再出现
# "改了绘制忘了改命中"或"某个 w-142 的魔法数字忘了同步"。
BTN_W, BTN_RIGHT, BTN_GAP = 28, 6, 4
BTN_STEP = BTN_W + BTN_GAP
BTN_VPAD, BTN_HIT_VPAD = 6, 4   # 按钮底色的上下内缩 / 命中区的上下内缩
TITLE_BUTTONS = (                       # 右 -> 左
    ("close", "×"), ("min", "—"), ("lock", "🔒"), ("set", "⚙"),
    ("opacity", "◐"), ("release", "⤴"), ("grab", "✥"))

# 赞赏按钮：贴在标题文字（有副标题时是副标题）后面，与右侧集群分开一段。
# 它不操作窗口 —— 混进右边那一排，会被当成"又一个功能键"，而这一排里
# 每个字形都对应一个窗口动作。宽度比 BTN_W 窄一点：它只是被点到为止的
# 入口，不需要和"关闭/最小化"一样大的靶心。
TIP_GLYPH, TIP_W, TIP_GAP = "♥", 26, 6

# 空面板引导文案：行高与段间距。整块高度由实测 bbox 累加，不再"行数 × 常数"。
HINT_LEAD, HINT_GAP = 8, 8

# 透明度浮层（点 ◐ 才出现）：只画在标题栏内。内容区被 SetParent 进来的
# 原生子窗口占着，画布浮层在那里会被整块盖住，所以它不能跨出标题栏。
POPUP_W_MAX, POPUP_H, POPUP_GAP = 176, 30, 4
POPUP_PAD, POPUP_PCT_W = 10, 40

# 缩放方向 -> 光标形状
CURSORS = {"l": "size_we", "r": "size_we", "t": "size_ns", "b": "size_ns",
           "tl": "size_nw_se", "br": "size_nw_se",
           "tr": "size_ne_sw", "bl": "size_ne_sw"}


# ================= 几何计算 =================
def title_buttons(w):
    """标题栏按钮的 (名字, 字形, bx) 元组，右 -> 左。绘制与测试共用这一份。"""
    return tuple((name, glyph, w - BTN_RIGHT - BTN_W - i * BTN_STEP)
                 for i, (name, glyph) in enumerate(TITLE_BUTTONS))


def cluster_left(w):
    """按钮集群最左边界；标题栏可拖拽区到此为止。"""
    return w - BTN_RIGHT - BTN_W - (len(TITLE_BUTTONS) - 1) * BTN_STEP


def title_hit(w):
    """标题栏拖拽/双击命中区，右边界给按钮集群留 4px。"""
    return (0, 0, cluster_left(w) - 4, H_TITLE)


def tip_rect(x):
    """赞赏按钮的 (x1, y1, x2, y2)：x 是它左边界（标题块末尾 + TIP_GAP）。

    竖向与右侧按钮对齐（同一套 BTN_VPAD），一行看起来才是一条线。
    """
    return (x, BTN_VPAD, x + TIP_W, H_TITLE - BTN_VPAD)


def tip_hit(x):
    """赞赏按钮命中区：比底色高一点，和右侧按钮用同一个 BTN_HIT_VPAD。"""
    x1, _y1, x2, _y2 = tip_rect(x)
    return (x1, BTN_HIT_VPAD, x2, H_TITLE - BTN_HIT_VPAD)


def content_rect(w, h):
    """嵌入窗口在面板客户区里占用的矩形 (x, y, w, h)。

    面板无边框，客户区原点与窗口原点重合，因此这里同时就是 MoveWindow
    需要的父窗口坐标。

    三个边界都是"从 chrome 反推"而不是写死高度：上边贴住标题栏，下边让出
    状态栏与留白，左右留 MARGIN。于是面板怎么缩放，内容区就怎么填满中间
    那一段 —— 这里不再出现"-24-6-2"这类凑出来的差值。
    """
    y = H_TITLE + GAP
    return (MARGIN, y, w - MARGIN * 2, h - H_STATUS - y - MARGIN)


def popup_rect(w):
    """透明度浮层的 (x1, y1, x2, y2)：永远在标题栏内、按钮集群左侧。

    右边界由按钮集群决定，左边界由画布决定；窄面板时自动收窄而不是越界。
    它只可能临时盖住 logo 与标题文字，不会盖住任何按钮。
    """
    x2 = cluster_left(w) - POPUP_GAP
    x1 = max(4, x2 - POPUP_W_MAX)
    y1 = (H_TITLE - POPUP_H) // 2
    return x1, y1, x2, y1 + POPUP_H


def slider_geo(w):
    """浮层内滑块的 (x1, y, x2, y)，绝对画布坐标。"""
    px1, _py1, px2, _py2 = popup_rect(w)
    return px1 + POPUP_PAD, H_TITLE // 2, px2 - POPUP_PCT_W, H_TITLE // 2


def resize_zone(w, h, x, y):
    """鼠标在面板内的位置属于哪个缩放方向；不在边缘时返回 None。"""
    cl, cr = x <= CORNER, x >= w - CORNER
    ct, cb = y <= CORNER, y >= h - CORNER
    if ct and cl:
        return "tl"
    if ct and cr:
        return "tr"
    if cb and cl:
        return "bl"
    if cb and cr:
        return "br"
    if x <= EDGE:
        return "l"
    if x >= w - EDGE:
        return "r"
    if y <= EDGE:
        return "t"
    if y >= h - EDGE:
        return "b"
    return None


def resized_rect(from_rect, delta, zone):
    """按起始几何 + 鼠标位移算出新的 (x, y, w, h)。

    触到最小尺寸时反向修正位置，保证拖动左/上边时"边跟手"而不是整块跳。
    """
    x0, y0, w0, h0 = from_rect
    dx, dy = delta
    zone = zone or ""
    nx, ny, nw, nh = x0, y0, w0, h0
    if "l" in zone:
        nw, nx = w0 - dx, x0 + dx
    if "r" in zone:
        nw = w0 + dx
    if "t" in zone:
        nh, ny = h0 - dy, y0 + dy
    if "b" in zone:
        nh = h0 + dy
    if nw < MIN_W:
        if "l" in zone:
            nx = x0 + w0 - MIN_W
        nw = MIN_W
    if nh < MIN_H:
        if "t" in zone:
            ny = y0 + h0 - MIN_H
        nh = MIN_H
    return nx, ny, nw, nh


def rrect(cv, x1, y1, x2, y2, r=5, **kw):
    """圆角矩形（用 polygon 的平滑模式近似）。"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# ================= 最小尺寸的由来 =================
# MIN_W = 380 是三条约束的交点，再小就必须做取舍：
#   - 标题栏：按钮集群 226 + 副标题右端 129 + 两侧留白 ≈ 371；
#   - 浮层：集群 226 + 间隙 4 + 浮层最小可用宽 148 + 左边界 4 ≈ 382
#     （380 时浮层 146 宽、滑块 96px，已是可以拖动的下限）；
#   - 想更宽松应该上调到 400（浮层 166 / 滑块 116），而不是下调。
# MIN_H = 240 的约束不是 chrome，而是空面板的引导文案：380 宽下按实际像素
# 折行后实测 179px，内容区 172px —— 差的 7px 由状态栏压住（文案是顶格排的，
# 不会把标题栏顶掉）。这一条比按"九行 × 固定行高"估算的旧版更宽松：
# 旧版按估算要 196px，实际同样溢出。

