# -*- coding: utf-8 -*-
"""收拾 WebView2 漏在后台的进程。

## 为什么需要它

窗口是 pywebview 的 WebView2。正常关窗时它会自己退干净，但如果进程被
强杀——任务管理器结束任务、崩溃、调试时 kill——`msedgewebview2.exe`
会留在后台，而且不是一个：浏览器进程带一窝渲染进程和 GPU 进程。

这些孤儿握着两样东西：

1. `user-data-dir`（数据目录下的 runtime/webview），导致这个目录删不掉；
2. 页面资源的句柄，表现是「改 web/js 下的文件提示 Permission denied，
   但文件属性明明是「可写」，`os.access` 也返回 True」。

第 2 条特别迷惑人：属性、ACL、磁盘权限全都正常，只有真正写入时才被拒，
第一反应会以为文件只读或者杀毒软件在拦。这次排查就被它坑了一轮。

## 做两件事

- `sweep_stale()`：启动后把指向上次那个 user-data-dir、且父进程已经不在的
  进程清掉。
- `kill_children()`：退出时把自己拉起来的子进程树收干净，别留尾巴。

## 为什么不用 PowerShell 一把梭

实测一次 `Get-CimInstance Win32_Process` 要 1.2 秒，`Get-Process` 0.9 秒，
拼起来 5 秒多——放启动路径上不可接受。所以先用 kernel32 的进程快照
（十几毫秒）把"名字对得上、父进程已经没了"的挑出来，通常一个都没有，
直接返回；真挑出来了才去查命令行确认是不是我们的。

命令行是唯一能区分"我们的 WebView2"和"别人家应用的 WebView2"，
这一步不能省，但只在有候选时发生。
"""

import ctypes
import json
import os
import subprocess
import sys
from ctypes import wintypes

__all__ = ["sweep_stale", "kill_children", "snapshot", "main"]

#: 清扫时只认 WebView2 —— 它才是主窗口那条路。
#: 不带 msedge.exe：Edge 自己有个 "--no-startup-window /prefetch" 常驻进程，
#: 父进程经常早就不在了，每次都会被当成候选，白查一遍命令行（1.3 秒）。
WEBVIEW_NAME = "msedgewebview2.exe"

#: 退出时还可能存在的、我们自己拉起来的进程。
#: msedge / chrome 是窗口 shell 的兜底模式，它们有 proc 句柄，也不靠命令行判断。
SHELL_NAMES = {"msedgewebview2.exe", "msedge.exe", "chrome.exe"}

_CREATE_NO_WINDOW = 0x08000000
_TH32CS_SNAPPROCESS = 0x00000002
_MAX_PATH = 260


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * _MAX_PATH),
    ]


def snapshot():
    """枚举当前所有进程：[(pid, ppid, exe_name)]。失败返回空表。"""
    if not hasattr(ctypes, "windll"):
        return []

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]

    handle = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if handle == wintypes.HANDLE(-1).value:
        return []

    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)

    rows = []
    try:
        ok = k32.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            rows.append((int(entry.th32ProcessID),
                         int(entry.th32ParentProcessID),
                         (entry.szExeFile or "").strip().lower()))
            ok = k32.Process32NextW(handle, ctypes.byref(entry))
    finally:
        k32.CloseHandle(handle)
    return rows


# ---------------------------------------------------------------- 命令行
def _powershell():
    root = os.environ.get("SystemRoot", r"C:\Windows")
    exe = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return exe if os.path.isfile(exe) else "powershell"


def _commands_of(pids):
    """查这几个进程的命令行。只在有候选时调用，慢一点没关系。"""
    if not pids:
        return {}
    cond = " or ".join("ProcessId=%d" % int(p) for p in pids)
    script = (
        "$out=@();"
        "foreach ($p in (Get-CimInstance Win32_Process -Filter \"%s\" "
        "-ErrorAction SilentlyContinue)) {"
        "  $out += [pscustomobject]@{procId=[int]$p.ProcessId; cmd=[string]$p.CommandLine}"
        "};"
        "if ($out.Count -eq 0) { '[]' } else { $out | ConvertTo-Json -Compress -Depth 3 }"
    ) % cond

    try:
        proc = subprocess.run(
            [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=12,
            creationflags=_CREATE_NO_WINDOW,
        )
        data = json.loads((proc.stdout or "").strip() or "[]")
    except Exception:
        return {}
    if isinstance(data, dict):
        data = [data]
    return {int(d["procId"]): (d.get("cmd") or "") for d in data if "procId" in d}


def _kill(pid):
    try:
        # /T 连子进程一起收，否则渲染进程会变成新的孤儿
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(int(pid))],
            capture_output=True, timeout=15, creationflags=_CREATE_NO_WINDOW,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 对外
def _orphan_candidates():
    """名字对得上、父进程已经不在的浏览器进程。"""
    rows = snapshot()
    alive = {pid for pid, _ppid, _exe in rows}
    me = os.getpid()
    out = []
    for pid, ppid, exe in rows:
        if exe != WEBVIEW_NAME:
            continue
        if pid == me or ppid == me:
            # 自己，或者自己刚拉起来的那个。这里显式排除，不依赖
            # "自己一定出现在快照里"——万一快照漏了，就会把自己的窗口杀掉。
            continue
        # 父进程还活着 → 那是别人正在跑的程序，不是孤儿
        if ppid in alive:
            continue
        out.append(pid)
    return out


def sweep_stale(user_data_dir, verbose=True):
    """清掉上次留下的孤儿。返回清掉的数量。

    判据两条，宁漏勿错：父进程已经不在，且命令行里的 user-data-dir
    确实是我们的。第二条要查命令行，所以放在候选筛完之后。
    """
    if not user_data_dir:
        return 0
    key = os.path.normcase(os.path.abspath(user_data_dir)).lower()
    if not key:
        return 0

    pids = _orphan_candidates()
    if not pids:
        return 0

    killed = 0
    for pid, cmd in _commands_of(pids).items():
        if key not in cmd.lower():
            continue
        if _kill(pid):
            killed += 1
            if verbose:
                print("🧹 清掉一个上次没退干净的窗口进程 (PID %d)" % pid)

    if killed and verbose:
        print("🧹 共清理 %d 个残留进程，文件占用已释放" % killed)
    return killed


def kill_children(verbose=True):
    """收掉自己拉起来的子进程树（退出时调用）。

    只认父进程号等于当前进程的——另一个实例的 WebView2 父号是别人，
    不会被误伤。用快照，十几毫秒。
    """
    me = os.getpid()
    targets = [pid for pid, ppid, exe in snapshot()
               if ppid == me and exe in SHELL_NAMES]
    killed = 0
    for pid in targets:
        if _kill(pid):
            killed += 1
    if killed and verbose:
        print("🧹 已收掉 %d 个窗口进程" % killed)
    return killed


# ---------------------------------------------------------------- 命令行
def main(argv=None):
    """手动跑：清理当前数据目录下的残留。

    开发时改前端被锁住，在项目里执行 `python runtime_guard.py` 就行，
    不用去任务管理器里翻进程。
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    target = next((a for a in argv if not a.startswith("-")), None)
    if target is None:
        try:
            import app_paths
            target = app_paths.webview_dir()
        except Exception:
            target = None

    if not target:
        print("没找到窗口数据目录，无法判断哪些进程是我们的")
        return 1

    print("窗口数据目录: %s" % target)

    pids = _orphan_candidates()
    if not pids:
        print("没有处于孤儿状态的窗口进程")
        return 0

    print("候选进程: %s" % ", ".join(str(p) for p in pids))
    killed = sweep_stale(target)
    if not killed:
        print("这些进程不是我们的（user-data-dir 对不上），没有动它们")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
