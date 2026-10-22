# -*- coding: utf-8 -*-
"""安装/卸载共用的底座：快捷方式、注册表、进程与路径。

为什么自己用 ctypes 调 COM 建快捷方式，而不是拖进 pywin32 / comtypes：
安装程序要能在一台干净的 Windows 上跑，多一个第三方依赖就多一个失败点。
IShellLinkW 只用到五个方法（SetPath / SetArguments / SetWorkingDirectory /
SetIconLocation / Save），直接按虚表序号调用即可，总共几十行。

约定：
  · 快捷方式图标一律 <安装目录>\\floatdock.ico（用户要求统一用程序图标）
  · 快捷方式带 --config，把配置指到 %LOCALAPPDATA%\\FloatDock\\config.json，
    这样即使装到 Program Files（不可写）也能正常保存面板状态
"""
import ctypes
import os
import subprocess
import sys
import winreg
from ctypes import wintypes

APP_NAME = "浮坞 FloatDock"
# 安装链的版本号。产品版本在 panel.VERSION；这一份要跟着改
# （tools/make_archive.py 归档前会对账，不一致直接拒绝打包）。
DISPLAY_VERSION = "v1.10.0"
EXE_NAME = "FloatDock.exe"
ICO_NAME = "floatdock.ico"
DOC_NAME = "使用说明.md"
UNINST_NAME = "卸载程序.exe"
UNINST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\FloatDock"

CLSCTX_INPROC_SERVER = 1
_CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
_IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
_IID_IPersistFile = "{0000010B-0000-0000-C000-000000000046}"

# IShellLinkW 虚表序号（IUnknown 占 0–2）
_VT_SET_PATH = 20
_VT_SET_ARGS = 11
_VT_SET_WORKDIR = 9
_VT_SET_ICON = 17
_VT_QUERY_INTERFACE = 0
# IPersistFile 虚表序号
_VT_SAVE = 6

_ole32 = ctypes.oledll.ole32          # oledll：HRESULT 失败会自动抛 OSError


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super(GUID, self).__init__()
        _ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


def _call(ptr, index, argtypes, *args):
    """按虚表序号调用 COM 方法。

    argtypes 必须显式给：ctypes.byref() 产生的是 CArgObject，不能靠 type()
    反推类型（那是 ValueError 的常见来源）。
    """
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    hr = proto(vtbl[index])(ptr, *args)
    if hr < 0:
        raise OSError("COM 调用失败 hr=0x%08X（虚表 %d）" % (hr & 0xFFFFFFFF,
                                                        index))


def _shell_link():
    """建一个 IShellLinkW 对象；返回 (指针, 是否本线程需要 CoUninitialize)。"""
    need_uninit = False
    hr = ctypes.oledll.ole32.CoInitialize(None)
    if hr in (0, 1):                       # S_OK / S_FALSE 都算可用
        need_uninit = True
    p = ctypes.c_void_p()
    ctypes.oledll.ole32.CoCreateInstance(
        ctypes.byref(GUID(_CLSID_ShellLink)), None, CLSCTX_INPROC_SERVER,
        ctypes.byref(GUID(_IID_IShellLinkW)), ctypes.byref(p))
    return p, need_uninit


def _release(p, need_uninit):
    try:
        _call(p, 2, [])                    # IUnknown::Release
    except Exception:
        pass
    if need_uninit:
        try:
            ctypes.oledll.ole32.CoUninitialize()
        except Exception:
            pass


def create_shortcut(lnk_path, target, args="", workdir="", icon="",
                    desc=""):
    """写一个 .lnk。失败抛 OSError，调用方负责给出人话提示。"""
    parent = os.path.dirname(lnk_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    p, need_uninit = _shell_link()
    try:
        w = [ctypes.c_wchar_p]
        _call(p, _VT_SET_PATH, w, target)
        if args:
            _call(p, _VT_SET_ARGS, w, args)
        if workdir:
            _call(p, _VT_SET_WORKDIR, w, workdir)
        if desc:
            _call(p, 7, w, desc)                  # IShellLinkW::SetDescription
        if icon:
            _call(p, _VT_SET_ICON, [ctypes.c_wchar_p, ctypes.c_int], icon, 0)
        pf = ctypes.c_void_p()
        _call(p, _VT_QUERY_INTERFACE,
              [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
              ctypes.byref(GUID(_IID_IPersistFile)), ctypes.byref(pf))
        _call(pf, _VT_SAVE, [ctypes.c_wchar_p, wintypes.BOOL], lnk_path,
              True)
        _call(pf, 2, [])                          # 用完就放
        return lnk_path
    finally:
        _release(p, need_uninit)


# ================= 目录 =================
# 这几个目录允许用环境变量重定向：自动化测试要在不碰真实桌面的前提下跑完整
# 安装流程；企业环境里桌面/开始菜单被组策略改到别处时也能照常工作。
def local_appdata():
    return os.environ.get("FD_LOCALAPPDATA") or os.environ.get("LOCALAPPDATA") \
        or os.path.expanduser("~")


def default_install_dir():
    """默认装到当前用户可写的位置，不需要管理员权限。"""
    return os.path.join(local_appdata(), "Programs", "FloatDock")


def config_dir():
    """配置目录：安装版把 config.json 放这儿（安装目录可能不可写）。"""
    return os.environ.get("FD_CONFIG_DIR") or os.path.join(local_appdata(),
                                                           "FloatDock")


def config_path():
    return os.path.join(config_dir(), "config.json")


def launch_args():
    """快捷方式/运行用的参数：把配置固定到用户目录。"""
    return '--config "%s"' % config_path()


def desktop_dir():
    return os.environ.get("FD_DESKTOP_DIR") or os.path.join(
        os.path.expanduser("~"), "Desktop")


def start_menu_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.environ.get("FD_STARTMENU_DIR") or os.path.join(
        base, "Microsoft", "Windows", "Start Menu", "Programs")


def startup_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.environ.get("FD_STARTUP_DIR") or os.path.join(
        base, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def shortcut_targets(install_dir):
    """返回 [(说明, 快捷方式路径)] —— 卸载时按这个清单逐个删。"""
    return [
        ("桌面快捷方式", os.path.join(desktop_dir(), APP_NAME + ".lnk")),
        ("开始菜单项", os.path.join(start_menu_dir(), APP_NAME + ".lnk")),
        ("开机启动项", os.path.join(startup_dir(), APP_NAME + ".lnk")),
    ]


# ================= 注册表（"应用和功能"里的卸载入口） =================
def register_uninstall(install_dir):
    ico = os.path.join(install_dir, ICO_NAME)
    unins = os.path.join(install_dir, UNINST_NAME)
    import datetime
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINST_KEY, 0,
                            winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ,
                          DISPLAY_VERSION)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "FloatDock")
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, ico)
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ,
                          install_dir + os.sep)
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                          '"%s"' % unins)
        winreg.SetValueEx(k, "QuietUninstallString", 0, winreg.REG_SZ,
                          '"%s" /S' % unins)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "InstallDate", 0, winreg.REG_SZ,
                          datetime.date.today().strftime("%Y%m%d"))
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD,
                          _dir_size_kb(install_dir))
        winreg.SetValueEx(k, "URLInfoAbout", 0, winreg.REG_SZ,
                          "本地应用（无网站）")


def unregister_uninstall():
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINST_KEY)
        return True
    except FileNotFoundError:
        return False


def uninstall_key_exists():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINST_KEY):
            return True
    except FileNotFoundError:
        return False


def _dir_size_kb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return max(1, total // 1024)


# ================= 进程与目录 =================
def kill_running_app():
    """结束正在运行的安装版浮坞（源码版跑的是 pythonw，不受影响）。

    用 image name 精确匹配 FloatDock.exe：安装目录里这个文件被占用时删不掉，
    必须先让它退出；而用户自己用 python 跑的浮坞进程名是 pythonw.exe，不会被误伤。
    """
    try:
        out = subprocess.run(["taskkill", "/IM", EXE_NAME, "/F"],
                             capture_output=True, text=True,
                             creationflags=_no_window())
        return "SUCCESS" in (out.stdout or "").upper()
    except Exception:
        return False


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def rmtree(path):
    """尽力删除整个目录树（只读文件也删），返回是否删干净。"""
    import shutil
    import stat

    def onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, onerror=onerror)
    return not os.path.exists(path)


def payload_dir():
    """安装源文件在哪：冻结后在程序包内，源码运行时用构建目录。"""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS"),
                            "payload")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "发布", "_build", "payload")


def install_dir_of_this_exe():
    """卸载程序自己所在的目录（就是安装目录）。"""
    return os.path.dirname(os.path.abspath(sys.executable))
