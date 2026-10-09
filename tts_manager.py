# -*- coding: utf-8 -*-
"""
TTS管理器 - 多引擎支持
支持的引擎：
1. edge-tts (推荐) - 微软Edge在线TTS，高质量中文语音，免费
2. pyttsx3 - 离线TTS，使用系统语音引擎
3. gpt-sovits - 原有的GPT-SoVITS支持（可选）
"""
import threading
import io
import re
import os
import tempfile


class TTSManager:
    """TTS管理器 - 支持多种TTS引擎"""
    
    def __init__(self):
        self.is_enabled = False
        self.is_speaking = False
        self.current_engine = None
        self.engine_name = "edge"  # 默认使用edge-tts
        
        # Edge-TTS 配置
        self.edge_voice = "zh-CN-XiaoyiNeural"  # 小艺 - 年轻女声
        # 可选声音：
        # zh-CN-XiaoxiaoNeural - 晓晓（活泼）
        # zh-CN-XiaoyiNeural - 小艺（温柔）
        # zh-CN-YunxiNeural - 云希（男声）
        # zh-CN-YunyangNeural - 云扬（新闻播报）
        
        # 初始化pygame
        self._init_pygame()
        
        # 检测可用引擎
        self._detect_engines()
    
    def _init_pygame(self):
        """初始化pygame音频"""
        try:
            import pygame
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)
            self.pygame = pygame
            print("✓ 音频设备初始化成功")
        except Exception as e:
            print(f"⚠️ 音频设备初始化失败: {e}")
            self.pygame = None
    
    def _detect_engines(self):
        """检测可用的TTS引擎"""
        self.available_engines = []
        
        # 检测 edge-tts
        try:
            import edge_tts
            self.available_engines.append("edge")
            print("✓ edge-tts 可用 (推荐)")
        except ImportError:
            print("⚠️ edge-tts 未安装，运行: pip install edge-tts")
        
        # 检测 pyttsx3
        try:
            import pyttsx3
            self.available_engines.append("pyttsx3")
            print("✓ pyttsx3 可用 (离线)")
        except ImportError:
            print("⚠️ pyttsx3 未安装，运行: pip install pyttsx3")
        
        # 设置默认引擎
        if "edge" in self.available_engines:
            self.engine_name = "edge"
        elif "pyttsx3" in self.available_engines:
            self.engine_name = "pyttsx3"
        else:
            print("❌ 没有可用的TTS引擎！请安装: pip install edge-tts")

    def set_enabled(self, enabled: bool):
        """设置语音开关"""
        self.is_enabled = enabled
        print(f"🔊 语音{'已开启' if enabled else '已关闭'} (引擎: {self.engine_name})")
        if not enabled:
            self.stop()
    
    def set_engine(self, engine_name: str):
        """切换TTS引擎"""
        if engine_name in self.available_engines:
            self.engine_name = engine_name
            print(f"✓ 已切换到 {engine_name} 引擎")
            return True
        print(f"❌ 引擎 {engine_name} 不可用")
        return False
    
    def set_voice(self, voice: str):
        """设置Edge-TTS声音"""
        self.edge_voice = voice
        print(f"✓ 已设置声音: {voice}")
    
    def stop(self):
        """停止播放"""
        try:
            if self.pygame and self.pygame.mixer.get_init():
                if self.pygame.mixer.music.get_busy():
                    self.pygame.mixer.music.stop()
            self.is_speaking = False
        except:
            pass
    
    def clean_text(self, text: str) -> str:
        """清理文本"""
        text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'\{.*?"pad_delta".*?\}', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'[\(（].*?[\)）]', '', text)
        text = text.replace('*', '')
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def speak(self, text: str):
        """对外接口：让AI说话"""
        if not self.is_enabled or not self.available_engines:
            return
        
        clean_text = self.clean_text(text)
        if not clean_text or len(clean_text) < 2:
            return
        
        threading.Thread(target=self._run_tts, args=(clean_text,), daemon=True).start()
    
    def _run_tts(self, text: str):
        """执行TTS"""
        self.stop()
        
        if self.engine_name == "edge":
            self._run_edge_tts(text)
        elif self.engine_name == "pyttsx3":
            self._run_pyttsx3(text)

    def _run_edge_tts(self, text: str):
        """使用edge-tts合成语音"""
        try:
            import edge_tts
            import asyncio
            
            async def synthesize():
                communicate = edge_tts.Communicate(text, self.edge_voice)
                
                # 创建临时文件
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as f:
                    temp_path = f.name
                
                await communicate.save(temp_path)
                return temp_path
            
            print(f"🔊 合成语音: {text[:30]}{'...' if len(text) > 30 else ''}")
            
            # 运行异步任务
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            temp_path = loop.run_until_complete(synthesize())
            loop.close()
            
            # 播放
            if self.pygame and os.path.exists(temp_path):
                self.pygame.mixer.music.load(temp_path)
                self.pygame.mixer.music.play()
                self.is_speaking = True
                
                while self.pygame.mixer.music.get_busy():
                    self.pygame.time.Clock().tick(10)
                
                self.is_speaking = False
                
                # 清理临时文件
                try:
                    os.unlink(temp_path)
                except:
                    pass
                    
                print("✓ 语音播放完成")
            
        except Exception as e:
            print(f"❌ Edge-TTS错误: {e}")
    
    def _run_pyttsx3(self, text: str):
        """使用pyttsx3合成语音（离线）"""
        try:
            import pyttsx3
            
            if not hasattr(self, '_pyttsx3_engine'):
                self._pyttsx3_engine = pyttsx3.init()
                self._pyttsx3_engine.setProperty('rate', 180)  # 语速
                
                # 尝试设置中文声音
                voices = self._pyttsx3_engine.getProperty('voices')
                for voice in voices:
                    if 'chinese' in voice.name.lower() or 'zh' in voice.id.lower():
                        self._pyttsx3_engine.setProperty('voice', voice.id)
                        break
            
            print(f"🔊 合成语音: {text[:30]}{'...' if len(text) > 30 else ''}")
            self.is_speaking = True
            self._pyttsx3_engine.say(text)
            self._pyttsx3_engine.runAndWait()
            self.is_speaking = False
            print("✓ 语音播放完成")
            
        except Exception as e:
            print(f"❌ pyttsx3错误: {e}")
    
    def get_available_voices(self):
        """获取可用的Edge-TTS声音列表"""
        return [
            {"id": "zh-CN-XiaoyiNeural", "name": "小艺 (温柔女声)", "gender": "女"},
            {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (活泼女声)", "gender": "女"},
            {"id": "zh-CN-YunxiNeural", "name": "云希 (年轻男声)", "gender": "男"},
            {"id": "zh-CN-YunyangNeural", "name": "云扬 (新闻播报)", "gender": "男"},
            {"id": "zh-CN-XiaohanNeural", "name": "晓涵 (温和女声)", "gender": "女"},
            {"id": "zh-CN-XiaomengNeural", "name": "晓梦 (可爱女声)", "gender": "女"},
            {"id": "zh-CN-XiaoruiNeural", "name": "晓睿 (成熟女声)", "gender": "女"},
            {"id": "zh-CN-YunjianNeural", "name": "云健 (运动解说)", "gender": "男"},
        ]
