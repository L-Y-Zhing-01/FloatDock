# -*- coding: utf-8 -*-
"""配置持久化：config.json 的读取、校验、归一化与保存。

读取时逐项校验并夹到合法区间，任何一项写坏都退回默认值 ——
"配置坏了也要能打开面板"是这个模块存在的首要理由。
"""
import json

import hotkey as hk
import theme
from debug import dbg

HIDE_DELAY_DEF = 0.05                               # 鼠标移出后多少秒隐藏
HIDE_DELAY_MIN, HIDE_DELAY_MAX = 0.02, 0.60

DEFAULT_W, DEFAULT_H = 470, 660
DEFAULT_OPACITY = 0.92

# 本程序认识的键；其余键原样保留，避免覆盖用户自己加的字段
_KNOWN = ("x", "y", "w", "h", "opacity", "locked", "hide_delay", "hotkey",
          "auto_release")


class Config(object):
    """面板的可持久化状态。"""

    def __init__(self, path):
        self.path = path
        self.x = None          # None = 还没定过位，交给面板算初始位置
        self.y = None
        self.w = DEFAULT_W
        self.h = DEFAULT_H
        self.opacity = DEFAULT_OPACITY
        self.locked = False
        self.hide_delay = HIDE_DELAY_DEF
        self.hotkey = dict(hk.DEFAULT_HOTKEY)
        # 单窗口替换时是否还弹确认窗。True = 用户勾过「不再提醒」，直接替换。
        self.auto_release = False
        self._extra = {}
        self.load()

    # ================= 读 =================
    def load(self):
        raw = self._read_json()
        self._extra = {k: v for k, v in raw.items() if k not in _KNOWN}
        self.w = self._number(raw.get("w"), self.w, theme.MIN_W, 3000, int)
        self.h = self._number(raw.get("h"), self.h, theme.MIN_H, 2000, int)
        self.opacity = self._number(raw.get("opacity"), self.opacity,
                                    theme.OP_MIN, theme.OP_MAX, float)
        self.hide_delay = self._number(raw.get("hide_delay"), self.hide_delay,
                                       HIDE_DELAY_MIN, HIDE_DELAY_MAX, float)
        if isinstance(raw.get("x"), int) and isinstance(raw.get("y"), int):
            self.x, self.y = raw["x"], raw["y"]
        self.locked = bool(raw.get("locked", False))
        self.hotkey = hk.sanitize(raw.get("hotkey"))
        self.auto_release = raw.get("auto_release") is True
        return self

    @staticmethod
    def _number(value, fallback, lo, hi, cast):
        """数值字段校验：类型不对或超范围一律夹到合法区间。"""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return fallback
        return max(lo, min(cast(value), hi))

    def _read_json(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    # ================= 写 =================
    def save(self):
        data = dict(self._extra)
        data.update({"x": self.x, "y": self.y,
                     "w": int(self.w), "h": int(self.h),
                     "opacity": round(self.opacity, 3),
                     "locked": self.locked,
                     "hide_delay": round(self.hide_delay, 3),
                     "hotkey": dict(self.hotkey),
                     "auto_release": bool(self.auto_release)})
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception as e:
            dbg("保存配置失败", e)
