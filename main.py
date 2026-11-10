# -*- coding: utf-8 -*-
"""
星织 - 智能对话助手 (Web UI版)
使用Eel框架实现现代化Web界面
"""
import sys
import os
import time

import boot
import app_install

#: 兼容旧代码里对 boot_ms / boot_log 的引用
boot_ms = boot.ms
boot_log = boot.log


# 打包成无控制台程序后 sys.stdout / sys.stderr 是 None，
# 任何一次 print 都会抛 AttributeError 直接把进程带走。
# 所以要在其它模块导入之前先把这两个流接上。
def _ensure_std_streams():
    boot_log("解释器就绪")

    if sys.stdout is not None and sys.stderr is not None:
        return

    import app_paths

    stream = None
    try:
        log_path = app_paths.log_file()
        if os.path.exists(log_path) and os.path.getsize(log_path) > 2 * 1024 * 1024:
            os.remove(log_path)
        stream = open(log_path, 'a', encoding='utf-8', buffering=1)
    except Exception:
        try:
            stream = open(os.devnull, 'w', encoding='utf-8')
        except Exception:
            return

    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


import threading
import re
import json

import app_paths

_ensure_std_streams()

from tts_manager import TTSManager
from config import ConfigManager
from conversation_manager import ConversationManager
from api_handler import APIHandler
from reply_stream import ReplyStreamer, split_segments
import safety
from theme_system import ThemeManager
from web_bridge import start_web_app

boot_log("业务模块加载完成")


def _balanced_json(text, must_have=("appraisal", "dominant_emotion", "relationship_delta")):
    """从回复里挖出心理状态 JSON：优先代码块，其次按括号配平。

    用配平而不是正则，是因为这个 JSON 是嵌套的（appraisal 本身是个对象），
    非贪婪正则会在内层 } 处截断，解析必然失败，情绪就白算了。
    """
    if not text:
        return None, None

    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1)), m.group(0)
        except Exception:
            pass

    for start, ch in enumerate(text):
        if ch != "{":
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    block = text[start:i + 1]
                    if any(k in block for k in must_have):
                        try:
                            return json.loads(block), block
                        except Exception:
                            pass
                    break
    return None, None


def _has_word(text):
    """这句话里有没有真的说出字来。

    纯标点、纯省略号、纯空白都算没说话——模型偶尔会"省"过头，
    用户在界面上就只看到一个「...」，像是坏了。
    """
    if not text:
        return False
    # \w 已经把中文和字母数字包进来了；emoji 单独放行，
    # 因为「😭」本身也是一种回答。
    return bool(re.search(r"[\w\U0001F300-\U0001FAFF]", text))


class AIChatAppWeb:
    """星织AI助手 - Web版本"""
    
    def __init__(self):
        """初始化应用"""
        print("🚀 初始化星织AI助手...")
        
        # ⭐ 数据目录：非系统盘优先，用户可在设置里随时改
        self.data_dir = app_paths.data_dir()
        print("📁 数据目录: %s" % self.data_dir)
        boot_log("数据目录 " + self.data_dir)

        # 配置管理器
        self.config_manager = ConfigManager(save_dir=self.data_dir)
        boot_log("配置已载入")
        
        # 主题管理器
        self.theme_manager = ThemeManager(save_dir=self.config_manager.save_dir)
        
        # 对话管理器
        self.conversation_manager = ConversationManager(
            save_dir=self.config_manager.save_dir,
            builtin_role_prompt=self.config_manager.get_builtin_role_prompt()
        )
        
        # API处理器
        self.api_handler = None
        
        # TTS管理器（把配置传进去，语音选择能记住）
        self.tts_manager = TTSManager(self.config_manager)
        # 说话时让立绘的嘴跟着动
        self.tts_manager.on_talk = self._on_tts_talk
        self.tts_manager.on_stop = self._on_tts_stop
        
        # 立绘图片路径
        self.avatar_images = self.load_avatar_images()
        
        # 状态
        self.voice_enabled = bool(getattr(self.config_manager, 'tts_enabled', False))
        self.tts_manager.is_enabled = self.voice_enabled
        self.avatar_visible = self.config_manager.show_avatar
        self.current_mood = 'neutral'  # 当前情绪状态
        
        # Web桥接（稍后由web_bridge设置）
        self.web_bridge = None

        # 主动消息调度器（web 起好之后再启动）
        self.proactive = None
        self._bg_started = False
        
        # 如果没有对话，创建新对话
        if not self.conversation_manager.conversations:
            self.new_conversation()
        
        print("✅ 初始化完成")

    def toggle_voice(self):
        """切换语音开关"""
        self.voice_enabled = not self.voice_enabled
        self.tts_manager.set_enabled(self.voice_enabled)
        try:
            self.config_manager.tts_enabled = self.voice_enabled
            self.config_manager.save_config()
        except Exception:
            pass
        return self.voice_enabled

    # ---------------- 语音 → 口型 ----------------
    def _on_tts_talk(self, seconds):
        if self.web_bridge:
            self.web_bridge.start_avatar_talking(seconds)

    def _on_tts_stop(self):
        if self.web_bridge:
            self.web_bridge.stop_avatar_talking()
    def reload_avatars(self):
        """重新加载立绘"""
        print("🔄 刷新立绘列表...")
        self.avatar_images = self.load_avatar_images()
        # 通知前端更新当前立绘
        if self.web_bridge:
            self.web_bridge.update_avatar(self.current_mood)
    
    def load_avatar_images(self):
        """加载所有立绘图片路径（已弃用，使用Live2D）"""
        avatars = {}
        script_dir = os.path.dirname(os.path.abspath(__file__))
        avatar_dir = os.path.join(script_dir, "assets", "avatars")
        emotions = ["neutral", "happy", "angry", "sad", "shy"]
        
        if os.path.exists(avatar_dir):
            for emotion in emotions:
                path = os.path.join(avatar_dir, f"{emotion}.png")
                if os.path.exists(path):
                    avatars[emotion] = path
        
        # 默认返回空，因为现在使用Live2D
        if not avatars:
            avatars["neutral"] = None
        
        return avatars
    
    def new_conversation(self, continuity=True):
        """新建对话。continuity=False 表示"重新认识"：关系与跨对话记忆都不带过来。"""
        conv_id, conv = self.conversation_manager.new_conversation(continuity=continuity)
        print(f"✨ 新对话已创建: {conv['title']}")
        return conv_id
    
    def load_conversation(self, conv_id):
        """加载指定对话"""
        try:
            self.conversation_manager.current_conversation_id = conv_id
            self.conversation_manager._ensure_messages_loaded(conv_id)
            self.conversation_manager.apply_time_decay()
            print(f"📂 已加载对话: {conv_id}")
            return True
        except Exception as e:
            print(f"❌ 加载对话失败: {e}")
            return False
    
    # ---------------------------------------------------------------- 后台
    def start_background_services(self):
        """页面起来之后再做：写她今天的生活、开主动消息的定时器。

        放这儿而不是 __init__，是因为这两件事都要调模型；启动时先让窗口出来，
        用户看到界面再慢慢补，比转圈等 3 秒强。
        """
        if self._bg_started:
            return
        self._bg_started = True

        # 主动消息的定时器先起来：它只是看表，很轻，不会被网络拖住
        try:
            import proactive
            self.proactive = proactive.ProactiveScheduler(self)
            self.proactive.start()
        except Exception as exc:
            print("⚠️ 主动消息启动失败: %s" % exc)

        def warm_life():
            # 补她今天的生活：这是她"有自己的一天"的地基。要调一次模型，
            # 所以单独一个线程——它慢不能拖累上面那个定时器。
            try:
                if getattr(self.config_manager, "daily_life_enabled", True):
                    cfg = self.config_manager.get_current_api_config()
                    handler = APIHandler(
                        cfg["api_key"], cfg["api_endpoint"], cfg["model"],
                        "disabled", False, cfg.get("provider", ""))
                    self.conversation_manager.ensure_life_async(handler)
            except Exception as exc:
                print("⚠️ 生活预热失败: %s" % exc)

        threading.Thread(target=warm_life, daemon=True).start()

    def proactive_fire(self, force=True):
        """前端「现在让她说一句」/ 定时器共用。"""
        if self.proactive is None:
            try:
                import proactive
                self.proactive = proactive.ProactiveScheduler(self)
            except Exception as exc:
                return {"ok": False, "reason": "调度器不可用: %s" % exc}
        return self.proactive.fire(force=force)

    def proactive_status(self):
        if self.proactive is None:
            return {"enabled": bool(getattr(self.config_manager, "proactive_enabled", False)),
                    "why": "还没起来，稍等一会儿再刷新"}
        return self.proactive.status()

    def process_message(self, user_input):
        """
        处理用户消息
        Args:
            user_input: 用户输入的消息
        """
        # 在新线程中调用API
        threading.Thread(
            target=self._call_api_async,
            args=(user_input,),
            daemon=True
        ).start()
    
    def _call_api_async(self, user_input):
        """异步调用API"""
        try:
            current_conv = self.conversation_manager.get_current_conversation()
            if not current_conv:
                raise Exception("没有活动对话")
            
            # ⭐ Phase 3: 双系统思考 - 快速通道检查
            thinking_result = self.conversation_manager.process_with_dual_thinking(user_input)
            
            if thinking_result["use_fast_path"] and thinking_result["fast_response"]:
                # 使用快速通道（<100ms响应）
                print(f"⚡ 快速通道: {thinking_result['reason']}")
                fast_response = thinking_result["fast_response"]
                
                # 保存消息
                self.conversation_manager.add_message("user", user_input)
                self.conversation_manager.add_message("assistant", fast_response)
                
                # 发送到Web
                if self.web_bridge:
                    self.web_bridge.update_ai_response(fast_response)
                
                # TTS
                if self.voice_enabled:
                    self.tts_manager.speak(fast_response)
                
                return
            
            # ⭐ 0. 分析用户输入情绪
            user_emotion = self.conversation_manager.analyze_user_emotion(user_input)
            self._last_user_text = user_input
            self._last_user_emotion = user_emotion
            print(f"📊 用户情绪分析: {user_emotion['dominant_emotion']} (置信度: {user_emotion['confidence']:.2f})")
            if user_emotion['complex_emotions']:
                print(f"💭 复杂情绪: {list(user_emotion['complex_emotions'].keys())}")
            
            # ⭐ 立即保存用户消息（在API调用之前）
            self.conversation_manager.add_message("user", user_input)

            # 对方的情绪要攒起来：单轮没意义，连着几轮低落才是"他最近不太好"
            self.conversation_manager.note_user_emotion(user_emotion)
            
            # 1. 获取有效角色设定
            current_role = self.conversation_manager.get_effective_role_prompt()
            
            # 2. 获取智能压缩后的消息历史（包含刚存进去的这条，别再重复追加）
            compressed_messages_copy, recent_summary = \
                self.conversation_manager.get_compressed_messages()
            
            # 3. 构建长期记忆上下文：按这句话检索，不再整本注入
            current_psych = self.conversation_manager.get_psych_state()
            
            # ⭐ 改进1：添加时间戳到心理状态
            import time
            current_psych['last_interaction_time'] = time.time()
            
            pinned, recalled = self.conversation_manager.recall_memories(
                user_input, current_psych['state'])
            timeline = self.conversation_manager.recent_timeline()
            light_turn = self.conversation_manager.is_light_turn(user_input)
            if light_turn:
                # "在吗""晚安"这种：往事不用翻，固定事实还在，注入能薄一半
                recalled, timeline = [], []
                pinned = self.conversation_manager.pinned_only()
            memory_context = self.conversation_manager.memory_manager.build_context(
                pinned, recalled, recent_summary, budget_chars=1000, timeline=timeline)
            if pinned or recalled:
                print(f"🧠 记忆: 常用 {len(pinned)} 条, 相关 {len(recalled)} 条"
                      f"{'，时间线 %d 条' % len(timeline) if timeline else ''}"
                      f"{'（寒暄轮，已精简）' if light_turn else ''}")

            # 3.5 本地风险识别：命中就轻一点说话，不拦截、不审查
            risk_level, safety_note = safety.check(user_input)
            if risk_level:
                print(f"⚠️ 风险等级: {risk_level}")
            
            # 4. 获取离线生活状态
            offline_life = self.conversation_manager.get_offline_life_status()
            
            # 5. 获取情绪触发的记忆提示
            emotion_trigger = self.conversation_manager.get_emotion_trigger_context()
            
            # 6. 检测情绪过载
            mood_note = ""
            overload_status = self.conversation_manager.detect_emotion_overload()
            if overload_status["overloaded"]:
                print(f"⚠️  情绪过载检测: {overload_status['suggestion']}")
                mood_note = f"[内心感受: {overload_status['suggestion']}]"
            
            # 7. 根据当前模式获取API配置
            api_config = self.config_manager.get_current_api_config()
            
            # 创建或更新API handler
            self.api_handler = APIHandler(
                api_config["api_key"],
                api_config["api_endpoint"],
                api_config["model"],
                api_config.get("thinking_mode", "disabled"),  # ⭐ 传递思考模式
                api_config.get("web_search_enabled", False),  # ⭐ 传递联网搜索开关
                api_config.get("provider", "")  # ⭐ 传递提供商标识，用于适配请求参数
            )
            
            # 7.5 她这一天过到哪儿了：够久没补就后台补一段，不挡这一轮
            if getattr(self.config_manager, "daily_life_enabled", True):
                self.conversation_manager.ensure_life_async(self.api_handler)
                # 补写是异步的，这一轮拿到的可能还是旧的那份——无所谓，
                # 她要能说"我刚才在做什么"，慢一轮也比编一句强。
                offline_life = self.conversation_manager.get_offline_life_status()
            if mood_note:
                offline_life = (offline_life + "\n\n" + mood_note).strip()

            # 8. 调用API（流式：边生成边把气泡一条条推出去）
            streamer = None
            if self.web_bridge:
                streamer = ReplyStreamer(
                    lambda seg: self.web_bridge.update_ai_response(seg),
                    patch=lambda extra: self.web_bridge.append_ai_response(extra)
                )

            success, result = self.api_handler.call_api(
                compressed_messages_copy,
                current_role,
                current_psych,
                memory_context,
                offline_life,
                emotion_trigger,
                on_delta=streamer.feed if streamer else None,
                safety_note=safety_note,
                max_tokens=400 if light_turn else 1024
            )
            
            if success:
                clean_result = self._process_ai_response(result)

                # 只回了一串标点：模型把"可以很短"理解成了"可以不说"。
                # 流式还没往外吐过东西时才纠正——已经吐过了就认了，
                # 免得把她刚说出口的话又抹掉。
                if not _has_word(clean_result) and not (streamer and streamer.any_emitted):
                    print("ℹ️ 回复只有标点（%r），换成一句短话" % clean_result)
                    clean_result = "……嗯，我在。"

                if streamer is not None and streamer.any_emitted:
                    # 流式已经把绝大部分推过了，这里只补最后一段
                    streamer.finish(clean_result)
                    segments = streamer.segments
                else:
                    # 非流式（本地模型/接口不支持）：按句子切开，依次弹出
                    segments = self._push_reply_bubbles(clean_result)

                # 存档按气泡断行，重新打开时长得跟当时看到的一样
                if segments and len(segments) > 1:
                    clean_result = "\n".join(s for s in segments if s.strip())

                self.conversation_manager.add_message('assistant', clean_result)
                
                # ⭐ Phase 2: 认知一致性检查
                consistency_check = self.conversation_manager.check_cognitive_consistency(
                    result,
                    {"recent_turns": current_conv.get('messages', [])[-10:]}
                )
                
                if consistency_check["has_contradiction"]:
                    print("⚠️ 检测到认知矛盾:")
                    for suggestion in consistency_check["suggestions"]:
                        print(suggestion)
                
                # ⭐ Phase 2: 个性化学习
                self.conversation_manager.learn_from_interaction(
                    user_input,
                    {
                        "response_time": 30,  # 可以从实际测量获取
                        "topic_continued": True,  # 可以从对话分析获取
                        "current_topic": ""
                    }
                )
                
                # 规则抽取：姓名/生日/职业/喜好这些，不需要额外花 token 问模型
                extracted_info = self.conversation_manager.memory_manager.extract_key_information(
                    user_input,
                    clean_result          # 用去掉 JSON 的正文
                )

                if any([extracted_info.get("user_info"),
                        extracted_info.get("preferences"),
                        extracted_info.get("topics")]):
                    saved = self.conversation_manager.remember_from_extraction(
                        extracted_info, clean_result, pad=current_psych.get('state'))
                    if saved:
                        print(f"✅ 记忆入库: {saved} 条（规则抽取）")

                # 旧消息攒够一批就做一次摘要（后台跑，不挡回复）
                try:
                    threading.Thread(
                        target=self.conversation_manager.maybe_summarize,
                        args=(self.api_handler,), daemon=True).start()
                except Exception:
                    pass
                
                # ⭐ Phase 2: 检查是否需要主动行为
                initiative_check = self.conversation_manager.check_initiative_needed({
                    "recent_turns": current_conv.get('messages', [])[-20:],
                    "silence_duration": 0,  # 可以从实际测量获取
                    "unresolved_issues": [],  # 可以从记忆中提取
                    "recent_topics": []
                })
                
                if initiative_check.get("should_send"):
                    print(f"🎯 主动行为触发: {initiative_check['need']}")
                    initiative_message = initiative_check["message"]
                    
                    # 追加主动消息
                    clean_result += "\n\n" + initiative_message
                    
                    # 保存主动消息
                    self.conversation_manager.add_message("assistant", initiative_message)
                    
                    # 发送主动消息到Web（分段和非分段都需要）
                    if self.web_bridge:
                        self.web_bridge.update_ai_response(initiative_message)
                
                # TTS语音（使用完整的回复内容）
                if self.voice_enabled:
                    self.tts_manager.speak(clean_result)
            else:
                # 发送错误消息到Web
                if self.web_bridge:
                    self.web_bridge.update_ai_response(f"❌ 错误: {result}")
        
        except Exception as e:
            error_str = str(e)
            print(f"❌ 发生错误: {error_str}")
            
            # 针对连接错误的特殊提示
            friendly_error = error_str
            if "connection" in error_str.lower() or "connect" in error_str.lower():
                friendly_error = f"无法连接到模型服务器。\n\n如果您正在使用本地模式，请确保本地模型软件(如LM Studio)已开启并启动了Server。\n\n如果无法解决，请尝试切换到【在线模式】。(如果以前保存过，可能需要手动切换一次模型以刷新状态)"
            
            if self.web_bridge:
                self.web_bridge.update_ai_response(f"❌ 系统提示: {friendly_error}")
    
    def _push_reply_bubbles(self, text):
        """非流式时的兜底：把整段回复按句子切成气泡，一条条弹出来。

        第一段同步推（用户立刻看到反馈），其余丢到后台线程按 0.7~1.4 秒
        的间隔推，既不卡住 TTS，也不会让请求线程陪着 sleep。
        返回切出来的气泡列表，供调用方存档。
        """
        if not self.web_bridge or not text:
            return []

        segments = split_segments(text)
        if not segments:
            return []
        if len(segments) == 1:
            self.web_bridge.update_ai_response(segments[0])
            return segments

        self.web_bridge.update_ai_response(segments[0])

        rest = segments[1:]

        def run():
            import random
            for seg in rest:
                time.sleep(random.uniform(0.7, 1.4))
                try:
                    self.web_bridge.update_ai_response(seg)
                except Exception as exc:
                    print(f"⚠️ 气泡推送失败: {exc}")
                    break

        threading.Thread(target=run, daemon=True).start()
        return segments

    def _process_ai_response(self, raw_response):
        """处理AI原始回复，提取JSON和清理文本"""
        json_data = {}
        clean_text = raw_response
        
        # 提取心理状态 JSON（代码块优先，其次括号配平）
        json_data, block = _balanced_json(raw_response)
        if block:
            clean_text = raw_response.replace(block, "").strip()
            if json_data:
                mono = json_data.get('internal_monologue')
                if mono:
                    print(f"\n🧠 AI内心独白: {mono}")
                print(f"📊 评价: {json_data.get('appraisal', {})}")
                print(f"💞 关系变化: {json_data.get('relationship_delta', {})}")
        if not json_data:
            print("ℹ️ 这轮没拿到状态 JSON，情绪只按时间回落")
        
        # 强力清理：移除所有 JSON 相关内容（包括不完整的）
        # 1. 移除 ```json ... ``` 块
        clean_text = re.sub(r'```json.*?```', '', clean_text, flags=re.DOTALL)
        
        # 2. 移除完整的 { ... } 块（包含特定关键字）- 多次执行以处理嵌套
        for _ in range(3):
            clean_text = re.sub(r'\{[^{}]*?(?:pad_delta|relationship_delta|dominant_emotion|internal_monologue|user_intent_analysis|memory_update|appraisal)[^{}]*?\}', '', clean_text, flags=re.DOTALL)
        
        # 3. 移除任何以逗号开头的JSON片段（最常见的残留模式）
        clean_text = re.sub(r',\s*"[^"]+"\s*:\s*[^,}]*(?:,\s*"[^"]+"\s*:\s*[^,}]*)*\s*\}', '', clean_text, flags=re.DOTALL)
        
        # 4. 移除包含JSON关键字的任何行
        lines = clean_text.split('\n')
        filtered_lines = []
        for line in lines:
            # 如果行中包含JSON关键字，跳过
            if any(keyword in line for keyword in ['relationship_delta', 'dominant_emotion', 'pad_delta', 'internal_monologue', 'user_intent_analysis', 'memory_update', 'trust', 'intimacy', 'stress', 'pleasure', 'arousal', 'dominance']):
                continue
            # 如果行主要是JSON语法（大括号、冒号、逗号），跳过
            stripped = line.strip()
            if stripped and not any(c.isalpha() and ord(c) > 127 for c in stripped):  # 没有中文字符
                if stripped.count('{') + stripped.count('}') + stripped.count(':') + stripped.count(',') > len(stripped) * 0.3:
                    continue
            filtered_lines.append(line)
        clean_text = '\n'.join(filtered_lines)
        
        # 5. 移除孤立的JSON语法字符
        clean_text = re.sub(r'^\s*[,{}\[\]:]+\s*$', '', clean_text, flags=re.MULTILINE)
        
        # 6. 移除开头和结尾的逗号、大括号
        clean_text = re.sub(r'^[,\s{}]+', '', clean_text)
        clean_text = re.sub(r'[,\s{}]+$', '', clean_text)
        
        # 7. 特殊处理：移除特定的残留模式（用户报告的具体案例）
        # 匹配类似 ', "relationship_delta": { "trust": , "intimacy": , "stress": }, "dominant_emotion": "" }'
        clean_text = re.sub(r',\s*"relationship_delta"\s*:\s*\{[^}]*\}\s*,\s*"dominant_emotion"\s*:\s*"[^"]*"\s*\}', '', clean_text)
        
        # 8. 移除任何包含空值的JSON片段（trust: , intimacy: 等）
        clean_text = re.sub(r'"[^"]+"\s*:\s*,', '', clean_text)
        
        # 最后的清理：移除多余的空行和空格
        clean_text = re.sub(r'\n\s*\n+', '\n', clean_text)
        clean_text = re.sub(r'\s+', ' ', clean_text)  # 合并多个空格
        clean_text = clean_text.strip()
        
        # 如果清理后文本为空，返回一个默认消息
        if not clean_text or clean_text in [',', '{', '}', '{}', '{ }']:
            clean_text = "..."
        
        # 更新心理状态
        if json_data:
            user_text = getattr(self, '_last_user_text', '') or ''
            user_emotion = getattr(self, '_last_user_emotion', None)

            new_core = self.conversation_manager.update_psych_state(
                json_data, user_text=user_text, analyzer_result=user_emotion)

            emotion_info = getattr(self.conversation_manager, '_last_emotion_info', None)
            if emotion_info:
                print("🎭 情绪: %s | ΔPAD=%s | 基线=%s%s" % (
                    emotion_info.get('emotions') or '平静',
                    emotion_info.get('delta'),
                    emotion_info.get('baseline'),
                    ' (与文本情绪冲突，已削弱)' if emotion_info.get('contradicted') else ''))
                if emotion_info.get('lingering'):
                    print("💭 余味: %s ×%.2f" % (
                        emotion_info['lingering'].get('emotion'),
                        float(emotion_info['lingering'].get('intensity', 0))))

            mood = json_data.get('dominant_emotion', 'neutral')
            self.current_mood = mood  # 保存当前情绪状态

            # ⭐ 把情绪交给语音：开心时语调上扬、难过时放缓，听着才像有情绪的人
            try:
                pad_now = None
                if new_core:
                    pad_now = {
                        'pleasure': new_core['state']['pleasure'],
                        'arousal': new_core['state']['arousal'],
                        'dominance': new_core['state']['dominance'],
                    }
                self.tts_manager.set_mood(mood, pad_now)
            except Exception:
                pass
            
            # 更新Web界面
            if self.web_bridge:
                self.web_bridge.update_avatar(mood)
                if new_core:
                    self.web_bridge.update_affection(new_core['relationship']['intimacy'])
                    
                    # ⭐ 新增：发送PAD值到前端
                    pad_values = {
                        'pleasure': new_core['state']['pleasure'],
                        'arousal': new_core['state']['arousal'],
                        'dominance': new_core['state']['dominance']
                    }
                    self.web_bridge.update_pad_values(pad_values)
                    
                self.web_bridge.update_mood(mood)
                
                # ⭐ 新增：根据对话内容触发特效
                self.web_bridge.trigger_avatar_effect(clean_text)
                
                # ⭐ 说话动画：只在语音真正播放时由 TTS 回调驱动（on_talk / on_stop）
                # 以前这里按字数估一个时长去动嘴，但单位是毫秒、前端按秒算，
                # 结果嘴会张两小时；而且没开语音也会动。现在统一交给语音。
                if not self.voice_enabled:
                    self.web_bridge.stop_avatar_talking()
            
            # 模型主动给的记忆（memory_update）落库
            mem_update = json_data.get('memory_update')
            if isinstance(mem_update, dict) and mem_update.get('content'):
                kind = mem_update.get('type') or 'event'
                kind = {'profile': 'profile', 'preference': 'preference',
                        'event': 'event'}.get(kind, 'event')
                saved = self.conversation_manager.remember_fact(
                    mem_update['content'], kind=kind,
                    pad=new_core['state'] if new_core else None)
                if saved:
                    print("✅ 记住了: %s" % mem_update['content'])
        
        # 清理文本
        clean_text = self._clean_ai_message(clean_text)
        return clean_text
    
    def _clean_ai_message(self, text):
        """清洗AI消息中的所有标签和情绪文字"""
        # 移除```json...```代码块（贪婪匹配，包含换行）
        text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL | re.MULTILINE)
        
        # 移除独立的JSON对象（包含pad_delta等关键字）
        # 使用非贪婪匹配，处理多行JSON
        text = re.sub(r'\{[^}]*?(?:"pad_delta"|"internal_monologue"|"dominant_emotion")[^}]*?\}', '', text, flags=re.DOTALL)
        
        # 额外处理：移除包含多个嵌套对象的JSON块
        text = re.sub(r'\{\s*"[^"]+"\s*:\s*[^}]+,\s*"[^"]+"\s*:\s*\{[^}]+\}[^}]*\}', '', text, flags=re.DOTALL)
        
        # 移除XML样式的标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 移除情绪关键词和数字
        text = re.sub(r'\b(neutral|happy|sad|angry|shy)\s*-?\d+\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\b(neutral|happy|sad|angry|shy)\b', '', text, flags=re.IGNORECASE)
        
        # 清理多余空格和换行。
        # 注意不能把 \n 压成空格：气泡之间就是用 \n 存的，
        # 压平之后重新打开对话，一轮里的三五条会粘成一大段。
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r' *\n *', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()


def _handle_uninstall():
    """被 `Hoshiori.exe --uninstall` 调起时走这里（Windows「应用和功能」里点的卸载）。"""
    if not getattr(sys, 'frozen', False):
        print("开发模式下不执行卸载")
        return
    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    quiet = '--quiet' in sys.argv
    print("开始卸载: %s" % install_dir)
    app_install.run_uninstall(install_dir, quiet=quiet)


def main():
    """主函数"""
    if app_install.is_uninstall_request():
        _handle_uninstall()
        return

    # --unlock：手动清掉上次没退干净的窗口进程。
    # 开发时改前端提示"文件被占用/权限不足"，跑一下这个就好，
    # 不用去任务管理器里一个个翻 msedgewebview2。
    if '--unlock' in sys.argv:
        import runtime_guard
        runtime_guard.main([a for a in sys.argv[1:] if a != '--unlock'])
        return

    print("=" * 50)
    print("🌟 星织 - 智能对话助手")
    print("=" * 50)

    boot_log("进入 main()")

    # 创建应用实例
    app = AIChatAppWeb()
    boot_log("应用对象就绪")

    # 启动Web应用（使用随机端口避免冲突）
    start_web_app(app, port=0)


if __name__ == "__main__":
    main()