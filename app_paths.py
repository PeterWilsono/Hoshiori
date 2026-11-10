# -*- coding: utf-8 -*-
"""星织的路径策略。

设计出发点只有一句用户的话：数据不要默认落在 C 盘，而且我应该能自己改。

优先级（从高到低）：
1. 环境变量 HOSHIORI_DATA_DIR —— 给高级用户/绿色启动器用
2. %APPDATA%\\Hoshiori\\location.json 里用户自己选过的位置
3. 便携模式：程序目录旁边已经有 baocun / data 目录时，就地存放
4. 自动挑一块非系统盘（D: E: F: ...）根目录下的 HoshioriData
5. 兜底：%USERPROFILE%\\Documents\\Hoshiori（只有真的没有别的盘时才用 C 盘）

这个模块只依赖标准库，并且要在任何重型 import 之前就能用——
因为日志文件的位置就是从这里算出来的。
"""

import json
import os
import shutil
import string
import sys

APP_NAME = "Hoshiori"
DATA_SUBDIR = "HoshioriData"
#: 老版本把数据放在程序目录的 baocun 里，迁移时用得上
LEGACY_NAMES = ("baocun", "data")
#: 自动选址时要求的最小剩余空间
MIN_FREE_BYTES = 200 * 1024 * 1024

_CACHE = {}


# ---------------------------------------------------------------- 程序位置

def app_root():
    """打包后是 exe 所在目录；开发时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def is_onefile():
    """单文件版每次启动都要把 payload 解压到临时目录，启动明显更慢。"""
    if not is_frozen():
        return False
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return False
    return os.path.normcase(os.path.abspath(meipass)) != os.path.normcase(app_root())


def resource_root():
    """只读资源（web、assets）的根目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    return meipass if meipass else app_root()


def resource(*parts):
    return os.path.join(resource_root(), *parts)


# ---------------------------------------------------------------- 引导文件

def boot_candidates():
    """位置配置文件可能落脚的目录，按优先级排。

    正常情况下就是 %APPDATA%\\Hoshiori\\location.json（几十字节）；
    某些环境下 APPDATA 被重定向/只读，所以留几个后备。
    """
    override = (os.environ.get("HOSHIORI_CONFIG_DIR") or "").strip()
    if override:
        return [os.path.abspath(os.path.expanduser(override))]

    candidates = []
    for key in ("APPDATA", "LOCALAPPDATA"):
        base = os.environ.get(key)
        if base:
            candidates.append(os.path.join(base, APP_NAME))

    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, "." + APP_NAME.lower()))
    candidates.append(os.path.join(app_root(), "." + APP_NAME.lower()))
    return candidates


def boot_file():
    """当前实际生效的位置配置文件路径。"""
    for folder in boot_candidates():
        path = os.path.join(folder, "location.json")
        if os.path.exists(path):
            return path
    return os.path.join(boot_candidates()[0], "location.json")


def read_boot():
    for folder in boot_candidates():
        path = os.path.join(folder, "location.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def write_boot(data):
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    for folder in boot_candidates():
        path = os.path.join(folder, "location.json")
        try:
            os.makedirs(folder, exist_ok=True)
            # 直接写。之前用 os.replace 做原子替换，碰上被重定向的 APPDATA
            # 会报 "无法将文件移到不同的磁盘驱动器"（WinError 17）。
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
            return True
        except Exception as exc:
            print("⚠️ 写入位置配置失败(%s): %s" % (folder, exc))
    return False


# ---------------------------------------------------------------- 工具

def _writable(path):
    """真的写一个探针文件，比 os.access 靠谱（Windows 上 ACL 也拦）。"""
    if not path:
        return False
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".hoshiori-write-test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def _free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return 0


def _portable_dir():
    """程序目录旁边已经有数据目录 → 认它是便携模式，别乱搬。"""
    root = app_root()
    for name in LEGACY_NAMES:
        candidate = os.path.join(root, name)
        if not os.path.isdir(candidate):
            continue
        for mark in ("config.json", "conversations.json", "theme_config.json"):
            if os.path.exists(os.path.join(candidate, mark)):
                return candidate
    return None


def _non_system_drive():
    """挑一块可写的非系统盘，返回 X:\\HoshioriData。"""
    system = os.environ.get("SystemDrive", "C:").rstrip("\\").upper()
    for letter in string.ascii_uppercase[2:]:  # 从 D 开始，跳过 A/B
        root = "%s:\\" % letter
        if not os.path.isdir(root):
            continue
        if ("%s:" % letter).upper() == system:
            continue
        target = os.path.join(root, DATA_SUBDIR)
        try:
            if not _writable(target):
                continue
        except Exception:
            continue
        if _free_bytes(root) < MIN_FREE_BYTES:
            try:
                os.rmdir(target)
            except Exception:
                pass
            continue
        return target
    return None


def documents_dir():
    home = os.path.expanduser("~")
    for name in ("Documents", "文档"):
        candidate = os.path.join(home, name)
        if os.path.isdir(candidate):
            return os.path.join(candidate, APP_NAME)
    return os.path.join(home, APP_NAME)


# ---------------------------------------------------------------- 数据目录

def resolve_data_dir():
    """算一遍该用哪个目录（不创建、不缓存）。"""
    override = (os.environ.get("HOSHIORI_DATA_DIR") or "").strip().strip('"')
    if override:
        override = os.path.abspath(os.path.expanduser(override))
        if _writable(override):
            return override

    chosen = (read_boot().get("data_dir") or "").strip()
    if chosen:
        chosen = os.path.abspath(os.path.expanduser(chosen))
        if _writable(chosen):
            return chosen
        print("⚠️ 上次设定的数据目录不可用: %s" % chosen)

    portable = _portable_dir()
    if portable:
        return portable

    drive = _non_system_drive()
    if drive:
        return drive

    return documents_dir()


def data_dir():
    """当前数据目录（带缓存，已保证存在且可写）。"""
    if "data" in _CACHE:
        return _CACHE["data"]
    path = resolve_data_dir()
    if not _writable(path):
        fallback = documents_dir()
        print("⚠️ 数据目录不可写，回退到 %s" % fallback)
        path = fallback if _writable(fallback) else app_root()
    _CACHE["data"] = path
    return path


def set_data_dir(path, migrate=True):
    """用户指定新的数据目录。返回 (是否成功, 提示语)。"""
    if not path or not str(path).strip():
        return False, "没有选择目录"

    path = os.path.abspath(os.path.expanduser(str(path).strip().strip('"')))
    if is_frozen() and os.path.normcase(path) == os.path.normcase(resource_root()):
        return False, "不能选程序自己的资源目录"

    if not _writable(path):
        return False, "这个位置不可写，换一个试试（比如 D:\\HoshioriData）"

    if migrate:
        copied = migrate_from(data_dir(), path)

    boot = read_boot()
    boot["data_dir"] = path
    boot["updated_at"] = _now()
    if not write_boot(boot):
        return False, "没能记住这个位置，请重试"

    _CACHE["data"] = path
    suffix = "，已搬运 %d 个文件" % copied if copied else ""
    return True, "数据目录已切换到 %s%s" % (path, suffix)


def migrate_from(source, target):
    """把旧目录里的存档复制到新目录（不覆盖已有文件）。"""
    if not source or not target:
        return 0
    source = os.path.abspath(source)
    target = os.path.abspath(target)
    if os.path.normcase(source) == os.path.normcase(target) or not os.path.isdir(source):
        return 0

    copied = 0
    try:
        entries = os.listdir(source)
    except Exception:
        return 0

    for name in entries:
        if name.endswith(".log") or name.startswith("."):
            continue
        src = os.path.join(source, name)
        dst = os.path.join(target, name)
        if os.path.exists(dst):
            continue
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            copied += 1
        except Exception as exc:
            print("⚠️ 迁移 %s 失败: %s" % (name, exc))
    return copied


def reset_data_dir():
    """忘掉用户设定，回到自动选址。"""
    boot = read_boot()
    boot.pop("data_dir", None)
    write_boot(boot)
    _CACHE.pop("data", None)


# ---------------------------------------------------------------- 常用子路径

def _sub(name):
    path = os.path.join(data_dir(), name)
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def log_dir():
    return _sub("logs")


def log_file():
    return os.path.join(log_dir(), "app.log")


def webview_dir():
    return _sub(os.path.join("runtime", "webview"))


def open_path(path):
    """用资源管理器打开某个目录 / 选中某个文件。"""
    try:
        if os.path.isfile(path):
            os.startfile(os.path.dirname(path))  # noqa: S606
        else:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # noqa: S606
        return True
    except Exception as exc:
        print("⚠️ 打开目录失败: %s" % exc)
        return False


def describe():
    """给前端看的一份路径说明。"""
    return {
        "data_dir": data_dir(),
        "log_dir": log_dir(),
        "app_dir": app_root(),
        "boot_file": boot_file(),
        "portable": bool(_portable_dir()),
        "on_system_drive": data_dir().upper().startswith(
            (os.environ.get("SystemDrive", "C:").rstrip("\\").upper() + ":",)),
        "onefile": is_onefile(),
    }


def _now():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
