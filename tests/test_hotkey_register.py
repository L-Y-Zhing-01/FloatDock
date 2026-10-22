# -*- coding: utf-8 -*-
"""进程级：裸功能键（无修饰键）全链路 + 用户数据护栏。

验证 配置读取 -> 策略校验 -> 真实注册 -> 系统独占 -> 退出释放 这条链。
"按键真的装上去了"这件事，应用自己打日志说成功不算证据：必须由外部进程
去注册同一个组合、拿到 ERROR_HOTKEY_ALREADY_REGISTERED(1409)，才算数。

同时守住两条铁律（本项目所有测试都必须守）：
  · 绝不终止用户正在使用的那个浮坞实例；
  · 绝不改动 / 覆盖用户的 config.json。

隔离手段：独立 config.json + --allow-multiple（见 harness.Sandbox）。
沙箱不提供物理键盘注入，所以"按下按键触发"一环由 test_e2e_app.py 走
消息注入覆盖，这里只验证可判定的事实。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import harness as H                             # noqa: E402

import hotkey                                   # noqa: E402

CK = H.Checker("裸功能键注册链路")

# 候选键：先探测哪些真的空闲，避免和用户实例已占用的键撞车
CANDIDATES = ["F9", "F10", "F11", "F13", "F14", "F15", "F16", "F17"]


def free_probe(name, tries=3):
    """某功能键现在是否空闲。

    连续重试几次再下结论：探针本身是"试注册-立刻注销"，紧跟在一个刚退出的
    实例后面时偶发拿到 1409（系统释放有极短的滞后），单次探测会误判。
    """
    for _ in range(tries):
        ok, _err = H.try_register_hotkey(hotkey.VK_MAP[name])
        if ok:
            return True
        time.sleep(0.12)
    return False


def free_keys():
    return [name for name in CANDIDATES if free_probe(name)]


def bare(key):
    return {"ctrl": False, "alt": False, "shift": False, "win": False,
            "key": key}


guard = H.UserGuard()
print("用户实例 pythonw PID: %s" % (guard.pids or "无"))
print("用户 config.json sha256: %s" % guard.cfg[:16])

free = free_keys()
if len(free) < 2:
    CK.skip("裸功能键注册链路", "空闲功能键不足 2 个（%s），环境不适合测独占" % free)
    sys.exit(CK.report())

TARGET, CONTROL = free[0], free[1]
print("选用：目标键=%s（将被独占） 对照键=%s（应保持空闲）" % (TARGET, CONTROL))

CK.ok("测试前 %s 空闲（环境干净）" % TARGET, free_probe(TARGET) is True)

sb = H.Sandbox("hotkey_bare", {
    "x": 260, "y": 160, "w": 470, "h": 620, "opacity": 0.92,
    "locked": False, "hide_delay": 0.30, "hotkey": bare(TARGET)})

try:
    sb.start()
    log = sb.wait_log("初始热键", timeout=15.0)
    CK.ok("隔离实例已启动并输出热键日志", "初始热键" in log, "%d 字节" % len(sb.text()))
    CK.ok("日志确认裸 %s 注册成功" % TARGET,
          "初始热键: True %s" % TARGET in log,
          [ln.strip() for ln in sb.lines() if "初始热键" in ln][:2])
    CK.ok("生效配置确为裸键（无修饰键）",
          "热键=%s" % TARGET in sb.text(),
          [ln.strip() for ln in sb.lines() if "生效配置" in ln][:1])

    panel = sb.panel(15.0)
    CK.ok("面板顶层窗口已创建", bool(panel), "hwnd=%s" % panel)

    busy, err = H.try_register_hotkey(hotkey.VK_MAP[TARGET])
    CK.ok("%s 已被该实例独占（外部注册 err=1409）" % TARGET,
          busy is False and err == H.ERR_HOTKEY_ALREADY_REGISTERED,
          "ok=%s err=%s" % (busy, err))
    CK.ok("对照：未配置的 %s 仍可用" % CONTROL, free_probe(CONTROL) is True)

    CK.ok("运行期无异常", "Traceback" not in sb.text(),
          [ln.strip() for ln in sb.lines()
           if "Traceback" in ln or "Error" in ln][:3])

    CK.ok("用户实例未被本次测试终止", guard.unchanged(), guard.detail())
    CK.ok("用户的 config.json 未被改动", guard.unchanged(), guard.cfg[:16])

    # 隔离沙箱自己的配置应照常被读取（说明 --config 生效，写回也落在沙箱那份）
    CK.ok("沙箱实例读的是沙箱配置",
          sb.read_cfg().get("hotkey", {}).get("key") == TARGET,
          sb.read_cfg().get("hotkey"))
finally:
    sb.stop()

after, aerr = H.try_register_hotkey(hotkey.VK_MAP[TARGET])
CK.ok("实例退出后 %s 被系统释放" % TARGET, after is True, "err=%s" % aerr)
CK.ok("测试结束后用户实例仍在运行", guard.unchanged(), guard.detail())
CK.ok("用户的 config.json 全程未被改动", guard.unchanged(), guard.cfg[:16])

sys.exit(CK.report())
