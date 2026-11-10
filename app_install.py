# -*- coding: utf-8 -*-
"""安装 / 卸载相关的系统集成。

安装程序（installer/setup.py）和主程序（main.py --uninstall）都要用到：
写注册表的“应用和功能”条目、建/删快捷方式、以及把安装目录整个删掉。
放在一个模块里，两边就不会各写一套。
"""

import ctypes
import os
import subprocess
import sys

APP_NAME = "星织"
APP_NAME_EN = "Hoshiori"
APP_ID = "Hoshiori"
PUBLISHER = "Hoshiori"

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\%s" % APP_ID


# ---------------------------------------------------------------- 位置

def _home():
    return os.path.expanduser("~")


def desktop_dir():
    # 中文系统的桌面目录可能被重定向，先读注册表里的真实位置
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        value, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        return os.path.expandvars(value)
    except Exception:
        return os.path.join(_home(), "Desktop")


def start_menu_dir():
    base = os.environ.get("APPDATA") or os.path.join(_home(), "AppData", "Roaming")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")


def default_install_dir():
    """默认装到非系统盘；没有别的盘时退回用户目录下的 Programs。"""
    system = (os.environ.get("SystemDrive") or "C:").rstrip("\\").upper()
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        drive = "%s:\\" % letter
        if not os.path.isdir(drive):
            continue
        if letter == system[0]:
            continue
        target = os.path.join(drive, APP_NAME_EN)
        if _writable(target):
            return target

    base = os.environ.get("LOCALAPPDATA") or os.path.join(_home(), "AppData", "Local")
    return os.path.join(base, "Programs", APP_NAME_EN)


def _writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        try:
            os.rmdir(path)
        except Exception:
            pass
        return False


def free_gb(path):
    try:
        drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
        free = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(drive), None, None, ctypes.byref(free))
        return free.value / (1024.0 ** 3)
    except Exception:
        return 0.0


# ---------------------------------------------------------------- 快捷方式

def _shortcut_paths(desktop=True):
    paths = [os.path.join(start_menu_dir(), "%s.lnk" % APP_NAME)]
    if desktop:
        paths.insert(0, os.path.join(desktop_dir(), "%s.lnk" % APP_NAME))
    return paths


def create_shortcuts(install_dir, desktop=True):
    exe = os.path.join(install_dir, "%s.exe" % APP_NAME_EN)
    made = []
    for path in _shortcut_paths(desktop):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        ps = (
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
            "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';"
            "$s.Description='%s';$s.Save()"
        ) % (_ps(path), _ps(exe), _ps(install_dir), _ps(exe), _ps(APP_NAME))
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                creationflags=0x08000000, timeout=30,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(path):
                made.append(path)
        except Exception as exc:
            print("⚠️ 创建快捷方式失败 %s: %s" % (path, exc))
    return made


def remove_shortcuts():
    for path in _shortcut_paths(True):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def _ps(text):
    return str(text).replace("'", "''")


# ---------------------------------------------------------------- 注册表

def write_uninstall_entry(install_dir, version, size_kb=0):
    try:
        import winreg
        exe = os.path.join(install_dir, "%s.exe" % APP_NAME_EN)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "%s %s" % (APP_NAME, APP_NAME_EN))
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, exe + ",0")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, '"%s" --uninstall' % exe)
            winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, '"%s" --uninstall --quiet' % exe)
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
            if size_kb:
                winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))
        return True
    except Exception as exc:
        print("⚠️ 写入卸载信息失败: %s" % exc)
        return False


def remove_uninstall_entry():
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 卸载

def is_uninstall_request(argv=None):
    argv = argv if argv is not None else sys.argv
    return "--uninstall" in argv


def _confirm(title, text):
    try:
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        MB_TOPMOST = 0x40000
        res = ctypes.windll.user32.MessageBoxW(
            None, text, title, MB_YESNO | MB_ICONWARNING | MB_TOPMOST)
        return res == 6  # IDYES
    except Exception:
        return True


def run_uninstall(install_dir, quiet=False):
    """确认后：删快捷方式、删注册表、让一个独立进程等本进程退出后删目录。"""
    if not quiet:
        text = (
            "要把 %s 从这台电脑上移除吗？\n\n"
            "程序文件会被删除：%s\n\n"
            "注意：你的对话和设置保存在数据目录里，不会被删掉。"
            % (APP_NAME, install_dir)
        )
        if not _confirm("卸载 %s" % APP_NAME, text):
            return False

    remove_shortcuts()
    remove_uninstall_entry()

    # 自己删不掉自己：写一个临时 bat，等本进程退出后重试着删，
    # 删干净了自己也退出（比 cmd 单行命令可靠得多，文件被占用时还会重试）
    try:
        bat = os.path.join(os.environ.get("TEMP") or os.path.expanduser("~"), "hoshiori-uninstall.bat")
        lines = [
            "@echo off",
            ":retry",
            "ping -n 2 127.0.0.1 >nul",
            'rmdir /s /q "%s" 2>nul' % install_dir,
            'if exist "%s" goto retry' % install_dir,
            'del "%~f0"',
        ]
        # newline="" 自己控制换行：文本模式下写 \r\n 会变成 \r\r\n，bat 直接跑不动。
        # mbcs 跟系统 ANSI 代码页走，中文路径在 cmd 里才认得出来。
        with open(bat, "w", encoding="mbcs", errors="replace", newline="") as f:
            f.write("\r\n".join(lines) + "\r\n")
        subprocess.Popen(
            ["cmd", "/c", bat],
            creationflags=0x00000008 | 0x00000200,  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            close_fds=True)
    except Exception as exc:
        print("⚠️ 无法启动清理进程: %s" % exc)

    return True
