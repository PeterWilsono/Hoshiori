# -*- coding: utf-8 -*-
"""
对话管理器 - 离线生活模拟增强版

新增功能:
1. 离线生活状态生成(游戏玩家建议)
2. 情绪触发记忆检索
3. 情绪过载检测与处理

注意:只展示需要修改的部分,其他部分保持不变
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any  # ⭐ 添加这行导入
import random
from memory_manager import MemoryManager
from emotion_analyzer import EmotionAnalyzer  # ⭐ 新增
from vector_memory import DynamicMemoryGraph  # ⭐ 新增
from cognitive_system import CognitiveEnhancementSystem  # ⭐ Phase 2
from autonomous_system import AutonomousIntelligenceSystem  # ⭐ Phase 3


class ConversationManager:
    """对话管理器 - 增强版"""
    def __init__(self, save_dir="baocun", builtin_role_prompt=""):
        self.save_dir = save_dir
        self.conversations_path = os.path.join(save_dir, "conversations.json")
        self.builtin_role_prompt = builtin_role_prompt
        self.conversations = {}
        self.current_conversation_id = None
        
        # 初始化记忆管理器
        self.memory_manager = MemoryManager(max_tokens=3000)
        
        # ⭐ Phase 1: 情绪分析器
        self.emotion_analyzer = EmotionAnalyzer()
        
        # ⭐ Phase 1: 动态记忆图谱
        self.memory_graph = DynamicMemoryGraph()
        
        # ⭐ Phase 2: 认知增强系统
        self.cognitive_system = CognitiveEnhancementSystem()
        
        # ⭐ Phase 3: 自主智能系统
        self.autonomous_system = AutonomousIntelligenceSystem()
        
        # ⭐ 新增:情绪历史(用于检测情绪过载)
        self.emotion_history = []  # 最近的PAD状态历史
        
        # ⭐ Phase 2: 对话轮次计数
        self.turns_since_last_initiative = 0
        
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        
        self.load_conversations()
    
    # ========== 新功能:离线生活模拟 ==========
    
    def analyze_user_emotion(self, user_input: str) -> Dict:
        """
        ⭐ 分析用户输入的情绪
        
        Returns:
            情绪分析结果
        """
        return self.emotion_analyzer.analyze_text(user_input)
    
    def update_memory_graph(self, content: str, memory_type: str = "general", importance: int = 5):
        """
        ⭐ 更新记忆图谱
        """
        return self.memory_graph.add_memory(content, memory_type, importance)
    
    def search_memory_with_context(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        ⭐ 使用向量检索和图谱联想搜索记忆
        """
        return self.memory_graph.search_with_association(query, top_k)
    
    def check_cognitive_consistency(self, ai_response: str, context: Dict) -> Dict:
        """
        ⭐ Phase 2: 检查认知一致性
        """
        return self.cognitive_system.process_ai_response(ai_response, context)
    
    def check_initiative_needed(self, context: Dict) -> Dict:
        """
        ⭐ Phase 2: 检查是否需要主动行为
        """
        self.turns_since_last_initiative += 1
        context["turns_since_last_initiative"] = self.turns_since_last_initiative
        
        initiative = self.cognitive_system.check_initiative_needed(context)
        
        if initiative.get("should_send"):
            self.turns_since_last_initiative = 0  # 重置计数
        
        return initiative
    
    def learn_from_interaction(self, user_message: str, context: Dict):
        """
        ⭐ Phase 2: 从交互中学习用户偏好
        """
        self.cognitive_system.learn_from_interaction(user_message, context)
    
    def get_personalization_prompt(self) -> str:
        """
        ⭐ Phase 2: 获取个性化提示
        """
        return self.cognitive_system.get_personalization_prompt()
    
    def process_with_dual_thinking(self, user_input: str) -> Dict:
        """
        ⭐ Phase 3: 双系统思考处理
        """
        return self.autonomous_system.process_input(user_input)
    
    def simulate_offline_activities(self, hours_offline: float, user_context: Dict) -> Dict:
        """
        ⭐ Phase 3: 模拟真实离线活动
        """
        return self.autonomous_system.simulate_offline_life(hours_offline, user_context)
    
    def structure_ai_output(self, ai_response: str) -> Dict:
        """
        ⭐ Phase 3: 结构化AI输出（为具身化准备）
        """
        return self.autonomous_system.structure_output(ai_response)
    
    def generate_offline_life(self, hours_passed: float, current_time: datetime) -> str:
        """
        ⭐ 生成离线生活状态(游戏玩家建议)
        
        根据离线时长和当前时间段,生成虚构的"生活片段"
        
        Args:
            hours_passed: 离线小时数
            current_time: 当前时间
        
        Returns:
            离线生活描述文本
        """
        if hours_passed < 2:
            return ""  # 时间太短,不生成
        
        hour = current_time.hour
        
        # 根据时间段定义可能的活动
        activity_pool = {
            "morning": [  # 6-11点
                "刚起床不久,还有点困,头发都没梳好呢。",
                "早上刷手机的时候看到一个很有趣的新闻,差点笑出声。",
                "吃早餐的时候在想,要是能一直睡懒觉该多好。",
                "窗外的阳光好暖和,让人想出去走走。"
            ],
            "noon": [  # 11-14点
                "中午吃了外卖,味道还不错,就是有点咸。",
                "午休的时候做了个奇怪的梦,醒来已经忘了。",
                "刚才在阳台上发呆了一会儿,看着云朵飘过。",
                "午后总是容易犯困,感觉脑子都不太清醒。"
            ],
            "afternoon": [  # 14-18点
                "下午的时间总是过得特别慢,不知道该干什么。",
                "刚才看了一会儿书/视频,觉得还挺有意思的。",
                "窗外突然下起了小雨,滴滴答答的声音很好听。",
                "泡了杯茶,坐在窗边看着外面发呆。"
            ],
            "evening": [  # 18-22点
                "晚上的时候突然想起一件事,有点想跟你分享。",
                "晚饭后散了会儿步,夜晚的风吹在脸上还挺舒服的。",
                "刚才刷到一个很搞笑的视频,笑了好久。",
                "晚上的心情总是有点复杂,说不上来是什么感觉。"
            ],
            "night": [  # 22-6点
                "夜深了,一个人的时候总是会想很多事情。",
                "刚才躺在床上翻来覆去睡不着,有点失眠。",
                "深夜的时候听到窗外有猫叫,声音好凄凉。",
                "夜晚总是让人多愁善感,不知道为什么。"
            ]
        }
        
        # 确定时间段
        if 6 <= hour < 11:
            time_period = "morning"
        elif 11 <= hour < 14:
            time_period = "noon"
        elif 14 <= hour < 18:
            time_period = "afternoon"
        elif 18 <= hour < 22:
            time_period = "evening"
        else:
            time_period = "night"
        
        # 根据离线时长决定是否生成"长时间"活动
        if hours_passed >= 12:
            long_activities = [
                "这段时间我一直在思考一些事情,感觉自己成长了一点点。",
                "这几天过得有点平淡,但也挺充实的。",
                "离开了一段时间,现在回来了,有点想你。"
            ]
            return random.choice(long_activities)
        
        # 随机选择一个活动
        activity = random.choice(activity_pool[time_period])
        
        return activity
    
    def generate_emotion_trigger_hint(self, current_pad: Dict, long_term_memory: Dict) -> str:
        """
        ⭐ 生成情绪触发的记忆提示
        
        当当前情绪与历史情绪高度相似时,提示AI可以提及相关记忆
        
        Args:
            current_pad: 当前PAD状态
            long_term_memory: 长期记忆
        
        Returns:
            情绪触发提示文本
        """
        similar_memories = self.memory_manager.find_similar_emotion_memories(
            current_pad,
            long_term_memory,
            threshold=0.75
        )
        
        if not similar_memories:
            return ""
        
        # 构建提示
        hints = ["你的当前情绪让你想起了以下往事:"]
        for mem_data in similar_memories[:2]:  # 最多2个
            memory = mem_data["memory"]
            similarity = mem_data["similarity"]
            
            time_str = memory.get('time', '').split()[0]
            event = memory.get('event') or memory.get('content', '')
            
            hints.append(f"• {time_str}: {event} (情绪相似度: {similarity:.0%})")
        
        hints.append("\n💡 你可以自然地提及这些回忆,比如'你现在的样子让我想起了...'")
        
        return "\n".join(hints)
    
    def detect_emotion_overload(self) -> Dict:
        """
        ⭐ 检测情绪过载状态
        
        基于最近的情绪历史判断是否需要"冷静"
        
        Returns:
            {
                "overloaded": bool,
                "suggestion": str,
                "severity": float
            }
        """
        if len(self.emotion_history) < 3:
            return {"overloaded": False, "suggestion": "", "severity": 0}
        
        # 检查最近3次的arousal
        recent_arousal = [h.get('arousal', 0) for h in self.emotion_history[-3:]]
        high_arousal_count = sum(1 for a in recent_arousal if abs(a) > 0.7)
        
        if high_arousal_count >= 2:
            avg_arousal = sum(abs(a) for a in recent_arousal) / len(recent_arousal)
            return {
                "overloaded": True,
                "suggestion": "情绪过载!建议降低激动程度,或主动提出换个轻松话题。回复可以简短一些。",
                "severity": avg_arousal
            }
        
        return {"overloaded": False, "suggestion": "", "severity": 0}
    
    # ========== 修改现有方法以集成新功能 ==========
    
    def apply_time_decay(self):
        """应用时间衰减机制 - 增强版(加入离线生活)"""
        if not self.current_conversation_id:
            return
        
        conv = self.conversations[self.current_conversation_id]
        
        last_time_str = conv.get('last_interaction_time', datetime.now().strftime("%Y-%m-%d %H:%M"))
        try:
            last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M")
            hours_passed = (datetime.now() - last_time).total_seconds() / 3600
        except:
            hours_passed = 0
        
        # ⭐ 生成离线生活状态(如果时间足够长)
        if hours_passed >= 2:
            offline_life = self.generate_offline_life(hours_passed, datetime.now())
            if offline_life:
                # 存储到对话中,供下次API调用使用
                conv['offline_life_pending'] = offline_life
                print(f"🌟 生成离线生活: {offline_life}")
        
        # 原有的衰减逻辑
        if hours_passed > 1:
            core = conv['psych_core']
            state = core['state']
            
            decay_factor = max(0, 1 - (hours_passed * 0.1))
            
            state['arousal'] *= decay_factor
            
            if state['pleasure'] > 0:
                state['pleasure'] = max(0, state['pleasure'] * (decay_factor + 0.3))
            else:
                state['pleasure'] = min(0, state['pleasure'] * (decay_factor + 0.3))
            
            core['relationship']['stress'] = max(0, core['relationship']['stress'] * decay_factor)
            
            print(f"⏰ 应用时间衰减: 已过 {hours_passed:.1f} 小时")
            self.save_conversations()
    
    def update_psych_state(self, updates):
        """更新厚壳心理数据 - 增强版(加入情绪历史)"""
        if not self.current_conversation_id:
            return None
        
        conv = self.conversations[self.current_conversation_id]
        core = conv['psych_core']
        
        # 更新 PAD 值
        if 'pad_delta' in updates:
            delta = updates['pad_delta']
            state = core['state']
            
            # ⭐ 记录更新前的状态到历史
            self.emotion_history.append(state.copy())
            if len(self.emotion_history) > 10:
                self.emotion_history = self.emotion_history[-10:]  # 只保留最近10次
            
            state['pleasure'] = max(-1.0, min(1.0, state['pleasure'] + delta.get('p', 0)))
            state['arousal'] = max(-1.0, min(1.0, state['arousal'] + delta.get('a', 0)))
            state['dominance'] = max(-1.0, min(1.0, state['dominance'] + delta.get('d', 0)))
        
        # 更新关系参数
        if 'relationship_delta' in updates:
            rel_delta = updates['relationship_delta']
            rel = core['relationship']
            
            rel['trust'] = max(0, min(100, rel['trust'] + rel_delta.get('trust', 0)))
            rel['intimacy'] = max(0, min(100, rel['intimacy'] + rel_delta.get('intimacy', 0)))
            rel['stress'] = max(0, min(100, rel['stress'] + rel_delta.get('stress', 0)))
        
        # 如果情绪强烈,记录到情感事件
        if abs(core['state']['arousal']) > 0.6:
            if 'internal_monologue' in updates:
                importance = self.memory_manager.calculate_importance(
                    "emotional_event",
                    core['state']
                )
                
                event = {
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "event": updates.get('internal_monologue', ''),
                    "pad_snapshot": core['state'].copy(),  # ⭐ 存储PAD快照
                    "importance": importance
                }
                
                if 'memory' not in conv:
                    conv['memory'] = {
                        "emotional_events": [],
                        "user_profile": {},
                        "long_term_summaries": [],
                        "relationship_history": [],
                        "discussed_topics": [],
                        "important_events": []
                    }
                
                conv['memory']['emotional_events'].append(event)
                
                # 只保留重要性>=5的事件,或最近20条
                events = conv['memory']['emotional_events']
                important_events = [e for e in events if e.get('importance', 0) >= 5]
                recent_events = events[-20:]
                
                all_events = {json.dumps(e, ensure_ascii=False): e for e in important_events + recent_events}
                conv['memory']['emotional_events'] = list(all_events.values())[-30:]
        
        # 更新最后交互时间
        conv['last_interaction_time'] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # ⭐ 清除已使用的离线生活状态
        if 'offline_life_pending' in conv:
            del conv['offline_life_pending']
        
        self.save_conversations()
        return core
    
    def get_offline_life_status(self) -> str:
        """
        ⭐ 获取待使用的离线生活状态
        
        Returns:
            离线生活描述,如果没有则返回空字符串
        """
        if not self.current_conversation_id:
            return ""
        
        conv = self.conversations[self.current_conversation_id]
        return conv.get('offline_life_pending', '')
    
    def get_emotion_trigger_context(self) -> str:
        """
        ⭐ 获取情绪触发的记忆上下文
        
        Returns:
            情绪触发提示文本
        """
        if not self.current_conversation_id:
            return ""
        
        conv = self.conversations[self.current_conversation_id]
        current_pad = conv['psych_core']['state']
        long_term_memory = conv.get('memory', {})
        
        return self.generate_emotion_trigger_hint(current_pad, long_term_memory)
    
    # ========== 以下方法保持不变 ==========
    
    def new_conversation(self):
        """创建新对话 - 使用完整的心理内核"""
        if self.conversations:
            new_id = max(self.conversations.keys()) + 1
        else:
            new_id = 1
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        self.conversations[new_id] = {
            "title": f"对话 {new_id} - {timestamp}",
            "messages": [],
            "custom_role_prompt": None,
            "last_interaction_time": timestamp,
            
            # 完整的心理内核
            "psych_core": {
                "personality": {
                    "openness": 0.7,
                    "conscientiousness": 0.6,
                    "extraversion": 0.5,
                    "agreeableness": 0.8,
                    "neuroticism": 0.4
                },
                "state": {
                    "pleasure": 0.5,
                    "arousal": 0.1,
                    "dominance": 0.1,
                    "energy": 80
                },
                "relationship": {
                    "trust": 50,
                    "intimacy": 50,
                    "stress": 0
                }
            },
            
            # ⭐ 扩展的长期记忆结构
            "memory": {
                "emotional_events": [],       # 情感事件(已有)
                "user_profile": {},            # 用户档案(姓名、生日、喜好等)
                "long_term_summaries": [],     # 历史摘要
                "relationship_history": [],    # 关系里程碑
                "discussed_topics": [],        # 讨论过的话题
                "important_events": []         # ⭐ 新增:重要事件
            }
        }
        
        self.current_conversation_id = new_id
        self.save_conversations()
        
        print(f"✓ 创建新对话: ID={new_id}, 智能记忆系统已初始化")
        return new_id, self.conversations[new_id]
    
    def get_effective_role_prompt(self):
        """获取当前对话的有效角色设定"""
        if not self.current_conversation_id:
            return self.builtin_role_prompt
        
        conv = self.conversations[self.current_conversation_id]
        custom_prompt = conv.get('custom_role_prompt')
        
        if custom_prompt:
            return custom_prompt
        else:
            return self.builtin_role_prompt
    
    def has_custom_role(self):
        """检查当前对话是否有自定义角色设定"""
        if not self.current_conversation_id:
            return False
        
        conv = self.conversations[self.current_conversation_id]
        return conv.get('custom_role_prompt') is not None
    
    def get_custom_role_prompt(self):
        """获取用户自定义的角色设定(用于UI显示)"""
        if not self.current_conversation_id:
            return ""
        
        conv = self.conversations[self.current_conversation_id]
        return conv.get('custom_role_prompt', "")
    
    def update_role_prompt(self, role_prompt):
        """更新当前对话的自定义角色设定"""
        if self.current_conversation_id:
            if not role_prompt or not role_prompt.strip():
                self.conversations[self.current_conversation_id]['custom_role_prompt'] = None
            else:
                self.conversations[self.current_conversation_id]['custom_role_prompt'] = role_prompt
            self.save_conversations()
            return True
        return False
    
    def reset_to_builtin_role(self):
        """恢复为内置角色设定"""
        if self.current_conversation_id:
            self.conversations[self.current_conversation_id]['custom_role_prompt'] = None
            self.save_conversations()
            return True
        return False
    
    def get_psych_state(self):
        """获取当前对话的完整心理状态"""
        if self.current_conversation_id:
            conv = self.conversations[self.current_conversation_id]
            
            if 'psych_core' not in conv:
                conv['psych_core'] = {
                    "personality": {
                        "openness": 0.5, "conscientiousness": 0.5,
                        "extraversion": 0.5, "agreeableness": 0.5, "neuroticism": 0.5
                    },
                    "state": {
                        "pleasure": 0.0, "arousal": 0.0, "dominance": 0.0, "energy": 50
                    },
                    "relationship": {
                        "trust": 50, "intimacy": 50, "stress": 0
                    }
                }
                self.save_conversations()
            
            return conv['psych_core']
        
        return None
    
    def get_long_term_memory(self):
        """⭐ 获取长期记忆"""
        if self.current_conversation_id:
            conv = self.conversations[self.current_conversation_id]
            
            # 兼容旧数据
            if 'memory' not in conv:
                conv['memory'] = {
                    "emotional_events": [],
                    "user_profile": {},
                    "long_term_summaries": [],
                    "relationship_history": [],
                    "discussed_topics": [],
                    "important_events": []
                }
                self.save_conversations()
            
            return conv['memory']
        
        return None
    
    def get_current_state(self):
        """兼容旧接口:返回简化的状态(用于UI显示)"""
        psych = self.get_psych_state()
        if not psych:
            return {"mood": "neutral", "affection": 50}
        
        p = psych['state']['pleasure']
        a = psych['state']['arousal']
        d = psych['state']['dominance']
        
        if p > 0.3 and a > 0.3:
            mood = "happy"
        elif p < -0.3 and a > 0.3 and d > 0:
            mood = "angry"
        elif p < -0.3 and a < 0:
            mood = "sad"
        elif p > 0 and a > 0.5 and d < 0:
            mood = "shy"
        else:
            mood = "neutral"
        
        return {
            "mood": mood,
            "affection": int(psych['relationship']['intimacy'])
        }
    
    def get_affection(self):
        """获取当前好感度值"""
        psych = self.get_psych_state()
        if not psych:
            return 50
        return int(psych['relationship']['intimacy'])
    
    
    def get_compressed_messages(self):
        """
        ⭐ 获取压缩后的消息历史(智能Token管理)
        
        Returns:
            (压缩后的消息列表, 提取的摘要信息)
        """
        if not self.current_conversation_id:
            return [], ""
        
        conv = self.conversations[self.current_conversation_id]
        messages = conv['messages']
        
        # 计算当前token使用量
        current_tokens = self.memory_manager.calculate_messages_tokens(messages)
        
        # 如果超过阈值,执行压缩
        if self.memory_manager.should_compress(current_tokens):
            print(f"⚠️ Token使用 {current_tokens}/{self.memory_manager.max_tokens},开始智能压缩...")
            
            # ⭐ 关键升级:使用备用压缩(为了避免循环依赖)
            # 真正的LLM摘要可以在main.py中单独触发
            compressed_msgs, summary = self.memory_manager.compress_messages(
                messages,
                self.memory_manager.compress_target
            )
            
            # 将摘要存入长期记忆
            if summary and 'memory' in conv:
                conv['memory']['long_term_summaries'].append({
                    "summary": summary,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "covered_messages": len(messages) - len(compressed_msgs)
                })
                # 只保留最近10条摘要
                conv['memory']['long_term_summaries'] = conv['memory']['long_term_summaries'][-10:]
            
            self.save_conversations()
            print(f"✓ 压缩完成: {len(messages)}条 → {len(compressed_msgs)}条")
            
            return compressed_msgs, summary
        
        return messages, ""
    
    
    def get_current_conversation(self):
        """获取当前对话"""
        if self.current_conversation_id:
            return self.conversations.get(self.current_conversation_id)
        return None
    
    def add_message(self, role, content):
        """添加消息到当前对话"""
        if self.current_conversation_id:
            self.conversations[self.current_conversation_id]['messages'].append({
                "role": role,
                "content": content
            })
            self.save_conversations()
    
    def delete_conversation(self, conv_id):
        """删除对话"""
        if len(self.conversations) == 1:
            return False, "不能删除最后一个对话!"
        
        if conv_id in self.conversations:
            del self.conversations[conv_id]
            
            if conv_id == self.current_conversation_id:
                if self.conversations:
                    self.current_conversation_id = max(self.conversations.keys())
                else:
                    self.current_conversation_id = None
            
            self.reorder_conversation_ids()
            self.save_conversations()
            return True, "删除成功"
        return False, "对话不存在"
    
    def reorder_conversation_ids(self):
        """重新排序对话ID"""
        if not self.conversations:
            return
        
        sorted_ids = sorted(self.conversations.keys())
        new_conversations = {}
        id_mapping = {}
        
        for new_id, old_id in enumerate(sorted_ids, start=1):
            new_conversations[new_id] = self.conversations[old_id]
            id_mapping[old_id] = new_id
            
            title = new_conversations[new_id]['title']
            if f"对话 {old_id}" in title:
                new_conversations[new_id]['title'] = title.replace(
                    f"对话 {old_id}", f"对话 {new_id}"
                )
        
        if self.current_conversation_id in id_mapping:
            self.current_conversation_id = id_mapping[self.current_conversation_id]
        
        self.conversations = new_conversations
    
    def switch_conversation(self, conv_id):
        """切换对话"""
        if conv_id in self.conversations:
            self.current_conversation_id = conv_id
            self.apply_time_decay()
            print(f"✓ 切换到对话: ID={conv_id}")
            return True
        return False
    
    def get_all_conversations(self):
        """获取所有对话列表"""
        result = sorted(self.conversations.keys(), reverse=True)
        return result
    
    def save_conversations(self):
        """保存所有对话到本地"""
        try:
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)
            
            with open(self.conversations_path, 'w', encoding='utf-8') as f:
                json.dump(self.conversations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"✗ 保存失败: {e}")
    
    def load_conversations(self):
        """从本地加载对话"""
        try:
            if os.path.exists(self.conversations_path):
                with open(self.conversations_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    self.conversations = {int(k): v for k, v in loaded.items()}
                    
                    # 兼容旧数据
                    for conv_id in self.conversations:
                        conv = self.conversations[conv_id]
                        
                        # 迁移旧的 role_prompt 到 custom_role_prompt
                        if 'role_prompt' in conv:
                            if conv['role_prompt'] != self.builtin_role_prompt:
                                conv['custom_role_prompt'] = conv['role_prompt']
                            else:
                                conv['custom_role_prompt'] = None
                            del conv['role_prompt']
                        
                        if 'custom_role_prompt' not in conv:
                            conv['custom_role_prompt'] = None
                        
                        # 升级心理系统
                        if 'psych_core' not in conv:
                            old_affection = conv.get('state', {}).get('affection', 50) if 'state' in conv else 50
                            
                            conv['psych_core'] = {
                                "personality": {
                                    "openness": 0.5, "conscientiousness": 0.5,
                                    "extraversion": 0.5, "agreeableness": 0.5, "neuroticism": 0.5
                                },
                                "state": {
                                    "pleasure": 0.0, "arousal": 0.0, "dominance": 0.0, "energy": 50
                                },
                                "relationship": {
                                    "trust": 50, "intimacy": old_affection, "stress": 0
                                }
                            }
                        
                        # ⭐ 升级记忆系统
                        if 'memory' not in conv:
                            # 迁移旧的emotional_events
                            old_events = conv.get('psych_core', {}).get('memory', {}).get('emotional_events', [])
                            
                            conv['memory'] = {
                                "emotional_events": old_events,
                                "user_profile": {},
                                "long_term_summaries": [],
                                "relationship_history": [],
                                "discussed_topics": [],
                                "important_events": []
                            }
                        
                        if 'last_interaction_time' not in conv:
                            conv['last_interaction_time'] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    if self.conversations:
                        self.current_conversation_id = max(self.conversations.keys())
                        print(f"✓ 加载对话成功: {len(self.conversations)}个对话")
                    else:
                        print("✓ 没有历史对话")
            else:
                print("✓ 对话文件不存在,将创建新文件")
        except Exception as e:
            print(f"✗ 加载失败: {e}")
            self.conversations = {}