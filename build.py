# -*- coding: utf-8 -*-
"""打包脚本 —— 一次产出两个版本。

    python build.py            # 两个版本都打
    python build.py dir        # 只打目录版（推荐，启动快）
    python build.py onefile    # 只打单文件版（便携，启动要解压）

产物：
    dist/Hoshiori/Hoshiori.exe         目录版，启动约 2 秒，解压到哪就装在哪
    dist/Hoshiori.exe                  单文件版，单文件便携，每次启动要先解压
    dist/Hoshiori-<版本>-win64.zip     目录版的压缩包（发给别人用这个）

为什么有两个版本：单文件版每次启动都要把几十 MB 运行时解到临时目录，
这是 PyInstaller 的机制，20 秒里大部分花在这儿；目录版免掉这一步，
代价是旁边多一个 _internal 文件夹。
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")

sys.path.insert(0, ROOT)
from version import VERSION  # noqa: E402  版本号唯一来源

APP = "Hoshiori"

COMMON_ARGS = [
    "--noconfirm",
    "--windowed",
    "--name", APP,
    "--icon", os.path.join(ROOT, "app_icon.ico"),
    "--add-data", os.path.join(ROOT, "web") + os.pathsep + "web",
    # 本地语义模型（bge-small-zh 量化版，24MB）：只读资源，随包发出去
    "--add-data", os.path.join(ROOT, "models", "bge-small-zh")
    + os.pathsep + os.path.join("models", "bge-small-zh"),
    # version.py 是在 try/except 里导入的，PyInstaller 的静态分析找不到它，
    # 不显式声明的话，打包后 import 会失败、版本号退回兜底值
    "--hidden-import", "version",
    # 语义检索是可选能力：embedder 在 try/except 里导入，静态分析同样看不到
    "--hidden-import", "embedder",
    "--hidden-import", "bert_tokenizer",
    "--hidden-import", "safety",
    "--hidden-import", "onnxruntime",
    "--hidden-import", "onnxruntime.capi._pybind_state",
    "--collect-binaries", "onnxruntime",
    # eel 的服务端组件都是延迟导入的，PyInstaller 静态分析看不到
    "--hidden-import", "eel",
    "--hidden-import", "bottle",
    "--hidden-import", "bottle_websocket",
    "--hidden-import", "gevent",
    "--hidden-import", "geventwebsocket",
    "--hidden-import", "webview.platforms.winforms",
    # 系统语音（SAPI）走 pywin32 的 COM，是 import 在函数里的，静态分析看不到
    "--hidden-import", "win32com",
    "--hidden-import", "win32com.client",
    "--hidden-import", "pythoncom",
    "--hidden-import", "pywintypes",
    # pywebview 在 Windows 上依赖 pythonnet / clr_loader 原生库
    "--collect-all", "webview",
    "--collect-all", "pythonnet",
    "--collect-all", "clr_loader",
    # 这些库本项目不用，带上会让包大一圈（numpy 现在要留着，语义模型靠它）。
    # torch 是重点：一旦 numpy 被包含，PyInstaller 会顺着某些 hook 把它整个拖进来，
    # 单它一个就 260MB。项目只跑 ONNX，不需要它。
    "--exclude-module", "torch",
    "--exclude-module", "torchvision",
    "--exclude-module", "torchaudio",
    "--exclude-module", "transformers",
    "--exclude-module", "matplotlib",
    "--exclude-module", "pandas",
    "--exclude-module", "scipy",
    "--exclude-module", "sklearn",
    "--exclude-module", "numba",
    "--exclude-module", "llvmlite",
    # 本机 site-packages 里躺着一份坏掉的 tensorflow（版本号读不出来），
    # 它的 hook 一被加载就抛异常，整个打包直接失败。项目根本不用它，排掉。
    "--exclude-module", "tensorflow",
    "--exclude-module", "tensorflow_estimator",
    "--exclude-module", "tensorflow_io_gcs_filesystem",
    "--exclude-module", "keras",
]


def run_pyinstaller(mode):
    # 两种模式的中间产物必须分开放：共用 workpath 时后一次会撞上被占用的 PYZ-00.pyz
    args = [sys.executable, "-m", "PyInstaller"] + COMMON_ARGS
    spec_dir = os.path.join(BUILD, "spec-" + mode)
    args += [
        "--distpath", DIST,
        "--workpath", os.path.join(BUILD, "work-" + mode),
        "--specpath", spec_dir,
    ]

    # PyInstaller 生成 spec 时会覆盖同名文件；某些安全软件/沙箱会拦住这个覆盖，
    # 直接报 PermissionError。先自己删掉，让它新建。
    stale_spec = os.path.join(spec_dir, APP + ".spec")
    if os.path.exists(stale_spec):
        try:
            os.remove(stale_spec)
        except OSError as exc:
            print("⚠️ 删不掉旧 spec（%s），继续尝试" % exc)

    if mode == "onefile":
        args += ["--onefile", "--splash", os.path.join(ROOT, "splash.png")]
    else:
        args += ["--onedir"]

    args.append(os.path.join(ROOT, "main.py"))

    print("\n$ " + " ".join(args[:6]) + f" ... ({mode})")
    started = time.time()
    subprocess.run(args, cwd=ROOT, check=True)
    print("✓ %s 打包完成，用时 %.1f 秒" % (mode, time.time() - started))


def stash_old_output():
    """PyInstaller 重建目录版时会先整目录删掉，某些安全策略会拦下来。

    改个做法：把旧产物整体挪到临时目录（一次 rename，很快），
    让 PyInstaller 从零生成一个干净的目录。
    """
    target = os.path.join(DIST, APP)
    if not os.path.isdir(target):
        return
    # 必须在同一个盘里 rename：跨盘会退化成“复制 + 逐个删除”，
    # 那样又会撞上批量删除的保护，反而把产物删一半。
    trash = os.path.join(BUILD, "old-%d" % int(time.time()))
    os.makedirs(BUILD, exist_ok=True)
    try:
        os.rename(target, trash)
        print("旧产物已移到 %s" % trash)
    except Exception as exc:
        print("⚠️ 没能移走旧产物: %s" % exc)


def build_installer():
    """用目录版产物做安装包：payload.zip 塞进 setup.exe 里。"""
    payload_dir = os.path.join(DIST, APP)
    if not os.path.isdir(payload_dir):
        print("⚠️ 没有目录版产物，先跑 python build.py dir")
        return None

    stage = os.path.join(BUILD, "installer")
    os.makedirs(stage, exist_ok=True)
    zip_path = os.path.join(stage, "payload.zip")

    print("📦 打包安装负载 ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for base, _dirs, files in os.walk(payload_dir):
            for name in files:
                full = os.path.join(base, name)
                zf.write(full, os.path.relpath(full, payload_dir))
    print("   payload.zip %.1f MB" % (os.path.getsize(zip_path) / 1024 / 1024))

    name = "%s-Setup-%s" % (APP, VERSION)
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--windowed", "--onefile",
        "--name", name,
        "--icon", os.path.join(ROOT, "app_icon.ico"),
        "--add-data", os.path.join(ROOT, "installer", "ui.html") + os.pathsep + ".",
        "--add-data", zip_path + os.pathsep + ".",
        "--paths", ROOT,
        "--hidden-import", "app_install",
        "--hidden-import", "version",
        "--collect-all", "webview",
        "--collect-all", "pythonnet",
        "--collect-all", "clr_loader",
        "--distpath", DIST,
        "--workpath", os.path.join(BUILD, "work-installer"),
        "--specpath", os.path.join(BUILD, "spec-installer"),
        os.path.join(ROOT, "installer", "setup.py"),
    ]
    started = time.time()
    subprocess.run(args, cwd=ROOT, check=True)
    print("✓ 安装包完成，用时 %.1f 秒" % (time.time() - started))
    return os.path.join(DIST, name + ".exe")


def make_zip():
    """目录版打成 zip：别人解压到任意位置就等于“安装”到任意位置。"""
    src = os.path.join(DIST, APP)
    if not os.path.isdir(src):
        print("⚠️ 没有目录版产物，跳过压缩")
        return None

    out = os.path.join(DIST, "%s-%s-win64.zip" % (APP, VERSION))
    if os.path.exists(out):
        os.remove(out)

    print("📦 正在压缩 %s ..." % out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for base, _dirs, files in os.walk(src):
            for name in files:
                full = os.path.join(base, name)
                rel = os.path.join(APP, os.path.relpath(full, src))
                zf.write(full, rel)
    print("✓ %s (%.1f MB)" % (out, os.path.getsize(out) / 1024 / 1024))
    return out


def report():
    print("\n产物：")
    for name in (APP, APP + ".exe", "%s-Setup-%s.exe" % (APP, VERSION)):
        path = os.path.join(DIST, name)
        if os.path.isdir(path):
            total = sum(os.path.getsize(os.path.join(b, f))
                        for b, _d, fs in os.walk(path) for f in fs)
            print("  %-28s 目录   %.1f MB" % (name + "/", total / 1024 / 1024))
        elif os.path.isfile(path):
            print("  %-28s 单文件 %.1f MB" % (name, os.path.getsize(path) / 1024 / 1024))


def main():
    parser = argparse.ArgumentParser(description="打包星织")
    parser.add_argument("mode", nargs="?", default="all",
                        choices=["all", "dir", "onefile", "installer"])
    args = parser.parse_args()

    os.makedirs(DIST, exist_ok=True)
    os.makedirs(os.path.join(BUILD, "spec-dir"), exist_ok=True)
    os.makedirs(os.path.join(BUILD, "spec-onefile"), exist_ok=True)

    if args.mode in ("all", "dir"):
        stash_old_output()
        run_pyinstaller("dir")
    if args.mode in ("all", "installer"):
        build_installer()
    if args.mode in ("all", "onefile"):
        run_pyinstaller("onefile")
    if args.mode in ("all", "dir"):
        make_zip()

    report()


if __name__ == "__main__":
    main()
