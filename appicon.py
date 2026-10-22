# -*- coding: utf-8 -*-
"""应用图标的唯一来源。

全程序凡是"要露脸"的地方都从这里取，不存在第二处定义：

    · 窗口图标（标题栏 / 任务栏 / Alt+Tab）
                      —— apply(win)，一次挂到 Tk 的窗口类上，
                         之后所有顶层窗口（含以后新建的）自动继承
    · 托盘图标        —— load_hicon()
    · 自绘标题栏      —— photo()（文件里那一层的位图）+ title_text() 兜底
    · 窗口标题、托盘提示 —— APP_TITLE / SUBTITLE

**换图标只动这一个文件**：把新的 `.ico` 覆盖到下面 PATH 声明的位置即可。
之所以能做到"不必逐个修改"，是因为窗口图标挂在**窗口类**上，
而不是一个个窗口上 —— 见 apply() 的说明。

图案已选定定稿，全项目没有第二份副本，也没有生成脚本（设计过程稿在定稿
后已删除）。**覆盖前先备份** —— 旧图案唯一的找回途径是历史归档zip。

两个刻意的设计：
  · 不用 Tk 自带的 wm iconbitmap。实测它把 .ico 里第一个条目（16×16）当成唯一
    图标，缩放到系统大图标尺寸再交给窗口，读回来是"16 放大到 32"的插值图
    （边缘一圈 alpha 渐变），任务栏一放大就糊。自己调 SetClassLongPtr 并指定
    尺寸，读回来的像素与文件里那一层逐字节相同。
  · 不用 WM_SETICON 逐个窗口设。窗口级图标要求调用方持有句柄并在窗口销毁时
    销毁，而 Tk 的 overrideredirect() 会重建顶层窗口（句柄变化），注册表一乱就
    会误销毁别的窗口正在用的图标。挂到类上只有两个句柄，随进程退出回收。
"""
import base64
import os
import pathlib
import struct

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= 品牌标识（改这里就够） =================
APP_NAME = "浮坞"                       # 产品名
SUBTITLE = "FloatDock"                  # 副标题（标题栏右侧的小字）
GLYPH = "🕯"                            # 自绘标题栏用的字形，与 .ico 图案同源
APP_TITLE = APP_NAME + " " + SUBTITLE   # 窗口标题 / 托盘悬停提示

# ================= 图标文件 =================
FILENAME = "floatdock.ico"
PATH = os.path.join(APP_DIR, FILENAME)

# 已挂上的窗口类：类名 -> 句柄与现场，供 release() 还原
_mounted = {}


def title_text():
    """自绘标题栏上的主文字。"""
    return GLYPH + " " + APP_NAME


def settings_title():
    """设置窗口的标题（带系统标题栏，会显示在任务栏上）。"""
    return APP_NAME + " · 设置"


def photo(master, px=32):
    """自绘标题栏用的位图：图标文件里 px 那一层的原像素，画上去不走样。

    为什么不用 GLYPH 字形：emoji 走的是本机字体，不少环境把 🕯 渲染成
    单色剪影，和托盘/任务栏里那枚橙色图标完全对不上（实测截图里就是
    一根白描边的"灰蜡烛"）。位图直接取自图标文件，四处看到的必然是
    同一张图 —— 这才是"统一"该有的样子。

    取不到位图（文件缺失、该层不是 PNG）返回 None，调用方退回
    title_text() 字形，绝不开天窗。缓存挂在 master 上（窗口在图就在，
    窗口销毁缓存随之消失），key 含 PATH：换图标文件自动重取。
    """
    key = (PATH, px)
    cached = getattr(master, "_appicon_photo", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    blob = _png_layer(px)
    if blob is None:
        return None
    import tkinter as tk     # 推迟到真要画的时候：纯 import 本模块不该建 Tk
    try:
        img = tk.PhotoImage(master=master,
                            data=base64.b64encode(blob).decode("ascii"))
    except Exception:
        return None
    master._appicon_photo = (key, img)
    return img


def load_hicon(cx=None, cy=None):
    """从图标文件载入一个图标句柄，返回 (hicon, 是否本程序创建)。

    默认取通知区小图标尺寸（托盘用）；窗口图标按系统大/小图标尺寸各取一份。
    第二个返回值告诉调用方这个句柄要不要自己 DestroyIcon —— 系统共享图标
    销毁了会牵连别的程序，绝不能乱动。
    """
    from winapi import (u32, IMAGE_ICON, LR_LOADFROMFILE, IDI_APPLICATION,
                        make_int_resource, SM_CXSMICON, SM_CYSMICON)
    if cx is None:
        cx = u32.GetSystemMetrics(SM_CXSMICON)
    if cy is None:
        cy = u32.GetSystemMetrics(SM_CYSMICON)
    if os.path.exists(PATH):
        hicon = u32.LoadImageW(None, PATH, IMAGE_ICON, cx, cy, LR_LOADFROMFILE)
        if hicon:
            return hicon, True
    return u32.LoadIconW(None, make_int_resource(IDI_APPLICATION)), False


def apply(win):
    """确保这个窗口（以及同类的新窗口）带上应用图标。幂等，可多次调用。

    做两件事，缺一不可：
      1. 挂到窗口类上 —— Tk 的顶层窗口共用 TkTopLevel 类，挂一次，之后新建
         的窗口（设置窗、拾取层）自动继承，这就是"不必逐个修改"的实现方式；
      2. 设到本窗口上 —— 面板是 overrideredirect + 分层的窗口，Tk 在重建它
         时会顺手设一个自己的默认图标（羽毛）在窗口实例上，实例图标优先于
         类图标，不打点的话任务栏里就是那只羽毛。

    第 2 步的判据是"本窗口当前的大图标是不是我们这一对"：是就什么都不做，
    所以运行期反复调用不会重复载入句柄；Tk 重建后判据不成立，会自动补上。
    """
    from winapi import (u32, SM_CXICON, SM_CYICON, SM_CXSMICON, SM_CYSMICON,
                        GCLP_HICON, GCLP_HICONSM, WM_GETICON, WM_SETICON,
                        ICON_BIG, ICON_SMALL)
    hwnd, cls = _top_hwnd(win)
    if not hwnd or not cls:
        return False
    state = _mounted.get(cls)
    if state is None:
        big, _ = load_hicon(u32.GetSystemMetrics(SM_CXICON),
                            u32.GetSystemMetrics(SM_CYICON))
        small, _ = load_hicon(u32.GetSystemMetrics(SM_CXSMICON),
                              u32.GetSystemMetrics(SM_CYSMICON))
        if not big and not small:
            return False
        # old_* 只在首次记录：别拿"当前的类图标"当原值，它可能是我们上一次
        # 留下的句柄，销毁后就成了悬空引用。
        state = _mounted[cls] = {
            "big": big, "small": small,
            "old_big": u32.SetClassLongPtrW(hwnd, GCLP_HICON, big or 0),
            "old_small": u32.SetClassLongPtrW(hwnd, GCLP_HICONSM, small or 0),
        }
    else:
        # 复用同一对句柄，绝不重新载入（否则每补一次就多漏一对）
        if u32.GetClassLongPtrW(hwnd, GCLP_HICON) != state["big"]:
            u32.SetClassLongPtrW(hwnd, GCLP_HICON, state["big"])
            u32.SetClassLongPtrW(hwnd, GCLP_HICONSM, state["small"])
    state["hwnd"] = hwnd                    # 记最新窗口，release 时用它还原
    if u32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0) == state["big"]:
        return False
    u32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, state["big"])
    u32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, state["small"])
    return True


def release():
    """摘掉实例图标、还原窗口类图标，并销毁自己载入的句柄（退出时调用）。

    顺序不能反：先把窗口上的实例图标置空、并让窗口类指回原图标，再销毁句柄
    —— 否则窗口还指着已经销毁的图标，重绘时会出问题。

    类图标是本进程内的事，进程结束系统本来就会回收；主动还回去是为了让
    "退出时把借来的东西逐样交还"这条纪律在图标上也成立，同时给测试一个
    明确的释放点。
    """
    from winapi import (u32, GCLP_HICON, GCLP_HICONSM, WM_SETICON, ICON_BIG,
                        ICON_SMALL)
    for state in _mounted.values():
        hwnd = state["hwnd"]
        if hwnd and u32.IsWindow(hwnd):
            u32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, 0)
            u32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, 0)
            u32.SetClassLongPtrW(hwnd, GCLP_HICON, state["old_big"])
            u32.SetClassLongPtrW(hwnd, GCLP_HICONSM, state["old_small"])
        _dispose(state)
    _mounted.clear()


def mounted_classes():
    """已挂上应用图标的窗口类名（测试与排查用）。"""
    return sorted(_mounted)


# ================= 内部 =================
def _png_layer(px):
    """从图标文件里取出 px×px 那一层的 PNG 原始字节；取不到返回 None。

    ICO 目录本身是纯结构解析（struct，不碰系统）；只认 PNG-in-ICO 条目
    （现用的 floatdock.ico 就是这种），BMP 老格式不支持 —— 支持不了就如实
    返回 None 让调用方兜底，不猜。
    """
    try:
        data = pathlib.Path(PATH).read_bytes()
    except OSError:
        return None
    if len(data) < 6:
        return None
    _res, kind, count = struct.unpack_from("<HHH", data, 0)
    if kind != 1:
        return None
    for i in range(count):
        w, h, _c, _r, _p, _bpp, size, off = \
            struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        if (w or 256) == px and (h or 256) == px:
            blob = data[off:off + size]
            return blob if blob[:8] == b"\x89PNG\r\n\x1a\n" else None
    return None


def _dispose(state):
    """销毁这一对图标句柄（只销毁，不动窗口类）。"""
    from winapi import u32
    for hicon in (state["big"], state["small"]):
        if hicon:
            u32.DestroyIcon(hicon)


def _top_hwnd(win):
    """Tk 窗口对应的 (顶层窗口句柄, 窗口类名)；拿不到时 (None, "")。

    winfo_id() 给的是内部窗口，要上溯。两个坑，实测都踩过：
      · 窗口还没 map 之前，winfo_id() 给的是类名 TkChild 的内部窗口
        （安装程序就是栽在这：建完 Tk() 立刻 apply，图标挂到了子窗口类上，
        稍后真正建出来的 TkTopLevel 自然继承不到）。所以先 update_idletasks
        把真正的顶层窗口逼出来，且拿到手要验类名不是 TkChild 才认。
      · 验不过时催一次再试，仍不行就如实返回空，让调用方失败。

    类名一起返回：调用方本来就要拿它当"窗口类是哪个"的 key，省得再查一次
    （而它也正是上面判 TkChild 用的那个值）。
    """
    import wndutil
    for _attempt in (0, 1):
        try:
            hwnd = wndutil.root_of(win.winfo_id())
        except Exception:
            hwnd = None
        cls = wndutil.win_class(hwnd) if hwnd else ""
        if hwnd and cls != "TkChild":
            return hwnd, cls
        if not _attempt:
            try:
                win.update_idletasks()
            except Exception:
                break
    return None, ""
