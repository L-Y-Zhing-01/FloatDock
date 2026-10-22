# -*- coding: utf-8 -*-
"""浮坞 FloatDock —— 启动入口。

用法：
    pythonw floatdock.pyw                     正常启动（或双击 启动浮坞.vbs）
    python  floatdock.pyw --debug             带调试输出运行
    python  floatdock.pyw --config D:\\fd.json 指定配置文件（便携/多套配置时用）
    python  floatdock.pyw --allow-multiple    允许多开（默认单实例）

代码结构（按依赖方向自下而上）：

    debug      调试输出开关
    winapi     Win32 绑定：DLL、常量、ctypes 签名
    wndutil    窗口查询与操作
    appicon    图标与品牌标识的唯一来源
    theme      配色、尺寸、几何计算
    hotkey     热键映射 / 校验 / 按键解析        config  配置读写
    absorb     跨进程窗口吸附引擎                tray    托盘图标 + 全局热键线程
    render     面板绘制与命中区                  picker  拖拽拾取器    settings  设置窗口
    hint       按钮悬停提示                      tip     赞赏窗        confirm   替换确认窗
    panel      主面板：状态机与事件编排
    floatdock.pyw（本文件）入口：参数 -> DPI -> 单实例 -> 启动
"""
import argparse
import ctypes
import os
import sys
from ctypes import wintypes as wt

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import appicon                                  # noqa: E402
import debug                                    # noqa: E402
import winapi                                   # noqa: E402

MUTEX_NAME = "FloatDock_SingleInstance_Mutex"
ERROR_ALREADY_EXISTS = 183


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="floatdock",
                                     description=appicon.APP_TITLE)
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    parser.add_argument("--config", metavar="PATH",
                        help="配置文件路径（默认：程序目录下的 config.json）")
    parser.add_argument("--allow-multiple", action="store_true",
                        help="允许同时运行多个实例")
    return parser.parse_args(argv)


def single_instance_ok():
    """用命名互斥体判断是否已有实例在跑。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = wt.HANDLE
    k32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
    k32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def warn_already_running():
    ctypes.windll.user32.MessageBoxW(
        0, "浮坞已在运行。\n可在系统托盘找到它（右键出菜单），"
           "或按你设定的全局快捷键切换显示。",
        appicon.APP_TITLE, 0x40)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.debug:
        debug.enable()

    # DPI 感知必须早于任何 GUI 库初始化，否则坐标会被系统缩放、吸附就会错位。
    # 因此 tkinter 相关的模块（panel 及其下游）都推迟到这一步之后再导入。
    winapi.enable_dpi_awareness()

    if not args.allow_multiple and not single_instance_ok():
        warn_already_running()
        return 1

    from config import Config
    from panel import FloatDock

    cfg_path = (os.path.abspath(args.config) if args.config
                else os.path.join(APP_DIR, "config.json"))
    FloatDock(Config(cfg_path)).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
