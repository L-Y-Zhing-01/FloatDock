# -*- coding: utf-8 -*-
"""全局热键：按键名映射、配置校验、以及按键输入的解析。

刻意做成不依赖 Tk 的纯逻辑，便于单独测试；设置窗口只负责把 Tk 事件喂进来。
分三类职责：
  · 注册 —— spec -> (mods, vk, 显示名)
  · 策略 —— 哪些主键可以不带修饰键单独使用
  · 输入 —— 一次按键（keycode=VK、keysym）解析成修饰键 / 主键
"""
import re

# ================= 修饰键 =================
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x0001, 0x0002, 0x0004, 0x0008
MOD_NOREPEAT = 0x4000
HOTKEY_TOGGLE = 0xB00B          # 显隐热键的注册 ID

# 顺序即显示顺序；显示名由 flag 派生（Ctrl / Alt / Shift / Win）。
# 位掩码、显示名、配置键都从这一张表出，加修饰键只改这里。
MODS = (("ctrl", MOD_CONTROL), ("alt", MOD_ALT),
        ("shift", MOD_SHIFT), ("win", MOD_WIN))
MOD_NAMES = tuple((flag, flag.capitalize()) for flag, _bits in MODS)

# ================= 主键 -> 虚拟键码 =================
VK_MAP = {}
for _c in range(0x30, 0x3A):        # 主键盘 0-9
    VK_MAP[chr(_c)] = _c
for _c in range(0x41, 0x5B):        # A-Z
    VK_MAP[chr(_c)] = _c
for _i in range(1, 25):             # F1-F24
    VK_MAP["F%d" % _i] = 0x6F + _i
# 小键盘数字的 VK 与主键盘数字不同（VK_NUMPAD0-9 = 0x60-0x69）。两者必须分开
# 记录，否则会出现"注册成功但按下去没反应"。
for _i in range(10):
    VK_MAP["NUMPAD%d" % _i] = 0x60 + _i

_KEY_BY_VK = {vk: name for name, vk in VK_MAP.items()}

# 带惯用中文名的按键
KEY_LABEL = {"NUMPAD%d" % _i: "小键盘%d" % _i for _i in range(10)}

DEFAULT_HOTKEY = {"ctrl": True, "alt": True, "shift": False, "win": False,
                  "key": "D"}

KEY_HINT = "可用 A–Z / 0–9 / F1–F24 / 小键盘数字"

# 实测（RegisterHotKey）：F12 被 Windows 保留给调试器，裸注册返回
# ERROR_HOTKEY_ALREADY_REGISTERED(1409)，连 Shift+F12 也被预留，
# 只有加 Ctrl/Alt/Win 才可用。提前告知，省得用户应用失败后才困惑。
RESERVED_KEYS = ("F12",)


def label_of(key):
    """主键的显示名。"""
    return KEY_LABEL.get(key, key)


def is_debugger_reserved(key):
    return str(key or "").strip().upper() in RESERVED_KEYS


def is_standalone_ok(key):
    """该主键是否允许不加任何修饰键单独使用。

    只有功能键 F1–F24 可以：它们不产生字符输入，独占不会影响打字。
    字母/数字若裸注册，会在全系统范围内吞掉该键的输入（打一次字就触发
    一次显隐），所以仍强制要求至少一个修饰键。
    """
    return bool(re.fullmatch(r"F([1-9]|1\d|2[0-4])",
                             str(key or "").strip().upper()))


def mods_of(spec):
    """spec -> (mods 位掩码, 显示名列表)。"""
    mods, names = 0, []
    for flag, bits in MODS:
        if spec.get(flag):
            mods |= bits
            names.append(flag.capitalize())
    return mods, names


def hotkey_to_win(spec):
    """配置字典 -> (mods, vk, 显示名)。非法组合抛 ValueError。"""
    spec = spec if isinstance(spec, dict) else {}
    mods, names = mods_of(spec)
    key = str(spec.get("key", "")).strip().upper()
    if key not in VK_MAP:
        raise ValueError("不支持的按键：%s（%s）" % (key or "空", KEY_HINT))
    if not names and not is_standalone_ok(key):
        raise ValueError(
            "「%s」必须搭配至少一个修饰键（Ctrl / Alt / Shift / Win）；"
            "只有功能键 F1–F11 / F13–F24 可以单独使用"
            "（F12 被 Windows 保留给调试器）" % label_of(key))
    return mods, VK_MAP[key], "+".join(names + [label_of(key)])


def sanitize(spec):
    """把配置里读出来的热键规格修成合法的；不合法就退回默认值。

    目的是"配置写坏了也仍然打得开面板"。
    """
    spec = spec if isinstance(spec, dict) else {}
    try:
        hotkey_to_win(spec)
    except (ValueError, TypeError):
        return dict(DEFAULT_HOTKEY)
    return {flag: bool(spec.get(flag)) for flag, _ in MOD_NAMES} | {
        "key": str(spec.get("key", "")).strip().upper()}


# ================= 按键输入解析 =================
# Windows 上 Tk 的 event.keycode 就是 Win32 虚拟键码，用它判定比 keysym 可靠：
# 实测右 Ctrl 的 keysym 会退化成 "??"，小键盘数字的 keysym 又与主键盘完全相同
# （但 VK 不同，判错会"注册成功却按不出来"）。
_MOD_BY_VK = {0x10: "shift", 0x11: "ctrl", 0x12: "alt",
              0xA0: "shift", 0xA1: "shift",
              0xA2: "ctrl", 0xA3: "ctrl",
              0xA4: "alt", 0xA5: "alt",
              0x5B: "win", 0x5C: "win"}

_MOD_BY_KEYSYM = (("control", "ctrl"), ("alt", "alt"), ("shift", "shift"),
                  ("super", "win"), ("win", "win"), ("meta", "win"))

# NumLock 关闭时 Tk 把小键盘报成方向键式的名字，VK 仍是 VK_NUMPAD0-9
_KP_ALIAS = {"KP_Insert": "0", "KP_End": "1", "KP_Down": "2", "KP_Next": "3",
             "KP_Left": "4", "KP_Begin": "5", "KP_Right": "6", "KP_Home": "7",
             "KP_Up": "8", "KP_Prior": "9"}


def mod_of(keycode, keysym):
    """一次按键若是修饰键，返回 'ctrl'/'alt'/'shift'/'win'，否则 None。"""
    name = _MOD_BY_VK.get(int(keycode or 0))
    if name:
        return name
    ks = (keysym or "").lower()
    for prefix, mod in _MOD_BY_KEYSYM:
        if ks.startswith(prefix):
            return mod
    return None


def key_of(keycode, keysym):
    """一次按键若是可用主键，返回主键名；否则 None。keycode 优先于 keysym。"""
    name = _KEY_BY_VK.get(int(keycode or 0))
    if name:
        return name
    ks = keysym or ""
    if re.fullmatch(r"[Ff]\d{1,2}", ks):
        n = int(ks[1:])
        return "F%d" % n if 1 <= n <= 24 else None
    if len(ks) == 1 and ks.isalnum():
        return ks.upper()
    if re.fullmatch(r"KP_\d", ks):              # 小键盘数字（NumLock 开）
        return "NUMPAD" + ks[-1]
    alias = _KP_ALIAS.get(ks)                   # NumLock 关
    return "NUMPAD" + alias if alias else None
