# -*- coding: utf-8 -*-
"""
TTS 管理器 —— 句子级流水线 + 多引擎

为什么重写（2026-11）
--------------------
1. **edge-tts 已经不可用**：微软在 2026-10-10 之后改了 Edge「大声朗读」的鉴权，
   非官方调用一律返回 403（WSServerHandshakeError）。这不是网络问题，全球都一样。
   所以它从「默认引擎」降级为「能用就顺手用上」的备选。
2. **旧实现是「整段合完再播」**：一段 300 字的回复要先等整段合成（2~6 秒）才有
   第一个音，用户感觉就是「说了半天才出声」。现在按句子切开、边合成边播，
   第一声通常在 0.3~0.6 秒。
3. **旧实现用忙等循环播 mp3**：切消息、打断都要等它自己跑完。

现在的引擎（按优先级自动选）：
    baidu  —— 百度翻译的免费语音接口，无需 Key，中文自然，约 200~700ms/句
    sapi   —— Windows 系统语音（SAPI5 + OneCore），离线，20~50ms/句
    edge   —— 微软在线神经语音，需要网络且当前多地区 403

对外接口保持兼容：is_enabled / is_speaking / speak() / stop() / set_enabled() /
set_voice() / get_available_voices()
"""

import os
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------- 文本切分

_STRONG = '。！？!?…；;'
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
        seg = seg.strip()
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

    # -- 线程内缓存 SpVoice：Worker 线程固定两个，复用能省掉每次的 COM 建对象开销
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
                # 某些 pywin32 版本不接受 None，重新挂回默认输出
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


# ---------------------------------------------------------------- 在线引擎

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
    ('zh-CN-XiaohanNeural', '晓涵（温和）'),
    ('zh-CN-YunxiNeural', '云希（男声）'),
)


class TTSManager:
    """多引擎语音合成 + 逐句流水线播放"""

    PREFETCH = 2          # 播放第 n 句时，第 n+1、n+2 句在合成
    WORKERS = 1           # 合成线程只开一个：并发请求会被在线接口限流(503)
    MAX_FAILS = 2         # 同一引擎连续失败几次就本次会话不再用

    def __init__(self, config_manager=None):
        self.is_enabled = False
        self.is_speaking = False

        #: auto / baidu / sapi / edge
        self.engine_name = 'auto'
        self.voice_id = ''
        self.rate = 0             # 系统语音语速 -10~10
        self.speed = 5            # 百度语速 1~15
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

        self._sapi = SapiEngine()
        self._sapi_voice_key = None
        self._online_source = 'fanyi'
        self._baidu_ok = None     # None 未探测 / True / False
        self._edge_ok = False
        self._fails = {}
        self._prewarming = False
        self._warm_lock = threading.Lock()

        #: 口型联动回调：on_talk(秒) / on_stop()
        self.on_talk = None
        self.on_stop = None

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
            self._load_prefs()
            self._ready = True
        return True

    def prewarm(self):
        """后台预热：音频设备 + 网络连接。用户打开语音开关时就不用等。"""
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
            if self._baidu_ok is None:
                self._probe_baidu()
            if self._baidu_ok:
                # 提前建好 TLS 连接：冷启动那 1.5 秒基本就是握手
                try:
                    self._get_session().get('https://fanyi.baidu.com/', timeout=6)
                except Exception:
                    pass

            # 合成线程里第一次用系统语音要 0.5 秒（COM 初始化 + 找 token）。
            # 现在把两个 worker 线程先建出来、各自把语音对象准备好，
            # 真正说话时这一步就不算了。
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
                    'Referer': 'https://fanyi.baidu.com/',
                })
                self._session = s
            return self._session

    def _probe_baidu(self):
        try:
            import requests  # noqa: F401
            r = None
            for _ in range(2):
                r = self._get_session().get(
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
                self._apply_voice_id(saved)
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
        if self._baidu_ok is not False and 'baidu' in self.available_engines:
            self._apply_voice_id('baidu:fanyi')
        elif self._sapi.voices:
            self._apply_voice_id('sapi:' + self._sapi.voices[0]['id'])
        else:
            self._apply_voice_id('auto')

    # ------------------------------------------------------------ 声音选择

    def _voice_exists(self, voice_id):
        # 注意：这里不能用 get_available_voices()，那会再进一次 ensure_ready 的锁
        if not voice_id:
            return False
        engine, _, key = voice_id.partition(':')
        if engine == 'baidu':
            return self._baidu_ok is not False
        if engine == 'sapi':
            return any(v['id'] == key for v in self._sapi.voices)
        if engine == 'edge':
            return self._edge_ok
        return False

    def _apply_voice_id(self, voice_id):
        if not voice_id:
            return
        self.voice_id = voice_id
        engine, _, key = voice_id.partition(':')
        if engine in ('baidu', 'sapi', 'edge'):
            self.engine_name = engine
            if engine == 'sapi' and key:
                self._sapi_voice_key = key
            elif engine == 'baidu' and key in ONLINE_SOURCES:
                self._online_source = key
        else:
            self.engine_name = 'auto'

    def get_available_voices(self):
        self.ensure_ready()
        out = []
        if self._baidu_ok is not False and 'baidu' in self.available_engines:
            for key, conf in ONLINE_SOURCES.items():
                out.append({
                    'id': 'baidu:' + key,
                    'name': conf['label'],
                    'engine': 'baidu',
                    'note': '需要网络，约 0.3 秒出声' if key == 'fanyi' else '备用线路',
                })
        for v in self._sapi.voices:
            out.append({
                'id': 'sapi:' + v['id'],
                'name': '系统 · %s' % v['name'],
                'engine': 'sapi',
                'note': '离线可用，几乎瞬间出声',
            })
        if self._edge_ok:
            for vid, vname in EDGE_VOICES:
                out.append({
                    'id': 'edge:' + vid,
                    'name': '微软 · %s' % vname,
                    'engine': 'edge',
                    'note': '在线神经语音',
                })
        if not out:
            out.append({'id': 'auto', 'name': '暂无可用的语音引擎', 'engine': 'auto', 'note': ''})
        return out

    def set_voice(self, voice_id):
        """切换声音（voice_id 形如 'baidu:default' / 'sapi:<token>'）"""
        self.ensure_ready()
        if not voice_id:
            return False
        engine = voice_id.split(':', 1)[0]
        if engine == 'baidu' and self._baidu_ok is False:
            print('⚠️ 在线语音当前不可用')
            return False
        if engine == 'sapi':
            key = voice_id.split(':', 1)[1]
            if not any(v['id'] == key for v in self._sapi.voices):
                print('⚠️ 没有这个系统语音: %s' % key)
                return False
        self._apply_voice_id(voice_id)
        self._save_prefs()
        print('✓ 语音已切换: %s' % voice_id)
        return True

    def set_engine(self, engine_name):
        if engine_name == 'auto':
            self.engine_name = 'auto'
            self._choose_default_voice()
            self._save_prefs()
            return True
        return self.set_voice(engine_name)

    def get_engine_label(self):
        return {'baidu': '在线', 'sapi': '系统', 'edge': '微软', 'auto': '自动'}.get(
            self.engine_name, self.engine_name)

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
        threading.Thread(target=self._speak_worker, args=(gen, clean), daemon=True).start()

    def _speak_worker(self, gen, text):
        # 初始化可能还在后台跑，别让调用方（GUI 线程）陪着等
        self.ensure_ready()
        if gen != self._gen or not self.available_engines:
            return
        self._pipeline(gen, text)

    def _engine_order(self):
        if self.engine_name == 'sapi' and self._sapi.available:
            return ['sapi', 'baidu', 'edge']
        if self.engine_name == 'baidu' and self._baidu_ok is not False:
            return ['baidu', 'sapi', 'edge']
        if self.engine_name == 'edge' and self._edge_ok:
            return ['edge', 'baidu', 'sapi']
        order = []
        if self._baidu_ok is not False:
            order.append('baidu')
        if self._sapi.available:
            order.append('sapi')
        if self._edge_ok:
            order.append('edge')
        return order or ['sapi']

    def _get_pool(self):
        with self._pool_lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=self.WORKERS)
            return self._pool

    def _pipeline(self, gen, text):
        sentences = split_sentences(text)
        if not sentences:
            return

        pool = self._get_pool()
        futures = {}
        try:
            for i in range(min(self.PREFETCH, len(sentences))):
                futures[i] = pool.submit(self._synth, sentences[i])

            i = 0
            while i < len(sentences):
                if gen != self._gen:
                    break
                nxt = i + self.PREFETCH
                if nxt < len(sentences) and nxt not in futures:
                    futures[nxt] = pool.submit(self._synth, sentences[nxt])

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

    def _synth(self, text):
        last = None
        for engine in self._engine_order():
            try:
                if engine == 'baidu':
                    return self._synth_baidu(text)
                if engine == 'sapi':
                    return self._synth_sapi(text)
                if engine == 'edge':
                    return self._synth_edge(text)
            except Exception as exc:
                last = exc
                self._note_fail(engine, exc)
        if last is not None:
            print('❌ 语音合成失败: %s' % last)
        return None

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

    def _temp_path(self, suffix):
        if self._tmpdir is None or not os.path.isdir(self._tmpdir):
            self._tmpdir = tempfile.mkdtemp(prefix='hoshiori-tts-')
        return os.path.join(self._tmpdir, '%d%s' % (int(time.time() * 1000) % 10**9, suffix))

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

    # ------------------------------------------------------------ 兼容旧接口

    def get_available_voices_list(self):
        return self.get_available_voices()



def _unlink(path):
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass
