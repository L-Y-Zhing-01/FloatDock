# -*- coding: utf-8 -*-
"""浮坞主面板：状态机、事件分发，以及对各模块的编排。

职责边界（想改哪一块就去哪个文件）：
    · 本文件   —— 什么时候显示/隐藏、点在哪里该做什么
    · render   —— 画面长什么样
    · settings —— 设置窗口
    · picker   —— 拖拽拾取
    · absorb   —— 跨进程吸附与还原
    · tray     —— 托盘图标与全局热键
    · theme    —— 配色与尺寸
"""
import os
import queue
import tkinter as tk

import about
import appicon
import confirm
import hint
import hotkey
import render
import theme as T
import tip
import wndutil
from absorb import Absorber
from debug import dbg
from picker import WindowPicker
from settings import Hooks, SettingsDialog
from tray import AuxThread

VERSION = "v1.10.0"

TICK_MS = 20            # 状态轮询间隔；隐藏延迟靠它检测，取值即检测精度
WHEEL_STEP = 0.04       # 滚轮一次调多少透明度

IDLE_MSG = "把窗口拖到标题栏的「✥」上即可嵌入"

# 标题栏按钮的悬停提示。与 btn_actions 一一对应 —— 改了某个按钮干什么，
# 顺手把这里那句也改掉，免得提示还在说"释放"，其实早就不那么干了。
# 文案尽量讲"按下去会发生什么"，而不是重复字形本身（⚙ 不需要解释成"齿轮"）。
BTN_HINTS = {
    "grab": "吸附窗口：按住拖到目标窗口上松开",
    "release": "释放当前窗口，还回桌面",
    "opacity": "面板透明度",
    "set": "设置：热键、隐藏延迟、替换提醒",
    "min": "隐藏面板（热键可唤回）",
    "close": "退出浮坞，窗口全部还回桌面",
    "tip": "赞赏支持（完全自愿）",
}
# 锁定按钮的文案随状态走：(未锁定, 已锁定)
LOCK_HINTS = ("锁定面板：不再自动隐藏", "解锁面板：恢复自动隐藏")


class FloatDock(object):
    """悬浮面板本体。构造即就位，run() 进入消息循环。"""

    def __init__(self, config):
        self.cfg = config
        self.hotkey_spec = dict(config.hotkey)          # Config 已保证合法
        self.hotkey_label = hotkey.hotkey_to_win(self.hotkey_spec)[2]
        self.hide_delay = config.hide_delay

        self._build_window(config)
        self._init_state()

        self.aux = AuxThread(appicon.APP_TITLE, lambda: self.locked,
                             self.hotkey_spec)
        self.aux.start()
        # 只等一小会：不想让托盘/热键初始化的任何意外拖住窗口显示与状态机启动
        self.aux.ready.wait(0.15)

        self._bind()
        self._apply_alpha()
        # 图标挂在窗口类上，一次覆盖全部顶层窗口（含以后再建的设置窗、拾取层）。
        # 位置有讲究：overrideredirect 与分层属性会让 Tk 重建顶层窗口并把类图标
        # 还原成默认，所以必须等窗口属性全部定型之后再挂。
        appicon.apply(self.root)
        self._draw()
        self.root.after(90, self._tick)
        self.root.after(60, self._pump_aux)

    # ================= 构造 =================
    def _build_window(self, config):
        """建出顶层窗口与画布，并取到面板自身的 hwnd。"""
        self.root = tk.Tk()
        self.root.title(appicon.APP_TITLE)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.w, self.h = config.w, config.h
        self.x, self.y = self._initial_pos()
        self.root.geometry("%dx%d+%d+%d" % (self.w, self.h, self.x, self.y))
        self.op = config.opacity
        self.locked = config.locked

        self.cv = tk.Canvas(self.root, bg=T.C_BG, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        wndutil.add_clipsiblings(self.cv.winfo_id())

        self.root.update_idletasks()
        self.root.update()
        self.panel = wndutil.root_of(self.root.winfo_id())
        self.own_pid = wndutil.window_pid(self.panel)
        dbg("panel hwnd=%s pid=%s" % (self.panel, self.own_pid))
        dbg("生效配置 w=%d h=%d op=%.2f 隐藏延迟=%.3fs tick=%dms 热键=%s"
            % (self.w, self.h, self.op, self.hide_delay, TICK_MS,
               self.hotkey_label))

    def _init_state(self):
        """运行期状态：显隐机、拖拽机、绘制缓存、按钮分发表。"""
        self.absorber = Absorber(lambda: self.panel, self.own_pid)
        self.picker = WindowPicker(self.root, self._on_pick_target,
                                   self._on_pick_done)
        # render 决定标题栏有哪几个按钮（payload），这里决定按下去做什么。
        # 直接存绑定方法：既不必在模块级写一张"方法名字符串"的表，也不会有
        # 名字对不上的中间环节。
        self.btn_actions = {
            "grab": self._start_grab, "set": self._open_settings,
            "lock": self._toggle_lock, "min": self.hide, "close": self.quit,
            "release": self._release_current, "opacity": self._toggle_opacity,
            "tip": self._open_tip,
        }
        self.settings = None            # 打开中的设置窗口
        self.tip_window = None          # 打开中的赞赏窗
        self.about_window = None        # 打开中的关于框
        self.hint = hint.Hint(self.root)   # 按钮悬停提示（共用一个小窗）
        self.shown = True
        self._away = False              # 鼠标已移出面板，隐藏定时器已排上
        self._hide_job = None           # 待执行的隐藏定时器
        self.drag_mode = None           # None | 'move' | 'resize' | 'slider'
        self.drag_off = (0, 0)
        self.resize_edge = None         # 'l'|'r'|'t'|'b'|'tl'|'tr'|'bl'|'br'
        self._resize_from = None        # 缩放起始 (x, y, w, h)
        self._resize_mouse = (0, 0)     # 缩放起始鼠标屏幕坐标
        self._cursor = ""
        self.confirming = False         # 替换确认窗开着（期间不自动隐藏）
        self.popup = None               # None | 'opacity'（标题栏内的轻模态浮层）
        self.msg = IDLE_MSG
        self.msg_is_err = False
        self.hits = []

    def run(self):
        dbg("状态机启动，进入消息循环")
        self.root.mainloop()

    # ================= 初始位置 =================
    def _initial_pos(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if self.cfg.x is None:
            return sw - self.w - 48, max(90, (sh - self.h) // 3)
        # 存过的位置也要夹回屏幕，免得换了显示器之后面板在外面
        x = max(-self.w + 40, min(self.cfg.x, sw - 80))
        y = max(0, min(self.cfg.y, sh - 100))
        return x, y

    def _save(self):
        """把面板状态回写到配置。"""
        self.cfg.x, self.cfg.y = self.x, self.y
        self.cfg.w, self.cfg.h = self.w, self.h
        self.cfg.opacity, self.cfg.locked = self.op, self.locked
        self.cfg.hide_delay = self.hide_delay
        self.cfg.hotkey = dict(self.hotkey_spec)
        self.cfg.save()

    # ================= 事件绑定 =================
    def _bind(self):
        cv = self.cv
        cv.bind("<ButtonPress-1>", self._on_press)
        cv.bind("<B1-Motion>", self._on_motion)
        cv.bind("<ButtonRelease-1>", self._on_release)
        cv.bind("<Motion>", self._on_hover)
        cv.bind("<Leave>", self._on_leave)
        cv.bind("<Double-Button-1>", self._on_double)
        cv.bind("<MouseWheel>", self._on_wheel)
        cv.bind("<Configure>", self._on_resize)
        self.root.bind("<Escape>", self._on_esc)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

    def _hit(self, x, y):
        for hit in self.hits:
            x1, y1, x2, y2 = hit.rect
            if x1 <= x <= x2 and y1 <= y <= y2:
                return hit
        return None

    @staticmethod
    def _keeps_popup(hit):
        """这次按下的位置算不算"浮层内部"—— 算的话不关闭浮层。"""
        if hit is None:
            return False
        return (hit.kind in ("popup", "slider")
                or (hit.kind == "btn" and hit.payload == "opacity"))

    # ================= 鼠标按下 / 拖动 / 抬起 =================
    def _on_press(self, e):
        # 按下就收起提示：接下来要么拖窗、要么执行那个按钮的动作，
        # 提示条挂在按钮下面只会挡路。
        self.hint.hide()
        # 边缘缩放优先于一切命中：按钮都离边超过 5px，不会被感应区抢走
        zone = T.resize_zone(self.w, self.h, e.x, e.y)
        if zone:
            self.drag_mode = "resize"
            self.resize_edge = zone
            self._resize_from = (self.x, self.y, self.w, self.h)
            self._resize_mouse = (e.x_root, e.y_root)
            dbg("开始缩放 zone=%s 起始=%s" % (zone, self._resize_from))
            return
        hit = self._hit(e.x, e.y)
        # 浮层是轻模态：点在浮层与 ◐ 以外的地方，先收起、再按收起后的画面
        # 重新判定命中。不这么做的话，浮层盖住的那段标题拖拽区会把这次点击
        # 变成拖窗 —— 用户以为只是想关掉滑块，结果整个面板跟着手走了。
        if self.popup and not self._keeps_popup(hit):
            self.popup = None
            self._draw()
            hit = self._hit(e.x, e.y)
        dbg("press at (%d,%d) hit=%s" % (e.x, e.y, hit))
        self.drag_mode = None           # 普通按下：清掉上一次遗留的拖拽状态
        if hit is None:
            return
        if hit.kind == "popup":
            return                      # 浮层空白处：吃掉，别穿透成拖窗
        if hit.kind == "btn":
            action = self.btn_actions.get(hit.payload)
            if action:
                action()
        elif hit.kind == "slider":
            self.drag_mode = "slider"
            self._slider_set(e.x)
        elif hit.kind == "title":
            self.drag_mode = "move"
            self.drag_off = (e.x, e.y)

    def _on_motion(self, e):
        if self.drag_mode == "move":
            new_x = self.root.winfo_x() + e.x - self.drag_off[0]
            new_y = self.root.winfo_y() + e.y - self.drag_off[1]
            self.x, self.y = new_x, new_y
            self.root.geometry("+%d+%d" % (new_x, new_y))
        elif self.drag_mode == "resize":
            self._resize_apply(e.x_root, e.y_root)
            self._place_current()
        elif self.drag_mode == "slider":
            self._slider_set(e.x)

    def _on_release(self, e):
        if not self.drag_mode:
            return
        dbg("结束 %s -> (%d,%d,%d,%d)" % (self.drag_mode, self.x, self.y,
                                          self.w, self.h))
        self.drag_mode = None
        self.resize_edge = None
        self._resize_from = None
        self._save()
        self._place_current()
        self._draw()
        self._on_hover(e)

    def _on_hover(self, e):
        if self.drag_mode or self.picker.active:
            self.hint.hide()
            return
        self._set_cursor(T.CURSORS.get(
            T.resize_zone(self.w, self.h, e.x, e.y), ""))
        self._hint_for(self._hit(e.x, e.y))

    def _on_leave(self, _e):
        """光标离开画布就收起提示 —— 包括移进被嵌入的那个原生子窗口。"""
        self.hint.hide()

    def _hint_for(self, hit):
        """悬停在按钮上时在它正下方给一句说明，其余命中一律收起。"""
        text = self._hint_text(hit)
        if not text:
            self.hint.hide()
            return
        x1, _y1, x2, y2 = hit.rect
        self.hint.schedule(text, self.root.winfo_rootx() + (x1 + x2) // 2,
                           self.root.winfo_rooty() + y2 + hint.GAP)

    def _hint_text(self, hit):
        """这个命中区该提示什么；不给提示就返回 None。

        只有按钮有提示：拖拽区、浮层、滑块都是"手一放就知道"的操作，
        再挂文字反而碍事。
        """
        if hit is None or hit.kind != "btn":
            return None
        if hit.payload == "lock":
            return LOCK_HINTS[1 if self.locked else 0]
        return BTN_HINTS.get(hit.payload)

    def _on_double(self, e):
        # 双击标题栏或空白内容区隐藏（落在嵌入窗口上的双击被子窗口吃掉，不受影响）
        hit = self._hit(e.x, e.y)
        if hit is not None and hit.kind in ("btn", "popup", "slider"):
            return              # 双击按钮/浮层不是"隐藏面板"
        if e.y <= T.H_TITLE or self.absorber.tab is None:
            self.hide()

    def _on_wheel(self, e):
        if e.y <= T.H_TITLE:
            self._set_opacity(self.op + (WHEEL_STEP if e.delta > 0
                                         else -WHEEL_STEP))

    def _on_esc(self, _):
        if self.picker.active:
            self.picker.cancel()
        elif self.popup:
            self.popup = None
            self._draw()

    def _on_resize(self, _):
        if self.shown:
            self._draw()
            self._place_current()

    def _set_cursor(self, name):
        if name == self._cursor:
            return
        self._cursor = name
        try:
            self.cv.configure(cursor=name)
        except Exception:
            try:
                self.cv.configure(cursor="sizing" if name else "")
            except Exception:
                pass

    # ================= 边缘拖拽缩放 =================
    def _resize_apply(self, mx, my):
        """按起始几何 + 鼠标位移更新面板几何。

        用屏幕坐标而不是画布局部坐标：缩放过程中画布自身也在变，局部坐标会失真。
        """
        if not self._resize_from:
            return
        rect = T.resized_rect(
            self._resize_from,
            (mx - self._resize_mouse[0], my - self._resize_mouse[1]),
            self.resize_edge)
        if rect == (self.x, self.y, self.w, self.h):
            return
        self.x, self.y, self.w, self.h = rect
        self.root.geometry("%dx%d+%d+%d" % (rect[2], rect[3], rect[0], rect[1]))

    # ================= 显隐状态机 =================
    def _tick(self):
        try:
            self._tick_body()
        except Exception as e:
            dbg("tick 异常", e)
        try:
            # 兜底：被吸附窗口的"包边层"若又跑回屏幕里，再挪出去。
            # 名单通常为空 —— 那时这个方法一次 API 调用都不会发生。
            self.absorber.keep_parked()
            if self.absorber.prune_dead():
                self._draw()        # 窗口自己关掉了：标题收起、回到空面板
        except Exception as e:
            dbg("包边层兜底异常", e)
        self.root.after(TICK_MS, self._tick)

    def _busy(self):
        """正在拖拽/缩放/拾取或开着设置窗、赞赏窗时，一律不自动隐藏。

        这两个窗都是本进程的 Toplevel，鼠标移过去时 _cursor_inside() 就是
        False —— 不在这里拦住，用户刚要扫码面板就自己收起来了。
        """
        return bool(self.drag_mode or self.picker.active or self.settings
                    or self.confirming or self.tip_window or self.about_window)

    def _tick_body(self):
        """鼠标在面板外停留超过 hide_delay 就自动收起。

        隐藏后不留在屏幕上任何可供鼠标碰到的部分（hide() 走的是 withdraw()，
        面板整个消失），所以没有"移到左缘唤出"这条路；唤回只有三个入口：
        全局快捷键、托盘单击、托盘右键菜单。
        """
        if self._busy():
            self._away = False
            return
        if not self.shown:
            return
        if self._cursor_inside() or self.locked:
            if self._away:
                self._away = False
                self._cancel_hide()
        elif not self._away:
            # 一检测到移出就把隐藏时刻定下来：不依赖下一轮轮询，延迟才准
            self._away = True
            dbg("检测到鼠标移出，%.0fms 后隐藏" % (self.hide_delay * 1000))
            self._schedule_hide()

    def _cursor_inside(self):
        """鼠标是否在面板矩形内（含 2px 容差，避免贴边抖动）。"""
        cx, cy = wndutil.cursor_pos()
        px, py, pw, ph = wndutil.win_rect(self.panel)
        return px - 2 <= cx <= px + pw + 2 and py - 2 <= cy <= py + ph + 2

    def _schedule_hide(self):
        if self._hide_job is None:
            self._hide_job = self.root.after(
                max(1, int(round(self.hide_delay * 1000))), self._hide_if_out)

    def _cancel_hide(self):
        if self._hide_job is not None:
            try:
                self.root.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _hide_if_out(self):
        self._hide_job = None
        if self._busy() or self.locked:
            return
        if self._cursor_inside():
            self._away = False            # 又移回来了，取消这次隐藏
            return
        self.hide()

    def hide(self):
        if not self.shown:
            return
        self.shown = False
        self._away = False
        self._cancel_hide()
        self.popup = None               # 面板都收了，浮层没有留下的理由
        self.hint.hide()                # 提示条是独立窗口，不会跟着面板一起收
        self.root.withdraw()
        self._save()
        dbg("隐藏")

    def show(self):
        if self.shown:
            return
        self.shown = True
        self._away = False
        self._cancel_hide()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.after(60, self._place_current)
        dbg("显示")

    def toggle(self):
        self.hide() if self.shown else self.show()

    # ================= 托盘 / 热键动作 =================
    def _pump_aux(self):
        """把辅助线程排队的动作拿到主线程执行（Tk 不是线程安全的）。"""
        while True:
            try:
                action, _payload = self.aux.actions.get_nowait()
            except queue.Empty:
                break
            except Exception as e:
                dbg("读取动作失败", e)
                break
            if action == "quit":
                self.quit()
                return
            try:
                self._handle_action(action)
            except Exception as e:
                dbg("处理动作 %s 失败" % action, e)
        while True:
            try:
                ok, text = self.aux.hk_results.get_nowait()
            except queue.Empty:
                break
            except Exception as e:
                dbg("读取热键结果失败", e)
                break
            self._on_hotkey_result(ok, text)
        self.root.after(60, self._pump_aux)

    def _handle_action(self, action):
        if action == "toggle":
            self.toggle()
        elif action == "lock":
            self._toggle_lock()
        elif action == "release_all":
            had = self.absorber.tab is not None
            done = self.absorber.release_all()
            self._draw()
            self._place_current()
            if not had:
                msg = "没有可释放的窗口"
            elif done:
                msg = "已释放窗口"
            else:
                msg = "窗口未能还原，仍留在浮坞里"
            dbg("托盘释放全部 ->", msg)
            self._set_msg(msg, err=had and not done)
        elif action == "settings":
            self._open_settings()
        elif action == "tip":
            self._open_tip()
        elif action == "about":
            self._open_about()

    def _on_hotkey_result(self, ok, text):
        if ok:
            self.hotkey_spec = dict(self.aux.hotkey_spec)
            self.hotkey_label = self.aux.hotkey_label or self.hotkey_label
            self._save()
            dbg("热键已更新为", self.hotkey_label)
            if self.settings:
                self.settings.show_hotkey_result(True, text)
            else:
                self._set_msg("快捷键已改为 " + self.hotkey_label)
        else:
            dbg("热键注册失败", text)
            if self.settings:
                self.settings.show_hotkey_result(False, text)
            else:
                self._set_msg(text, err=True)
        self._draw()

    # ================= 设置窗口 =================
    def _open_settings(self):
        if self.popup:
            self.popup = None
            self._draw()
        if self.settings and self.settings.is_open:
            try:
                self.settings.window.lift()
                self.settings.window.focus_force()
            except Exception:
                pass
            return
        self.settings = SettingsDialog(
            self.root, (self.x, self.y, self.w), self.hotkey_spec,
            self.hotkey_label, self.hide_delay,
            Hooks(apply_hotkey=self.aux.set_hotkey,
                  delay_changed=self._set_hide_delay,
                  closed=self._on_settings_closed),
            about=self._open_about)

    def _on_settings_closed(self):
        self.settings = None
        self._place_current()
        self._draw()

    # ================= 关于框 =================
    def _open_about(self):
        """托盘「关于浮坞」与设置窗口底部共用：已经开着就抬到最前面。"""
        win = self.about_window
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except Exception:
                pass
            self.about_window = None    # 记着的窗口已经没了，重开一个
        self.about_window = about.open_about(
            self.root, VERSION, self.hotkey_label,
            (self.x, self.y, self.w, self.h), self._on_about_closed)

    def _on_about_closed(self):
        self.about_window = None

    # ================= 赞赏窗 =================
    def _open_tip(self):
        """♥：显示赞赏码。已经开着就抬到最前面，不叠第二个窗口。"""
        if self.popup:
            self.popup = None
            self._draw()
        win = self.tip_window
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except Exception:
                pass
            self.tip_window = None       # 记着的窗口已经没了，重开一个
        self.tip_window = tip.show(self.root, self._on_tip_closed)

    def _on_tip_closed(self):
        self.tip_window = None

    def _set_hide_delay(self, seconds):
        self.hide_delay = seconds
        self.cfg.hide_delay = seconds
        self.cfg.save()

    # ================= 透明度 =================
    def _apply_alpha(self):
        try:
            self.root.attributes("-alpha", self.op)
            # 分层属性有可能让 Tk 重建顶层窗口、顺手把窗口类图标还原成默认，
            # 这里补一道（幂等：没被还原就直接返回，不会多留句柄）。
            appicon.apply(self.root)
        except Exception as e:
            dbg("设置透明度失败", e)

    def _toggle_opacity(self):
        """◐：开/关标题栏里的透明度浮层。"""
        self.popup = None if self.popup else "opacity"
        self._draw()

    def _set_opacity(self, value, persist=True):
        self.op = max(T.OP_MIN, min(T.OP_MAX, value))
        self._apply_alpha()
        self._draw()
        if persist:
            self._save()

    def _slider_set(self, mouse_x):
        x1, _y, x2, _ = T.slider_geo(self.w)
        ratio = 0 if x2 == x1 else (mouse_x - x1) / float(x2 - x1)
        # 拖动过程中不落盘：每动一像素就 save 一次等于每秒几十次写 config.json，
        # 而 _on_release 无论如何会补一次 _save()，值不会丢。
        self._set_opacity(T.OP_MIN + ratio * (T.OP_MAX - T.OP_MIN),
                          persist=False)

    # ================= 窗口拾取（拖拽吸附） =================
    def _start_grab(self):
        if self.picker.active:
            return
        if self.popup:
            self.popup = None
            self._draw()
        dbg("开始拾取")
        self.picker.start()
        self._set_msg("按住拖动中：移到目标窗口上松开，Esc 取消")
        self._set_cursor("crosshair")

    def _on_pick_target(self, title):
        self._set_msg("目标：%s" % title)

    def _on_pick_done(self, target):
        dbg("结束拾取 target=%s" % target)
        self._set_cursor("")
        if target is None:
            self._set_msg("已取消吸附")
            return
        ok, info = wndutil.is_suitable_target(target, self.own_pid)
        if not ok:
            self._set_msg(info, err=True)
            return
        if not self._confirm_replace(target):
            self._set_msg("已取消吸附")
            return
        # 容器一次只放一个窗口，替换时的"先释放"由 Absorber 自己做（见其 docstring）
        tab, message = self.absorber.absorb(target)
        self._draw()
        self._place_current()
        wndutil.invalidate(self.panel)
        if tab is None:
            self._set_msg(message, err=True)
        else:
            self._set_msg(message)
        dbg("absorb ->", message)

    def _confirm_replace(self, target):
        """已有窗口时，第一次替换要把"当前那个会被还回去"讲清楚。

        用户勾了「不再提醒」就落盘到 config.auto_release，之后直接替换。
        """
        if self.absorber.tab is None or self.cfg.auto_release:
            return True
        current = self.absorber.tab
        self.confirming = True
        try:
            ok, no_more = confirm.ask_replace(
                self.root, (self.x, self.y, self.w, self.h),
                current.title, wndutil.win_text(target))
        finally:
            self.confirming = False
        if no_more:
            self.cfg.auto_release = True
            self._save()
            dbg("单窗口替换：已设为不再提醒")
        return ok

    # ================= 摆放嵌入窗口 =================
    def _place_current(self):
        if not self.shown:
            return
        # MoveWindow 要的是父窗口的客户区坐标（面板无边框，客户区原点即窗口原点）
        self.absorber.place_current(*T.content_rect(self.w, self.h))

    # ================= 按钮动作 =================
    def _toggle_lock(self):
        self.locked = not self.locked
        self._set_msg("锁定已%s" % ("开启（不再自动隐藏）" if self.locked
                                    else "关闭"))
        self._draw()
        self._save()

    def _release_current(self):
        if not self.absorber.release():
            self._set_msg("释放失败", err=True)
            return
        self._draw()
        self._place_current()
        wndutil.invalidate(self.panel)
        self._set_msg("已释放窗口")

    # ================= 绘制 =================
    def _view(self):
        """给绘制层的一帧只读状态。"""
        return render.View(
            w=self.w, h=self.h, opacity=self.op, locked=self.locked,
            shown=self.shown, msg=self.msg, msg_is_err=self.msg_is_err,
            hotkey_label=self.hotkey_label,
            tab=self.absorber.alive_title(), popup=self.popup)

    def _draw(self):
        self.hits = render.draw(self.cv, self._view())

    def _set_msg(self, text, err=False):
        self.msg = text
        self.msg_is_err = err
        render.draw_status(self.cv, self._view())   # 只重画状态栏，避免整帧闪烁

    # ================= 退出 =================
    def quit(self):
        """退出：按"谁的资源谁交还"的顺序逐样清理，最后才让进程消失。

        顺序：先还别人的窗口（最要紧，还不了就是数据损失），再落盘自己的状态，
        然后让辅助线程交还托盘/热键并结束，接着还掉图标句柄，最后销毁界面、
        退出进程。
        """
        def release_windows():
            had = self.absorber.tab is not None
            done = self.absorber.release_all(tries=3)
            dbg("退出释放 %d 个窗口（原有 %d 个）"
                % (done, 1 if had else 0))
            if self.absorber.last_stuck:
                dbg("警告：未还原的窗口", self.absorber.last_stuck)

        def stop_aux():
            self.aux.remove_tray()          # 删图标 + 注销热键 + 结束辅助线程
            self.aux.join(0.6)              # 同步等它结束，不留后台线程
            dbg("辅助线程已结束：%s" % (not self.aux.is_alive()))

        _safe("释放异常", release_windows)
        _safe("保存异常", self._save)
        _safe("辅助线程收尾异常", stop_aux)
        _safe("提示条收尾异常", self.hint.hide)   # 别让那条小窗活得比面板久
        _safe("图标收尾异常", appicon.release)  # 还原类图标 + 销毁自建图标句柄
        _safe("销毁界面异常", self.root.destroy)
        # 最后一道保险：上面任何一步万一卡住，这里保证进程一定会消失，
        # 内存与句柄随之交还系统 —— 绝不留下"看不见还在跑"的浮坞。
        os._exit(0)


def _safe(label, fn):
    """执行收尾动作，出错只记日志，绝不打断后续清理。"""
    try:
        fn()
    except Exception as e:
        dbg(label, e)
