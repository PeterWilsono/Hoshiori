# -*- coding: utf-8 -*-
"""
自主智能层 - Phase 3
包含：事件总线、双系统思考、真实离线行为、行为输出分离
"""
import json
import time
import threading
import queue
from datetime import datetime, timedelta
from typing import Dict, List, Any, Callable
from collections import deque
import random


class EventBus:
    """事件总线 - 多模态输入准备"""
    
    def __init__(self):
        # 事件队列（按优先级）
        self.event_queues = {
            "high": queue.PriorityQueue(),    # 快速通道（问候语等）
            "normal": queue.PriorityQueue(),  # 正常通道（普通对话）
            "low": queue.PriorityQueue()      # 慢速通道（深度推理）
        }
        
        # 事件监听器
        self.listeners = {}  # event_type -> [callbacks]
        
        # 感官缓冲区（避免信息过载）
        self.sensory_buffer = {
            "visual": deque(maxlen=30),   # 视觉缓冲（30帧）
            "audio": deque(maxlen=10),    # 音频缓冲
            "text": deque(maxlen=50)      # 文本缓冲
        }
        
        # 运行状态
        self.running = False
        self.worker_thread = None
    
    def publish(self, event_type: str, data: Dict, priority: str = "normal"):
        """发布事件"""
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            "priority": priority
        }
        
        # 根据优先级放入对应队列
        priority_value = {"high": 0, "normal": 1, "low": 2}[priority]
        self.event_queues[priority].put((priority_value, event))
        
        print(f"📤 事件发布: {event_type} (优先级: {priority})")
    
    def subscribe(self, event_type: str, callback: Callable):
        """订阅事件"""
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)
        print(f"📥 订阅事件: {event_type}")
    
    def start(self):
        """启动事件处理循环"""
        if self.running:
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._event_loop, daemon=True)
        self.worker_thread.start()
        print("🚀 事件总线已启动")
    
    def stop(self):
        """停止事件处理"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=1)
        print("⏹️ 事件总线已停止")
    
    def _event_loop(self):
        """事件处理循环"""
        while self.running:
            # 按优先级处理事件
            for priority in ["high", "normal", "low"]:
                try:
                    _, event = self.event_queues[priority].get_nowait()
                    self._dispatch_event(event)
                except queue.Empty:
                    continue
            
            time.sleep(0.01)  # 避免CPU占用过高
    
    def _dispatch_event(self, event: Dict):
        """分发事件到监听器"""
        event_type = event["type"]
        if event_type in self.listeners:
            for callback in self.listeners[event_type]:
                try:
                    callback(event["data"])
                except Exception as e:
                    print(f"❌ 事件处理错误: {e}")
    
    def add_to_buffer(self, sensory_type: str, data: Any):
        """添加到感官缓冲区"""
        self.sensory_buffer[sensory_type].append({
            "data": data,
            "timestamp": time.time()
        })
    
    def should_process_visual(self, new_frame: Any) -> bool:
        """判断是否应该处理新的视觉帧（变化检测）"""
        if not self.sensory_buffer["visual"]:
            return True
        
        # 简化的变化检测（实际应该用图像差异算法）
        last_frame = self.sensory_buffer["visual"][-1]
        time_diff = time.time() - last_frame["timestamp"]
        
        # 如果距离上次处理超过1秒，处理新帧
        if time_diff > 1.0:
            return True
        
        return False


class DualSystemThinking:
    """双系统思考 - 快思考/慢思考"""
    
    def __init__(self):
        # 系统1：快速规则库
        self.fast_rules = {
            # 精确匹配
            "exact_match": {
                "你好": ["你好呀~", "嗨！", "Hi~"],
                "再见": ["拜拜~", "下次见！", "路上小心~"],
                "谢谢": ["不客气~", "嘻嘻，小事情", "能帮到你就好！"],
                "晚安": ["晚安~做个好梦", "晚安，明天见~", "好好休息哦💤"],
                "早安": ["早安！新的一天加油~", "早上好呀！", "早安~☀️"],
            },
            
            # 情绪快速响应
            "emotion_patterns": {
                "夸奖": {
                    "keywords": ["棒", "厉害", "优秀", "聪明", "可爱"],
                    "responses": [
                        "嘿嘿，谢谢夸奖(*^▽^*)",
                        "真的吗？好开心！",
                        "你也很棒呀~"
                    ]
                },
                "安慰": {
                    "keywords": ["难过", "伤心", "痛苦", "不开心"],
                    "responses": [
                        "怎么了？我在这里陪你...",
                        "别难过，抱抱你(つ´ω`)つ",
                        "慢慢说，我听着呢"
                    ]
                }
            }
        }
        
        # 系统2：需要深度推理的标志
        self.slow_thinking_triggers = [
            "为什么", "怎么办", "如何", "解释", "分析",
            "建议", "帮我", "教我", "复杂", "详细"
        ]
    
    def process(self, user_input: str) -> Dict:
        """
        处理输入，决定使用快速通道还是慢速通道
        
        Returns:
            {
                "use_fast": bool,
                "response": str or None,
                "confidence": float
            }
        """
        # 1. 检查精确匹配
        if user_input in self.fast_rules["exact_match"]:
            return {
                "use_fast": True,
                "response": random.choice(self.fast_rules["exact_match"][user_input]),
                "confidence": 1.0,
                "reason": "exact_match"
            }
        
        # 2. 检查情绪模式
        for emotion, config in self.fast_rules["emotion_patterns"].items():
            if any(kw in user_input for kw in config["keywords"]):
                return {
                    "use_fast": True,
                    "response": random.choice(config["responses"]),
                    "confidence": 0.8,
                    "reason": f"emotion_{emotion}"
                }
        
        # 3. 检查是否需要慢速思考
        needs_slow = any(trigger in user_input for trigger in self.slow_thinking_triggers)
        
        if needs_slow:
            return {
                "use_fast": False,
                "response": None,
                "confidence": 0.0,
                "reason": "complex_query"
            }
        
        # 4. 默认：简单对话也走慢速通道（但优先级正常）
        return {
            "use_fast": False,
            "response": None,
            "confidence": 0.0,
            "reason": "normal_conversation"
        }
    
    def add_fast_rule(self, pattern: str, responses: List[str]):
        """动态添加快速规则"""
        self.fast_rules["exact_match"][pattern] = responses


class OfflineActivitySimulator:
    """真实离线行为模拟器"""
    
    def __init__(self):
        self.activities = []  # 离线活动记录
        self.pending_shares = []  # 待分享的内容
        
        # 活动类型
        self.activity_types = {
            "news_reading": {
                "name": "阅读新闻",
                "min_hours": 6,
                "enabled": True
            },
            "research": {
                "name": "研究问题",
                "min_hours": 2,
                "enabled": True
            },
            "memory_consolidation": {
                "name": "整理记忆",
                "min_hours": 12,
                "enabled": True
            },
            "learning": {
                "name": "学习新知识",
                "min_hours": 4,
                "enabled": True
            }
        }
    
    def simulate_offline_activities(self, hours_offline: float, user_context: Dict) -> List[Dict]:
        """
        模拟离线期间的活动
        
        Args:
            hours_offline: 离线小时数
            user_context: 用户上下文（兴趣、未解决问题等）
        
        Returns:
            活动列表
        """
        activities = []
        
        # 1. 新闻阅读（如果离线>6小时）
        if hours_offline >= 6 and self.activity_types["news_reading"]["enabled"]:
            news_activity = self._simulate_news_reading(user_context)
            if news_activity:
                activities.append(news_activity)
        
        # 2. 问题研究（如果有未解决的问题）
        unresolved = user_context.get("unresolved_questions", [])
        if unresolved and hours_offline >= 2:
            research_activity = self._simulate_research(unresolved[0])
            if research_activity:
                activities.append(research_activity)
        
        # 3. 记忆整理（每天凌晨）
        if hours_offline >= 12:
            consolidation = self._simulate_memory_consolidation(user_context)
            if consolidation:
                activities.append(consolidation)
        
        # 4. 学习新知识（如果用户分享了新内容）
        if user_context.get("user_shared_links"):
            learning = self._simulate_learning(user_context["user_shared_links"])
            if learning:
                activities.append(learning)
        
        return activities
    
    def _simulate_news_reading(self, user_context: Dict) -> Dict:
        """模拟新闻阅读"""
        # 获取用户感兴趣的话题
        interests = user_context.get("user_interests", [])
        
        if not interests:
            return None
        
        topic = random.choice(interests)
        
        # 模拟新闻内容（实际应该调用新闻API）
        fake_news = [
            f"看到一条关于{topic}的新闻，说是最近有新的进展",
            f"刚才刷到{topic}相关的讨论，挺有意思的",
            f"发现{topic}领域出了个新东西，感觉你可能会感兴趣"
        ]
        
        return {
            "type": "news_reading",
            "topic": topic,
            "content": random.choice(fake_news),
            "share_message": f"对了，{random.choice(fake_news)}，要不要我跟你说说？"
        }
    
    def _simulate_research(self, question: str) -> Dict:
        """模拟问题研究"""
        return {
            "type": "research",
            "question": question,
            "content": f"你上次问的'{question}'，我去查了一下",
            "share_message": f"对了，你上次问{question}，我去研究了一下，想听听我的发现吗？"
        }
    
    def _simulate_memory_consolidation(self, user_context: Dict) -> Dict:
        """模拟记忆整理（类似人类睡眠）"""
        return {
            "type": "memory_consolidation",
            "content": "整理了一下我们最近的对话",
            "insights": [
                "发现你最近好像压力有点大",
                "我们聊了好多有趣的话题",
                "感觉我们的关系更近了"
            ]
        }
    
    def _simulate_learning(self, links: List[str]) -> Dict:
        """模拟学习新知识"""
        return {
            "type": "learning",
            "content": f"看了你分享的内容",
            "share_message": "我看了你之前分享的那个链接，学到了不少东西呢~"
        }
    
    def generate_share_message(self, activities: List[Dict]) -> str:
        """生成分享消息"""
        if not activities:
            return ""
        
        # 选择最重要的活动分享
        activity = activities[0]
        return activity.get("share_message", "")


class StructuredOutputManager:
    """结构化输出管理器 - 为具身化准备"""
    
    def __init__(self):
        # 输出模板
        self.output_template = {
            "speech": "",           # 语音输出
            "emotion": "neutral",   # 情绪状态（用于立绘）
            "expression": "neutral", # 表情
            "actions": [],          # 肢体动作（未来使用）
            "gaze": "forward",      # 眼神方向（未来使用）
            "internal_state": {}    # 内部状态更新
        }
        
        # 动作库（为未来的机器人准备）
        self.action_library = {
            "nod": {"type": "head_movement", "intensity": 0.5, "duration": 1.0},
            "shake_head": {"type": "head_movement", "intensity": 0.7, "duration": 1.5},
            "wave": {"type": "arm_movement", "intensity": 0.6, "duration": 2.0},
            "clap": {"type": "hand_movement", "intensity": 0.8, "duration": 1.0},
            "stomp_feet": {"type": "leg_movement", "intensity": 0.8, "duration": 0.5},
            "cross_arms": {"type": "arm_movement", "intensity": 0.5, "duration": 3.0},
            "tilt_head": {"type": "head_movement", "intensity": 0.3, "duration": 2.0}
        }
    
    def parse_ai_response(self, raw_response: str) -> Dict:
        """
        解析AI回复为结构化输出
        
        Args:
            raw_response: AI原始回复（可能包含动作描述）
        
        Returns:
            结构化输出
        """
        output = self.output_template.copy()
        output["actions"] = []
        
        # 提取动作描述
        action_patterns = {
            r'\*点头\*': "nod",
            r'\*摇头\*': "shake_head",
            r'\*挥手\*': "wave",
            r'\*鼓掌\*': "clap",
            r'\*跺脚\*': "stomp_feet",
            r'\*抱臂\*': "cross_arms",
            r'\*歪头\*': "tilt_head"
        }
        
        clean_text = raw_response
        
        for pattern, action_name in action_patterns.items():
            if re.search(pattern, raw_response):
                action = self.action_library[action_name].copy()
                output["actions"].append(action)
                # 从文本中移除动作描述
                clean_text = re.sub(pattern, '', clean_text)
        
        output["speech"] = clean_text.strip()
        
        return output
    
    def generate_robot_commands(self, structured_output: Dict) -> List[Dict]:
        """
        生成机器人控制命令（未来使用）
        
        Returns:
            命令列表
        """
        commands = []
        
        # 表情控制
        if structured_output["expression"] != "neutral":
            commands.append({
                "type": "facial_expression",
                "expression": structured_output["expression"],
                "duration": 3.0
            })
        
        # 动作控制
        for action in structured_output["actions"]:
            commands.append({
                "type": "motor_control",
                "action": action["type"],
                "intensity": action["intensity"],
                "duration": action["duration"]
            })
        
        # 眼神控制
        if structured_output["gaze"] != "forward":
            commands.append({
                "type": "gaze_control",
                "direction": structured_output["gaze"],
                "duration": 2.0
            })
        
        return commands


class AutonomousIntelligenceSystem:
    """自主智能系统 - 整合所有自主功能"""
    
    def __init__(self):
        self.event_bus = EventBus()
        self.dual_thinking = DualSystemThinking()
        self.offline_simulator = OfflineActivitySimulator()
        self.output_manager = StructuredOutputManager()
        
        # 启动事件总线
        self.event_bus.start()
    
    def process_input(self, user_input: str, input_type: str = "text") -> Dict:
        """
        处理输入（支持多模态）
        
        Args:
            user_input: 用户输入
            input_type: 输入类型（text/visual/audio）
        
        Returns:
            处理结果
        """
        # 发布输入事件
        self.event_bus.publish(
            f"input_{input_type}",
            {"content": user_input},
            priority="normal"
        )
        
        # 双系统思考判断
        thinking_result = self.dual_thinking.process(user_input)
        
        return {
            "use_fast_path": thinking_result["use_fast"],
            "fast_response": thinking_result.get("response"),
            "confidence": thinking_result["confidence"],
            "reason": thinking_result["reason"]
        }
    
    def simulate_offline_life(self, hours_offline: float, user_context: Dict) -> Dict:
        """模拟离线生活"""
        activities = self.offline_simulator.simulate_offline_activities(
            hours_offline,
            user_context
        )
        
        share_message = self.offline_simulator.generate_share_message(activities)
        
        return {
            "activities": activities,
            "share_message": share_message,
            "has_content": len(activities) > 0
        }
    
    def structure_output(self, ai_response: str) -> Dict:
        """结构化AI输出"""
        return self.output_manager.parse_ai_response(ai_response)
    
    def shutdown(self):
        """关闭系统"""
        self.event_bus.stop()


# 导入必要的模块
import re
