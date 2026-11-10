# -*- coding: utf-8 -*-
"""
一键安装本地语音组件（可选，不装也能用云端语音）

做的事：
  1. 建一个独立虚拟环境（不动主程序的依赖，主程序也不会因此变大）
  2. 装 CUDA 版 torch + qwen-tts
  3. 从魔搭下模型
  4. 生成 start_tts.bat，双击就能起服务

用法（在项目根目录）：
    python local_tts/install_local_tts.py                # 默认 0.6B，约 3.5GB，显存 4GB 起
    python local_tts/install_local_tts.py --size 1.7b    # 音质更好，约 6GB，显存 6GB 起
    python local_tts/install_local_tts.py --mirror pypi  # 不用国内镜像

装完在软件里：设置 → 语音 → 本地语音服务填 http://127.0.0.1:9880 → 检测。
"""

import argparse
import os
import subprocess
import sys
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MODELS = {
    '0.6b': 'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice',
    '1.7b': 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice',
}

MIRRORS = {
    'aliyun': {
        'pypi': 'https://mirrors.aliyun.com/pypi/simple',
        'torch': 'https://mirrors.aliyun.com/pytorch-wheels/cu124',
    },
    'pypi': {'pypi': None, 'torch': None},
}


def run(cmd, env=None, retry_ignore=True):
    print('$', ' '.join(cmd))
    proc = subprocess.run(cmd, env=env)
    if proc.returncode == 0:
        return
    # 杀毒软件/沙箱会锁住旧文件，导致 pip 卸载失败。
    # 这种时候 --ignore-installed 直接覆盖写，通常能过。
    if retry_ignore and 'pip' in cmd:
        alt = [c for c in cmd]
        idx = alt.index('install') + 1
        alt.insert(idx, '--ignore-installed')
        print('↻ 失败，改用 --ignore-installed 重试一次…')
        if subprocess.run(alt, env=env).returncode == 0:
            return
    raise SystemExit('命令失败: %s' % ' '.join(cmd))


def venv_python(env_dir):
    return os.path.join(env_dir, 'Scripts', 'python.exe')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', default='0.6b', choices=sorted(MODELS))
    ap.add_argument('--dest', default=os.path.join(ROOT, 'local_tts', 'runtime'))
    ap.add_argument('--mirror', default='aliyun', choices=sorted(MIRRORS))
    ap.add_argument('--skip-torch', action='store_true')
    args = ap.parse_args()

    env_dir = os.path.join(args.dest, 'env')
    models_dir = os.path.join(args.dest, 'models')
    os.makedirs(args.dest, exist_ok=True)
    os.makedirs(models_dir, exist_ok=True)

    print('=' * 60)
    print('安装目录:', args.dest)
    print('模型:', MODELS[args.size])
    print('=' * 60)

    if not os.path.exists(venv_python(env_dir)):
        print('\n[1/4] 建虚拟环境…')
        venv.create(env_dir, with_pip=True)
    else:
        print('\n[1/4] 虚拟环境已存在，跳过')

    py = venv_python(env_dir)
    mirror = MIRRORS[args.mirror]

    # 所有缓存都放在安装目录里，别去占 C 盘（pip 默认会往用户目录塞几个 G）
    env = dict(os.environ)
    env['PIP_CACHE_DIR'] = os.path.join(args.dest, 'pip-cache')
    env['TMP'] = os.path.join(args.dest, 'tmp')
    env['TEMP'] = env['TMP']
    os.makedirs(env['PIP_CACHE_DIR'], exist_ok=True)
    os.makedirs(env['TMP'], exist_ok=True)

    print('\n[2/4] 升级 pip…')
    cmd = [py, '-m', 'pip', 'install', '-U', 'pip']
    if mirror['pypi']:
        cmd += ['-i', mirror['pypi']]
    run(cmd, env=env)

    if not args.skip_torch:
        print('\n[3/4] 安装 CUDA 版 PyTorch（约 2.5GB，慢一点是正常的）…')
        cmd = [py, '-m', 'pip', 'install', 'torch', 'torchaudio']
        if mirror['torch']:
            cmd += ['-f', mirror['torch']]
        run(cmd, env=env)
    else:
        print('\n[3/4] 跳过 torch')

    print('\n[4/4] 安装 qwen-tts 与下载工具…')
    cmd = [py, '-m', 'pip', 'install', 'qwen-tts', 'soundfile', 'numpy', 'modelscope']
    if mirror['pypi']:
        cmd += ['-i', mirror['pypi']]
    run(cmd, env=env)

    model_repo = MODELS[args.size]
    target = os.path.join(models_dir, model_repo.split('/')[-1])
    if os.path.isdir(target) and os.listdir(target):
        print('\n✓ 模型已存在:', target)
    else:
        print('\n下载模型到 %s（几个 GB，慢慢等）…' % target)
        code = (
            "from modelscope import snapshot_download;"
            "print(snapshot_download(%r, local_dir=%r))" % (model_repo, target)
        )
        run([py, '-c', code], env=env)

    bat = os.path.join(HERE, 'start_tts.bat')
    with open(bat, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('@echo off\r\n')
        f.write('chcp 65001 >nul\r\n')
        f.write('cd /d "%~dp0"\r\n')
        f.write('"%s" local_tts_server.py --model "%s" --port 9880\r\n' % (py, target))
        f.write('pause\r\n')

    print('\n' + '=' * 60)
    print('装好了。以后双击 local_tts\\start_tts.bat 就能起服务。')
    print('然后到软件里：设置 → 语音 → 本地语音服务填 http://127.0.0.1:9880 → 点「检测」。')
    print('=' * 60)


if __name__ == '__main__':
    main()
