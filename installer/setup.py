# -*- coding: utf-8 -*-
"""星织 Windows 安装程序。

为什么自己写而不是用 Inno Setup / NSIS：
  1. 这台机器上没有装它们，为了打一个包去装一套工具链不划算；
  2. 安装界面可以用项目自己的设计语言（原生 WebView2 窗口），和软件是一套观感；
  3. 安装逻辑本来就是“解压 + 建快捷方式 + 写注册表”，够用且可控。

产物是一个单文件 `Hoshiori-Setup-<版本>.exe`，里面带着打包好的目录版（payload.zip）。
运行时它解压到用户选的位置，建快捷方式，往注册表写“应用和功能”条目，
之后用户可以在 Windows 设置里直接卸载。
"""

import os
import sys
import threading
import traceback
import zipfile

import webview

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_install  # noqa: E402

VERSION = "1.3.0"
FROZEN = getattr(sys, "frozen", False)


def _res(relative):
    """安装器自己的资源（ui.html / payload.zip）。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, relative)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative)


def _payload_zip():
    path = _res("payload.zip")
    if os.path.exists(path):
        return path
    return None


def _payload_dir():
    """开发时直接用目录版产物，不必先打 zip。"""
    guess = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "dist", "Hoshiori")
    return guess if os.path.isdir(guess) else None


class Api:
    def __init__(self):
        self.window = None
        self.install_dir = ""

    # ---------- 给前端的工具方法 ----------

    def _js(self, code):
        try:
            if self.window:
                self.window.evaluate_js(code)
        except Exception:
            pass

    def _progress(self, pct, label):
        self._js("Installer.onProgress({pct:%f,label:%s})" % (pct, _jsstr(label)))

    def _step(self, label, done=False):
        self._js("Installer.onStep(%s,%s)" % (_jsstr(label), "true" if done else "false"))

    # ---------- 暴露给页面 ----------

    def get_defaults(self):
        default = app_install.default_install_dir()
        return {
            "version": VERSION,
            "default_dir": default,
            "free_gb": app_install.free_gb(default),
        }

    def pick_dir(self, current=""):
        try:
            result = self.window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=current or app_install.default_install_dir())
            if result:
                return result[0]
        except Exception as exc:
            print("选择目录失败: %s" % exc)
        return ""

    def install(self, target, desktop=True):
        target = (target or "").strip().strip('"')
        if not target:
            return {"ok": False, "message": "请先选一个安装目录"}

        target = os.path.abspath(os.path.expanduser(target))
        if target.rstrip("\\").lower() in ("c:\\", "c:\\windows", "c:\\program files", "c:\\program files (x86)"):
            return {"ok": False, "message": "这个位置不合适，换一个吧（比如 D:\\Hoshiori）"}

        if not app_install._writable(target):
            return {"ok": False, "message": "这个位置写不进去，换一个目录试试"}

        # 已经在运行就别覆盖，免得文件被占用
        if _is_running():
            return {"ok": False, "message": "星织正在运行，先把她关掉再安装"}

        self.install_dir = target
        threading.Thread(target=self._do_install, args=(target, bool(desktop)), daemon=True).start()
        return {"ok": True}

    def launch_app(self):
        try:
            exe = os.path.join(self.install_dir, "Hoshiori.exe")
            if os.path.exists(exe):
                os.startfile(exe)  # noqa: S606
        except Exception as exc:
            print("启动失败: %s" % exc)

    def close(self):
        try:
            self.window.destroy()
        except Exception:
            os._exit(0)

    # ---------- 真正的安装 ----------

    def _do_install(self, target, desktop):
        try:
            self._progress(1, "准备安装目录")
            self._step("安装目录：%s" % target)

            zip_path = _payload_zip()
            src_dir = _payload_dir()

            if zip_path:
                self._extract_zip(zip_path, target)
            elif src_dir:
                self._copy_dir(src_dir, target)
            else:
                self._js("Installer.onFail('安装包损坏：找不到程序文件')")
                return

            if os.environ.get("HOSHIORI_SETUP_DRY"):
                # 自测模式：只解压，不动快捷方式和注册表
                self._progress(100, "完成（自测）")
                self._js("Installer.onDone(%s)" % _jsstr(target))
                return True

            self._progress(92, "创建快捷方式")
            made = app_install.create_shortcuts(target, desktop=desktop)
            self._step("创建快捷方式（%d 个）" % len(made), True)

            self._progress(96, "登记到「应用和功能」")
            size_kb = _dir_size(target) // 1024
            app_install.write_uninstall_entry(target, VERSION, size_kb)
            self._step("已登记卸载信息", True)

            self._progress(100, "完成")
            self._js("Installer.onDone(%s)" % _jsstr(target))
            return True
        except Exception:
            traceback.print_exc()
            self._js("Installer.onFail('安装过程中出错了，详情见日志')")
            return False

    def _extract_zip(self, zip_path, target):
        with zipfile.ZipFile(zip_path) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            total = len(infos) or 1
            last = 0
            for index, info in enumerate(infos, 1):
                zf.extract(info, target)
                pct = 4 + index / total * 86
                if pct - last >= 0.6:
                    last = pct
                    self._progress(pct, os.path.basename(info.filename))
            self._step("解压了 %d 个文件" % total, True)

    def _copy_dir(self, src, target):
        total = 0
        for _root, _dirs, files in os.walk(src):
            total += len(files)
        total = total or 1
        done = 0
        last = 0
        for root, _dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            out = target if rel == "." else os.path.join(target, rel)
            os.makedirs(out, exist_ok=True)
            for name in files:
                s = os.path.join(root, name)
                d = os.path.join(out, name)
                try:
                    with open(s, "rb") as f:
                        data = f.read()
                    with open(d, "wb") as f:
                        f.write(data)
                except Exception:
                    continue
                done += 1
                pct = 4 + done / total * 86
                if pct - last >= 0.6:
                    last = pct
                    self._progress(pct, name)
        self._step("复制了 %d 个文件" % done, True)


def _jsstr(text):
    return "'" + str(text).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except Exception:
                pass
    return total


def _is_running():
    """用任务列表判断，比遍历窗口可靠（最小化到托盘也算运行中）。"""
    try:
        out = subprocess_run(["tasklist", "/FI", "IMAGENAME eq Hoshiori.exe"])
        return "Hoshiori.exe" in out
    except Exception:
        return False


def subprocess_run(args):
    import subprocess
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=10,
                           creationflags=0x08000000)
        return (p.stdout or "") + (p.stderr or "")
    except Exception:
        return ""


def _option(name, default=None):
    if name in sys.argv:
        index = sys.argv.index(name)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def run_silent():
    """Hoshiori-Setup.exe --silent [--dir D:////Hoshiori] [--no-desktop]

    没有界面，装完就退出，退出码 0 表示成功。给批量部署和自动化测试用。
    """
    target = _option("--dir") or app_install.default_install_dir()
    desktop = "--no-desktop" not in sys.argv
    print("静默安装 ->", target)
    api = Api()
    ok = api._do_install(os.path.abspath(os.path.expanduser(target)), desktop)
    return 0 if ok else 1


def main():
    if "--silent" in sys.argv or "--quiet" in sys.argv:
        sys.exit(run_silent())

    with open(_res("ui.html"), "r", encoding="utf-8") as f:
        html = f.read()

    api = Api()
    window = webview.create_window(
        "星织 安装程序",
        html=html,
        width=760,
        height=566,
        frameless=True,
        easy_drag=True,
        resizable=False,
        background_color="#090c12",
        js_api=api,
    )
    api.window = window

    def _on_closed():
        # 安装完关窗就退出，别在后台留进程
        os._exit(0)

    window.events.closed += _on_closed

    def _dev_show():
        # 开发时快速预览某一步：HOSHIORI_SETUP_SHOW=options
        want = os.environ.get("HOSHIORI_SETUP_SHOW")
        if not want:
            return
        import time as _t
        _t.sleep(2.4)
        try:
            window.evaluate_js("Installer.show('%s')" % want)
            if want == "progress":
                window.evaluate_js("Installer.onProgress({pct:42,label:'texture_00.png'});"
                                   "Installer.onStep('解压了 512 个文件',true)")
        except Exception:
            pass

    threading.Thread(target=_dev_show, daemon=True).start()

    webview.start(private_mode=True, debug=bool(os.environ.get("HOSHIORI_SETUP_DEBUG")))


if __name__ == "__main__":
    main()
