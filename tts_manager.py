# -*- coding: utf-8 -*-
"""
TTS 管理器 —— 句子级流水线 + 多引擎 + 情绪化朗读

为什么是现在这个样子（2026-11 第二版）
--------------------------------------
上一版能用，但声音「假」：百度翻译的免费接口是拼接式合成，音色平、没有起伏。
这次把它换成「能表达情绪」的引擎，同时保留随时可用的兜底线路。

引擎（按优先级自动选）：
    qwen   —— 阿里云百炼 Qwen3-TTS。中文最自然的一档，24kHz，支持情感标签
              （[sad] [excited] [whispers] [giggles]…）。0.8 元/万字符，
              开通送 11 万字符，普通聊天够用小半年。一句 20 字约 0.6~1.2 秒。
    local  —— 本地大模型服务（Qwen3-TTS / IndexTTS2 / Breeze TTS2 /
              GPT-SoVITS 都可以）。只要它在 127.0.0.1 上开了 HTTP 接口，
              这里自动识别协议并调用，数据不出本机、不限量。
    fish   —— Fish Audio S2 Pro。多人对话、ASMR、情绪标记最全，但服务器在
              海外，国内延迟不稳定，作为「想用就用」的选项保留。
    baidu  —— 百度免费接口，无需 Key，永远可用，音质一般（兜底）。
    sapi   —— Windows 系统语音，完全离线，几乎零延迟（最后一层兜底）。
    edge   —— 微软在线神经语音，2026-10 之后全线 403，代码留着但不启用。

情绪化朗读
----------
主程序每轮都会算出 dominant_emotion 和 PAD 值，通过 set_mood() 送进来。
合成时按情绪在句首插一个情感标签，于是同一句话在开心/难过/生气时
语调真的不一样 —— 这是「像真人」最关键的一步，比换音色管用。

对外接口保持兼容：is_enabled / is_speaking / speak() / stop() / set_enabled() /
set_voice() / get_available_voices()
"""

import base64
import itertools
import json
import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------- 文本切分

_STRONG = '。！？!?…；;\n'
_WEAK = '，,、：:'


def _hard_split(seg, max_len):
    """没有强标点的长句，退回逗号切；连逗号都没有就硬切。"""
    out = []
    while len(seg) > max_len:
        cut = -1
        for ch in _WEAK:
            i = seg.rfind(ch, 0, max_len + 1)
            if i > cut:
                cut = i
        if cut < max_len // 3:
            cut = max_len - 1
        out.append(seg[:cut + 1])
        seg = seg[cut + 1:]
    if seg:
        out.append(seg)
    return out


def split_sentences(text, first_len=24, max_len=46):
    """把回复切成适合逐句合成的片段。

    第一句刻意切短一点（first_len），因为它决定「多久听到第一个音」；
    后面的句子可以长一些，合成更省事、语气也更连贯。
    """
    text = (text or '').strip()
    if not text:
        return []

    raw = re.split(r'(?<=[%s])' % _STRONG, text)
    chunks = []
    for seg in raw:
        # 上一句末尾的 ！！ 会跟到下一段开头，念出来是多余的停顿
        seg = seg.strip().lstrip(_STRONG).strip()
        if not seg:
            continue
        limit = first_len if not chunks else max_len
        chunks.extend(_hard_split(seg, limit))

    # 太碎的片段并到前一句，避免一字一顿
    merged = []
    for c in chunks:
        if merged and len(merged) > 1 and len(c) < 8 and len(merged[-1]) + len(c) <= max_len:
            merged[-1] += c
        else:
            merged.append(c)
    return merged or [text]


# ---------------------------------------------------------------- 情绪 → 语气

#: dominant_emotion → (情感标签, 触发阈值)
#: 标签是各家 TTS 通用的写法，千问 / Fish / Breeze 都认（不认的时候会自动去掉重试）
MOOD_STYLE = {
    'joy': ('excited', 0.30),
    'happy': ('excited', 0.30),
    'happiness': ('excited', 0.30),
    'excited': ('excited', 0.20),
    'sadness': ('sad', 0.25),
    'sad': ('sad', 0.25),
    'sadness_soft': ('sad', 0.60),
    'anger': ('angry', 0.30),
    'angry': ('angry', 0.30),
    'annoyed': ('angry', 0.55),
    'surprise': ('amazed', 0.55),
    'surprised': ('amazed', 0.55),
    'fear': ('panicked', 0.60),
    'anxiety': ('panicked', 0.60),
    'nervous': ('panicked', 0.60),
    'shy': ('whispers', 0.75),
    'embarrassed': ('whispers', 0.75),
    'love': (None, 1.1),
    'trust': (None, 1.1),
    'anticipation': (None, 1.1),
    'disgust': ('scornful', 0.60),
    'neutral': (None, 0),
    'calm': (None, 0),
}

#: 允许标签的引擎（其余引擎收到标签反而会念出来）
TAG_ENGINES = ('qwen', 'fish', 'local')

#: 强度按哪个轴算：正面情绪看「多兴奋」，负面情绪看「多低落」
_POSITIVE_MOODS = ('joy', 'happy', 'happiness', 'excited', 'surprise', 'surprised',
                   'anticipation', 'love')
_NEGATIVE_MOODS = ('sadness', 'sad', 'anger', 'angry', 'annoyed', 'fear',
                   'anxiety', 'nervous', 'disgust')


def mood_tag(mood, pad=None, enabled=True):
    """按当前情绪返回一个情感标签字符串（含尾随空格），没有就给空串。

    强度用 PAD 估：愉悦/唤醒越高，越值得加标签；很平静的时候就不加，
    否则每句都「[excited]」听着像在演话剧。
    """
    if not enabled or not mood:
        return ''
    key = str(mood).strip().lower()
    tag, threshold = MOOD_STYLE.get(key, (None, 1.0))
    if not tag:
        return ''

    strength = 0.5
    if isinstance(pad, dict):
        try:
            pleasure = float(pad.get('pleasure', 0.0))
            arousal = float(pad.get('arousal', 0.0))
            pos = max(0.0, min(1.0, pleasure))
            neg = max(0.0, min(1.0, -pleasure))
            aro = max(0.0, min(1.0, arousal))
            if key in _POSITIVE_MOODS:
                strength = 0.45 * pos + 0.55 * aro
            elif key in _NEGATIVE_MOODS:
                strength = 0.55 * neg + 0.45 * aro
            else:
                strength = 0.5 * (abs(pleasure) + abs(arousal))
                strength = min(1.0, strength)
        except Exception:
            strength = 0.5
    if strength < threshold:
        return ''
    return '[%s] ' % tag


# ---------------------------------------------------------------- 系统语音

_SAPI_CATS = (
    r'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices',
    r'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices',
)


def _looks_chinese(desc, token_id):
    d = (desc or '').lower()
    t = (token_id or '').lower()
    return ('chinese' in d) or ('zh-cn' in t) or ('zhcn' in t) or ('_zh_' in t)


def _short_name(desc):
    """'Microsoft Yaoyao - Chinese (Simplified, PRC)' -> 'Yaoyao'"""
    name = (desc or '').split(' - ')[0].strip()
    if name.lower().startswith('microsoft '):
        name = name[10:].strip()
    return name or (desc or '系统语音')


class SapiEngine:
    """Windows 系统语音。

    OneCore 里那几个音色（Yaoyao / Kangkang）比 SAPI5 的 Huihui 好听，
    但它们注册在另一个分类下，SAPI5 的 GetVoices() 看不到。
    所以这里直接按分类枚举 token，再把 token 赋给 SpVoice —— 不需要管理员权限，
    也不用改注册表。
    """

    name = 'sapi'
    label = '系统语音'

    def __init__(self):
        self.available = False
        self.voices = []            # [{id, name, desc}]
        self._local = threading.local()

    def discover(self):
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            print('⚠️ 未安装 pywin32，系统语音不可用')
            return False

        pythoncom.CoInitialize()
        seen = set()
        voices = []
        for cat_path in _SAPI_CATS:
            try:
                cat = win32com.client.Dispatch('SAPI.SpObjectTokenCategory')
                cat.SetId(cat_path, False)
                toks = cat.EnumerateTokens()
                for i in range(toks.Count):
                    tok = toks.Item(i)
                    tid = tok.Id
                    desc = tok.GetDescription()
                    if not tid or tid in seen:
                        continue
                    if not _looks_chinese(desc, tid):
                        continue
                    seen.add(tid)
                    voices.append({'id': tid, 'name': _short_name(desc), 'desc': desc})
            except Exception as exc:
                print('⚠️ 枚举系统语音失败(%s): %s' % (cat_path, exc))

        self.voices = voices
        self.available = bool(voices)
        if voices:
            print('✓ 系统语音可用: %s' % ', '.join(v['name'] for v in voices))
        return self.available

    # -- 线程内缓存 SpVoice：Worker 线程固定，复用能省掉每次的 COM 建对象开销
    def _voice_for(self, voice_id, rate):
        import win32com.client

        cache = getattr(self._local, 'cache', None)
        if cache is None:
            cache = self._local.cache = {}
        key = (voice_id, rate)
        voice = cache.get(key)
        if voice is not None:
            return voice

        voice = win32com.client.Dispatch('SAPI.SpVoice')
        token = self._find_token(voice_id)
        if token is not None:
            try:
                voice.Voice = token
            except Exception as exc:
                print('⚠️ 指定系统语音失败，改用默认: %s' % exc)
        try:
            voice.Rate = rate
        except Exception:
            pass
        cache[key] = voice
        return voice

    def _find_token(self, voice_id):
        import win32com.client

        for cat_path in _SAPI_CATS:
            try:
                cat = win32com.client.Dispatch('SAPI.SpObjectTokenCategory')
                cat.SetId(cat_path, False)
                toks = cat.EnumerateTokens()
                for i in range(toks.Count):
                    tok = toks.Item(i)
                    if tok.Id == voice_id:
                        return tok
            except Exception:
                continue
        return None

    def warm(self, voice_id, rate):
        """在当前线程里把语音对象建好（跨线程不能共用 COM 对象）。"""
        import pythoncom
        pythoncom.CoInitialize()
        self._voice_for(voice_id, rate)

    def synthesize(self, text, voice_id, rate, out_path):
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        voice = self._voice_for(voice_id, rate)

        fmt = win32com.client.Dispatch('SAPI.SpAudioFormat')
        fmt.Type = 22          # 22kHz 16bit 单声道，够用且文件小
        stream = win32com.client.Dispatch('SAPI.SpFileStream')
        stream.Format = fmt
        if os.path.exists(out_path):
            os.unlink(out_path)
        stream.Open(out_path, 3)   # SSFMCreateForWrite
        try:
            voice.AudioOutputStream = stream
            voice.Speak(text, 0)   # 0 = 同步，写到流而不是扬声器
        finally:
            try:
                stream.Close()
            except Exception:
                pass
            try:
                voice.AudioOutputStream = None
            except Exception:
                pass
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 1024:
            raise RuntimeError('系统语音没有产生音频')


# ---------------------------------------------------------------- 播放

class Player:
    """播放一段已经合成好的音频。

    不用 pygame：`import pygame` 本身要 4.3 秒（它顺手把 setuptools 拉起来），
    为了播一段语音付这个代价太贵。这里直接用 Windows 自带的两条路：

    * .wav  —— winsound.PlaySound，标准库，几乎零延迟
    * .mp3  —— MCI（winmm.dll 的 mciSendStringW），系统自带 mp3 解码器，
               还能问「播到哪了」「放完了没」

    两者都是异步的，`play()` 立刻返回，不会卡住调用线程。
    """

    def __init__(self):
        self._alias = None
        self._wav = False
        self._duration = 0.0
        self._started = 0.0
        try:
            import ctypes
            self._winmm = ctypes.WinDLL('winmm')
            self._buf = ctypes.create_unicode_buffer(512)
        except Exception:
            self._winmm = None
        try:
            import winsound
            self._winsound = winsound
        except Exception:
            self._winsound = None

    @property
    def available(self):
        return bool(self._winmm or self._winsound)

    def _send(self, cmd):
        """发一条 MCI 命令，返回错误码（0 = 成功）"""
        if not self._winmm:
            return -1
        try:
            self._buf.value = ''
            return self._winmm.mciSendStringW(cmd, self._buf, 511, 0)
        except Exception:
            return -1

    def _ask(self, cmd):
        """发一条查询类命令，返回字符串结果"""
        return self._buf.value if self._send(cmd) == 0 else ''

    def play(self, path):
        """开始播放，返回时长（秒）；失败返回 0"""
        self.stop()
        if not path or not os.path.exists(path):
            return 0.0

        if path.lower().endswith('.wav') and self._winsound:
            try:
                self._winsound.PlaySound(path, self._winsound.SND_FILENAME | self._winsound.SND_ASYNC)
                self._wav = True
                self._duration = _wav_seconds(path)
                self._started = time.time()
                return self._duration
            except Exception as exc:
                print('⚠️ wav 播放失败: %s' % exc)

        if not self._winmm:
            return 0.0
        alias = 'hoshiori_tts'
        if self._send('open "%s" type mpegvideo alias %s' % (path, alias)) != 0:
            print('⚠️ 打不开音频: %s' % os.path.basename(path))
            return 0.0
        self._alias = alias
        try:
            length = int(self._ask('status %s length' % alias) or 0)
        except Exception:
            length = 0
        if self._send('play %s' % alias) != 0:
            self.stop()
            return 0.0
        self._duration = length / 1000.0
        self._started = time.time()
        return self._duration

    def busy(self):
        if self._wav:
            # winsound 查不到状态，只能按已知时长算
            return (time.time() - self._started) < max(0.2, self._duration - 0.05)
        if self._alias:
            return self._ask('status %s mode' % self._alias) == 'playing'
        return False

    def stop(self):
        if self._wav and self._winsound:
            try:
                self._winsound.PlaySound(None, self._winsound.SND_PURGE)
            except Exception:
                pass
            self._wav = False
        if self._alias:
            self._send('stop %s' % self._alias)
            self._send('close %s' % self._alias)
            self._alias = None
        self._duration = 0.0


def _wav_seconds(path):
    try:
        import wave
        with wave.open(path, 'rb') as w:
            rate = w.getframerate() or 1
            return w.getnframes() / float(rate)
    except Exception:
        try:
            return max(0.5, (os.path.getsize(path) - 44) / 44100.0)
        except Exception:
            return 0.0


def _looks_audio(content, content_type=''):
    """判断响应体是音频还是 JSON —— 各家本地服务的返回格式不太统一。"""
    if not content:
        return False
    ct = (content_type or '').lower()
    if 'audio' in ct or 'octet-stream' in ct:
        return True
    head = content[:4]
    return head in (b'RIFF', b'ID3\x03', b'ID3\x04', b'fLaC', b'OggS') or head[:2] == b'\xff\xfb'


def save_audio(content, content_type, out_path, session=None, timeout=15):
    """把各种形态的返回值落成音频文件：
    直接给字节 / {"url": ...} / {"data": base64} / {"audio": base64}
    """
    if _looks_audio(content, content_type):
        with open(out_path, 'wb') as f:
            f.write(content)
        return out_path

    try:
        data = json.loads(content.decode('utf-8', 'ignore'))
    except Exception:
        raise RuntimeError('返回内容既不是音频也不是 JSON')

    # 有些服务把结果包在 output/result 里
    for key in ('output', 'result', 'data'):
        if isinstance(data.get(key), dict):
            merged = dict(data)
            merged.update(data[key])
            data = merged
            break

    for key in ('url', 'audio_url', 'file'):
        val = data.get(key)
        if isinstance(val, str) and val.startswith('http'):
            import requests
            r = (session or requests).get(val, timeout=timeout)
            r.raise_for_status()
            with open(out_path, 'wb') as f:
                f.write(r.content)
            return out_path

    for key in ('data', 'audio', 'base64', 'audio_base64'):
        val = data.get(key)
        if isinstance(val, str) and val:
            try:
                raw = base64.b64decode(val)
            except Exception:
                continue
            if len(raw) > 400:
                with open(out_path, 'wb') as f:
                    f.write(raw)
                return out_path

    raise RuntimeError('没有从返回里找到音频: %s' % str(data)[:160])


# ---------------------------------------------------------------- 云端引擎

#: 两个都是百度自家接口，互相备份；音色相近（女声，约 210Hz）
ONLINE_SOURCES = {
    'fanyi': {
        'label': '在线女声 · 朗读',
        'url': 'https://fanyi.baidu.com/gettts',
        'referer': 'https://fanyi.baidu.com/',
    },
    'baike': {
        'label': '在线女声 · 百科',
        'url': 'https://tts.baidu.com/text2audio',
        'referer': 'https://baike.baidu.com/',
    },
}

EDGE_VOICES = (
    ('zh-CN-XiaoyiNeural', '小艺（温柔）'),
    ('zh-CN-XiaoxiaoNeural', '晓晓（活泼）'),
    ('zh-CN-XiaomengNeural', '晓梦（可爱）'),
)

#: 千问系统音色（qwen3-tts-flash 支持的全部中文音色里挑的，优先女声）
QWEN_VOICES = (
    ('Serena', '苏瑶 · 温柔小姐姐'),
    ('Chelsie', '千雪 · 二次元女友'),
    ('Cherry', '芊悦 · 阳光亲切'),
    ('Momo', '茉兔 · 撒娇搞怪'),
    ('Vivian', '十三 · 拽拽小暴躁'),
    ('Maia', '四月 · 知性温柔'),
    ('Nini', '邻家妹妹 · 又软又黏'),
    ('Bella', '萌宝 · 小萝莉'),
    ('Seren', '小婉 · 助眠舒缓'),
    ('Katerina', '卡捷琳娜 · 御姐'),
    ('Ethan', '晨煦 · 阳光男声'),
    ('Moon', '月白 · 帅气男声'),
)

QWEN_ENDPOINT = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'
QWEN_MODEL = 'qwen3-tts-flash'


class QwenEngine:
    """阿里云百炼 Qwen3-TTS。

    - 非流式一句话返回 wav（`output.audio.data` 是 base64，直接落盘，省一次
      CDN 往返），20 字大约 0.6~1.2 秒。
    - 文本里可以直接写情感标签：[sad] [excited] [angry] [whispers] [giggles]
      [sighing]…  这是它比免费接口「像人」的核心原因。
    - 0.8 元/万字符，开通送 11 万字符。

    Key 无效时把 fatal 置位，本次会话不再重试，直接让上层回落到别的引擎。
    """

    name = 'qwen'
    label = '千问神经语音'

    def __init__(self, key_getter, session_getter):
        self._key = key_getter
        self._session = session_getter
        self.fatal = False
        self.last_error = ''

    @property
    def available(self):
        return bool(self._key()) and not self.fatal

    def synthesize(self, text, voice, out_path, tag=''):
        key = self._key()
        if not key:
            raise RuntimeError('未填写千问 API Key')
        if self.fatal:
            raise RuntimeError(self.last_error or '千问语音不可用')

        voice = voice or 'Serena'
        first = self._request(text, key, voice, tag, out_path)
        if first is True:
            return out_path
        if first == 'retry-notag' and tag:
            # 这个模型/音色不认标签：去掉标签再说一遍，别让整句哑掉
            self._request(text, key, voice, '', out_path)
            return out_path
        raise RuntimeError(self.last_error or '千问语音没有返回音频')

    def _request(self, text, key, voice, tag, out_path):
        payload = {
            'model': QWEN_MODEL,
            'input': {
                'text': (tag + text)[:590],
                'voice': voice,
                'language_type': 'Chinese',
            },
        }
        headers = {
            'Authorization': 'Bearer %s' % key,
            'Content-Type': 'application/json',
        }
        session = self._session()
        r = session.post(QWEN_ENDPOINT, json=payload, headers=headers, timeout=20)

        if r.status_code in (401, 403):
            self.fatal = True
            self.last_error = '千问 API Key 无效或已过期'
            raise RuntimeError(self.last_error)
        if r.status_code == 400 and tag:
            return 'retry-notag'
        if r.status_code != 200:
            body = r.text[:200].replace('\n', ' ')
            # 429 / 5xx 是临时的，不要把引擎判死
            raise RuntimeError('千问返回 %s: %s' % (r.status_code, body))

        data = r.json()
        audio = (data.get('output') or {}).get('audio') or {}
        blob = audio.get('data')
        if blob:
            raw = base64.b64decode(blob)
            with open(out_path, 'wb') as f:
                f.write(raw)
            return True
        url = audio.get('url')
        if url:
            import requests
            rr = session.get(url, timeout=20)
            rr.raise_for_status()
            with open(out_path, 'wb') as f:
                f.write(rr.content)
            return True
        self.last_error = '千问没有返回音频: %s' % str(data)[:160]
        raise RuntimeError(self.last_error)


class FishEngine:
    """Fish Audio S2 Pro。

    强项是多人对话、ASMR 和极细的情绪标记（[sad]/[excited]/[whisper]），
    但节点在海外，国内直连经常要等 1~3 秒，所以只作为「想用就用」的选项。
    """

    name = 'fish'
    label = 'Fish Audio S2'
    ENDPOINT = 'https://api.fish.audio/v1/tts'

    def __init__(self, key_getter, session_getter, model='s2-pro'):
        self._key = key_getter
        self._session = session_getter
        self.model = model
        self.last_error = ''

    @property
    def available(self):
        return bool(self._key())

    def synthesize(self, text, voice, out_path, tag=''):
        key = self._key()
        if not key:
            raise RuntimeError('未填写 Fish Audio Key')
        headers = {
            'Authorization': 'Bearer %s' % key,
            'Content-Type': 'application/json',
            'model': self.model,
        }
        payload = {
            'text': (tag + text)[:1900],
            'format': 'mp3',
            'mp3_bitrate': 128,
            'latency': 'normal',
        }
        if voice:
            payload['reference_id'] = voice
        r = self._session().post(self.ENDPOINT, json=payload, headers=headers, timeout=25)
        if r.status_code in (401, 403):
            self.last_error = 'Fish Audio Key 无效'
            raise RuntimeError(self.last_error)
        if r.status_code != 200:
            self.last_error = 'Fish 返回 %s: %s' % (r.status_code, r.text[:160])
            raise RuntimeError(self.last_error)
        return save_audio(r.content, r.headers.get('Content-Type', ''), out_path, self._session())


class LocalEngine:
    """本地大模型 TTS 服务（自动识别协议）。

    支持三类常见服务，都是在 127.0.0.1 上开个端口：
      * OpenAI 兼容  POST /v1/audio/speech      —— Breeze TTS 2、GPT-SoVITS v2、
                                                  多数自建封装都是这个格式
      * IndexTTS2    POST /tts {text, ...}      —— 官方 Docker 镜像 8002 端口
      * GPT-SoVITS   POST /tts?text=...&...     —— api_v2.py 9880 端口

    探测顺序：/v1/models → /health → /docs。探测不到就当作不可用，
    绝不会因为本地服务没开而拖慢正常说话。
    """

    name = 'local'
    label = '本地大模型'

    def __init__(self, url_getter, session_getter, ref_audio_getter=None):
        self._url = url_getter
        self._session = session_getter
        self._ref = ref_audio_getter or (lambda: '')
        self.proto = None
        self.checked_at = 0.0
        self.info = ''
        self.last_error = ''

    @property
    def available(self):
        return bool(self._url()) and self.proto is not None

    def base(self):
        return (self._url() or '').strip().rstrip('/')

    def probe(self, timeout=2.5, force=False):
        """探一次本地服务；成功返回 True。结果缓存 60 秒。"""
        now = time.time()
        if not force and self.checked_at and now - self.checked_at < 60:
            return self.proto is not None
        self.checked_at = now
        self.proto = None
        self.info = ''

        base = self.base()
        if not base:
            return False
        session = self._session()
        for path, proto, label in (('/v1/models', 'openai', 'OpenAI 兼容'),
                                   ('/health', 'index', 'IndexTTS/本地服务'),
                                   ('/docs', 'index', 'IndexTTS/本地服务')):
            try:
                r = session.get(base + path, timeout=timeout)
                if r.status_code < 500:
                    self.proto = proto
                    self.info = '%s · %s' % (label, base)
                    return True
            except Exception:
                continue
        return False

    def synthesize(self, text, voice, out_path, tag=''):
        if not self.proto and not self.probe():
            raise RuntimeError('本地语音服务没有响应')
        base = self.base()
        session = self._session()
        text = tag + text

        if self.proto == 'openai':
            payload = {
                'model': voice or 'tts-1',
                'input': text,
                'voice': voice or 'alloy',
                'response_format': 'wav',
                'speed': 1.0,
            }
            r = session.post(base + '/v1/audio/speech', json=payload, timeout=60)
        elif self.proto == 'index':
            payload = {'text': text}
            ref = self._ref()
            if ref:
                payload['spk_audio_prompt'] = ref
            r = session.post(base + '/tts', json=payload, timeout=90)
        else:
            raise RuntimeError('未知的本地服务协议')

        if r.status_code >= 400:
            # 有些实现把参数放在 query 上，退化重试一次
            if self.proto == 'index':
                r = session.post(base + '/tts', params={'text': text}, timeout=90)
            if r.status_code >= 400:
                raise RuntimeError('本地服务返回 %s: %s' % (r.status_code, r.text[:160]))

        return save_audio(r.content, r.headers.get('Content-Type', ''), out_path, session)


# ---------------------------------------------------------------- 管理器

class TTSManager:
    """多引擎语音合成 + 逐句流水线播放"""

    PREFETCH = 2          # 播放第 n 句时，第 n+1、n+2 句在合成
    WORKERS = 1           # 合成线程只开一个：并发请求会被在线接口限流(503)
    MAX_FAILS = 2         # 同一引擎连续失败几次就本次会话不再用

    def __init__(self, config_manager=None):
        self.is_enabled = False
        self.is_speaking = False

        #: auto / qwen / local / fish / baidu / sapi
        self.engine_name = 'auto'
        self.voice_id = ''
        #: 用户是否手动选过声音。没选过就别把「自动挑的兜底音色」当成偏好，
        #: 否则后来配好千问也还是继续用百度，白白浪费了好引擎。
        self._explicit = False
        self.rate = 0             # 系统语音语速 -10~10
        self.speed = 5            # 百度语速 1~15
        self.emotion_enabled = True
        self._config = config_manager

        self._player = Player()
        self.available_engines = []
        self._ready = False
        self._ready_lock = threading.Lock()

        self._gen = 0
        self._gen_lock = threading.Lock()
        self._pool = None
        self._pool_lock = threading.Lock()
        self._play_lock = threading.Lock()
        self._playing_gen = -1     # 当前占用播放器的是哪一代请求
        self._tmpdir = None
        self._session = None
        self._session_lock = threading.Lock()
        self._seq = itertools.count(1)

        self._sapi = SapiEngine()
        self._sapi_voice_key = None
        self._online_source = 'fanyi'
        self._baidu_ok = None     # None 未探测 / True / False
        self._edge_ok = False
        self._fails = {}
        self._prewarming = False
        self._warm_lock = threading.Lock()

        #: 情绪状态：dominant_emotion + PAD
        self._mood = 'neutral'
        self._pad = None

        #: 口型联动回调：on_talk(秒) / on_stop()
        self.on_talk = None
        self.on_stop = None

        # 云端 / 本地引擎
        self._qwen = QwenEngine(lambda: self._cfg('tts_api_key', ''), self._get_session)
        self._fish = FishEngine(lambda: self._cfg('tts_fish_key', ''), self._get_session)
        self._local = LocalEngine(lambda: self._cfg('tts_local_url', ''),
                                  self._get_session,
                                  lambda: self._cfg('tts_ref_audio', ''))

    # ------------------------------------------------------------ 配置读取

    def _cfg(self, name, default=''):
        cm = self._config
        if cm is None:
            return default
        try:
            val = getattr(cm, name, default)
            return default if val is None else val
        except Exception:
            return default

    def _providers(self):
        return {
            'qwen': self._qwen,
            'fish': self._fish,
            'local': self._local,
        }

    # ------------------------------------------------------------ 初始化

    def ensure_ready(self):
        if self._ready:
            return True
        with self._ready_lock:
            if self._ready:
                return True
            self._init_audio()
            if self._sapi.discover():
                self.available_engines.append('sapi')
            # edge_tts 不在初始化时 import：它连带 aiohttp 要 3.2 秒，
            # 而这条线路目前基本处于 403 状态。用户真去选它时再加载。
            # 百度没有可探测的「安装」动作，首次真正合成时判定
            self.available_engines.append('baidu')
            if self._qwen.available:
                self.available_engines.append('qwen')
            if self._fish.available:
                self.available_engines.append('fish')
            self.emotion_enabled = bool(self._cfg('tts_emotion', True))
            self._load_prefs()
            self._ready = True
        return True

    def prewarm(self):
        """后台预热：音频设备 + 网络连接 + 本地服务探测。"""
        if self._ready and self._baidu_ok is not None:
            return
        with self._warm_lock:
            if self._prewarming:
                return
            self._prewarming = True
        threading.Thread(target=self._prewarm, daemon=True).start()

    def _prewarm(self):
        try:
            self.ensure_ready()

            # 千问：先把 TLS 建好，第一句话就少 0.3~0.5 秒
            if self._qwen.available:
                try:
                    self._get_session().get('https://dashscope.aliyuncs.com/', timeout=6)
                except Exception:
                    pass

            # 本地服务：探一下，探到就把引擎列表刷新（不阻塞界面）
            if self._cfg('tts_local_url', ''):
                try:
                    if self._local.probe():
                        if 'local' not in self.available_engines:
                            self.available_engines.append('local')
                        print('✓ 本地语音服务已就绪: %s' % self._local.info)
                    elif 'local' in self.available_engines:
                        self.available_engines.remove('local')
                except Exception:
                    pass

            if self._baidu_ok is None and not self._qwen.available:
                self._probe_baidu()
            if self._baidu_ok:
                try:
                    self._get_session().get('https://fanyi.baidu.com/', timeout=6)
                except Exception:
                    pass

            # 合成线程里第一次用系统语音要 0.5 秒（COM 初始化 + 找 token）。
            # 现在把 worker 线程先建出来、把语音对象准备好。
            if self._sapi.available:
                pool = self._get_pool()
                voice_id = getattr(self, '_sapi_voice_key', None) or self._sapi.voices[0]['id']
                for _ in range(self.PREFETCH):
                    pool.submit(self._warm_sapi, voice_id)
        except Exception as exc:
            print('⚠️ 语音预热失败: %s' % exc)
        finally:
            with self._warm_lock:
                self._prewarming = False

    def _warm_sapi(self, voice_id):
        try:
            self._sapi.warm(voice_id, self.rate)
        except Exception:
            pass

    def _init_audio(self):
        """音频输出：winsound(wav) + MCI(mp3)，都是系统自带，不用第三方库"""
        if self._player.available:
            print('✓ 音频输出就绪')
        else:
            print('⚠️ 没有可用的音频输出，语音将静音播放')

    def _get_session(self):
        with self._session_lock:
            if self._session is None:
                import requests
                s = requests.Session()
                s.headers.update({
                    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                                   'Chrome/131.0.0.0 Safari/537.36'),
                })
                self._session = s
            return self._session

    def _probe_baidu(self):
        try:
            import requests  # noqa: F401
            r = None
            session = self._get_session()
            session.headers['Referer'] = 'https://fanyi.baidu.com/'
            for _ in range(2):
                r = session.get(
                    'https://fanyi.baidu.com/gettts',
                    params={'lan': 'zh', 'text': '你好', 'spd': 5, 'source': 'web'},
                    timeout=6)
                if r.status_code == 200 and len(r.content) > 500:
                    break
                time.sleep(0.25)
            ok = bool(r is not None and r.status_code == 200 and len(r.content) > 500)
            # 5xx 多半是限流，不代表这条线路挂了；留给真正合成时再判定
            transient = bool(r is not None and 500 <= r.status_code < 600)
            self._baidu_ok = True if ok else (None if transient else False)
            if self._baidu_ok:
                # 第一段 mp3 要 200~600ms 加载解码器，这里先把它唤醒
                try:
                    path = self._temp_path('.mp3')
                    with open(path, 'wb') as f:
                        f.write(r.content)
                    self._player._send('open "%s" type mpegvideo alias hoshiori_warm' % path)
                    self._player._send('close hoshiori_warm')
                    _unlink(path)
                except Exception:
                    pass
        except Exception:
            self._baidu_ok = False
        if self._baidu_ok:
            print('✓ 在线语音可用')
        elif self._baidu_ok is False:
            print('⚠️ 在线语音不可达，改用系统语音')
        else:
            print('… 在线语音响应异常，留到真正说话时再判断')
        return self._baidu_ok

    def _load_prefs(self):
        cm = self._config
        if not cm:
            self._choose_default_voice()
            return
        try:
            saved = getattr(cm, 'tts_voice', '') or ''
            if saved and self._voice_exists(saved):
                self._apply_voice_id(saved, explicit=True)
                return
        except Exception:
            pass
        self._choose_default_voice()

    def _save_prefs(self):
        cm = self._config
        if not cm:
            return
        try:
            cm.tts_voice = self.voice_id
            cm.tts_engine = self.engine_name
            cm.save_config()
        except Exception:
            pass

    def _choose_default_voice(self):
        # 有 Key 就用千问 —— 质量和「像人」程度是断层式领先
        if self._qwen.available:
            self._apply_voice_id('qwen:Serena')
        elif self._local.available:
            self._apply_voice_id('local:default')
        elif self._fish.available:
            self._apply_voice_id('fish:default')
        elif self._baidu_ok is not False and 'baidu' in self.available_engines:
            self._apply_voice_id('baidu:fanyi')
        elif self._sapi.voices:
            self._apply_voice_id('sapi:' + self._sapi.voices[0]['id'])
        else:
            self._apply_voice_id('auto')

    # ------------------------------------------------------------ 情绪

    def set_mood(self, mood, pad=None):
        """主程序每轮调用：把角色当前情绪交给语音，说话才有情绪。"""
        self._mood = (mood or 'neutral').strip().lower()
        self._pad = pad if isinstance(pad, dict) else None

    def get_mood_tag(self):
        return mood_tag(self._mood, self._pad, self.emotion_enabled).strip()

    def set_emotion_enabled(self, enabled):
        self.emotion_enabled = bool(enabled)
        cm = self._config
        if cm:
            try:
                cm.tts_emotion = self.emotion_enabled
                cm.save_config()
            except Exception:
                pass
        return self.emotion_enabled

    # ------------------------------------------------------------ 声音选择

    def _voice_exists(self, voice_id):
        # 注意：这里不能用 get_available_voices()，那会再进一次 ensure_ready 的锁
        if not voice_id:
            return False
        engine, _, key = voice_id.partition(':')
        if engine == 'qwen':
            return self._qwen.available
        if engine == 'local':
            return bool(self._cfg('tts_local_url', ''))
        if engine == 'fish':
            return self._fish.available
        if engine == 'baidu':
            return self._baidu_ok is not False
        if engine == 'sapi':
            return any(v['id'] == key for v in self._sapi.voices)
        if engine == 'edge':
            return self._edge_ok
        return False

    def _apply_voice_id(self, voice_id, explicit=False):
        if not voice_id:
            return
        self.voice_id = voice_id
        if explicit:
            self._explicit = True
        engine, _, key = voice_id.partition(':')
        if engine in ('qwen', 'local', 'fish', 'baidu', 'sapi', 'edge'):
            self.engine_name = engine
            if engine == 'sapi' and key:
                self._sapi_voice_key = key
            elif engine == 'baidu' and key in ONLINE_SOURCES:
                self._online_source = key
        else:
            self.engine_name = 'auto'

    def get_voice_catalog(self):
        """给设置页用：按引擎分组，附带可用状态，方便用户知道去配什么。"""
        self.ensure_ready()
        groups = []

        groups.append({
            'engine': 'qwen',
            'label': '千问神经语音',
            'note': '最像真人，带情绪 · 0.8 元/万字符，开通送 11 万字',
            'available': self._qwen.available,
            'hint': '' if self._qwen.available else '填入百炼 API Key 即可启用',
            'voices': [{'id': 'qwen:' + vid, 'name': name, 'note': ''}
                       for vid, name in QWEN_VOICES],
        })

        local_voices = [{'id': 'local:default', 'name': '本地服务 · 默认音色', 'note': ''}]
        groups.append({
            'engine': 'local',
            'label': '本地大模型（离线）',
            'note': 'IndexTTS2 / Qwen3-TTS / Breeze / GPT-SoVITS，接上就能用，数据不出本机',
            'available': self._local.available,
            'hint': self._local.info or '在下面填本地服务地址并点「检测」',
            'voices': local_voices,
        })

        groups.append({
            'engine': 'fish',
            'label': 'Fish Audio S2',
            'note': '多人对话、ASMR 最擅长，节点在海外，国内会慢一些',
            'available': self._fish.available,
            'hint': '' if self._fish.available else '填入 Fish Audio Key 即可启用',
            'voices': [{'id': 'fish:default', 'name': '默认音色（用账号里的声音 ID）', 'note': ''}],
        })

        if self._baidu_ok is not False:
            groups.append({
                'engine': 'baidu',
                'label': '在线免费（百度）',
                'note': '不用 Key，永远可用，音质一般',
                'available': True,
                'hint': '',
                'voices': [{'id': 'baidu:' + k, 'name': v['label'], 'note': ''}
                           for k, v in ONLINE_SOURCES.items()],
            })

        if self._sapi.voices:
            groups.append({
                'engine': 'sapi',
                'label': '系统语音',
                'note': '完全离线，几乎瞬间出声',
                'available': True,
                'hint': '',
                'voices': [{'id': 'sapi:' + v['id'], 'name': '系统 · %s' % v['name'], 'note': ''}
                           for v in self._sapi.voices],
            })
        return groups

    def get_available_voices(self):
        self.ensure_ready()
        out = []
        for group in self.get_voice_catalog():
            if not group['available']:
                continue
            for v in group['voices']:
                out.append({'id': v['id'], 'name': v['name'], 'engine': group['engine'],
                            'note': group['note']})
        if not out:
            out.append({'id': 'auto', 'name': '暂无可用的语音引擎', 'engine': 'auto', 'note': ''})
        return out

    def set_voice(self, voice_id):
        """切换声音（voice_id 形如 'qwen:Serena' / 'local:default'）"""
        self.ensure_ready()
        if not voice_id:
            return False
        engine = voice_id.split(':', 1)[0]
        if engine == 'qwen' and not self._qwen.available:
            # 有 Key 才能用；没 Key 时不要假装切换成功
            if not self._cfg('tts_api_key', ''):
                print('⚠️ 千问语音需要先在设置里填写 API Key')
                return False
        if engine == 'local' and not self._cfg('tts_local_url', ''):
            print('⚠️ 还没有配置本地语音服务地址')
            return False
        if engine == 'fish' and not self._fish.available:
            print('⚠️ Fish Audio 需要先填写 Key')
            return False
        if engine == 'baidu' and self._baidu_ok is False:
            print('⚠️ 在线语音当前不可用')
            return False
        if engine == 'sapi':
            key = voice_id.split(':', 1)[1]
            if not any(v['id'] == key for v in self._sapi.voices):
                print('⚠️ 没有这个系统语音: %s' % key)
                return False
        self._apply_voice_id(voice_id, explicit=True)
        self._save_prefs()
        print('✓ 语音已切换: %s' % voice_id)
        return True

    def set_engine(self, engine_name):
        if engine_name == 'auto':
            self._explicit = False
            self.engine_name = 'auto'
            self._choose_default_voice()
            self._save_prefs()
            return True
        return self.set_voice(engine_name)

    def get_engine_label(self):
        return {'qwen': '千问', 'local': '本地', 'fish': 'Fish',
                'baidu': '在线', 'sapi': '系统', 'edge': '微软',
                'auto': '自动'}.get(self.engine_name, self.engine_name)

    def get_available_engines(self):
        self.ensure_ready()
        return list(self.available_engines)

    def get_available_voices_legacy(self):
        return self.get_available_voices()

    # ------------------------------------------------------------ 开关

    def set_enabled(self, enabled):
        if enabled:
            self.prewarm()          # 后台准备，别让界面等
        self.is_enabled = enabled
        print('🔊 语音%s (引擎: %s)' % ('已开启' if enabled else '已关闭', self.engine_name))
        if not enabled:
            self.stop()

    def stop(self):
        """立刻停住（切消息、关语音时调）"""
        with self._gen_lock:
            self._gen += 1
        self._halt_playback()

    # ------------------------------------------------------------ 合成

    def clean_text(self, text):
        """去掉不该念出来的东西"""
        if not text:
            return ''
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'\{.*?"pad_delta".*?\}', '', text, flags=re.DOTALL)
        text = re.sub(r'`[^`]*`', '', text)
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'[\(（\[【][^\)）\]】]{0,40}[\)）\]】]', '', text)   # 括号里的旁白
        text = re.sub(r'[*#_~>|]+', '', text)
        # emoji / 符号：念不出来，还会让在线接口报错
        text = re.sub(r'[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def speak(self, text):
        """对外接口：让 AI 说话（立即返回，合成和播放都在后台）"""
        if not self.is_enabled:
            return

        clean = self.clean_text(text)
        if len(clean) < 2:
            return

        with self._gen_lock:
            self._gen += 1
            gen = self._gen
        self._halt_playback()
        # 情绪在这一刻定死：试听/切换开关不会因为异步线程晚跑而串味
        tag = self.get_mood_tag()
        threading.Thread(target=self._speak_worker, args=(gen, clean, tag), daemon=True).start()

    def _speak_worker(self, gen, text, tag=''):
        # 初始化可能还在后台跑，别让调用方（GUI 线程）陪着等
        self.ensure_ready()
        if gen != self._gen or not self.available_engines:
            return
        self._pipeline(gen, text, tag)

    def _engine_order(self):
        """按「当前选择 → 剩余可用」排一条兜底链。"""
        preference = ['qwen', 'local', 'fish', 'baidu', 'sapi']
        usable = []
        for name in preference:
            if name == 'qwen' and self._qwen.available:
                usable.append('qwen')
            elif name == 'local' and self._local.available:
                usable.append('local')
            elif name == 'fish' and self._fish.available:
                usable.append('fish')
            elif name == 'baidu' and self._baidu_ok is not False:
                usable.append('baidu')
            elif name == 'sapi' and self._sapi.available:
                usable.append('sapi')

        chosen = self.engine_name if (self._explicit and self.engine_name in usable) else None
        if chosen:
            return [chosen] + [e for e in usable if e != chosen]
        return usable or ['sapi']

    def _get_pool(self):
        with self._pool_lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=self.WORKERS)
            return self._pool

    def _pipeline(self, gen, text, tag=''):
        sentences = split_sentences(text)
        if not sentences:
            return

        pool = self._get_pool()
        futures = {}
        try:
            for i in range(min(self.PREFETCH, len(sentences))):
                futures[i] = pool.submit(self._synth, sentences[i], tag)

            i = 0
            while i < len(sentences):
                if gen != self._gen:
                    break
                nxt = i + self.PREFETCH
                if nxt < len(sentences) and nxt not in futures:
                    futures[nxt] = pool.submit(self._synth, sentences[nxt], tag)

                fut = futures.pop(i, None)
                if fut is None:
                    break
                try:
                    path = fut.result()
                except Exception:
                    path = None
                if path is None:
                    i += 1
                    continue
                if gen != self._gen:
                    _unlink(path)
                    break
                self._play(path, gen)
                _unlink(path)
                i += 1
        except Exception as exc:
            print('❌ 语音流水线错误: %s' % exc)
        finally:
            for fut in futures.values():
                fut.cancel()   # 线程池常驻，任务取消即可
            # 整段念完了要主动闭嘴：不然口型只能等兜底定时器来收，
            # 中间会多张十几秒的嘴
            if gen == self._gen:
                self._notify_stop()

    def _synth(self, text, tag=''):
        last = None
        order = self._engine_order()
        for engine in order:
            try:
                if engine in TAG_ENGINES:
                    path = self._synth_rich(engine, text, tag)
                else:
                    path = self._synth_plain(engine, text)
                if path:
                    return path
            except Exception as exc:
                last = exc
                self._note_fail(engine, exc)
        if last is not None:
            print('❌ 语音合成失败: %s' % last)
        return None

    def _voice_key(self):
        engine, _, key = (self.voice_id or '').partition(':')
        return key

    def _synth_rich(self, engine, text, tag):
        """支持情感标签的引擎"""
        key = self._voice_key() if self.engine_name == engine else ''
        path = self._temp_path('.wav' if engine != 'fish' else '.mp3')
        if engine == 'qwen':
            return self._qwen.synthesize(text, key or 'Serena', path, tag)
        if engine == 'local':
            return self._local.synthesize(text, '', path, tag)
        if engine == 'fish':
            return self._fish.synthesize(text, '' if key in ('', 'default') else key, path, tag)
        raise RuntimeError('未知引擎 %s' % engine)

    def _synth_plain(self, engine, text):
        if engine == 'baidu':
            return self._synth_baidu(text)
        if engine == 'sapi':
            return self._synth_sapi(text)
        if engine == 'edge':
            return self._synth_edge(text)
        raise RuntimeError('未知引擎 %s' % engine)

    def _note_fail(self, engine, exc):
        count = min(self.MAX_FAILS, self._fails.get(engine, 0) + 1)
        self._fails[engine] = count
        if engine == 'baidu':
            print('⚠️ 在线语音失败(%s/%d): %s' % (count, self.MAX_FAILS, exc))
            if count >= self.MAX_FAILS:
                self._baidu_ok = False
                print('↩️ 在线语音不可用，本次会话改用系统语音')
                if self.engine_name == 'baidu':
                    self.engine_name = 'auto'
                    if self._sapi.voices:
                        self.voice_id = 'sapi:' + self._sapi.voices[0]['id']
        elif engine == 'edge':
            self._edge_ok = False
            print('⚠️ 微软在线语音不可用: %s' % exc)
        elif engine == 'qwen':
            if self._qwen.fatal:
                print('⚠️ 千问语音不可用: %s' % exc)
                self.available_engines = [e for e in self.available_engines if e != 'qwen']
            else:
                print('⚠️ 千问合成失败(%s/%d): %s' % (count, self.MAX_FAILS, exc))
        elif engine == 'local':
            print('⚠️ 本地语音失败(%s/%d): %s' % (count, self.MAX_FAILS, exc))
            if count >= self.MAX_FAILS:
                self._local.proto = None
        else:
            print('⚠️ %s 合成失败: %s' % (engine, exc))

    def _temp_path(self, suffix):
        if self._tmpdir is None or not os.path.isdir(self._tmpdir):
            self._tmpdir = tempfile.mkdtemp(prefix='hoshiori-tts-')
        return os.path.join(self._tmpdir, '%d-%d%s' % (
            int(time.time() * 1000) % 10 ** 9, next(self._seq), suffix))

    def _online_fetch(self, source, text):
        """向一个在线端点要一段音频，返回 mp3 字节"""
        conf = ONLINE_SOURCES[source]
        params = {'lan': 'zh', 'text': text, 'spd': self.speed, 'source': 'web'}
        if source == 'baike':
            params = {
                'tex': text, 'cuid': 'baike', 'lan': 'ZH', 'ctp': '1',
                'pdt': '301', 'vol': '9', 'rate': str(16 + self.speed * 3), 'per': '0',
            }
        session = self._get_session()
        session.headers['Referer'] = conf['referer']
        r = session.get(conf['url'], params=params, timeout=8)
        if r.status_code != 200 or len(r.content) < 400:
            raise RuntimeError('%s 返回 %s' % (source, r.status_code))
        return r.content

    def _synth_baidu(self, text):
        """在线合成。

        两个百度端点互为备份；都失败才抛错，让上层回退到系统语音。
        单个端点偶尔 503 是限流，隔一会儿再来一次通常就好。
        """
        preferred = self._online_source
        order = [preferred] + [k for k in ONLINE_SOURCES if k != preferred]
        last = None
        for source in order:
            for attempt in range(2):
                try:
                    data = self._online_fetch(source, text)
                    path = self._temp_path('.mp3')
                    with open(path, 'wb') as f:
                        f.write(data)
                    self._baidu_ok = True
                    self._fails.pop('baidu', None)
                    return path
                except Exception as exc:
                    last = exc
                    if attempt == 0:
                        time.sleep(0.2)
        raise last or RuntimeError('在线语音没有返回音频')

    def _synth_sapi(self, text):
        if not self._sapi.available:
            raise RuntimeError('系统语音不可用')
        voice_id = getattr(self, '_sapi_voice_key', None)
        if not voice_id or not any(v['id'] == voice_id for v in self._sapi.voices):
            voice_id = self._sapi.voices[0]['id']
        path = self._temp_path('.wav')
        self._sapi.synthesize(text, voice_id, self.rate, path)
        return path

    def _synth_edge(self, text):
        import asyncio
        import edge_tts

        voice = 'zh-CN-XiaoyiNeural'
        if self.voice_id.startswith('edge:'):
            voice = self.voice_id.split(':', 1)[1] or voice
        path = self._temp_path('.mp3')

        async def run():
            await edge_tts.Communicate(text, voice).save(path)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()
        if not os.path.exists(path) or os.path.getsize(path) < 400:
            raise RuntimeError('微软语音没有返回音频')
        return path

    # ------------------------------------------------------------ 播放

    def _play(self, path, gen):
        # 只有持锁时才能决定「现在播什么」。上一条回复的流水线可能刚好在
        # 这一瞬间判断出自己过期了，如果它不加判断就去 stop，会把新的这句掐掉。
        with self._play_lock:
            if gen != self._gen:
                return
            self._playing_gen = gen
            duration = self._player.play(path)
        if duration <= 0:
            return

        self.is_speaking = True
        self._notify_talk(duration)

        deadline = time.time() + max(2.0, duration + 5.0)
        try:
            while self._player.busy():
                if gen != self._gen:
                    with self._play_lock:
                        if self._playing_gen == gen:
                            self._player.stop()
                            self._playing_gen = -1
                    break
                if time.time() > deadline:
                    print('⚠️ 语音播放超时，强制收起')
                    with self._play_lock:
                        if self._playing_gen == gen:
                            self._player.stop()
                            self._playing_gen = -1
                    break
                time.sleep(0.025)
        finally:
            self.is_speaking = False

    def _halt_playback(self):
        self.is_speaking = False
        with self._play_lock:
            self._playing_gen = -1
            self._player.stop()
        self._notify_stop()

    def _notify_talk(self, seconds):
        cb = self.on_talk
        if cb:
            try:
                cb(max(0.6, seconds))
            except Exception:
                pass

    def _notify_stop(self):
        cb = self.on_stop
        if cb:
            try:
                cb()
            except Exception:
                pass

    # ------------------------------------------------------------ 状态 / 诊断

    def get_status(self):
        self.ensure_ready()
        return {
            'engine': self.engine_name,
            'engine_label': self.get_engine_label(),
            'voice_id': self.voice_id,
            'emotion': self.emotion_enabled,
            'mood': self._mood,
            'qwen_ok': self._qwen.available,
            'fish_ok': self._fish.available,
            'local_ok': self._local.available,
            'local_info': self._local.info,
            'local_url': self._cfg('tts_local_url', ''),
            'baidu_ok': self._baidu_ok is not False,
            'sapi_ok': self._sapi.available,
            'tag': self.get_mood_tag(),
        }

    def probe_local(self):
        """设置页「检测」按钮：立刻探一次本地服务。"""
        ok = self._local.probe(timeout=3.0, force=True)
        if ok and 'local' not in self.available_engines:
            self.available_engines.append('local')
        return {'ok': ok, 'info': self._local.info, 'url': self._cfg('tts_local_url', '')}

    def test_qwen(self):
        """设置页「测试 Key」：真的合成一句，确认 Key 能用。"""
        if not self._cfg('tts_api_key', ''):
            return {'ok': False, 'error': '还没有填写 API Key'}
        self._qwen.fatal = False
        path = self._temp_path('.wav')
        try:
            self._qwen.synthesize('你好呀，我是星织。这样说话，听起来自然些了吗？',
                                  'Serena', path, '')
            size = os.path.getsize(path)
            _unlink(path)
            return {'ok': size > 2000, 'error': '' if size > 2000 else '返回音频太小'}
        except Exception as exc:
            return {'ok': False, 'error': str(exc)[:200]}

    # ------------------------------------------------------------ 兼容旧接口

    def get_available_voices_list(self):
        return self.get_available_voices()


def _unlink(path):
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass
