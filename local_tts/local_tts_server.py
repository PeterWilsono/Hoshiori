# -*- coding: utf-8 -*-
"""
本地语音服务 —— 给星织用的「OpenAI 兼容」TTS 接口

为什么要单独一个进程
--------------------
本地大模型要装 torch + 权重（几个 GB），塞进主程序的安装包会让 120MB 变成 4GB。
所以这里做成一个可选组件：装在独立的虚拟环境里，主程序只通过 HTTP 调它。
主程序那边的「本地大模型」引擎会自动识别这个服务。

跑起来（用装了 torch 的那个 Python）：
    python local_tts_server.py --model Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
    python local_tts_server.py --model Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice --port 9880

接口：
    GET  /health                        → {"ok": true, "model": ...}
    GET  /v1/models                     → OpenAI 形状，主程序靠它判断协议
    POST /v1/audio/speech               → 返回 wav 字节
         {"input": "文本", "voice": "Serena", "response_format": "wav"}

文本里的情感标签（[excited] / [sad] / …）会被翻译成 Qwen3-TTS 的
自然语言指令，交给模型控制语气 —— 这是「说话有情绪」的关键。
"""

import argparse
import io
import json
import os
import re
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: 情感标签 → Qwen3-TTS 的 instruct 指令
TAG_TO_INSTRUCT = {
    'excited': '用兴奋、雀跃的语气说',
    'sad': '用低落、难过的语气说',
    'angry': '用生气、压抑着怒火的语气说',
    'amazed': '用惊讶、惊叹的语气说',
    'panicked': '用慌张、急促的语气说',
    'whispers': '用很轻的耳语说，气息声多一点',
    'scornful': '用轻蔑、不以为然的语气说',
    'mischievously': '用调皮、带笑意的语气说',
    'empathetic': '用温柔共情、安抚的语气说',
    'serious': '用认真、严肃的语气说',
    'tired': '用疲倦、有气无力的语气说',
    'bored': '用无聊、兴致不高的语气说',
    'curious': '用好奇、询问的语气说',
    'laughing': '带着笑声说',
    'giggles': '带着咯咯的笑声说',
    'sighing': '先轻轻叹一口气再说',
}

TAG_RE = re.compile(r'\[([a-zA-Z ]+)\]\s*')

DEFAULT_SPEAKERS = {
    'Cherry': 'Serena', 'Chelsie': 'Vivian', 'Momo': 'Serena',
    'Vivian': 'Vivian', 'Serena': 'Serena', 'Maia': 'Serena',
    'Nini': 'Serena', 'Bella': 'Serena', 'Seren': 'Serena',
    'Ethan': 'Ryan', 'Moon': 'Ryan', 'Kai': 'Aiden',
}


def split_tag(text):
    """把 '[excited] 你好' 拆成 ('你好', '用兴奋…说')"""
    match = TAG_RE.match(text or '')
    if not match:
        return (text or '').strip(), ''
    tag = match.group(1).strip().lower()
    rest = TAG_RE.sub('', text, count=1).strip()
    return rest, TAG_TO_INSTRUCT.get(tag, '')


def to_wav_bytes(samples, rate):
    """numpy float/int → wav 字节（24k 单声道 16bit）"""
    import numpy as np

    arr = np.asarray(samples)
    if arr.dtype.kind == 'f':
        arr = np.clip(arr, -1.0, 1.0)
        arr = (arr * 32767).astype('<i2')
    else:
        arr = arr.astype('<i2')
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(arr.tobytes())
    return buf.getvalue()


class Engine:
    """把模型加载和推理都收在这里，HTTP 层不碰 torch。"""

    def __init__(self, model_path, device, dtype):
        self.model_path = model_path
        self.device = device
        self.dtype = dtype
        self.model = None
        self.sample_rate = 24000
        self.speakers = []
        self.lock = threading.Lock()
        self.kind = 'custom'      # custom / base

    def load(self):
        import torch
        from qwen_tts import Qwen3TTSModel

        print('→ 加载模型 %s（首次会慢，之后常驻显存）' % self.model_path)
        t0 = time.time()
        kwargs = {'device_map': self.device}
        if self.dtype == 'bf16':
            kwargs['dtype'] = torch.bfloat16
        elif self.dtype == 'fp16':
            kwargs['dtype'] = torch.float16

        self.model = Qwen3TTSModel.from_pretrained(self.model_path, **kwargs)
        if 'Base' in self.model_path:
            self.kind = 'base'
        try:
            self.speakers = list(self.model.get_supported_speakers())
        except Exception:
            self.speakers = list(DEFAULT_SPEAKERS.values())
        print('✓ 模型就绪 %.1fs，音色: %s' % (time.time() - t0, ', '.join(self.speakers[:8])))

    def synth(self, text, voice='', instruct=''):
        """返回 (wav_bytes, sample_rate)"""
        if not self.model:
            raise RuntimeError('模型还没加载好')
        speaker = DEFAULT_SPEAKERS.get(voice, voice) or 'Serena'
        if self.speakers and speaker not in self.speakers:
            speaker = self.speakers[0]

        with self.lock:      # 单卡串行，避免并发把显存打爆
            if self.kind == 'base':
                wavs, sr = self.model.generate(
                    text=text, language='Chinese', speaker=speaker,
                    instruct=instruct or None)
            else:
                wavs, sr = self.model.generate_custom_voice(
                    text=text, language='Chinese', speaker=speaker,
                    instruct=instruct or None)
        return to_wav_bytes(wavs[0], sr), sr


STATE = {'engine': None, 'ready': False, 'model': ''}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print('  %s - %s' % (self.address_string(), fmt % args))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/health'):
            return self._json({'ok': STATE['ready'], 'model': STATE['model']})
        if self.path.startswith('/v1/models'):
            return self._json({'object': 'list', 'data': [
                {'id': 'local-qwen3-tts', 'object': 'model'}]})
        self._json({'error': 'not found'}, 404)

    def do_POST(self):
        if not self.path.startswith('/v1/audio/speech'):
            return self._json({'error': 'not found'}, 404)
        try:
            n = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(n) or b'{}')
            text = body.get('input') or body.get('text') or ''
            voice = body.get('voice') or ''
            text, instruct = split_tag(text)
            if not text:
                return self._json({'error': 'empty text'}, 400)

            t0 = time.time()
            data, sr = STATE['engine'].synth(text, voice, instruct)
            print('  ✓ %.2fs  %d 字  %s' % (time.time() - t0, len(text), instruct or '中性'))

            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            print('  ✗ 合成失败: %s' % exc)
            self._json({'error': str(exc)[:300]}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice',
                    help='模型目录或 HF/ModelScope 仓库名')
    ap.add_argument('--port', type=int, default=9880)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--device', default='cuda:0')
    ap.add_argument('--dtype', default='bf16', choices=['bf16', 'fp16', 'fp32'])
    args = ap.parse_args()

    engine = Engine(args.model, args.device, args.dtype)
    STATE['engine'] = engine
    STATE['model'] = args.model
    try:
        engine.load()
        STATE['ready'] = True
    except Exception as exc:
        print('⚠️ 模型加载失败: %s' % exc)
        print('   服务照常启动，但合成会返回 500；修好模型再重启即可。')

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print('🚀 本地语音服务: http://%s:%d  （Ctrl+C 结束）' % (args.host, args.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')


if __name__ == '__main__':
    main()
