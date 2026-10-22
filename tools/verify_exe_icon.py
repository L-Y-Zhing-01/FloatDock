# -*- coding: utf-8 -*-
"""待验：打包出来的 exe 里到底嵌了几层图标、是不是我们那张 floatdock.ico。

    python tools/verify_exe_icon.py [exe 路径]     默认查发布/_build/dist/FloatDock/FloatDock.exe

**这项为什么要单独存在、且还没进发布链路**：

`installer/verify_app.py` 里的"窗口图标 == floatdock.ico"两项，证明的是
*程序运行时* 会 `LoadImage` 正确的那一层。但它**证明不了**"编译期把图标嵌进
exe 了" —— 资源管理器里那个文件长什么样，取决于 PE 资源段，与运行时无关。
PyInstaller 是通过 `--icon floatdock.ico` 嵌的，参数写在 `installer/build.py`
里，但"参数写了"和"资源真在里面"是两件事，值得单独验一次。

**为什么它现在不在发布链路上**：本轮试了两条路，都没走通 ——
  · 手写 PE 解析：修完一个坑又撞下一个（见下面「本轮实测」）；
  · Win32 现成 API：`ExtractIconExW` / `SHGetFileInfoW` 在本机沙箱下对 exe
    一律返回 0 句柄 / 索引 0，拿不到"系统认为的层数"来交叉印证。
既然无法自证，**就不能把一个未验证的实现挂进发布链路** —— 那等于每次发布
都亮一个不知真假的红灯。宁可单独放着，等下次在正常环境跑一次，验通后再并进
`installer/verify_app.py`。

判据（拿到数据后按这个核对，缺一即 FAIL）：
  1. exe 资源里存在 RT_GROUP_ICON；
  2. 它的各层尺寸覆盖 16 / 32 / 48 / 256（缺层 → 高分屏靠系统放大，显示糊）；
  3. 尺寸与 `floatdock.ico` 的四层一致。

本轮实测记录（2026-10-15，留给下轮省时间）：

**已经查明的（别再重走）**
  · `FloatDock.exe` 资源段 `.rsrc` 存在，vsize 0xE248（约 58 KB）；
  · **资源目录 RVA 在 data directory 第 2 项**（0x4C000，正好是 .rsrc 起点）。
    不要靠记忆定索引：脚本里 `rsrc_rva()` 改成"哪一项的 RVA 落在名为 .rsrc
    的 section 内"，这样换构建器也不会错；
  · 资源树第一层确实有 `RT_ICON(3)` / `RT_GROUP_ICON(14)` / `RT_VERSION(24)` ——
    所以 `--icon floatdock.ico` 是**生效了**的，不是没嵌；
  · `LoadImageW` 只认 .ico/.cur/.bm，**不能直接传 exe 路径**；
  · `ExtractIconExW` 在 **shell32** 不在 user32，且只返回"图标个数"（实测 1），
    不是层数；
  · 沙箱下 `SHGetFileInfoW(..., SHGFI_SYSICONINDEX)` 返回 0，
    所以**本机无法作为验证环境**，这条只能在正常桌面会话跑。

**还卡着的（本轮没做完）**
  · PE 资源目录里，**子目录/数据项的偏移量是"相对资源目录起点"的，不是 RVA**
    —— 把它当 RVA 送进" RVA→文件偏移"的函数里，会得到"不报错、也读不出东西"
    的静默失败，最容易误判成"数据有问题"。这一点已在 `group_icon_sizes()`
    的实现里修正（`walk()` 直接 `base + 相对偏移`）；
  · 修正后仍卡在**第三层**（语言 ID 层）：`RT_GROUP_ICON → ID=1 → 偏移 0x800000E8`
    指向的子目录按 `GRIDDIR` 格式读出来是 0 项，怀疑是 PyInstaller 写的层数
    与结构不一致。**下次从这里继续**：先 `hexdump` 那 16 字节目录项，
    确认 `NumberOfNamedEntries` / `NumberOfIdEntries` 到底是不是按标准布局放的。
  · 若三次修不好，退一步用**第三方库**（如 `pefile`）读，别再手写 —— 这个脚本
    只是"锦上添花的确认"，不值得为它耗时间。
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def pe_sections(d):
    """解析节表，返回 [(name, vaddr, vsize, rawptr, rawsize)]。"""
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optoff = pe + 24
    so = optoff + struct.unpack_from("<H", d, pe + 20)[0]
    out = []
    for i in range(nsec):
        o = so + 40 * i
        name = d[o:o + 8].rstrip(b"\x00").decode("ascii", "replace")
        vsz, va, rsz, ptr = struct.unpack_from("<IIII", d, o + 8)
        out.append((name, va, vsz, ptr, rsz))
    return pe, optoff, out


def data_dirs(d, optoff):
    """返回 data directory 的 16 项 [(rva, size)]。"""
    magic = struct.unpack_from("<H", d, optoff)[0]
    base = optoff + (112 if magic == 0x20B else 96)      # PE32+ / PE32
    return [struct.unpack_from("<II", d, base + i * 8) for i in range(16)]


def rsrc_rva(d):
    """定位资源目录 RVA。

    不写死索引：正常 PE 里资源目录是 data directory 第 2 项，但**索引不能靠
    记忆**（本轮就先把第 1 项当资源、读出一堆垃圾条目又自我怀疑）。这里的
    判据是"哪一项的 RVA 真的落在名为 .rsrc 的 section 里"。
    """
    _pe, optoff, secs = pe_sections(d)
    dirs = data_dirs(d, optoff)
    for idx, (rva, size) in enumerate(dirs):
        if not rva or not size:
            continue
        for name, va, vsz, _ptr, _rsz in secs:
            if name == ".rsrc" and va <= rva < va + vsz:
                return idx, rva
    return None, 0


def group_icon_sizes(path):
    """返回 exe 里 RT_GROUP_ICON 的各层尺寸 [(w, h)]；取不到就报错。

    **最容易错的地方**：PE 资源目录里的偏移量是"**相对资源目录起点**"的，
    不是 RVA，也不是文件偏移。只有根（.rsrc 开头）才需要做 RVA→文件偏移的
    换算。我第一版把子目录偏移当 RVA 传进 `r2o()`，结果"能解析、不报错、
    就是找不到 RT_GROUP_ICON" —— 这种静默失败最容易让人怀疑数据有问题。
    """
    with open(path, "rb") as f:
        d = f.read()
    if d[:2] != b"MZ":
        raise ValueError("不是 PE 文件")
    idx, res_rva = rsrc_rva(d)
    if idx is None:
        raise ValueError("找不到 .rsrc 段")

    _pe, _optoff, secs = pe_sections(d)

    def r2o(rva):
        for _name, va, vsz, ptr, rsz in secs:
            if va <= rva < va + max(vsz, rsz):
                return ptr + (rva - va)
        return None

    base = r2o(res_rva)
    if base is None:
        raise ValueError("资源目录 RVA 0x%X 不在任何 section 内" % res_rva)

    RT_GROUP_ICON = 14
    found = []

    def walk(rel_off, depth):
        """rel_off：相对资源目录起点的偏移（不是 RVA）。"""
        p = base + rel_off
        named, ids = struct.unpack_from("<HH", d, p + 12)
        for i in range(named + ids):
            e = p + 16 + 8 * i
            name_id = struct.unpack_from("<I", d, e)[0]
            child = struct.unpack_from("<I", d, e + 4)[0] & 0x7FFFFFFF
            if depth == 0:
                if name_id == RT_GROUP_ICON:
                    walk(child, 1)
            elif depth == 1:
                dp = base + child               # 数据目录项：同样是相对偏移
                _res, _typ, cnt = struct.unpack_from("<HHH", d, dp)
                for j in range(cnt):
                    w, h = struct.unpack_from("<BB", d, dp + 6 + 14 * j)
                    found.append((w or 256, h or 256))   # 目录里 256 记作 0

    walk(0, 0)
    if not found:
        raise ValueError("资源目录在 data directory[%d] 里，但没有 RT_GROUP_ICON"
                         % idx)
    return found, idx


def ico_sizes(path):
    """列出 .ico 文件里的层尺寸，作为对照。"""
    with open(path, "rb") as f:
        d = f.read()
    _res, kind, cnt = struct.unpack_from("<HHH", d, 0)
    if kind != 1:
        raise ValueError("不是 ICO 文件")
    out = []
    for i in range(cnt):
        w, h = struct.unpack_from("<BB", d, 6 + 16 * i)
        out.append((w or 256, h or 256))
    return sorted(set(out))


def app_exe_name():
    """产物 exe 的名字 —— 从构建脚本里取，不在这里另写一份。

    这个名字由 `installer/build.py` 传给 PyInstaller 的 `--name` 决定，
    **不是产品品牌字样**（品牌串的唯一来源是 `appicon.APP_TITLE`）。
    验证脚本与被它验证的程序是同一棵树，写两遍就等于自己制造假违规。
    """
    import re
    src = open(os.path.join(ROOT, "installer", "build.py"),
               encoding="utf-8").read()
    m = re.search(r'pyinstaller\(\s*"([^"]+)"', src)
    if not m:
        raise SystemExit("installer/build.py 里没找到 pyinstaller() 的产物名，"
                         "请更新本脚本")
    return m.group(1) + ".exe"


def default_exe():
    """默认被测 exe：发布构建产物里的应用本体（onedir，所以是 <name>/<name>.exe）。"""
    name = os.path.splitext(app_exe_name())[0]
    return os.path.join(ROOT, "发布", "_build", "dist", name, app_exe_name())


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else default_exe()
    # 图标路径向 appicon 要，不自己拼—— 全项目"图标在哪"只有那一处声明。
    sys.path.insert(0, ROOT)
    import appicon
    ico = appicon.PATH
    print("被测 exe :", exe)
    print("对照 ico  :", ico)
    print()
    if not os.path.exists(exe):
        print("找不到 exe；先跑 installer/build.py app")
        return 2

    try:
        want = ico_sizes(ico)
        print("floatdock.ico 的层：%s" % (want,))
    except Exception as e:
        print("读不到 floatdock.ico：%s: %s" % (type(e).__name__, e))
        return 2

    try:
        sizes, idx = group_icon_sizes(exe)
    except Exception as e:
        print("\n[未通过] %s: %s" % (type(e).__name__, e))
        print("\n说明：本脚本尚未在真实环境验证过（见文件头「本轮实测记录」）。")
        print("若你是正常桌面会话且这里失败，请把上面的报错连同本段一起反馈。")
        return 1

    got = sorted(set(sizes))
    print("exe 里的层：%s（资源目录在 data directory[%d]）" % (got, idx))
    print()
    ok = True
    for s in want:
        hit = s in got
        print("  %-8s %s" % ("%dx%d" % s, "有" if hit else "缺"))
        ok = ok and hit
    extra = [s for s in got if s not in want]
    print("  多余的层：%s" % (extra or "无"))
    print()
    print("结论：%s" % ("四层齐全且与 floatdock.ico 一致" if ok and not extra
                        else "不一致，需要排查 --icon 参数"))
    return 0 if ok and not extra else 1


if __name__ == "__main__":
    sys.exit(main())