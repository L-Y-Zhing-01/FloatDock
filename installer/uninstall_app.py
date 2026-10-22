# -*- coding: utf-8 -*-
"""浮坞 FloatDock 卸载程序。

命令行：
    卸载程序.exe /S [/KEEPCONFIG]
  /S           静默卸载（不显示界面）
  /KEEPCONFIG  保留配置目录 %LOCALAPPDATA%\\FloatDock

自删除怎么做的：
  卸载程序自己就躺在安装目录里，Windows 不允许删掉正在运行的文件。所以真正
  干活的那一份会被复制到临时目录再启动（带 FD_UNINST_TEMP 标记），临时的那份
  清完安装目录后，再让一个 cmd 等它退出、删掉目录与自己的临时副本。原目录里
  的这一个只负责"转发 + 退出"。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(          # 源码直跑时也能找到根目录的模块
    os.path.dirname(os.path.abspath(__file__))))

import shortcut as S

APP_TITLE = "%s 卸载程序" % S.APP_NAME
LOG_PATH = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                        "FloatDock-uninstall.log")


def log(text):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), text)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def parse_args(argv):
    opts = {"silent": False, "keep_config": False, "cleanup": False,
            "target": None}
    argv = list(argv)
    for i, a in enumerate(argv):
        low = a.lower()
        if low == "/s":
            opts["silent"] = True
        elif low in ("/keepconfig", "/keep"):
            opts["keep_config"] = True
        elif low == "/cleanup":
            opts["cleanup"] = True
            if i + 1 < len(argv):
                opts["target"] = argv[i + 1]
    return opts


# ================= 卸载动作 =================
def do_uninstall(install_dir, keep_config, progress=None):
    """删除快捷方式、注册表项、安装目录。返回 (是否成功, 消息)。"""

    def step(pct, text):
        log(text)
        if progress:
            progress(pct, text)

    step(5, "结束正在运行的浮坞…")
    S.kill_running_app()
    time.sleep(0.8)

    step(25, "删除快捷方式…")
    for label, path in S.shortcut_targets(install_dir):
        try:
            if os.path.exists(path):
                os.remove(path)
                log("已删除%s：%s" % (label, path))
        except OSError as e:
            log("删除%s失败：%s" % (label, e))

    step(45, "移除卸载信息…")
    try:
        S.unregister_uninstall()
    except OSError as e:
        log("移除注册表项失败：%s" % e)

    if not keep_config:
        step(60, "删除配置与设置…")
        try:
            if os.path.isdir(S.config_dir()):
                S.rmtree(S.config_dir())
                log("已删除配置目录：%s" % S.config_dir())
        except OSError as e:
            log("删除配置目录失败：%s" % e)
    else:
        log("按你的选择保留了配置：%s" % S.config_dir())

    step(75, "删除程序文件…")
    # 临时目录里的那一份负责清安装目录；安装目录里的这一份只转发
    here = os.path.dirname(os.path.abspath(sys.executable))
    if os.path.normcase(here) != os.path.normcase(install_dir):
        log("从临时副本执行清理：%s" % install_dir)

    leftover = []
    for name in sorted(os.listdir(install_dir)) if os.path.isdir(install_dir) else []:
        path = os.path.join(install_dir, name)
        try:
            if os.path.isdir(path):
                if not S.rmtree(path):
                    leftover.append(name)
            else:
                os.remove(path)
        except OSError as e:
            log("删除 %s 失败：%s" % (name, e))
            leftover.append(name)

    step(92, "收尾…")
    if leftover:
        # 正在运行的就是自己（卸载程序），交给 cmd 等我们退出后再删
        schedule_self_delete(install_dir, here)
        return True, ("程序文件已删除，但下面这些被占用、会在几秒后自动清掉：\n"
                      + "、".join(leftover))
    if not os.path.isdir(install_dir) or not os.listdir(install_dir):
        try:
            os.rmdir(install_dir)
        except OSError:
            schedule_self_delete(install_dir, here)
    step(100, "卸载完成")
    return True, install_dir


def schedule_self_delete(install_dir, exe_dir):
    """让一个批处理在本进程退出后删掉安装目录（和临时目录里的自己）。

    为什么用批处理而不是一条 cmd 命令：卸载程序自己就占着安装目录里的一个文件，
    必须先等它解锁。批处理里"只要文件还在就等一秒再删"的重试循环，比靠 ping
    计时靠谱得多 —— 实测单条 `ping -n 3 & rmdir` 会跑得太早，rmdir 直接失败退出，
    目录和 exe 就永远留下来了。
    """
    exe = os.path.join(install_dir, S.UNINST_NAME)
    tmp_exe = sys.executable
    same_dir = os.path.normcase(exe_dir) == os.path.normcase(install_dir)
    bat = os.path.join(tempfile.gettempdir(),
                       "FloatDock-清理-%d.bat" % os.getpid())
    lines = [
        "@echo off",
        "setlocal",
        "set /a n=0",
        ":wait",
        'if not exist "%s" goto clean' % exe,
        "set /a n+=1",
        "if %n% gtr 40 goto clean",
        "ping -n 2 127.0.0.1 >nul",
        'del /f /q "%s" >nul 2>nul' % exe,
        "goto wait",
        ":clean",
        'rmdir /s /q "%s" >nul 2>nul' % install_dir,
    ]
    if not same_dir:
        lines.append('del /f /q "%s" >nul 2>nul' % tmp_exe)
    lines.append('del /f /q "%~f0" >nul 2>nul')
    try:
        with open(bat, "w", encoding="gbk", errors="replace") as f:
            f.write("\r\n".join(lines) + "\r\n")
    except OSError as e:
        log("写清理脚本失败：%s" % e)
        return False
    log("已安排退出后清理：%s" % bat)
    try:
        subprocess.Popen(["cmd", "/c", bat], close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                               0))
        return True
    except OSError as e:
        log("安排清理失败：%s" % e)
        return False


def relaunch_from_temp(argv):
    """把自己复制到临时目录并用 FD_UNINST_TEMP 标记重启，返回 True 表示已接管。"""
    if os.environ.get("FD_UNINST_TEMP"):
        return False
    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    tmp_exe = os.path.join(tempfile.gettempdir(),
                           "FloatDock-卸载-%d.exe" % os.getpid())
    try:
        shutil.copy2(sys.executable, tmp_exe)
    except OSError as e:
        log("无法复制到临时目录（改为原地卸载）：%s" % e)
        return False
    env = dict(os.environ, FD_UNINST_TEMP="1")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    cmd = [tmp_exe, "--target-dir", install_dir] + list(argv)
    log("已切换到临时副本执行：%s" % tmp_exe)
    try:
        subprocess.Popen(cmd, env=env, close_fds=True, creationflags=flags)
        return True
    except OSError as e:
        log("启动临时副本失败（改为原地卸载）：%s" % e)
        return False


# ================= 界面 =================
class Remover(object):
    def __init__(self, opts):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk, self.opts = tk, ttk, opts
        self.done = False
        self.install_dir = opts["target"] or S.install_dir_of_this_exe()

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.resizable(False, False)
        self.root.configure(bg="#ffffff")
        self._icon()
        self._center(460, 250)

        self.body = ttk.Frame(self.root, padding=18)
        self.body.pack(fill="both", expand=True)
        self._page_confirm()

    def _icon(self):
        # 同 setup_app：走 appicon.apply，不走 Tk 的 iconbitmap（会把 16×16
        # 条目放大成糊图）。运行位置可能是临时副本，所以先找真正的安装目录。
        import appicon
        chosen = None
        for cand in (os.path.join(self.install_dir, S.ICO_NAME),
                     os.path.join(S.install_dir_of_this_exe(), S.ICO_NAME),
                     os.path.join(S.config_dir(), S.ICO_NAME)):
            if os.path.exists(cand):
                chosen = cand
                appicon.PATH = cand
                break
        ok = appicon.apply(self.root)
        log("图标：PATH=%s（存在=%s）apply=%s 挂到=%s"
            % (chosen, chosen is not None, ok, appicon.mounted_classes()))

    def _center(self, w, h):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2,
                                            max(0, (sh - h) // 2 - 40)))

    def _clear(self):
        for c in self.body.winfo_children():
            c.destroy()

    def _page_confirm(self):
        tk, ttk = self.tk, self.ttk
        self._clear()
        ttk.Label(self.body, text="卸载 %s" % S.APP_NAME,
                  font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        ttk.Label(self.body, text="安装位置：\n%s\n\n"
                                  "将删除程序文件、快捷方式与卸载入口。"
                                  % self.install_dir,
                  foreground="#5a6270", wraplength=420,
                  justify="left").pack(anchor="w", pady=(10, 0))
        self.var_keep = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="保留我的设置（位置 / 透明度 / 快捷键）",
                        variable=self.var_keep).pack(anchor="w", pady=(12, 0))
        foot = ttk.Frame(self.body)
        foot.pack(fill="x", side="bottom", pady=(16, 0))
        ttk.Button(foot, text="取消", width=10,
                   command=self.root.destroy).pack(side="right")
        ttk.Button(foot, text="卸载", width=10,
                   command=self._start).pack(side="right", padx=(0, 8))

    def _page_progress(self):
        ttk, tk = self.ttk, self.tk
        self._clear()
        ttk.Label(self.body, text="正在卸载…",
                  font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        self.var_line = tk.StringVar(value="准备中…")
        ttk.Label(self.body, textvariable=self.var_line,
                  foreground="#5a6270").pack(anchor="w", pady=(10, 6))
        self.bar = ttk.Progressbar(self.body, mode="determinate", maximum=100)
        self.bar.pack(fill="x")

    def _progress_cb(self, pct, text):
        try:
            self.bar["value"] = pct
            self.var_line.set(text)
            self.root.update()
        except Exception:
            pass

    def _start(self):
        self.opts["keep_config"] = self.var_keep.get()
        self._page_progress()
        ok, message = do_uninstall(self.install_dir, self.opts["keep_config"],
                                   progress=self._progress_cb)
        from tkinter import messagebox
        if ok:
            messagebox.showinfo(APP_TITLE,
                                "浮坞已卸载。\n\n%s" % message, parent=self.root)
            self.done = True
        else:
            messagebox.showerror(APP_TITLE, message, parent=self.root)
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        return self.done


def main():
    opts = parse_args(sys.argv[1:])
    log("参数：%s" % opts)
    # 静默卸载直接从安装目录执行（自己删不掉自己，交给 cmd 收尾）
    if opts["silent"]:
        ok, message = do_uninstall(opts["target"] or S.install_dir_of_this_exe(),
                                   opts["keep_config"])
        log("静默卸载结果：%s" % ("成功" if ok else "失败 - %s" % message))
        return 0 if ok else 1
    # 图形卸载：先把自己挪到临时目录，免得"删掉自己所在的目录"这件事做不干净
    if relaunch_from_temp(sys.argv[1:]):
        return 0
    if "--target-dir" in sys.argv:
        i = sys.argv.index("--target-dir")
        if i + 1 < len(sys.argv):
            opts["target"] = sys.argv[i + 1]
    return 0 if Remover(opts).run() else 1


if __name__ == "__main__":
    sys.exit(main())
