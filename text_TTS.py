# test_tts.py
import time
from tts_manager import TTSManager

tts = TTSManager()
tts.set_enabled(True)
tts.speak("你好，我是星织，很高兴认识你！")
time.sleep(20)  # 等待足够时间完成合成和播放