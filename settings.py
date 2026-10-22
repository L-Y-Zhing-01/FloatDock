# -*- coding: utf-8 -*-
"""设置窗口：呼出热键（按键捕获式）与"鼠标移开后隐藏"的灵敏度。

与主面板只通过回调耦合，自己不认识面板的任何内部状态：
    hooks.apply_hotkey(spec)   提交新热键，由面板转给托盘线程注册
    hooks.delay_changed(秒)    隐藏延迟变化
    hooks.closed()             窗口已关闭，面板据此恢复自动隐藏并重绘

按键框为什么是"捕获式"而不是让用户手打：F1–F12 是功能键，不产生字符
（event.char 为空），普通 Entry 的默认绑定根本不会写入 —— 用户按下去
毫无反应。所以改成只读输入框 + 按键捕获：点一下，直接按下想用的组合键。

布局一律用 grid + 权重（sticky="ew"）铺满一行，宽度由窗口决定：
    · 说明文字没有固定 wraplength，跟着窗口宽度重新折行；
    · 灵敏度滑块没有固定 length，占满它所在那一行剩下的宽度；
    · 窗口自然尺寸就是最小尺寸（minsize），拖大只多给空间、不会撑坏版式。

本窗口的标题栏/任务栏图标由 appicon 挂在窗口类上，这里不用管。
"""
import tkinter as tk
from collections import namedtuple

import appicon
import hotkey
import theme as T
from config import HIDE_DELAY_MIN, HIDE_DELAY_MAX
from debug import dbg

Hooks = namedtuple("Hooks", "apply_hotkey delay_changed closed")

PAD = 14                          # 左右留白
INITIAL_WRAP = 420                # 首次测量用的折行宽度，之后由实际宽度接管

_F12_NOTE = ("F12 被 Windows 保留给调试器，单独注册通常失败，"
             "建议改用 F1–F11（或给 F12 加一个修饰键）")


class SettingsDialog(object):
    """设置窗口。构造即打开；关掉之后实例不再复用。"""

    def __init__(self, parent, panel_rect, spec, label, hide_delay, hooks,
                 about=None):
        self.hooks = hooks
        self.hide_delay = hide_delay
        self._about = about                 # 「许可与来源」入口；None 则不显示
        self._panel_rect = panel_rect      # (x, y, w)，用于把窗口贴在面板旁边
        self._spec = dict(spec)
        self._label = label
        self._mods = {}                    # flag -> BooleanVar
        self._hints = []                   # 需要随窗口宽度重新折行的说明文字
        self._hint = None                  # 热键状态提示行
        self._key_entry = None
        self._delay_txt = None
        self._ready = False                # 构建期间抑制滑块回调

        d = tk.Toplevel(parent)
        self.window = d
        d.title(appicon.settings_title())
        d.configure(bg=T.C_BG)
        d.attributes("-topmost", True)
        d.columnconfigure(0, weight=1)     # 唯一一列吃掉整行宽度
        d.protocol("WM_DELETE_WINDOW", self.close)
        self._build_hide_delay(d, self._build_hotkey(d, 0))
        d.bind("<Configure>", self._on_resize)
        self._place()
        self._ready = True

    @property
    def is_open(self):
        if self.window is None:
            return False
        try:
            return bool(self.window.winfo_exists())
        except Exception:
            return False

    # ================= 构建 =================
    def _build_hotkey(self, d, row):
        """呼出/隐藏快捷键：修饰键勾选框、捕获式按键框、应用按钮与提示行。

        返回下一段该用的行号 —— grid 行号由各段接力传递，不写死、也不靠
        往 self 上挂一个中间量。
        """
        row = _section(d, row, "呼出 / 隐藏 快捷键")
        self._build_mods_row(d, row)
        row += 1
        self._build_key_row(d, row)
        row += 1
        self._build_hotkey_buttons(d, row)
        row += 1
        for text in (
            "点上面的「按键」框后直接按下组合键。功能键可单独使用："
            "点「清空修饰键」再按 F1–F11（或 F13–F24）即可，无需任何修饰键。",
            "单独使用的功能键会被浮坞独占，其他程序将收不到该键；"
            "字母 / 数字 / 小键盘必须搭配至少一个修饰键，否则打字时会误触发。",
            "全局热键在任何程序处于前台时都能唤出浮坞。若该组合已被其他软件"
            "占用，会提示失败并保留原快捷键。",
        ):
            row = _hint(d, row, text, self._hints)
        return row

    def _build_mods_row(self, d, row):
        """修饰键勾选框行；勾选状态写入 self._mods。"""
        box = tk.Frame(d, bg=T.C_BG)
        box.grid(row=row, column=0, sticky="w", padx=PAD, pady=(2, 6))
        for flag, name in hotkey.MOD_NAMES:
            var = tk.BooleanVar(master=d, value=bool(self._spec.get(flag)))
            self._mods[flag] = var
            tk.Checkbutton(box, text=name, variable=var, bg=T.C_BG, fg=T.C_FG,
                           selectcolor=T.C_BAR, activebackground=T.C_BG,
                           activeforeground=T.C_FG, highlightthickness=0, bd=0,
                           font=(T.FONT, -11)).pack(side="left", padx=(0, 12))

    def _build_key_row(self, d, row):
        """捕获式按键框：只读 Entry，聚焦时高亮，按下组合键即记录。"""
        box = tk.Frame(d, bg=T.C_BG)
        box.grid(row=row, column=0, sticky="ew", padx=PAD)
        tk.Label(box, text="按键：", bg=T.C_BG, fg=T.C_FG,
                 font=(T.FONT, -11)).pack(side="left")
        self._key_entry = tk.Entry(box, width=10, bg=T.C_BAR, fg=T.C_FG,
                                   insertbackground=T.C_FG, relief="flat",
                                   justify="center", state="readonly",
                                   readonlybackground=T.C_BAR,
                                   font=(T.FONT, -11, "bold"))
        self._key_entry.pack(side="left", padx=(6, 0), ipady=3)
        self._set_key_text(self._spec.get("key", "D"))
        self._key_entry.bind("<KeyPress>", self._key_capture)
        self._key_entry.bind("<Return>", self._key_enter)
        # readonly 状态下背景由 readonlybackground 决定，改 bg 是无效的
        self._key_entry.bind("<FocusIn>", lambda _e: self._key_entry.configure(
            readonlybackground=T.C_BAR2))
        self._key_entry.bind("<FocusOut>", lambda _e: self._key_entry.configure(
            readonlybackground=T.C_BAR))

    def _build_hotkey_buttons(self, d, row):
        """应用 / 清空按钮，以及显示当前热键的提示行（占满剩余宽度）。"""
        box = tk.Frame(d, bg=T.C_BG)
        box.grid(row=row, column=0, sticky="ew", padx=PAD, pady=(10, 0))
        box.columnconfigure(0, weight=1)
        buttons = tk.Frame(box, bg=T.C_BG)
        buttons.grid(row=0, column=0, sticky="w")
        tk.Button(buttons, text="应用快捷键", command=self._apply_hotkey,
                  bg=T.C_ACC, fg=T.C_ON_ACC, activebackground=T.C_ACC,
                  activeforeground=T.C_ON_ACC, relief="flat", bd=0, padx=12,
                  font=(T.FONT, -11, "bold")).pack(side="left")
        tk.Button(buttons, text="清空修饰键", command=self._clear_mods,
                  bg=T.C_BAR2, fg=T.C_FG, activebackground=T.C_BAR,
                  activeforeground=T.C_FG, relief="flat", bd=0, padx=10,
                  font=(T.FONT, -10)).pack(side="left", padx=(8, 0))
        self._hint = tk.Label(box, text="当前：%s" % self._label,
                              bg=T.C_BG, fg=T.C_DIM, font=(T.FONT, -10),
                              anchor="w")
        self._hint.grid(row=0, column=1, sticky="ew", padx=(10, 0))

    def _build_hide_delay(self, d, row):
        """鼠标移开后隐藏：延迟滑块、数值回显与关闭按钮。"""
        row = _section(d, row, "鼠标移开后隐藏")
        box = tk.Frame(d, bg=T.C_BG)
        box.grid(row=row, column=0, sticky="ew", padx=PAD)
        box.columnconfigure(0, weight=1)       # 滑块吃掉除读数以外的全部宽度
        self._delay_var = tk.DoubleVar(master=d, value=self.hide_delay)
        tk.Scale(box, from_=HIDE_DELAY_MIN, to=HIDE_DELAY_MAX, resolution=0.01,
                 orient="horizontal", bg=T.C_BG, fg=T.C_FG,
                 troughcolor=T.C_BAR, highlightthickness=0, bd=0,
                 activebackground=T.C_ACC, showvalue=0, font=(T.FONT, -9),
                 variable=self._delay_var,
                 command=self._on_delay_changed).grid(row=0, column=0,
                                                      sticky="ew")
        self._delay_txt = tk.Label(box, text="%.2f 秒" % self.hide_delay,
                                   bg=T.C_BG, fg=T.C_FG, font=(T.FONT, -11),
                                   anchor="w")
        self._delay_txt.grid(row=0, column=1, padx=(8, 0), sticky="w")
        row += 1
        row = _hint(d, row,
                    "默认 0.05 秒。实测总耗时（含 20ms 轮询开销）约 60–90ms，"
                    "均在 0.1 秒内。调小更灵敏，调大更适合慢慢移动鼠标的场景。",
                    self._hints)

        box2 = tk.Frame(d, bg=T.C_BG)
        box2.grid(row=row, column=0, sticky="ew", padx=PAD, pady=(16, 16))
        box2.columnconfigure(1, weight=1)
        tk.Button(box2, text="关闭", command=self.close, bg=T.C_BAR2,
                  fg=T.C_FG, activebackground=T.C_BAR, activeforeground=T.C_FG,
                  relief="flat", bd=0, padx=16,
                  font=(T.FONT, -11)).grid(row=0, column=0, sticky="w")
        tk.Label(box2, text="本窗口打开期间浮坞不会自动隐藏", bg=T.C_BG,
                 fg=T.C_DIM, font=(T.FONT, -9), anchor="w").grid(
            row=0, column=1, sticky="ew", padx=(10, 0))
        if self._about is not None:
            # 版本、许可、源码地址、反馈邮箱都在这个入口后面，与托盘「关于」同一个窗
            tk.Button(box2, text="许可与来源…", command=self._about,
                      bg=T.C_BAR2, fg=T.C_DIM, activebackground=T.C_BAR,
                      activeforeground=T.C_FG, relief="flat", bd=0, padx=10,
                      font=(T.FONT, -9)).grid(row=0, column=2, sticky="e")

    def _place(self):
        """把窗口贴在面板旁边（默认会飘到屏幕左上，离面板很远）并拿到键盘焦点。"""
        d = self.window
        px, py, pw = self._panel_rect
        try:
            # 两趟：先量自然宽度据此定折行宽度，再量一次得到最终尺寸。
            # 于是"窗口多宽、文字就折多宽"，不需要预设一个固定值。
            d.update_idletasks()
            self._wrap_to(d.winfo_reqwidth())
            d.update_idletasks()
            dw, dh = d.winfo_reqwidth(), d.winfo_reqheight()
            d.minsize(dw, dh)              # 自然尺寸即下限，再小就只剩裁字
            sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
            x = px + pw + 12
            if x + dw > sw - 8:
                x = px - dw - 12
            x = max(8, min(x, max(8, sw - dw - 8)))
            y = max(8, min(py, max(8, sh - dh - 56)))
            d.geometry("+%d+%d" % (x, y))
        except Exception as e:
            dbg("设置窗口定位失败", e)
        d.lift()
        try:
            # 必须把键盘焦点真正交给这个窗口：只调 focus_set 的话，
            # 反复开关设置窗口会出现"窗口看得见但按什么都没反应"。
            d.focus_force()
            self._key_entry.focus_set()
        except Exception as e:
            dbg("设置窗口聚焦失败", e)

    def _wrap_to(self, width):
        """把说明文字的折行宽度对齐到窗口当前宽度（内容区宽度 = 窗宽 - 两侧留白）。"""
        wrap = max(240, width - 2 * PAD)
        for label in self._hints:
            if int(label.cget("wraplength") or 0) != wrap:
                label.configure(wraplength=wrap)

    def _on_resize(self, event):
        if event.widget is self.window:
            self._wrap_to(event.width)

    # ================= 对外 =================
    def close(self):
        if self.window is None:
            return
        if self.is_open:
            try:
                self.window.destroy()
            except Exception:
                pass
        self.window = None
        self.hooks.closed()

    def show_hotkey_result(self, ok, text):
        """托盘线程注册完热键后，把结果写回提示行。"""
        if not self.is_open:
            return
        try:
            self._hint.configure(text=("已生效：" + text) if ok else text,
                                 fg=T.C_ACC if ok else T.C_DANGER)
        except Exception:
            pass

    # ================= 热键输入 =================
    def _set_key_text(self, text):
        entry = self._key_entry
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, text)
        entry.configure(state="readonly")

    def _key_enter(self, _e):
        """回车 = 点「应用快捷键」。

        Tk 在同一级只跑最具体的那个绑定，所以这里不会和 <KeyPress> 捕获重复触发。
        """
        self._apply_hotkey()
        return "break"

    def _key_capture(self, e):
        """按键框里按下任意键：修饰键同步勾选框，主键写入并给下一步提示。"""
        vk = int(getattr(e, "keycode", 0) or 0)
        mod = hotkey.mod_of(vk, e.keysym)
        if mod is not None:
            self._mods[mod].set(True)
            self._hint.configure(text="已按下 %s，继续按主键" % mod.upper(),
                                 fg=T.C_DIM)
            dbg("捕获修饰键 vk=%d keysym=%s -> %s" % (vk, e.keysym, mod))
            return "break"
        if e.keysym == "Tab":
            return None                     # 放行，保留键盘在控件之间导航
        key = hotkey.key_of(vk, e.keysym)
        if key is None:
            shown = e.keysym if e.keysym and e.keysym != "??" else "vk=%d" % vk
            self._hint.configure(
                text="不支持的按键：%s（%s）" % (shown, hotkey.KEY_HINT),
                fg=T.C_DANGER)
            dbg("捕获到不支持的按键 vk=%d keysym=%s" % (vk, e.keysym))
            return "break"
        self._set_key_text(key)
        names = [label for flag, label in hotkey.MOD_NAMES
                 if self._mods[flag].get()]
        dbg("捕获主键 vk=%d keysym=%s -> key=%s mods=%s"
            % (vk, e.keysym, key, names))
        text, fg = self._capture_hint(key, names)
        self._hint.configure(text=text, fg=fg)
        return "break"

    @staticmethod
    def _capture_hint(key, names):
        """捕获主键后的提示：提前把"组合能不能用"讲清楚，不必等点了应用才报错。"""
        shown = hotkey.label_of(key)
        if names:
            return ("已捕获 %s，点「应用快捷键」或按回车生效"
                    % "+".join(names + [shown]), T.C_DIM)
        if hotkey.is_standalone_ok(key):
            if hotkey.is_debugger_reserved(key):
                return "已捕获 %s：%s" % (shown, _F12_NOTE), T.C_DANGER
            return ("已捕获 %s（单独使用，不带修饰键），"
                    "点「应用快捷键」或按回车生效" % shown, T.C_DIM)
        return ("已捕获 %s，但它必须搭配修饰键：勾选 Ctrl / Alt / Shift / Win，"
                "或改用 F1–F11" % shown, T.C_DANGER)

    def _clear_mods(self):
        """清空所有修饰键勾选，便于把功能键设成"单独使用"。"""
        for var in self._mods.values():
            var.set(False)
        key = self._key_entry.get().strip().upper()
        shown = hotkey.label_of(key)
        if not hotkey.is_standalone_ok(key):
            text, fg = ("修饰键已清空，但「%s」必须搭配修饰键——请改按 F1–F11"
                        % shown, T.C_DANGER)
        elif hotkey.is_debugger_reserved(key):
            text, fg = "修饰键已清空，但 %s" % _F12_NOTE, T.C_DANGER
        else:
            text, fg = ("修饰键已清空：%s 将单独生效，点「应用快捷键」或按回车"
                        % shown, T.C_DIM)
        self._hint.configure(text=text, fg=fg)
        dbg("清空修饰键，当前主键=%s" % key)

    def _apply_hotkey(self):
        spec = {flag: bool(var.get()) for flag, var in self._mods.items()}
        spec["key"] = self._key_entry.get().strip().upper()
        try:
            hotkey.hotkey_to_win(spec)      # 先本地校验，非法组合不必打扰后台线程
        except ValueError as e:
            self._hint.configure(text=str(e), fg=T.C_DANGER)
            return
        self._hint.configure(text="正在注册…", fg=T.C_DIM)
        self.hooks.apply_hotkey(spec)

    def _on_delay_changed(self, value):
        if not self._ready:
            return
        try:
            seconds = max(HIDE_DELAY_MIN, min(HIDE_DELAY_MAX, float(value)))
        except Exception:
            return
        self.hide_delay = seconds
        try:
            self._delay_txt.configure(text="%.2f 秒" % seconds)
        except Exception:
            pass
        self.hooks.delay_changed(seconds)


# ================= 小工具 =================
def _section(parent, row, text):
    """一节的小标题；返回下一行行号（grid 行号由调用方接力，不写死）。"""
    tk.Label(parent, text=text, bg=T.C_BG, fg=T.C_ACC,
             font=(T.FONT, -12, "bold")).grid(
        row=row, column=0, sticky="w", padx=PAD, pady=(14, 4))
    return row + 1


def _hint(parent, row, text, sink):
    """一行说明文字：sticky="ew" 铺满整行，折行宽度由窗口宽度决定。

    sink 收集这些标签，窗口尺寸变化时统一改 wraplength。
    """
    label = tk.Label(parent, text=text, bg=T.C_BG, fg=T.C_DIM,
                     font=(T.FONT, -9), justify="left", anchor="w",
                     wraplength=INITIAL_WRAP)
    label.grid(row=row, column=0, sticky="ew", padx=PAD, pady=(2, 0))
    sink.append(label)
    return row + 1
