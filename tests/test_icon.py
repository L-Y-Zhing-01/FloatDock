# -*- coding: utf-8 -*-
"""图标统一性验证：全程序只认 appicon 那一个图标文件。

要证明的四件事：
  A 唯一来源   —— 产品代码里没有第二处图标路径或品牌字样
  B 文件本身   —— appicon.PATH 是合法多尺寸 ICO，32 层与最初设计逐像素一致
  C 真的挂上了 —— 面板窗口、设置窗口的图标就是文件里的那一层，而不是 Tk
                  默认羽毛、也不是"16 放大到 32"的糊图
  D 换一处全变 —— 把 appicon.PATH 指向另一个文件，图标立刻跟着变，
                  证明"以后换图标只改这一处"

托盘那一侧：通知区图标用的句柄由 appicon.load_hicon() 产生，本文件验证它的
像素等于文件里的小图标层，并用打桩确认托盘自己不碰图标（只问 appicon）。
托盘图标确实进了通知区、退出时确实删掉，由 test_shutdown.py 覆盖。
"""
import glob
import os
import struct
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import harness as H                               # noqa: E402
import winapi                                     # noqa: E402
import appicon                                    # noqa: E402
import tray                                       # noqa: E402
import wndutil                                    # noqa: E402

# 与子进程（沙箱实例）保持同一套系统度量：不启用 DPI 感知时 GetSystemMetrics
# 会被系统虚拟化，两边算出来的图标尺寸不同就没法比像素了。
winapi.enable_dpi_awareness()

CK = H.Checker("图标统一性")


def _png_of(size, rgb):
    """造一个纯色 PNG（供换图标用）。"""
    row = b"\x00" + bytes((rgb[0], rgb[1], rgb[2], 255)) * size
    raw = row * size

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def write_solid_ico(path, size=32, rgb=(220, 40, 40)):
    png = _png_of(size, rgb)
    ico = struct.pack("<HHH", 0, 1, 1)
    ico += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), 22)
    ico += png
    with open(path, "wb") as f:
        f.write(ico)
    return path


def read_ico(path):
    """解析 ICO：返回 [ (宽, 高, 字节数, 偏移, 内嵌数据) ]。"""
    with open(path, "rb") as f:
        b = f.read()
    reserved, kind, count = struct.unpack("<HHH", b[:6])
    assert reserved == 0 and kind == 1, "不是 ICO 文件"
    out, off = [], 6
    for _ in range(count):
        w, h, _c, _r, _p, bpp, size, pos = struct.unpack("<BBBBHHII",
                                                         b[off:off + 16])
        off += 16
        out.append((w or 256, h or 256, size, pos, b[pos:pos + size], bpp))
    return out


# ==================================================================
print("\n=== A. 图标只有一个来源 ===")
prod = []
for pat in ("*.py", "*.pyw", "tools/*.py"):
    prod += glob.glob(os.path.join(ROOT, pat))


def icon_path_literals(path):
    """这个文件里真正当作"路径"用的 .ico 字符串字面量。

    判据要精确，否则文档与提示语会误报：`make_archive.py` 的排除清单里解释
    ".ico 已收录"、`appicon.py` 的注释里说明图标路径 —— 那是给人看的说明，
    不是代码里的第二处路径声明。只有**看起来真在指路径**的才算（短、且不带
    中文标点与空格）。
    """
    return _string_literals(path, lambda s: ".ico" in s, short_only=True)


def brand_literals(path):
    """这个文件里真正当作"标识"用的品牌字面量（同样只看代码，不看注释）。

    与 `icon_path_literals` 同一个毛病：不精确就会把文档字符串里的
    「FloatDock.exe」这类**产物名/说明文字**当成"硬编码品牌"，而产物名
    是 PyInstaller 的 `--name`，恰恰应该跟着构建配置走、不该从 appicon 取。
    """
    tokens = ("浮坞 · 设置", "🕯 浮坞", "FloatDock", "浮坞 FloatDock")
    return _string_literals(
        path, lambda s: any(t in s for t in tokens), short_only=True)


def _string_literals(path, match, short_only=True):
    import ast
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant)
                and isinstance(node.value, str) and match(node.value)):
            continue
        s = node.value.strip()
        if not short_only:
            hits.append(s)
            continue
        # 超过 24 个字、或含空格/标点的，是说明文字不是标识
        if len(s) > 24 or any(c in s for c in "，。；：、 “”—-（(《"):
            continue
        hits.append(s)
    return hits


offenders = []
for path in prod:
    if os.path.basename(path) == "appicon.py":
        continue
    for lit in icon_path_literals(path):
        offenders.append((os.path.relpath(path, ROOT), lit))
CK.ok("产品代码里除 appicon.py 外没有第二处 .ico 路径",
      offenders == [], offenders)

brand = []
for path in prod:
    if os.path.basename(path) == "appicon.py":
        continue
    for lit in brand_literals(path):
        brand.append((os.path.relpath(path, ROOT), lit))
CK.ok("产品代码里没有硬编码的品牌字样（名称/字形/副标题都在 appicon）",
      brand == [], brand)
CK.ok("appicon 提供全部品牌标识",
      all(bool(getattr(appicon, n)) for n in
          ("APP_NAME", "SUBTITLE", "GLYPH", "APP_TITLE"))
      and appicon.title_text() == appicon.GLYPH + " " + appicon.APP_NAME
      and appicon.settings_title().endswith("设置"))


# ==================================================================
print("\n=== B. 图标文件本身 ===")
CK.ok("图标文件存在", os.path.exists(appicon.PATH), appicon.PATH)
entries = read_ico(appicon.PATH)
sizes = sorted(e[0] for e in entries)
CK.ok("是多尺寸 ICO（托盘/任务栏/大图标都有对应层）",
      sizes == [16, 32, 48, 256], sizes)
CK.ok("每层都是 32bpp 带 alpha 的 PNG-in-ICO",
      all(e[5] == 32 and e[4][:8] == b"\x89PNG\r\n\x1a\n" for e in entries),
      [(e[0], e[5]) for e in entries])

png32 = [e for e in entries if e[0] == 32][0][4]
CK.ok("32 层 PNG 头声明的尺寸是 32×32",
      struct.unpack(">II", png32[16:24]) == (32, 32),
      struct.unpack(">II", png32[16:24]))


# ==================================================================
print("\n=== A2. 自绘标题栏贴的就是文件里的那一层 ===")

def decode_png_rgba(png):
    """纯手写解码 32bpp RGBA 的 PNG（只为本测试服务，无第三方依赖）。

    返回 (宽, 高, 每行字节列表)。5 种过滤器都实现，产出的文件用哪种都能解。
    """
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG"
    pos, idat, w, h = 8, b"", 0, 0
    while pos + 8 <= len(png):
        ln, tag = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert (depth, ctype) == (8, 6), (depth, ctype)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * 4
    out, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(4, stride):
                line[i] = (line[i] + line[i - 4]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                b, c = prev[i], (prev[i - 4] if i >= 4 else 0)
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        out.append(bytes(line))
        prev = line
    return w, h, out

import tkinter as tk2                              # noqa: E402
import render                                      # noqa: E402

CK.ok("_png_layer(32) 取出的就是文件里的 32 层（逐字节相同）",
      appicon._png_layer(32) == png32)
iw, ih, rows = decode_png_rgba(png32)
CK.ok("32 层可离线解码为 32×32 RGBA", (iw, ih) == (32, 32), (iw, ih))

root2 = tk2.Tk()
root2.withdraw()
root2.update()
cv = tk2.Canvas(root2, width=470, height=620, bg="#000000")
cv.pack()
img = appicon.photo(cv)
CK.ok("photo() 返回 32×32 的 PhotoImage",
      img is not None and img.width() == 32 and img.height() == 32,
      (img.width(), img.height()) if img else None)
CK.ok("重复调用命中缓存（同一对象，不重复解码）", appicon.photo(cv) is img)

diff, tdiff = [], []
for (x, y) in ((0, 0), (1, 1), (5, 5), (16, 2), (16, 10), (16, 12), (16, 20),
               (10, 16), (22, 16), (16, 29), (31, 31), (30, 1)):
    alpha = rows[y][x * 4 + 3]
    if img.transparency_get(x, y) != (alpha == 0):
        tdiff.append((x, y, "alpha=%d" % alpha))
    if alpha:
        want = tuple(rows[y][x * 4:x * 4 + 3])
        got = tuple(img.get(x, y))
        if want != got:
            diff.append(((x, y), want, got))
CK.ok("抽样不透明像素与文件层逐点一致", diff == [], diff)
CK.ok("抽样透明像素（圆角）确实透明", tdiff == [], tdiff)

view = render.View(w=470, h=620, opacity=0.8, locked=True, shown=True,
                   msg="", msg_is_err=False, hotkey_label="F1",
                   tab=None, popup=None)
render.draw(cv, view)
imgs = [i for i in cv.find_all() if cv.type(i) == "image"]
CK.ok("标题栏上贴的是位图（整幅画面只有这一处 image 图元）",
      len(imgs) == 1, len(imgs))
glyph_left = [cv.itemcget(i, "text") for i in cv.find_all()
              if cv.type(i) == "text" and appicon.GLYPH in cv.itemcget(i, "text")]
CK.ok("画面上不再出现 emoji 字形", glyph_left == [], glyph_left)

# ---------- 命中区不变量：浮层开/关两个状态下都成立 ----------
hits_closed = render.draw(cv, view)
CK.ok("浮层关着时没有 slider/popup 命中",
      not [h for h in hits_closed if h.kind in ("slider", "popup")],
      [h.kind for h in hits_closed])

view_open = view._replace(popup="opacity")
hits_open = render.draw(cv, view_open)
sl = [h for h in hits_open if h.kind == "slider"]
pp = [h for h in hits_open if h.kind == "popup"]
title_i = [i for i, h in enumerate(hits_open) if h.kind == "title"][0]
CK.ok("浮层开着时有 slider/popup 命中且排在 title 之前",
      bool(sl) and bool(pp) and hits_open.index(pp[0]) < title_i
      and hits_open.index(sl[0]) < hits_open.index(pp[0]),
      [(h.kind, h.rect) for h in hits_open[:4]])
grab = [h for h in hits_open if h.kind == "btn" and h.payload == "grab"][0]
CK.ok("浮层不压住任何按钮", pp[0].rect[2] <= grab.rect[0],
      (pp[0].rect, grab.rect))
CK.ok("浮层开着时画面仍只有一处 image",
      len([i for i in cv.find_all() if cv.type(i) == "image"]) == 1, None)

# 无窗口时 ⤴ 不注册命中；有窗口时注册
CK.ok("无窗口时 ⤴ 不可点",
      not [h for h in hits_open if h.kind == "btn" and h.payload == "release"],
      None)
view_tab = view_open._replace(tab=("记事本", True))
hits_tab = render.draw(cv, view_tab)
rel = [h for h in hits_tab if h.kind == "btn" and h.payload == "release"]
CK.ok("有窗口时 ⤴ 可点且命中区与 ✥ 不重叠",
      len(rel) == 1 and rel[0].rect[0] >= grab.rect[2] + 2, rel)

real_layer = appicon._png_layer
appicon._png_layer = lambda *a, **k: None          # 模拟图标文件不可用
try:
    try:
        del cv._appicon_photo                      # 清缓存，逼它走取层路径
    except AttributeError:
        pass
    render.draw(cv, view)
finally:
    appicon._png_layer = real_layer
texts = [cv.itemcget(i, "text") for i in cv.find_all() if cv.type(i) == "text"]
CK.ok("取不到位图时退回 GLYPH 字形（不会开天窗）",
      any(appicon.GLYPH in t for t in texts),
      [t for t in texts if t][:3])
root2.destroy()


# ==================================================================
print("\n=== C. 挂到窗口上的是文件里的那一层 ===")
import tkinter as tk                               # noqa: E402

SM_CXICON, SM_CYICON = 11, 12
SM_CXSMICON, SM_CYSMICON = 49, 50
big_px = H.u32.GetSystemMetrics(SM_CXICON)
small_px = H.u32.GetSystemMetrics(SM_CXSMICON)

h = H.load_icon_from(appicon.PATH, big_px)
base_big = H.icon_pixels(h)
H.u32.DestroyIcon(h)
h = H.load_icon_from(appicon.PATH, small_px)
base_small = H.icon_pixels(h)
H.u32.DestroyIcon(h)
CK.ok("能从文件载入大图标（%dpx）作基准" % big_px, base_big is not None,
      base_big)
CK.ok("能从文件载入小图标（%dpx）作基准" % small_px, base_small is not None,
      base_small)

root = tk.Tk()
root.withdraw()
root.update()
default_icon = H.icon_fingerprint(wndutil.root_of(root.winfo_id()), True)
CK.ok("对照：未挂图标时是 Tk 默认图标（与我们的不同）",
      default_icon is not None and default_icon != base_big,
      "默认=%s" % (default_icon[2][:16] if default_icon else None))

win = tk.Toplevel(root)
win.geometry("+2400+1800")
win.update()
applied = appicon.apply(win)
win.update()
got = H.icon_fingerprint(wndutil.root_of(win.winfo_id()), True)
CK.ok("apply() 报告挂载成功", applied is True)
CK.ok("窗口图标 = 从文件载入的大图标（逐像素相同）", got == base_big,
      "窗口=%s 基准=%s" % (got[2][:16] if got else None,
                          base_big[2][:16] if base_big else None))
CK.ok("窗口图标不是 Tk 默认图标", got != default_icon)
CK.ok("已挂载的窗口类登记在案", appicon.mounted_classes() != [],
      appicon.mounted_classes())
first_big = appicon._mounted["TkTopLevel"]["big"]
for _ in range(3):
    appicon.apply(win)
CK.ok("反复 apply 复用同一对句柄（不会每次多漏一对）",
      len(appicon.mounted_classes()) == 1
      and appicon._mounted["TkTopLevel"]["big"] == first_big,
      appicon.mounted_classes())
CK.ok("反复 apply 后图标依然是我们的",
      H.icon_fingerprint(wndutil.root_of(win.winfo_id()), True) == base_big)
sibling = tk.Toplevel(root)
sibling.update()
CK.ok("同类的另一个新窗口自动继承图标（这就是不必逐个修改的原因）",
      H.icon_fingerprint(wndutil.root_of(sibling.winfo_id()), True)
      == base_big)


# ==================================================================
print("\n=== C2. 托盘只问 appicon，不自己碰图标 ===")
aux = tray.AuxThread(appicon.APP_TITLE, lambda: False)
asked = []
real_load = appicon.load_hicon
appicon.load_hicon = lambda *a, **k: (asked.append(1), real_load(*a, **k))[1]
try:
    # 走真实装配路径（托盘条目的图标就是这一步填进去的），
    # 顺便证明它没有第二条取图标的途径
    aux._add_tray()
finally:
    appicon.load_hicon = real_load
hicon = aux._nid.hIcon
CK.ok("托盘载图标走的是 appicon.load_hicon", len(asked) == 1, asked)
px = H.icon_pixels(hicon)
CK.ok("托盘拿到的就是文件里的小图标层", px == base_small,
      "托盘=%s 基准=%s" % (px[2][:16] if px else None,
                          base_small[2][:16] if base_small else None))
CK.ok("托盘图标归本程序所有（退出时需销毁）", aux._own_icon is True)


# ==================================================================
print("\n=== D. 换文件即换图标（改一处就够） ===")
tmp_ico = write_solid_ico(os.path.join(tempfile.gettempdir(), "fd_red.ico"),
                          size=big_px, rgb=(220, 40, 40))
real_path = appicon.PATH
red_base = None
try:
    h = H.load_icon_from(tmp_ico, big_px)
    red_base = H.icon_pixels(h)
    H.u32.DestroyIcon(h)
    CK.ok("临时图标（纯红）可载入且与正式图标不同", red_base != base_big)

    CK.ok("release() 能还原窗口类图标", appicon.release() is None
          and appicon.mounted_classes() == [])
    win.update()
    CK.ok("还原后窗口回到 Tk 默认图标",
          H.icon_fingerprint(wndutil.root_of(win.winfo_id()), True)
          == default_icon)

    appicon.PATH = tmp_ico
    appicon.apply(win)
    win.update()
    CK.ok("只改 appicon.PATH，窗口图标立刻变成新图标",
          H.icon_fingerprint(wndutil.root_of(win.winfo_id()), True) == red_base,
          "窗口=%s 新基准=%s" % (H.icon_fingerprint(
              wndutil.root_of(win.winfo_id()), True)[2][:16],
              red_base[2][:16] if red_base else None))
    CK.ok("且不再是原图标",
          H.icon_fingerprint(wndutil.root_of(win.winfo_id()), True) != base_big)
finally:
    appicon.PATH = real_path
    appicon.release()
    root.destroy()


# ==================================================================
print("\n=== E. 整机实例：面板与设置窗口 ===")
sb = H.Sandbox("icon", {"x": 260, "y": 160, "w": 470, "h": 620,
                        "locked": True,
                        "hotkey": {"ctrl": False, "alt": False, "shift": False,
                                   "win": False, "key": "F13"}})
panel = None
try:
    sb.start()
    panel = sb.panel(15.0)
    CK.ok("隔离实例已启动", bool(panel), "hwnd=%s" % panel)
    if panel:
        # 面板窗口是「先创建、后补图标」的（Tk 建窗在 appicon.apply 之前），
        # 拿到窗口句柄时初始化可能还没走到那一步，所以等它生效再判。
        waited = H.wait_expr(
            lambda: H.icon_fingerprint(panel, True) == base_big, 8.0)
        got = H.icon_fingerprint(panel, True)
        CK.ok("面板窗口图标 = 文件里的大图标层", waited is not None,
              ("%.0f ms 后一致" % (waited * 1000)) if waited
              else "超时，实际=%s" % (got[2][:16] if got else None))
        CK.ok("面板窗口图标不是 Tk 默认羽毛", got != default_icon)

        aux_hwnd = sb.aux(8.0)
        CK.ok("辅助窗口已创建", bool(aux_hwnd), aux_hwnd)

        H.post_menu_command(aux_hwnd, tray.CMD_SETTINGS)
        dlg = sb.settings(6.0)
        CK.ok("设置窗口已打开", bool(dlg), "hwnd=%s" % dlg)
        if dlg:
            waited = H.wait_expr(
                lambda: H.icon_fingerprint(dlg, True) == base_big, 8.0)
            dlg_icon = H.icon_fingerprint(dlg, True)
            CK.ok("设置窗口（任务栏上那个）图标 = 同一个文件",
                  waited is not None,
                  "设置=%s 基准=%s" % (dlg_icon[2][:16] if dlg_icon else None,
                                      base_big[2][:16] if base_big else None))
            CK.ok("设置窗口图标也不是 Tk 默认羽毛", dlg_icon != default_icon)

    CK.ok("运行期无异常", "Traceback" not in sb.text(),
          [ln.strip() for ln in sb.lines() if "Traceback" in ln][:2])
finally:
    sb.stop()

with open(os.path.join(ROOT, "appicon.py"), encoding="utf-8") as f:
    _src = f.read()
_writers = [t for t in ("open(", "shutil", "os.remove", "os.rename")
            if t in _src]
CK.ok("appicon 只读图标、不写任何文件（不会碰你的数据）", _writers == [],
      _writers)
CK.ok("测试进程侧已清理（没有留下挂载记录）",
      appicon.mounted_classes() == [], appicon.mounted_classes())

sys.exit(CK.report())
