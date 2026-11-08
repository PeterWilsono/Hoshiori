# -*- coding: utf-8 -*-
"""窗口壳：把 Edge / Chrome 的 --app 窗口变成星织自己的窗口。

Chromium 的 ``--app`` 模式依然会带一条系统标题栏，而 ``--kiosk`` 又会
被 ``--app`` 覆盖掉，所以 eel 默认那套参数永远会留下一条「浏览器边框」。

这里的做法是：自己拉起浏览器，等窗口出现后用 Win32 API 摘掉标题栏、
按比例摆好位置，并把「拖动 / 最小化」交给系统处理，界面上那条 38px
的窗口栏就成了真正的标题栏。
"""

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------- Win32 常量
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000

SW_MINIMIZE = 6
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

WM_CLOSE = 0x0010
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2

SPI_GETWORKAREA = 0x0030
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2

APP_TITLE_HINT = "星织"

_user32 = ctypes.WinDLL("user32", use_last_error=True) if IS_WINDOWS else None
_dwmapi = ctypes.WinDLL("dwmapi") if IS_WINDOWS else None

_app_hwnd = None


# ---------------------------------------------------------------- DPI
def enable_dpi_awareness():
    """让本进程拿到物理像素，SetWindowPos 才不会在缩放屏上错位。"""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ---------------------------------------------------------------- 窗口枚举
def list_windows():
    """返回当前所有可见的 Chromium 顶层窗口 [(hwnd, title)]。"""
    found = []
    if not IS_WINDOWS:
        return found

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        try:
            if not _user32.IsWindowVisible(hwnd):
                return True
            length = _user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            cls = ctypes.create_unicode_buffer(128)
            _user32.GetClassNameW(hwnd, cls, 128)
            if cls.value == "Chrome_WidgetWin_1":
                found.append((hwnd, buf.value))
        except Exception:
            pass
        return True

    try:
        _user32.EnumWindows(_cb, 0)
    except Exception:
        return []
    return found


def find_by_title(keyword=APP_TITLE_HINT, timeout=20.0, sleep=None):
    """按标题找一个可见的顶层窗口（pywebview 的窗口也适用）。"""
    global _app_hwnd

    if sleep is None:
        sleep = time.sleep

    deadline = time.time() + timeout
    while time.time() < deadline:
        if IS_WINDOWS:
            hits = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def _cb(hwnd, _lparam):
                try:
                    if not _user32.IsWindowVisible(hwnd):
                        return True
                    length = _user32.GetWindowTextLengthW(hwnd)
                    if length:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        _user32.GetWindowTextW(hwnd, buf, length + 1)
                        if keyword in buf.value:
                            hits.append(hwnd)
                except Exception:
                    pass
                return True

            try:
                _user32.EnumWindows(_cb, 0)
            except Exception:
                hits = []

            for hwnd in hits:
                # 跳过 Chromium 的子窗口（尺寸极小的那种）
                rect = wintypes.RECT()
                if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    if rect.right - rect.left < 200:
                        continue
                parent = _user32.GetParent(hwnd)
                if parent:
                    continue
                _app_hwnd = hwnd
                print(f"✅ 已绑定窗口 hwnd={hwnd}")
                return hwnd
        sleep(0.2)
    return None


def _work_area():
    rect = wintypes.RECT()
    if IS_WINDOWS and _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, 1920, 1080


# ---------------------------------------------------------------- 启动
def find_browser():
    """优先 Edge，其次 Chrome。"""
    candidates = [
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ]
    for raw in candidates:
        path = os.path.expandvars(raw)
        if path and os.path.exists(path):
            return path
    return None


def launch(url, width=1300, height=900):
    """用独立 profile 拉起一个干净的浏览器应用窗口。"""
    exe = find_browser()
    if not exe:
        print("⚠️ 没找到 Edge / Chrome，无法创建应用窗口")
        return None

    profile = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "Hoshiori",
        "runtime",
    )
    try:
        os.makedirs(profile, exist_ok=True)
    except Exception:
        pass

    args = [
        exe,
        "--app=%s" % url,
        "--window-size=%d,%d" % (width, height),
        "--user-data-dir=%s" % profile,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-http-cache",
        # 关掉一切浏览器痕迹：翻译气泡、侧栏、账号、信息栏、默认应用
        "--disable-features=Translate,TranslateUI,msEdgeTranslate,"
        "msEdgeSidebarV2,msEdgeIdentityFeatures,msEdgeCollections,"
        "msEdgeReadAloud,msEdgeShoppingAssistant,EdgeCollections",
        "--disable-translate",
        "--no-service-autorun",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-background-mode",
        "--disable-default-apps",
        "--disable-infobars",
        "--noerrdialogs",
        "--disable-component-update",
        "--disable-background-networking",
        "--lang=zh-CN",
        # 页面还没画出来时用夜色打底，避免白屏闪一下
        "--default-background-color=090C12",
    ]

    creationflags = 0x08000000  # CREATE_NO_WINDOW
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        print(f"🪟 已启动应用窗口: {os.path.basename(exe)}")
        return proc
    except Exception as e:
        print(f"⚠️ 启动浏览器失败: {e}")
        return None


# ---------------------------------------------------------------- 去边框
def _strip_frame(hwnd, width, height):
    try:
        style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
        # 去掉标题栏与系统菜单；保留 WS_THICKFRAME，边缘仍可拉伸
        style &= ~(WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        _user32.SetWindowLongW(hwnd, GWL_STYLE, style)

        left, top, right, bottom = _work_area()
        avail_w = right - left
        avail_h = bottom - top
        w = min(width, int(avail_w * 0.94))
        h = min(height, int(avail_h * 0.94))
        x = left + (avail_w - w) // 2
        y = top + (avail_h - h) // 2

        _user32.SetWindowPos(
            hwnd, 0, x, y, w, h,
            SWP_FRAMECHANGED | SWP_NOZORDER | SWP_SHOWWINDOW,
        )

        # Windows 11 圆角
        if _dwmapi:
            try:
                pref = ctypes.c_int(DWMWCP_ROUND)
                _dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(pref),
                    ctypes.sizeof(pref),
                )
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"⚠️ 窗口去边框失败: {e}")
        return False


def adopt(existing_hwnds, width=1300, height=900, timeout=30.0, sleep=None):
    """等待新窗口出现并接管它。

    ``sleep`` 由调用方注入：eel 跑在 gevent 上，等待窗口时必须让出调度，
    否则 bottle 的 greenlet 拿不到执行机会，页面会一直连不上。
    """
    global _app_hwnd

    if sleep is None:
        sleep = time.sleep

    existing = set(existing_hwnds or [])
    deadline = time.time() + timeout

    while time.time() < deadline:
        # 只认标题带「星织」的新窗口。
        # Edge 可能同时弹出「翻译此页面」之类的小窗，认错就会在它消失时误判程序已退出。
        candidates = [
            (h, t) for h, t in list_windows()
            if h not in existing and APP_TITLE_HINT in (t or "")
        ]
        if candidates:
            chosen = candidates[0][0]
            # 等页面稍微加载一下再改样式，避免和 Chromium 抢窗口状态
            sleep(0.5)
            if _strip_frame(chosen, width, height):
                _app_hwnd = chosen
                print(f"✅ 已接管窗口 hwnd={chosen}")
                return chosen
        sleep(0.15)

    print("⚠️ 没有等到浏览器窗口")
    return None


# ---------------------------------------------------------------- 控制
def begin_drag():
    """拖动窗口（前端窗口栏按下时调用）。

    pywebview 用的是 WinForms 窗口，发 WM_NCLBUTTONDOWN 不会进入系统的移动循环，
    所以这里自己捕获鼠标：按住期间跟着光标走 SetWindowPos，松开就停。
    """
    if not _app_hwnd:
        return False

    try:
        hwnd = _app_hwnd
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))

        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False

        # 光标相对窗口左上角的偏移，拖动时保持不变
        offset_x = pt.x - rect.left
        offset_y = pt.y - rect.top

        print(f"🖱 开始拖动 hwnd={hwnd} from ({pt.x},{pt.y})")

        _user32.SetCapture(hwnd)
        try:
            while _user32.GetAsyncKeyState(0x01) & 0x8000:
                _user32.GetCursorPos(ctypes.byref(pt))
                _user32.SetWindowPos(
                    hwnd, 0,
                    pt.x - offset_x, pt.y - offset_y,
                    0, 0,
                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
                )
                time.sleep(0.012)
        finally:
            _user32.ReleaseCapture()
        return True
    except Exception as e:
        print(f"⚠️ 拖动失败: {e}")
        return False


def minimize():
    if not _app_hwnd:
        return False
    try:
        _user32.ShowWindow(_app_hwnd, SW_MINIMIZE)
        return True
    except Exception:
        return False


def close_window():
    global _app_hwnd
    if not _app_hwnd:
        return False
    try:
        _user32.PostMessageW(_app_hwnd, WM_CLOSE, 0, 0)
        _app_hwnd = None
        return True
    except Exception:
        return False


def is_alive():
    if not _app_hwnd:
        return False
    try:
        return bool(_user32.IsWindow(_app_hwnd))
    except Exception:
        return False


def has_window():
    return _app_hwnd is not None
