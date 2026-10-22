# -*- coding: utf-8 -*-
"""测试总入口：按依赖从轻到重依次跑完，汇总结果。

    python tests/run_all.py             跑全部
    python tests/run_all.py units e2e   只跑名字里含这些关键字的

用带 tkinter 的 Python 运行（本机 C:\\Python314\\python.exe）。
每个测试都是独立子进程，互不影响；它们一律通过 tests/harness.py 的
Sandbox 启动隔离实例，所以可以和你正在用的浮坞并存。
"""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# 顺序即依赖方向：纯逻辑 -> 单模块 -> 需要真实系统调用的 -> 整机
TESTS = [
    ("units", "test_units.py", "纯逻辑：热键映射 / 缩放几何 / 配置容错"),
    ("icon", "test_icon.py", "图标统一：单一来源 / 三处同源 / 换一处即全局"),
    ("settings", "test_settings.py", "设置窗口：按键捕获 / 校验 / 灵敏度"),
    ("layout", "test_layout.py", "界面布局：实测填充 / 不写死像素"),
    ("tip", "test_tip.py", "赞赏：标题后 ♥ / 命中优先级 / 图片整数倍缩放"),
    ("hint", "test_hint.py", "悬停提示：按钮文案 / 延迟 / 位置 / 抖动不重置"),
    ("about", "test_about.py", "关于框：文案单一来源 / 可复制 / 不随面板隐藏"),
    ("tray", "test_tray.py", "托盘：左键切换 / 右键菜单 / 双击忽略"),
    ("hotkey", "test_hotkey_register.py", "裸功能键注册与独占（进程级）"),
    ("frame", "test_frame_layer.py", "阴影/外框层：包边不留在桌面（收得走、还得回）"),
    ("single", "test_single.py", "单窗口容器：换窗口先释放旧的 / 确认窗 / 不再提醒"),
    ("e2e", "test_e2e_app.py", "整机端到端：热键 / 设置 / 按键 / 隐藏 / 缩放"),
    ("absorb", "test_absorb.py", "吸附与释放：跨进程改挂与逐位还原"),
    ("shutdown", "test_shutdown.py", "关停审计：退出后不留后台进程 / 窗口 / 热键 / 图标"),
]

SUMMARY = re.compile(r"^(?P<title>.+?)：通过 (?P<ok>\d+) 项，失败 (?P<bad>\d+) 项")


def run_one(path):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([PY, "-u", os.path.join(HERE, path)],
                            cwd=os.path.dirname(HERE), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    lines = []
    for line in proc.stdout:
        sys.stdout.write(line)
        lines.append(line.rstrip("\n"))
    proc.wait()
    return proc.returncode, lines


def main(argv):
    picks = [a.lower() for a in argv]
    if picks:
        selected = [t for t in TESTS if any(p in t[0] or p in t[1].lower()
                                            for p in picks)]
    else:
        selected = TESTS
    if not selected:
        print("没有匹配的测试：%s" % picks)
        return 2

    try:
        import tkinter                                 # noqa: F401
    except ImportError:
        print("警告：当前 Python 没有 tkinter，界面相关测试会失败。")
        print("请改用带 tkinter 的解释器，例如 C:\\Python314\\python.exe")

    # 清掉上轮沙箱残留，保证这轮日志干净
    shutil.rmtree(os.path.join(HERE, "_sandbox"), ignore_errors=True)

    results = []
    t_all = time.time()
    for key, path, desc in selected:
        print("\n" + "=" * 66)
        print("▶ %s  ——  %s" % (path, desc))
        print("=" * 66)
        t0 = time.time()
        code, lines = run_one(path)
        ok = bad = None
        for line in reversed(lines):
            m = SUMMARY.match(line)
            if m:
                ok, bad = int(m.group("ok")), int(m.group("bad"))
                break
        results.append((path, code, ok, bad, time.time() - t0))

    print("\n" + "=" * 66)
    print("汇总")
    print("=" * 66)
    print("%-28s %-8s %-8s %-8s %s" % ("测试", "通过", "失败", "退出码", "耗时"))
    tot_ok = tot_bad = failed = 0
    for path, code, ok, bad, dt in results:
        tot_ok += ok or 0
        tot_bad += bad or 0
        if code != 0:
            failed += 1
        print("%-28s %-8s %-8s %-8s %.1fs"
              % (path, "—" if ok is None else ok, "—" if bad is None else bad,
                 code, dt))
    print("-" * 66)
    print("合计：%d 项通过，%d 项失败，%d/%d 个文件未通过，总耗时 %.1fs"
          % (tot_ok, tot_bad, failed, len(results), time.time() - t_all))
    if failed:
        print("未通过：" + "、".join(p for p, c, _o, _b, _d in results if c))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
