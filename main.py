# -*- coding: utf-8 -*-
"""
星织 - 智能对话助手 (Web UI版)
使用Eel框架实现现代化Web界面
"""
import threading
import re
import os
import json

from tts_manager import TTSManager
from config import ConfigManager
from conversation_manager import ConversationManager
from api_handler import APIHandler
from theme_system import ThemeManager
from web_bridge import start_web_app


class AIChatAppWeb:
    """星织AI助手 - Web版本"""
    
    def __init__(self):
        """初始化应用"""
        print("🚀 初始化星织AI助手...")
        
        # 配置管理器
        self.config_manager = ConfigManager()
        
        # 主题管理器
        self.theme_manager = ThemeManager(save_dir=self.config_manager.save_dir)
        
        # 对话管理器
        self.conversation_manager = ConversationManager(
            save_dir=self.config_manager.save_dir,
            builtin_role_prompt=self.config_manager.get_builtin_role_prompt()
        )
        
        # API处理器
        self.api_handler = None
        
        # TTS管理器
        self.tts_manager = TTSManager()
        
        # 立绘图片路径
        self.avatar_images = self.load_avatar_images()
        
        # 状态
        self.voice_enabled = self.tts_manager.is_enabled
        self.avatar_visible = self.config_manager.show_avatar
        self.current_mood = 'neutral'  # 当前情绪状态
        
        # Web桥接（稍后由web_bridge设置）
        self.web_bridge = None
        
        # 如果没有对话，创建新对话
        if not self.conversation_manager.conversations:
            self.new_conversation()
        
        print("✅ 初始化完成")

    def toggle_voice(self):
        """切换语音开关"""
        self.voice_enabled = not self.voice_enabled
        self.tts_manager.set_enabled(self.voice_enabled)
        return self.voice_enabled
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
    
    def new_conversation(self):
        """新建对话"""
        conv_id, conv = self.conversation_manager.new_conversation()
        print(f"✨ 新对话已创建: {conv['title']}")
        return True
    
    def load_conversation(self, conv_id):
        """加载指定对话"""
        try:
            self.conversation_manager.current_conversation_id = conv_id
            self.conversation_manager.apply_time_decay()
            
            # ⭐ 加载记忆图谱
            conv = self.conversation_manager.get_current_conversation()
            if conv and 'memory' in conv:
                print("🔄 正在构建记忆图谱...")
                self.conversation_manager.memory_graph.build_from_json(conv['memory'])
                print("✅ 记忆图谱构建完成")
            
            print(f"📂 已加载对话: {conv_id}")
            return True
        except Exception as e:
            print(f"❌ 加载对话失败: {e}")
            return False
    
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
            print(f"📊 用户情绪分析: {user_emotion['dominant_emotion']} (置信度: {user_emotion['confidence']:.2f})")
            if user_emotion['complex_emotions']:
                print(f"💭 复杂情绪: {list(user_emotion['complex_emotions'].keys())}")
            
            # ⭐ 立即保存用户消息（在API调用之前）
            self.conversation_manager.add_message("user", user_input)
            
            # 1. 获取有效角色设定
            current_role = self.conversation_manager.get_effective_role_prompt()
            
            # 2. 获取智能压缩后的消息历史
            compressed_messages, recent_summary = self.conversation_manager.get_compressed_messages()
            
            # 添加当前用户消息
            compressed_messages_copy = compressed_messages.copy()
            compressed_messages_copy.append({"role": "user", "content": user_input})
            
            # 3. 构建长期记忆上下文
            long_term_memory = self.conversation_manager.get_long_term_memory()
            current_psych = self.conversation_manager.get_psych_state()
            
            # ⭐ 改进1：添加时间戳到心理状态
            import time
            current_psych['last_interaction_time'] = time.time()
            
            memory_context = ""
            if long_term_memory:
                memory_context = self.conversation_manager.memory_manager.build_memory_context(
                    long_term_memory,
                    recent_summary,
                    current_pad=current_psych['state']
                )
            
            # 4. 获取离线生活状态
            offline_life = self.conversation_manager.get_offline_life_status()
            
            # 5. 获取情绪触发的记忆提示
            emotion_trigger = self.conversation_manager.get_emotion_trigger_context()
            
            # 6. 检测情绪过载
            overload_status = self.conversation_manager.detect_emotion_overload()
            if overload_status["overloaded"]:
                print(f"⚠️  情绪过载检测: {overload_status['suggestion']}")
                if offline_life:
                    offline_life += f"\n\n[内心感受: {overload_status['suggestion']}]"
                else:
                    offline_life = f"[内心感受: {overload_status['suggestion']}]"
            
            # 7. 根据当前模式获取API配置
            api_config = self.config_manager.get_current_api_config()
            
            # 创建或更新API handler
            self.api_handler = APIHandler(
                api_config["api_key"],
                api_config["api_endpoint"],
                api_config["model"],
                api_config.get("thinking_mode", "disabled"),  # ⭐ 传递思考模式
                api_config.get("web_search_enabled", False)  # ⭐ 传递联网搜索开关
            )
            
            # 8. 调用API
            success, result = self.api_handler.call_api(
                compressed_messages_copy,
                current_role,
                current_psych,
                memory_context,
                offline_life,
                emotion_trigger
            )
            
            if success:
                # ⭐ 改进2：后处理分段回复
                # 检查是否包含分段标记 $
                if '$' in result:
                    print("🎯 检测到分段标记，启动分段回复功能")
                    segments = result.split('$')
                    print(f"📊 分段数量: {len(segments)}")
                    
                    # 处理并发送第一段
                    clean_first = self._process_ai_response(segments[0].strip())
                    print(f"📤 发送第1段: {clean_first[:50]}...")
                    
                    # 发送第一段到前端
                    if self.web_bridge:
                        self.web_bridge.update_ai_response(clean_first)
                    
                    # 保存完整消息到对话历史（移除$符号）
                    full_message = ' '.join([seg.strip() for seg in segments])
                    self.conversation_manager.add_message('assistant', full_message)
                    
                    # 延迟发送后续段落
                    import time
                    import random
                    for i, segment in enumerate(segments[1:], 1):
                        if segment.strip():
                            # 随机延迟 1-2 秒，模拟"正在输入"
                            delay = random.uniform(1.0, 2.0)
                            print(f"⏳ 等待 {delay:.1f}秒 后发送第{i+1}段...")
                            time.sleep(delay)
                            
                            # 清理后续段落（可能包含JSON）
                            clean_segment = self._clean_ai_message(segment.strip())
                            print(f"📤 发送第{i+1}段: {clean_segment[:50]}...")
                            
                            # 发送后续段落
                            if self.web_bridge:
                                self.web_bridge.update_ai_response(clean_segment)
                    
                    print("✅ 分段回复完成")
                    # 使用完整消息进行后续处理
                    clean_result = full_message
                else:
                    # 正常处理（无分段）
                    clean_result = self._process_ai_response(result)
                    
                    # 发送到前端
                    if self.web_bridge:
                        self.web_bridge.update_ai_response(clean_result)
                    
                    # 保存到对话历史
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
                
                # 双重记忆提取
                extracted_info = self.conversation_manager.memory_manager.extract_key_information(
                    user_input,
                    result if not '$' in result else full_message  # 使用完整消息
                )
                
                # 如果规则方式提取到信息，合并到记忆
                if any([
                    extracted_info.get("user_info"),
                    extracted_info.get("preferences"),
                    extracted_info.get("topics"),
                    extracted_info.get("emotional_events")
                ]):
                    if long_term_memory is not None:
                        updated_mem = self.conversation_manager.memory_manager.merge_extracted_info_to_memory(
                            extracted_info,
                            long_term_memory
                        )
                        self.conversation_manager.conversations[
                            self.conversation_manager.current_conversation_id
                        ]['memory'] = updated_mem
                        self.conversation_manager.save_conversations()
                        
                        if extracted_info.get("user_info"):
                            print(f"✅ 记忆已更新(规则): 用户信息 {extracted_info['user_info']}")
                        if extracted_info.get("preferences"):
                            print(f"✅ 记忆已更新(规则): 偏好 {extracted_info['preferences']}")
                        if extracted_info.get("topics"):
                            print(f"✅ 记忆已更新(规则): 话题 {extracted_info['topics']}")
                
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
    
    def _process_ai_response(self, raw_response):
        """处理AI原始回复，提取JSON和清理文本"""
        json_data = {}
        clean_text = raw_response
        
        # 尝试提取JSON（多种模式）
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', raw_response, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\{.*?"pad_delta".*?\})', raw_response, re.DOTALL)
        if not json_match:
            # 尝试匹配任何包含 relationship_delta 或 dominant_emotion 的 JSON
            json_match = re.search(r'(\{[^}]*?"(?:relationship_delta|dominant_emotion|internal_monologue)"[^}]*?\})', raw_response, re.DOTALL)
        
        if json_match:
            try:
                json_str = json_match.group(1)
                
                # 简单清理
                if "'" in json_str and '"' not in json_str:
                    json_str = json_str.replace("'", '"')
                    
                json_data = json.loads(json_str)
                # 从原文中移除 JSON 部分
                clean_text = raw_response.replace(json_match.group(0), "").strip()
                
                if 'internal_monologue' in json_data:
                    print(f"\n🧠 AI内心独白: {json_data['internal_monologue']}")
                    print(f"📊 PAD变化: {json_data.get('pad_delta', {})}")
                    print(f"💞 关系变化: {json_data.get('relationship_delta', {})}")
                    
            except Exception as e:
                print(f"⚠️  JSON解析失败: {e}")
                # JSON 解析失败时，尝试移除看起来像 JSON 的部分
                clean_text = raw_response
        
        # 强力清理：移除所有 JSON 相关内容（包括不完整的）
        # 1. 移除 ```json ... ``` 块
        clean_text = re.sub(r'```json.*?```', '', clean_text, flags=re.DOTALL)
        
        # 2. 移除完整的 { ... } 块（包含特定关键字）- 多次执行以处理嵌套
        for _ in range(3):
            clean_text = re.sub(r'\{[^{}]*?(?:pad_delta|relationship_delta|dominant_emotion|internal_monologue|user_intent_analysis|memory_update)[^{}]*?\}', '', clean_text, flags=re.DOTALL)
        
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
            if 'memory_update' in json_data and json_data['memory_update']:
                mem = json_data['memory_update']
                if mem.get('type'):
                    print(f"📝 记忆更新 [{mem['type']}]: {mem['content']}")
            
            new_core = self.conversation_manager.update_psych_state(json_data)
            
            mood = json_data.get('dominant_emotion', 'neutral')
            self.current_mood = mood  # 保存当前情绪状态
            
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
                
                # ⭐ 新增：计算说话动画时长
                talk_duration = min(len(clean_text) * 50, 5000)  # 最多5秒
                self.web_bridge.start_avatar_talking(talk_duration)
            
            # 处理记忆更新(JSON方式)
            memory_info = self.conversation_manager.memory_manager.extract_memory_from_json(json_data)
            if memory_info["has_update"]:
                long_term_mem = self.conversation_manager.get_long_term_memory()
                if long_term_mem is not None:
                    updated_mem = self.conversation_manager.memory_manager.merge_memory_to_storage(
                        memory_info,
                        long_term_mem
                    )
                    self.conversation_manager.conversations[
                        self.conversation_manager.current_conversation_id
                    ]['memory'] = updated_mem
                    self.conversation_manager.save_conversations()
                    print(f"✅ 记忆已更新(JSON): {memory_info['content']}")
        
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
        
        # 清理多余空格和换行
        text = re.sub(r'\s+-?\d+\s*', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n', text)
        
        return text.strip()


def main():
    """主函数"""
    print("=" * 50)
    print("🌟 星织 - 智能对话助手")
    print("=" * 50)
    
    # 创建应用实例
    app = AIChatAppWeb()
    
    # 启动Web应用（使用随机端口避免冲突）
    start_web_app(app, port=0)


if __name__ == "__main__":
    main()