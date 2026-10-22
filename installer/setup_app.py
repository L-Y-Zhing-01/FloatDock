# -*- coding: utf-8 -*-
"""浮坞 FloatDock 图形安装程序。

命令行长这样（给脚本化安装/自动化测试用）：
    安装程序.exe /S [/D=C:\\路径] [/NODESKTOP] [/NOSTARTUP] [/AUTORUN]
  /S          静默安装，不显示界面
  /D=路径     指定安装目录（必须放最后，路径可以带空格但不要加引号）
  /NODESKTOP  不建桌面快捷方式
  /NOSTARTUP  不建开始菜单项、不建开机启动项
  /AUTORUN    装完立即启动浮坞

设计取舍：
  · 默认装到 %LOCALAPPDATA%\\Programs\\FloatDock —— 当前用户可写，不需要管理员，
    也不会因为装到 Program Files 而写不了配置；
  · 配置固定放 %LOCALAPPDATA%\\FloatDock\\config.json，由快捷方式的 --config 指定，
    所以用户就算把程序装到别处，状态也总能存下来；
  · 快捷方式图标与卸载程序图标一律用安装目录里的 floatdock.ico（用户要求统一）。
"""
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(          # 源码直跑时也能找到根目录的模块
    os.path.dirname(os.path.abspath(__file__))))

import shortcut as S

APP_TITLE = "%s %s" % (S.APP_NAME, S.DISPLAY_VERSION)
LOG_PATH = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                        "FloatDock-setup.log")

_log_file = None


def log(text):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), text)
    global _log_file
    if _log_file is None:
        try:
            _log_file = open(LOG_PATH, "w", encoding="utf-8")
        except OSError:
            _log_file = False
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()
    try:
        print(line, flush=True)
    except Exception:
        pass


# ================= 参数 =================
def parse_args(argv):
    opts = {"silent": False, "dir": None, "desktop": True, "startup": True,
            "autorun": False, "keep_config": False}
    for a in argv:
        low = a.lower()
        if low == "/s":
            opts["silent"] = True
        elif low.startswith("/d="):
            opts["dir"] = a[3:].strip('"')
        elif low == "/nodesktop":
            opts["desktop"] = False
        elif low == "/nostartup":
            opts["startup"] = False
        elif low == "/autorun":
            opts["autorun"] = True
        elif low in ("/keepconfig", "/keep"):
            opts["keep_config"] = True
    return opts


# ================= 安装动作（界面与静默共用） =================
def do_install(install_dir, opts, progress=None, ask=None):
    """执行安装。progress(percent, text) 与 ask(问题)->bool 都由界面传入。

    返回 (是否成功, 消息)。任何一步失败都如实报告，不假装成功。
    """
    src = S.payload_dir()
    log("安装源：%s" % src)
    log("安装到：%s" % install_dir)
    if not os.path.isdir(os.path.join(src, "app")):
        return False, "安装包内容不完整：找不到 %s" % os.path.join(src, "app")

    def step(pct, text):
        log(text)
        if progress:
            progress(pct, text)

    # 1. 已装过就当作升级：先让旧版本退出
    existed = os.path.exists(os.path.join(install_dir, S.EXE_NAME))
    if existed:
        step(4, "检测到已安装的版本，正在结束它在运行的进程…")
        S.kill_running_app()
        time.sleep(0.6)
        if ask and not ask("检测到 %s 已安装。\n继续将覆盖安装并保留你的设置，是否继续？"
                           % S.APP_NAME):
            return False, "已取消"
        step(8, "清理旧版本文件…")
        for name in os.listdir(install_dir):
            path = os.path.join(install_dir, name)
            if os.path.isdir(path):
                S.rmtree(path)
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass

    # 2. 铺开程序文件
    try:
        os.makedirs(install_dir, exist_ok=True)
    except OSError as e:
        return False, "无法创建安装目录：%s\n%s" % (install_dir, e)
    if not os.access(install_dir, os.W_OK):
        return False, "这个位置没有写入权限：%s\n请换一个目录（例如我的文档下）。" % install_dir

    step(20, "正在安装程序文件…")
    try:
        shutil.copytree(os.path.join(src, "app"), install_dir,
                        dirs_exist_ok=True)
    except OSError as e:
        return False, "复制程序文件失败：%s" % e

    step(62, "正在安装卸载程序与说明文档…")
    for name in (S.ICO_NAME, S.DOC_NAME):
        try:
            shutil.copy2(os.path.join(src, name), os.path.join(install_dir, name))
        except OSError as e:
            return False, "复制 %s 失败：%s" % (name, e)
    try:
        shutil.copy2(os.path.join(src, S.UNINST_NAME),
                     os.path.join(install_dir, S.UNINST_NAME))
    except OSError as e:
        return False, "安装卸载程序失败：%s" % e

    # 3. 配置目录（配置放用户目录，装到只读位置也能保存）
    step(72, "准备配置目录…")
    os.makedirs(S.config_dir(), exist_ok=True)

    # 4. 快捷方式
    exe = os.path.join(install_dir, S.EXE_NAME)
    ico = os.path.join(install_dir, S.ICO_NAME)
    made = []
    try:
        if opts["desktop"]:
            step(80, "创建桌面快捷方式…")
            S.create_shortcut(os.path.join(S.desktop_dir(), S.APP_NAME + ".lnk"),
                              exe, S.launch_args(), install_dir, ico,
                              "悬浮窗口容器：把任意窗口收进面板继续用")
            made.append("桌面")
        if opts["startup"]:
            step(85, "创建开始菜单项…")
            S.create_shortcut(os.path.join(S.start_menu_dir(),
                                           S.APP_NAME + ".lnk"),
                              exe, S.launch_args(), install_dir, ico,
                              "悬浮窗口容器")
            made.append("开始菜单")
    except OSError as e:
        return False, "创建快捷方式失败：%s" % e

    # 5. 注册卸载信息
    step(92, "写入卸载信息…")
    try:
        S.register_uninstall(install_dir)
    except OSError as e:
        return False, "写入卸载信息失败：%s" % e

    step(100, "安装完成")
    log("快捷方式：%s" % ("、".join(made) if made else "未创建"))
    return True, install_dir


def launch(install_dir):
    exe = os.path.join(install_dir, S.EXE_NAME)
    args = [exe] + S.launch_args().replace('"', "").split()
    try:
        subprocess.Popen(args, cwd=install_dir, close_fds=True)
        log("已启动：%s" % exe)
        return True
    except OSError as e:
        log("启动失败：%s" % e)
        return False


# ================= 图形界面 =================
class Wizard(object):
    """一页流：选项 → 进度 → 完成。刻意做得朴素，安装程序不该抢戏。"""

    def __init__(self, opts):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.opts = opts
        self.ok = False
        self.install_dir = opts["dir"] or S.default_install_dir()

        self.root = tk.Tk()
        self.root.title("%s 安装程序" % APP_TITLE)
        self.root.resizable(False, False)
        self.root.configure(bg="#ffffff")
        self._icon()
        self._center(560, 396)

        self.body = ttk.Frame(self.root, padding=18)
        self.body.pack(fill="both", expand=True)
        self._page_options()

    def _icon(self):
        # 不用 Tk 自带的 iconbitmap：它把 .ico 里第一个条目（16×16）当成唯一
        # 图标再放大，任务栏里就是一张糊图。appicon.apply 与主程序同源。
        import appicon
        chosen = None
        for cand in (os.path.join(S.payload_dir(), S.ICO_NAME),
                     os.path.join(S.install_dir_of_this_exe(), S.ICO_NAME)):
            if os.path.exists(cand):
                chosen = cand
                appicon.PATH = cand
                break
        ok = appicon.apply(self.root)
        log("图标：PATH=%s（存在=%s）apply=%s 挂到=%s"
            % (chosen, chosen is not None, ok, appicon.mounted_classes()))

    def _center(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2,
                                            max(0, (sh - h) // 2 - 40)))

    def _clear(self):
        for child in self.body.winfo_children():
            child.destroy()

    # ---- 第一页：选项 ----
    def _page_options(self):
        tk, ttk = self.tk, self.ttk
        self._clear()
        head = ttk.Frame(self.body)
        head.pack(fill="x")
        ttk.Label(head, text=S.APP_NAME, font=("Microsoft YaHei UI", 15, "bold")
                  ).pack(anchor="w")
        ttk.Label(head, text="版本 %s · 悬浮窗口容器：鼠标移开自动隐藏，"
                             "把任意窗口收进面板继续用" % S.DISPLAY_VERSION,
                  foreground="#5a6270").pack(anchor="w", pady=(2, 0))
        ttk.Separator(self.body).pack(fill="x", pady=12)

        ttk.Label(self.body, text="安装位置").pack(anchor="w")
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(4, 0))
        self.var_dir = tk.StringVar(value=self.install_dir)
        ttk.Entry(row, textvariable=self.var_dir).pack(side="left", fill="x",
                                                       expand=True)
        ttk.Button(row, text="浏览…", width=8, command=self._browse
                   ).pack(side="left", padx=(6, 0))

        self.var_desktop = tk.BooleanVar(value=True)
        self.var_start = tk.BooleanVar(value=True)
        self.var_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.body, text="创建桌面快捷方式",
                        variable=self.var_desktop).pack(anchor="w", pady=(14, 0))
        ttk.Checkbutton(self.body, text="在开始菜单中创建快捷方式",
                        variable=self.var_start).pack(anchor="w")
        ttk.Checkbutton(self.body, text="开机时自动启动浮坞",
                        variable=self.var_auto).pack(anchor="w")

        ttk.Label(self.body,
                  text="设置（位置 / 透明度 / 快捷键）保存在 %s" % S.config_dir(),
                  foreground="#5a6270", wraplength=500).pack(anchor="w",
                                                            pady=(14, 0))
        # 许可与来源：安装页是用户唯一会认真看一眼的地方，放这里比塞进说明文档有用。
        # 不写完整 URL —— 许可全文与源码地址随安装目录的 LICENSE / NOTICE 一起交付。
        ttk.Label(self.body,
                  text="代码以 MIT 许可发布，图标、赞赏码与名称另附条款；"
                       "许可全文与源码地址见装好后的 LICENSE / NOTICE",
                  foreground="#8a919c", wraplength=500).pack(anchor="w",
                                                              pady=(6, 0))
        foot = ttk.Frame(self.body)
        foot.pack(fill="x", side="bottom", pady=(14, 0))
        ttk.Button(foot, text="取消", width=10,
                   command=self.root.destroy).pack(side="right")
        self.btn_go = ttk.Button(foot, text="安装", width=10,
                                 command=self._start)
        self.btn_go.pack(side="right", padx=(0, 8))
        self.root.bind("<Return>", lambda _e: self._start())
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

    def _browse(self):
        from tkinter import filedialog
        chosen = filedialog.askdirectory(title="选择安装位置",
                                         initialdir=self.var_dir.get())
        if chosen:
            self.var_dir.set(os.path.normpath(chosen))

    # ---- 第二页：进度 ----
    def _page_progress(self):
        ttk, tk = self.ttk, self.tk
        self._clear()
        ttk.Label(self.body, text="正在安装…",
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

    def _ask(self, question):
        from tkinter import messagebox
        return messagebox.askyesno(APP_TITLE, question, parent=self.root)

    # ---- 第三页：完成 ----
    def _page_done(self, install_dir):
        tk, ttk = self.tk, self.ttk
        self._clear()
        ttk.Label(self.body, text="安装完成",
                  font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        ttk.Label(self.body,
                  text="浮坞已装到：\n%s\n\n"
                       "启动方式：桌面快捷方式 / 开始菜单，或直接双击 %s。\n"
                       "退出：面板标题栏 ✕，或右键托盘图标 →「退出浮坞」。\n"
                       "卸载：开始菜单或「设置 → 应用 → 已安装的应用」里的「%s」。"
                       % (install_dir, S.EXE_NAME, S.APP_NAME),
                  foreground="#3c444a", justify="left",
                  wraplength=500).pack(anchor="w", pady=(10, 0))
        self.var_run = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.body, text="立即运行浮坞",
                        variable=self.var_run).pack(anchor="w", pady=(16, 0))
        foot = ttk.Frame(self.body)
        foot.pack(fill="x", side="bottom", pady=(14, 0))
        ttk.Button(foot, text="完成", width=10, command=self._finish
                   ).pack(side="right")

    def _finish(self):
        if getattr(self, "var_run", None) and self.var_run.get():
            launch(self.install_dir)
        self.ok = True
        self.root.destroy()

    # ---- 流程 ----
    def _start(self):
        for w in (self.btn_go,):
            try:
                w.state(["disabled"])
            except Exception:
                w.configure(state="disabled")
        self.install_dir = os.path.normpath(self.var_dir.get().strip())
        self.opts["desktop"] = self.var_desktop.get()
        self.opts["startup"] = self.var_start.get()
        self._page_progress()
        ok, message = do_install(self.install_dir, self.opts,
                                 progress=self._progress_cb, ask=self._ask)
        if not ok:
            from tkinter import messagebox
            messagebox.showerror(APP_TITLE, message, parent=self.root)
            self._page_options()
            return
        # 开机启动单独处理：它不放在安装目录的快捷方式清单里
        if self.var_auto.get():
            try:
                S.create_shortcut(os.path.join(S.startup_dir(),
                                               S.APP_NAME + ".lnk"),
                                  os.path.join(self.install_dir, S.EXE_NAME),
                                  S.launch_args(), self.install_dir,
                                  os.path.join(self.install_dir, S.ICO_NAME),
                                  "开机自动启动浮坞")
                log("已创建开机启动项")
            except OSError as e:
                log("创建开机启动项失败：%s" % e)
        self._page_done(message)

    def run(self):
        self.root.mainloop()
        return self.ok


def main():
    opts = parse_args(sys.argv[1:])
    log("参数：%s" % opts)
    if opts["silent"]:
        ok, message = do_install(opts["dir"] or S.default_install_dir(), opts)
        log("静默安装结果：%s" % ("成功" if ok else "失败 - %s" % message))
        if ok and opts["autorun"]:
            launch(message)
        return 0 if ok else 1
    return 0 if Wizard(opts).run() else 1


if __name__ == "__main__":
    sys.exit(main())
