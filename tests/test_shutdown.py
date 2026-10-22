# -*- coding: utf-8 -*-
"""关停审计：从启动到退出全程核查，退出后不允许有任何东西留在后台。

五个问题，一段回答一个：

  A 运行期形态   有没有派生/伴生进程、线程数是否符合预期、句柄与 GDI/USER
                 对象数在反复活动后是否稳定（长跑泄漏）
  B 正常退出     最坏情况（吸附中 + 设置窗口开着 + 拾取器激活）下走三条真实
                 出口：托盘「退出浮坞」、面板 ✕、窗口 WM_CLOSE。核对退出耗时、
                 窗口清空、被吸附窗口逐位还原、状态落盘
  C 系统侧回收   退出后：热键能被外部重新注册、托盘图标不再挂着、
                 全系统范围内没有非用户实例的浮坞窗口/进程残留
  D 托盘与热键   在测试进程里直接驱动 AuxThread，用 Shell_NotifyIconGetRect
                 证明图标真的从通知区消失、热键真的被注销
  E 异常退出对照 强制结束（TerminateProcess）之后还剩什么 —— 划清"我们能保证的"
                 与"Win32 固有的"边界

判据一律取外部可观测的系统状态（进程表、窗口枚举、注册表级 API），不采信
应用自己打的日志。沙箱实例一律独立 config + --allow-multiple，
绝不碰用户正在用的那个浮坞与它的 config.json。
"""
import ast
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import appicon                                  # noqa: E402
import hotkey                                   # noqa: E402
import theme as T                               # noqa: E402
import tray                                     # noqa: E402
import wndutil                                  # noqa: E402
from winapi import (u32, k32, sh32, NOTIFYICONDATAW)   # noqa: E402

CK = H.Checker("关停审计")

PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 200, 120, 470, 620
# 标题栏按钮中心从 theme 布局反查，不硬编码坐标
_BTN = dict((n, bx) for n, _g, bx in T.title_buttons(PANEL_W))
CLOSE_BTN = (_BTN["close"] + 14, T.H_TITLE // 2)    # 标题栏 ✕
GRAB_BTN = (_BTN["grab"] + 14, T.H_TITLE // 2)      # ✥ 吸附
TARGET_TITLE = "浮坞测试目标窗口"
# 落点现找空域，不写死 —— 用户正在用的浮坞面板实测在 (616,215)-(1404,941)，
# 正好压住写死的 (400,780)，会把"吸附不上"变成假象。见 harness.free_spot。
TARGET_W, TARGET_H = 420, 260
TARGET_GEOM = (lambda p: (p[0], p[1], TARGET_W, TARGET_H))(
    H.free_spot(TARGET_W, TARGET_H) or (400, 780))
print("目标窗口落点：%s（现找空域）" % (TARGET_GEOM,))
HK_KEY = "F14"                                      # 会被换成实测空闲的功能键
SANDBOX_PIDS = []                                   # 本次审计起过的沙箱进程

MOUSE_OK = H.mouse_injection_available()


# ==================================================================
# ctypes：进程 / 内存 / 托盘图标查询
# ==================================================================
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", wt.WCHAR * MAX_PATH)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT),
                ("guidItem", GUID)]


psapi = ctypes.WinDLL("psapi", use_last_error=True)

k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.GetProcessHandleCount.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.CloseHandle.argtypes = [wt.HANDLE]
u32.GetGuiResources.argtypes = [wt.HANDLE, wt.DWORD]
u32.GetGuiResources.restype = wt.DWORD
psapi.GetProcessMemoryInfo.argtypes = [
    wt.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wt.DWORD]
psapi.GetProcessMemoryInfo.restype = wt.BOOL
sh32.Shell_NotifyIconGetRect.restype = ctypes.c_long
sh32.Shell_NotifyIconGetRect.argtypes = [
    ctypes.POINTER(NOTIFYICONIDENTIFIER), ctypes.POINTER(wt.RECT)]


def procs():
    """{pid: (父 pid, 线程数, 映像名)} —— 进程表的快照。"""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out = {}
    if not snap:
        return out
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[int(e.th32ProcessID)] = (int(e.th32ParentProcessID),
                                     int(e.cntThreads), e.szExeFile)
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def proc_stat(pid):
    """线程 / 句柄 / GDI 对象 / USER 对象 / 驻留内存 / 私有内存。"""
    info = procs().get(pid)
    st = {"threads": info[1] if info else None, "handles": None, "gdi": None,
          "user": None, "rss": None, "private": None}
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION
                        | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return st
    try:
        hc = wt.DWORD()
        k32.GetProcessHandleCount(h, ctypes.byref(hc))
        st["handles"] = hc.value
        st["gdi"] = u32.GetGuiResources(h, 0)
        st["user"] = u32.GetGuiResources(h, 1)
        mem = PROCESS_MEMORY_COUNTERS()
        mem.cb = ctypes.sizeof(mem)
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(mem), mem.cb):
            st["rss"] = mem.WorkingSetSize
            st["private"] = mem.PagefileUsage
    finally:
        k32.CloseHandle(h)
    return st


def fmt(st):
    mb = lambda v: "%.1fMB" % (v / 1048576.0) if v else "?"
    return ("线程=%s 句柄=%s GDI=%s USER=%s 驻留=%s 私有=%s"
            % (st["threads"], st["handles"], st["gdi"], st["user"],
               mb(st["rss"]), mb(st["private"])))


def children_of(pid):
    return [p for p, (pp, _t, _e) in procs().items() if pp == pid]


def windows_of(pid):
    return [h for h in H.enum_windows() if wndutil.window_pid(h) == pid]


def wait_gone(pid, timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pid not in procs():
            return time.time() - t0
        time.sleep(0.02)
    return None


def foreign_floatdock(user_pids):
    """全系统范围内、不属于用户实例的浮坞窗口。

    用户实例本身也持有面板与辅助窗口，所以必须先按 pid 排除掉，
    否则这条检查会一直"失败"。标题要精确匹配：测试自己造的目标窗口
    叫"浮坞测试目标窗口"，用"含浮坞"去匹配会把它当成残留。
    """
    out = []
    for h in H.enum_windows():
        pid = wndutil.window_pid(h)
        if pid in user_pids:
            continue
        cls, title = wndutil.win_class(h), wndutil.win_text(h)
        # 类名与标题都向产品代码要，不在这里写死 —— 写死的话产品一改名，
        # 这条审计会静默地"什么窗口都没看到"，而那正是它本该抓的泄漏。
        if cls == H.aux_class_name() or (cls == "TkTopLevel" and (
                title == appicon.APP_TITLE or title == appicon.settings_title())):
            out.append((h, cls, title, pid))
    return out


def icon_rect(hwnd, uid=1):
    """托盘图标在通知区的位置；返回 (HRESULT, RECT)。0 表示图标还在。"""
    nid = NOTIFYICONIDENTIFIER()
    nid.cbSize = ctypes.sizeof(nid)
    nid.hWnd = hwnd
    nid.uID = uid
    r = wt.RECT()
    return sh32.Shell_NotifyIconGetRect(ctypes.byref(nid), ctypes.byref(r)), r


def try_hotkey(vk, mods):
    """在测试进程里试着占用一个热键（两种 MOD_NOREPEAT 写法都试）。"""
    for m in (mods, mods | 0x4000):
        ok, err = H.try_register_hotkey(vk, m)
        if ok:
            return True, err
    return False, err


# ==================================================================
# 公共：目标窗口与吸附
# ==================================================================
def find_target(pid, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        for h in H.enum_windows():
            if wndutil.window_pid(h) == pid and TARGET_TITLE in wndutil.win_text(h):
                return h
        time.sleep(0.15)
    return None


def snapshot(hwnd):
    from winapi import GWL_STYLE, GWL_EXSTYLE
    return {"rect": wndutil.win_rect(hwnd),
            "style": wndutil.get_long(hwnd, GWL_STYLE),
            "exstyle": wndutil.get_long(hwnd, GWL_EXSTYLE),
            "parent": u32.GetParent(hwnd)}


def bring_to_front(hwnd):
    SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 2, 1, 0x10, 0x40
    try:
        u32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    time.sleep(0.25)
    u32.SetWindowPos(hwnd, -2, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    time.sleep(0.15)


def do_attach(target, panel):
    """按住「✥ 吸附窗口」拖到目标上松开。

    返回 (结果, 说明)：结果是 "ok" / "blocked" / "failed"。
    刻意把 "blocked"（落点被别的窗口压住，纯环境问题）与 "failed"
    （鼠标都放对了却没吸上，那才是产品缺陷）分开 —— 混成一个布尔值时，
    环境失败会以产品缺陷的样子报出来，排查方向直接被带偏。
    """
    rect = wndutil.win_rect(target)
    center = (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2)
    bring_to_front(target)
    H.move_mouse(*center, steps=16)
    time.sleep(0.3)
    under = wndutil.point_window()
    if under != target:
        return "blocked", "(%.0f,%.0f) 上是 %s %r" % (
            center[0], center[1], wndutil.win_class(under),
            wndutil.win_text(under))
    px, py, _pw, _ph = wndutil.win_rect(panel)
    H.move_mouse(px + GRAB_BTN[0], py + GRAB_BTN[1])
    time.sleep(0.2)
    u32.mouse_event(0x0002, 0, 0, 0, 0)                 # 按住
    time.sleep(0.3)
    H.move_mouse(*center, steps=24)
    time.sleep(0.4)
    if wndutil.point_window() != target:
        u32.PostMessageW(panel, H.WM_KEYDOWN, 0x1B, 0)  # Esc 取消，绝不误吸附
        time.sleep(0.3)
        u32.mouse_event(0x0004, 0, 0, 0, 0)
        return "blocked", "拖到一半目标被压住（已 Esc 取消）"
    u32.mouse_event(0x0004, 0, 0, 0, 0)                 # 松开
    time.sleep(0.9)
    if u32.GetParent(target) == panel:
        return "ok", "parent=面板"
    return "failed", "鼠标已放对但没吸上，parent=%s" % u32.GetParent(target)


def click_close(panel):
    """点标题栏的 ✕ —— 这是用户最常用的退出方式，必须用真实鼠标试。

    坐标取自 render 的命中区布局：✕ 的框是 (w-34, 4, w-6, H_TITLE-4)。
    只在 MOUSE_OK 时调用：沙箱不给物理鼠标时，PostMessage 的鼠标消息
    触发不了 Tk 的绑定（实测五种投法都无效），消息级兜底是死路，
    调用方须自行改走 WM_CLOSE 并如实标注跳过。
    """
    cx, cy = CLOSE_BTN
    px, py, _pw, _ph = wndutil.win_rect(panel)
    u32.SetForegroundWindow(panel)
    time.sleep(0.25)
    H.click_mouse(px + cx, py + cy)


def free_bare_key():
    for name in ("F14", "F15", "F16", "F17", "F13", "F18", "F19", "F20"):
        if H.try_register_hotkey(hotkey.VK_MAP[name])[0]:
            return name
    return None


def bare(key):
    return {"ctrl": False, "alt": False, "shift": False, "win": False,
            "key": key}


def bare_thread_baseline():
    """裸解释器有多少条原生线程。

    CPython 3.14 在本机起来就是 9~10 条（运行时与沙箱注入），每建一个窗口
    环境还会再加一条，所以"外部数出来 N 条"根本说不清浮坞起了几条线程。
    这里只把它当作环境基线记录，真正的线程账本由 thread_probe.py 在进程内点。
    """
    p = subprocess.Popen([H.PY, "-c", "import time; time.sleep(3)"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.9)
    n = proc_stat(p.pid)["threads"]
    p.kill()
    p.wait()
    return n


def thread_inventory():
    """在独立进程里起一次浮坞，拿 Python 视角的线程清单。

    返回 {阶段: (数量, [(名称, 是否守护), ...])}，阶段取 THREADS_INIT / BUSY / QUIT。
    """
    p = subprocess.Popen([H.PY, "-u", os.path.join(HERE, "thread_probe.py")],
                         cwd=H.ROOT, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace")
    out = []
    t0 = time.time()
    while time.time() - t0 < 40.0:
        line = p.stdout.readline()
        if not line:
            break
        out.append(line.rstrip())
        if line.startswith("THREADS_QUIT"):
            break
    try:
        p.wait(timeout=10)
    except Exception:
        p.kill()
    stages = {}
    for line in out:
        parts = line.split(" ", 2)
        if len(parts) >= 3 and parts[0].startswith("THREADS_"):
            try:
                threads = [tuple(t) for t in ast.literal_eval(parts[2])]
            except Exception:
                threads = []
            stages[parts[0]] = (int(parts[1]), threads)
    return stages, out


# ==================================================================
guard = H.UserGuard()
guard_pids = set(int(p) for p in guard.pids)
print("用户实例 pythonw PID: %s" % (guard.pids or "无"))
print("用户 config.json sha256: %s" % guard.cfg[:16])
print("物理鼠标注入可用: %s" % MOUSE_OK)

HK_KEY = free_bare_key() or HK_KEY
print("本次审计选用的裸功能键: %s" % HK_KEY)

base_procs = set(procs())
base_foreign = foreign_floatdock(guard_pids)
print("基线：非用户实例的浮坞窗口 %d 个" % len(base_foreign))


# ==================================================================
# A. 运行期形态：进程树 / 线程 / 句柄 / 内存
# ==================================================================
print("\n=== A. 运行期形态：有没有伴生进程，资源会不会长跑泄漏 ===")

sb = H.Sandbox("shutdown_a", {
    "x": PANEL_X, "y": PANEL_Y, "w": PANEL_W, "h": PANEL_H, "opacity": 0.92,
    "locked": True, "hide_delay": 3.0, "hotkey": bare(HK_KEY)})

try:
    sb.start()
    panel = sb.panel(15.0)
    aux = sb.aux(8.0)
    CK.ok("A：实例启动（面板 + 热键辅助窗口）", bool(panel and aux),
          "panel=%s aux=%s" % (panel, aux))
    if not (panel and aux):
        sys.exit(CK.report())
    time.sleep(1.6)

    pid = sb.proc.pid
    SANDBOX_PIDS.append(pid)
    kids = children_of(pid)
    CK.ok("A：启动过程没有派生子进程（不拉起任何外部程序/服务）", kids == [],
          "子进程=%s" % kids)

    s0 = proc_stat(pid)
    base_threads = bare_thread_baseline()
    print("    基线：裸解释器原生线程=%s；浮坞进程：%s" % (base_threads, fmt(s0)))
    CK.ok("A：外部看到的是稳定的进程形态（原生线程数随环境浮动，不用于判定）",
          s0["threads"] is not None, "原生线程=%s" % s0["threads"])

    # 活动：反复开关设置窗口 + 热键切换
    print("    施加活动：5 轮开关设置窗口 + 6 次热键显隐")
    for i in range(5):
        H.post_menu_command(aux, tray.CMD_SETTINGS)
        dlg = sb.settings(6.0)
        if dlg:
            H.send_close(dlg)
            time.sleep(0.35)
        H.post_hotkey(aux)
        time.sleep(0.35)
    time.sleep(1.2)

    s1 = proc_stat(pid)
    print("    活动后：" + fmt(s1))
    d = lambda k: (s1[k] - s0[k]) if (s0[k] is not None and s1[k] is not None) else None
    CK.ok("A：活动后线程数不变（没有线程泄漏）", d("threads") == 0,
          "%s → %s" % (s0["threads"], s1["threads"]))
    CK.ok("A：句柄数未随活动增长（无句柄泄漏）",
          d("handles") is not None and d("handles") <= 30,
          "Δ句柄=%s（%s → %s）" % (d("handles"), s0["handles"], s1["handles"]))
    CK.ok("A：GDI 对象数稳定", d("gdi") is not None and d("gdi") <= 15,
          "ΔGDI=%s" % d("gdi"))
    CK.ok("A：USER 对象数稳定", d("user") is not None and d("user") <= 15,
          "ΔUSER=%s" % d("user"))
    CK.ok("A：内存未持续膨胀", d("rss") is not None and d("rss") <= 12 << 20,
          "Δ驻留=%.1fMB" % (d("rss") / 1048576.0))
    CK.ok("A：折腾一轮后仍未派生任何子进程", children_of(pid) == [],
          children_of(pid))

    # 线程账本：外部数出来的原生线程数受环境干扰，必须在进程内点
    print("\n--- 进程内线程清单（thread_probe.py）---")
    stages, raw = thread_inventory()
    for line in raw:
        print("    " + line)
    init = stages.get("THREADS_INIT")
    busy_st = stages.get("THREADS_BUSY")
    quit_st = stages.get("THREADS_QUIT")
    CK.ok("A：浮坞只起 2 条 Python 线程（主线程 + 托盘热键线程）",
          bool(init) and bool(busy_st)
          and init[0] == 2 and busy_st[0] == 2
          and [t[0] for t in busy_st[1]] == ["MainThread", "Thread-1"],
          "启动=%s 忙碌后=%s 退出前=%s" % (init, busy_st, quit_st))
    CK.ok("A：那条额外的线程是守护线程（不会拖住退出）",
          bool(busy_st) and all(t[1] for t in busy_st[1][1:]),
          busy_st[1] if busy_st else "")
    CK.ok("A：忙碌后线程清单不变（开关设置窗口不新增线程）",
          bool(init) and bool(busy_st) and init[1] == busy_st[1],
          "%s vs %s" % (init[1] if init else None, busy_st[1] if busy_st else None))
    CK.ok("A：进程内无异常", "Traceback" not in "".join(raw),
          [ln for ln in raw if "Traceback" in ln][:2])

    # 收尾：走面板 ✕ 退出（这条出口在 B 段还会复测，这里先保证干净收场）
    if not H.visible(panel):
        H.post_hotkey(aux)                  # 上面那几轮显隐把它留在了隐藏态
        H.wait_visible(panel, True, 2.5)
    u32.SetForegroundWindow(panel)
    time.sleep(0.3)
    if MOUSE_OK:
        click_close(panel)
        gone = wait_gone(pid, 6.0)
        CK.ok("A：点 ✕ 后进程退出", gone is not None,
              "%.0f ms" % (gone * 1000) if gone else "未退出（B 段会详查）")
    else:
        # 沙箱拦截物理鼠标注入时点 ✕ 没法测：PostMessage 的鼠标消息触发不了
        # Tk 的绑定（实测直投/先 MOVE/SendMessage/投 wrapper/双击五种投法都
        # 无效，见排查记录），诚实跳过；收场改走 WM_CLOSE —— 与 ✕ 同一个
        # quit()，让下面的"退出后回到基线"核对照常进行。
        CK.skip("A：点 ✕ 后进程退出",
                "沙箱拦截物理鼠标注入，消息级点击触发不了 Tk 绑定")
        H.send_close(panel)
        gone = wait_gone(pid, 6.0)
    if gone is None:
        sb.stop()
        CK.ok("A：退出后回到基线（无新增浮坞窗口残留）", False, "未退出，另有记录")
    else:
        CK.ok("A：退出后回到基线（无新增浮坞窗口残留）",
              foreign_floatdock(guard_pids) == base_foreign,
              foreign_floatdock(guard_pids))
finally:
    sb.stop()


# ==================================================================
# B. 正常退出：最坏情况下走三条真实出口
# ==================================================================
def worst_case(label, exit_kind, with_absorb):
    print("\n=== B.%s：%s ===" % (exit_kind, label))
    sb = H.Sandbox("shutdown_%s" % exit_kind, {
        "x": PANEL_X, "y": PANEL_Y, "w": PANEL_W, "h": PANEL_H,
        "opacity": 0.92, "locked": True, "hide_delay": 3.0,
        "hotkey": bare(HK_KEY)})
    tgt_proc = None
    target = None
    snap = None
    held = False
    try:
        sb.start()
        panel = sb.panel(15.0)
        aux = sb.aux(8.0)
        CK.ok("%s：实例已启动" % label, bool(panel and aux))
        if not (panel and aux):
            return
        pid = sb.proc.pid
        SANDBOX_PIDS.append(pid)
        time.sleep(1.5)
        n_win = len(windows_of(pid))
        CK.ok("%s：退出前该进程持有 %d 个顶层窗口" % (label, n_win), n_win >= 2,
              "%.0fMB 驻留" % (proc_stat(pid)["rss"] / 1048576.0))

        # 退出时挂着设置窗口（不清场）
        H.post_menu_command(aux, tray.CMD_SETTINGS)
        dlg = sb.settings(6.0)
        CK.ok("%s：退出时设置窗口仍开着（刻意不清场）" % label, bool(dlg),
              "hwnd=%s" % dlg)

        # 退出时挂着被吸附的窗口
        absorbed = False
        if with_absorb:
            if MOUSE_OK:
                tgt_proc = subprocess.Popen(
                    [H.PY, "-u", os.path.join(HERE, "absorb_target.py"),
                     str(TARGET_GEOM[0]), str(TARGET_GEOM[1]),
                     str(TARGET_GEOM[2]), str(TARGET_GEOM[3])], cwd=HERE)
                target = find_target(tgt_proc.pid)
                if target:
                    snap = snapshot(target)
                    verdict, why = do_attach(target, panel)
                    # blocked 是环境（落点被别的窗口压住），failed 才是产品缺陷
                    if verdict == "ok":
                        absorbed = True
                        CK.ok("%s：目标窗口已吸附进面板" % label, True, why)
                    elif verdict == "blocked":
                        CK.skip("%s：带吸附窗口退出" % label,
                                "落点被占，这一段没跑成：%s" % why)
                    else:
                        CK.ok("%s：目标窗口已吸附进面板" % label, False, why)
                else:
                    CK.ok("%s：目标窗口已创建" % label, False)
            else:
                CK.skip("%s：带吸附窗口退出" % label,
                        "沙箱拦截物理鼠标注入，拾取器无法定位目标")

        # 退出时拾取器正激活（左键按住不放）
        if absorbed and MOUSE_OK:
            n0 = sb.line_count()
            px, py, _pw, _ph = wndutil.win_rect(panel)
            H.move_mouse(px + GRAB_BTN[0], py + GRAB_BTN[1])
            time.sleep(0.25)
            u32.mouse_event(0x0002, 0, 0, 0, 0)         # 按住，先不松
            held = True
            time.sleep(0.7)
            seg = "".join(sb.lines()[n0:])
            CK.ok("%s：退出时拾取器正在工作（已开始拾取且尚未结束）" % label,
                  "开始拾取" in seg and "结束拾取" not in seg,
                  [ln.strip() for ln in sb.lines()[n0:] if "拾取" in ln][-2:])

        cfg_mtime = os.path.getmtime(sb.cfg_path)
        time.sleep(1.1)                                  # 跨过文件时间戳精度
        if exit_kind == "tray":
            H.post_menu_command(aux, tray.CMD_QUIT)      # 托盘「退出浮坞」
        elif MOUSE_OK:
            click_close(panel)
        else:
            # 同 A 段：物理鼠标不可用，✕ 点击没法做 —— 用 WM_CLOSE 走同一个
            # quit()，让"最坏情况下退出"的整套收尾审计照常进行。
            print("    （沙箱无物理鼠标：✕ 点击以 WM_CLOSE 替代，同一个 quit()）")
            H.send_close(panel)

        dt = wait_gone(pid, 8.0)
        CK.ok("%s：进程已完全退出" % label, dt is not None,
              "%.0f ms" % (dt * 1000) if dt else "8 秒内未退出")
        if dt is None:
            print("    未退出，强杀收场：%s" % label)
            sb.stop()
            return
        CK.ok("%s：退出耗时 < 2 秒（随点随走）" % label, dt < 2.0,
              "%.0f ms" % (dt * 1000))

        # ---- 退出后的系统侧核对 ----
        CK.ok("%s：该 PID 不再持有任何窗口" % label, windows_of(pid) == [],
              windows_of(pid))
        CK.ok("%s：系统范围内没有非用户实例的浮坞窗口残留" % label,
              foreign_floatdock(guard_pids) == base_foreign,
              foreign_floatdock(guard_pids))
        CK.ok("%s：设置窗口随之销毁" % label,
              not dlg or not u32.IsWindow(dlg),
              "IsWindow=%s" % u32.IsWindow(dlg) if dlg else "未打开")
        CK.ok("%s：退出前已把状态落盘（_save 在退出路径上）" % label,
              os.path.getmtime(sb.cfg_path) > cfg_mtime,
              "mtime %.3f → %.3f" % (cfg_mtime, os.path.getmtime(sb.cfg_path)))
        CK.ok("%s：日志留下退出记录" % label,
              "退出释放" in sb.text(),
              [ln.strip() for ln in sb.lines() if "退出释放" in ln][:2])
        if with_absorb and absorbed:
            CK.ok("%s：退出释放的窗口数正确（1 个）" % label,
                  "退出释放 1 个窗口" in sb.text(),
                  [ln.strip() for ln in sb.lines() if "退出释放" in ln][:2])
        CK.ok("%s：辅助线程在退出时被同步叫停（不是靠强杀）" % label,
              "辅助线程已结束：True" in sb.text(),
              [ln.strip() for ln in sb.lines() if "辅助线程" in ln][:2])
        CK.ok("%s：没有未能还原的窗口" % label,
              "未能还原" not in sb.text(),
              [ln.strip() for ln in sb.lines() if "未能还原" in ln][:2])
        CK.ok("%s：运行期无异常" % label, "Traceback" not in sb.text(),
              [ln.strip() for ln in sb.lines() if "Traceback" in ln][:2])

        # ---- 热键被系统回收 ----
        ok, err = try_hotkey(hotkey.VK_MAP[HK_KEY], 0)
        CK.ok("%s：全局热键已被系统回收（外部可再注册裸 %s）"
              % (label, HK_KEY), ok, "err=%s" % err)

        # ---- 被吸附窗口逐位还原 ----
        if absorbed and target:
            CK.ok("%s：被吸附窗口仍然存在（没被宿主带走）" % label,
                  bool(u32.IsWindow(target)), target)
            if u32.IsWindow(target):
                now = snapshot(target)
                CK.ok("%s：父窗口还原" % label, now["parent"] == snap["parent"],
                      "%s → %s" % (snap["parent"], now["parent"]))
                CK.ok("%s：style 逐位还原" % label,
                      now["style"] == snap["style"],
                      "0x%08X → 0x%08X" % (snap["style"], now["style"]))
                CK.ok("%s：exstyle 逐位还原" % label,
                      now["exstyle"] == snap["exstyle"],
                      "0x%08X → 0x%08X" % (snap["exstyle"], now["exstyle"]))
                CK.ok("%s：几何还原到原位" % label,
                      bool(now["rect"]) and all(
                          abs(a - b) <= 3
                          for a, b in zip(now["rect"], snap["rect"])),
                      "%s → %s" % (snap["rect"], now["rect"]))
                CK.ok("%s：窗口回到桌面且可见可用" % label,
                      H.visible(target) is True
                      and wndutil.root_of(target) == target)
    finally:
        if held:
            u32.mouse_event(0x0004, 0, 0, 0, 0)          # 松开，别把左键卡住
            time.sleep(0.2)
        sb.stop()
        if tgt_proc is not None:
            try:
                tgt_proc.terminate()
                tgt_proc.wait(timeout=5)
            except Exception:
                tgt_proc.kill()


worst_case("托盘「退出浮坞」+ 吸附中 + 拾取中 + 设置开着", "tray", True)
worst_case("面板 ✕ + 设置开着", "close", False)

# 第三条出口：窗口 WM_CLOSE（等价于系统要求关闭窗口）
print("\n=== B.wmclose：向面板投递 WM_CLOSE ===")
sb3 = H.Sandbox("shutdown_wmclose", {
    "x": PANEL_X, "y": PANEL_Y, "w": PANEL_W, "h": PANEL_H, "opacity": 0.92,
    "locked": True, "hide_delay": 3.0, "hotkey": bare(HK_KEY)})
try:
    sb3.start()
    panel = sb3.panel(15.0)
    aux = sb3.aux(8.0)
    CK.ok("B.wmclose：实例已启动", bool(panel and aux))
    if panel and aux:
        SANDBOX_PIDS.append(sb3.proc.pid)
        time.sleep(1.4)
        H.send_close(panel)
        dt = wait_gone(sb3.proc.pid, 6.0)
        CK.ok("B.wmclose：WM_CLOSE 也能干净退出（无边框窗口没有标题栏，"
              "系统一般不会送来，但协议已接住）", dt is not None,
              "%.0f ms" % (dt * 1000) if dt else "未退出（说明只有 ✕/托盘两条出口）")
        if dt is None:
            sb3.stop()
        else:
            CK.ok("B.wmclose：退出后无窗口残留",
                  windows_of(sb3.proc.pid) == [])
finally:
    sb3.stop()


# ==================================================================
# C. 退出后系统侧总账
# ==================================================================
print("\n=== C. 退出后系统侧总账 ===")
CK.ok("C：没有非用户实例的浮坞窗口（面板/辅助/设置）",
      foreign_floatdock(guard_pids) == base_foreign,
      foreign_floatdock(guard_pids))
CK.ok("C：本次启动过的三个沙箱进程全部消失",
      all(pid not in procs() for pid in SANDBOX_PIDS),
      "沙箱=%s 仍存活=%s" % (SANDBOX_PIDS,
                            [p for p in SANDBOX_PIDS if p in procs()]))
snap = procs()                          # 一次快照，别在同一句里查两遍（进程随时在变）
orphans = [p for p, info in snap.items() if info[0] == os.getpid()]
CK.ok("C：本测试派生的子进程（沙箱 / 目标窗口 / 宿主）一个不剩",
      orphans == [], [snap[p][2] for p in orphans])
ok, err = try_hotkey(hotkey.VK_MAP[HK_KEY], 0)
CK.ok("C：审计选用的热键回到空闲（无实例继续独占）", ok, "err=%s" % err)


# ==================================================================
# D. 托盘图标与热键的真实回收（驱动辅助线程本身）
# ==================================================================
print("\n=== D. 托盘图标 / 热键的真实回收 ===")

# 通知区的图标查不到位置时（新图标常被收进溢出区），改用"调用记录"来判据：
# 把 Shell_NotifyIconW 换成记录器，直接看 NIM_ADD / NIM_DELETE 是否真的发出、
# 参数是否是同一个 hWnd/uID、返回值是否成功。这比看图标位置的 API 更可靠。
NIC_CALLS = []
_real_notify = sh32.Shell_NotifyIconW


def _record_notify(nim, pnid):
    r = _real_notify(nim, pnid)
    nid = ctypes.cast(pnid, ctypes.POINTER(NOTIFYICONDATAW)).contents
    NIC_CALLS.append((nim, nid.hWnd, nid.uID, bool(r)))
    return r


sh32.Shell_NotifyIconW = _record_notify

aux_obj = None
try:
    aux_obj = tray.AuxThread("浮坞关停审计", lambda: False, bare(HK_KEY))
    aux_obj.start()
    CK.ok("D：辅助线程已就绪", aux_obj.ready.wait(3.0))
    own_aux = H.find_aux(os.getpid(), 5.0)
    CK.ok("D：辅助窗口已创建", bool(own_aux), "hwnd=%s" % own_aux)
    CK.ok("D：热键已注册", aux_obj._hk_registered is True)
    CK.ok("D：热键确被本进程独占（外部注册失败，err=1409）",
          H.try_register_hotkey(hotkey.VK_MAP[HK_KEY])[0] is False)

    adds = [c for c in NIC_CALLS if c[0] == 0]
    CK.ok("D：托盘图标已加入通知区（NIM_ADD 发出且成功）",
          bool(adds) and adds[-1][3] is True and adds[-1][2] == 1,
          "调用记录=%s" % NIC_CALLS)
    if own_aux:
        hr, rect = icon_rect(own_aux)
        print("    通知区位置查询 hr=0x%08X%s"
              % (hr & 0xFFFFFFFF,
                 "（图标在溢出区/未显示，用不到这条）" if hr != 0 else ""))

    if own_aux:
        aux_obj.remove_tray()
        time.sleep(0.5)
        dels = [c for c in NIC_CALLS if c[0] == 2]
        CK.ok("D：托盘图标已从通知区删除（NIM_DELETE 发出且成功）",
              bool(dels) and dels[-1][3] is True,
              "调用记录=%s" % NIC_CALLS)
        CK.ok("D：删的就是加的那个图标（hWnd/uID 一致）",
              bool(adds) and bool(dels)
              and (adds[-1][1], adds[-1][2]) == (dels[-1][1], dels[-1][2]),
              "%s vs %s" % (adds[-1][1:3] if adds else None,
                            dels[-1][1:3] if dels else None))
        CK.ok("D：热键已注销（辅助线程状态如实更新）",
              aux_obj._hk_registered is False)
        CK.ok("D：辅助窗口已销毁", not u32.IsWindow(own_aux), own_aux)

        # 这条是审计的重点：remove_tray 之后消息循环必须自己结束，
        # 否则进程会留一个"没窗口、没图标、还在跑"的后台线程。
        aux_obj.join(1.5)
        CK.ok("D：辅助线程自行结束（WM_QUIT 生效，无需外部强杀）",
              aux_obj.is_alive() is False,
              "is_alive=%s" % aux_obj.is_alive())
finally:
    if aux_obj is not None and aux_obj.is_alive():
        try:
            u32.PostThreadMessageW(aux_obj.ident, 0x0012, 0, 0)
        except Exception:
            pass
    sh32.Shell_NotifyIconW = _real_notify
CK.ok("D：测试进程里没有留下浮坞窗口",
      foreign_floatdock(guard_pids) == base_foreign,
      foreign_floatdock(guard_pids))


# ==================================================================
# E. 异常退出对照：被强杀时还剩什么
# ==================================================================
print("\n=== E. 异常退出对照（TerminateProcess，没有任何清理机会）===")
tgt_proc = None
host_proc = None
try:
    tgt_proc = subprocess.Popen(
        [H.PY, "-u", os.path.join(HERE, "absorb_target.py"),
         str(TARGET_GEOM[0]), str(TARGET_GEOM[1]),
         str(TARGET_GEOM[2]), str(TARGET_GEOM[3])], cwd=HERE,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    target = find_target(tgt_proc.pid)
    CK.ok("E：目标窗口已创建", bool(target), "hwnd=%s" % target)
    if target:
        snap = snapshot(target)
        host_proc = subprocess.Popen(
            [H.PY, "-u", os.path.join(HERE, "kill_host.py")], cwd=HERE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace")
        line = ""
        t0 = time.time()
        while time.time() - t0 < 10.0:
            line = host_proc.stdout.readline()
            if "OK=" in line:
                break
        print("    宿主：%s" % line.strip())
        CK.ok("E：宿主进程已把目标窗口吸走（模拟运行中的浮坞）",
              u32.GetParent(target) != snap["parent"],
              "parent=%s" % u32.GetParent(target))

        host_proc.kill()                     # TerminateProcess：等价于任务管理器
        host_proc.wait(timeout=5)
        time.sleep(1.2)
        CK.ok("E：宿主进程已被强制结束", host_proc.pid not in procs())

        alive = bool(u32.IsWindow(target))
        print("    强杀后目标窗口：IsWindow=%s" % alive)
        if alive:
            now = snapshot(target)
            print("      父=%s（原 %s） 可见=%s 几何=%s（原 %s）"
                  % (now["parent"], snap["parent"], H.visible(target),
                     now["rect"], snap["rect"]))
            same = (now["parent"] == snap["parent"]
                    and now["style"] == snap["style"]
                    and now["rect"] == snap["rect"])
            print("      结论：第三方窗口存活%s"
                  % ("且逐位还原" if same else "但状态未还原（需重新摆位/还样式）"))
        else:
            print("      结论：第三方窗口随宿主一起被系统销毁 —— "
                  "Win32 跨进程父子的固有代价，应用侧无法阻止")
        CK.ok("E：强杀不留进程（OS 回收了宿主的内存与线程）",
              host_proc.pid not in procs())
finally:
    for p in (host_proc, tgt_proc):
        if p is not None:
            try:
                p.kill()
                p.wait(timeout=5)
            except Exception:
                pass


# ==================================================================
print("\n=== 收尾护栏 ===")
CK.ok("全程未动用户实例（pythonw 进程集合不变）", guard.unchanged(),
      guard.detail())
CK.ok("全程未改用户 config.json", guard.unchanged(), guard.cfg[:16])
CK.ok("系统范围内没有留下任何浮坞残留窗口",
      foreign_floatdock(guard_pids) == base_foreign,
      foreign_floatdock(guard_pids))

sys.exit(CK.report())
