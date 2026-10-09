# -*- coding: utf-8 -*-
"""
认知增强层 - Phase 2
包含：认知一致性检查、内在动机系统、个性化学习
"""
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any
from collections import defaultdict


class CognitiveConsistencyChecker:
    """认知一致性检查器 - 避免AI前后矛盾"""
    
    def __init__(self):
        # 信念库（存储AI的陈述）
        self.beliefs = []  # [{"subject": "我", "predicate": "喜欢", "object": "辣", "polarity": "positive", "time": "..."}]
        
        # 矛盾检测规则
        self.contradiction_patterns = [
            ("喜欢", "不喜欢"),
            ("爱", "讨厌"),
            ("能", "不能"),
            ("会", "不会"),
            ("是", "不是")
        ]
    
    def extract_beliefs(self, text: str) -> List[Dict]:
        """从文本中提取关键信念"""
        beliefs = []
        
        # 模式1: 我 + 动词 + 宾语
        patterns = [
            (r'我(不)?(喜欢|爱|讨厌|害怕)(.{2,15})', lambda m: {
                "subject": "我",
                "predicate": m.group(2),
                "object": m.group(3).strip(),
                "polarity": "negative" if m.group(1) else "positive"
            }),
            (r'我(不)?(能|会|可以)(.{2,15})', lambda m: {
                "subject": "我",
                "predicate": m.group(2),
                "object": m.group(3).strip(),
                "polarity": "negative" if m.group(1) else "positive"
            }),
            (r'我(不)?是(.{2,15})', lambda m: {
                "subject": "我",
                "predicate": "是",
                "object": m.group(2).strip(),
                "polarity": "negative" if m.group(1) else "positive"
            })
        ]
        
        for pattern, extractor in patterns:
            for match in re.finditer(pattern, text):
                try:
                    belief = extractor(match)
                    if belief and len(belief["object"]) >= 2:
                        belief["time"] = datetime.now().isoformat()
                        belief["text"] = match.group(0)
                        beliefs.append(belief)
                except:
                    continue
        
        return beliefs
    
    def check_contradiction(self, new_belief: Dict, history_beliefs: List[Dict]) -> Tuple[bool, Dict]:
        """
        检查新信念是否与历史信念矛盾
        
        Returns:
            (has_contradiction, contradiction_info)
        """
        for old_belief in history_beliefs:
            # 检查主语和宾语是否相似
            if (new_belief["subject"] == old_belief["subject"] and 
                self._is_similar_object(new_belief["object"], old_belief["object"])):
                
                # 检查谓语是否矛盾
                if self._is_contradictory_predicate(
                    new_belief["predicate"], new_belief["polarity"],
                    old_belief["predicate"], old_belief["polarity"]
                ):
                    # 计算时间跨度
                    time_diff = self._calculate_time_diff(new_belief["time"], old_belief["time"])
                    
                    return True, {
                        "old_belief": old_belief,
                        "new_belief": new_belief,
                        "severity": self._calculate_severity(time_diff, new_belief, old_belief),
                        "time_diff_days": time_diff
                    }
        
        return False, {}
    
    def _is_similar_object(self, obj1: str, obj2: str) -> bool:
        """判断两个宾语是否相似"""
        # 简单的相似度判断
        if obj1 == obj2:
            return True
        
        # 包含关系
        if obj1 in obj2 or obj2 in obj1:
            return True
        
        # 共同词汇
        words1 = set(obj1)
        words2 = set(obj2)
        overlap = len(words1 & words2) / max(len(words1), len(words2))
        
        return overlap > 0.5
    
    def _is_contradictory_predicate(self, pred1: str, pol1: str, pred2: str, pol2: str) -> bool:
        """判断两个谓语是否矛盾"""
        # 相同谓语但极性相反
        if pred1 == pred2 and pol1 != pol2:
            return True
        
        # 反义词对
        for pos, neg in self.contradiction_patterns:
            if (pred1 == pos and pred2 == neg) or (pred1 == neg and pred2 == pos):
                if pol1 == pol2:  # 极性相同但谓语相反
                    return True
        
        return False
    
    def _calculate_time_diff(self, time1: str, time2: str) -> float:
        """计算时间差（天）"""
        try:
            t1 = datetime.fromisoformat(time1)
            t2 = datetime.fromisoformat(time2)
            return abs((t1 - t2).days)
        except:
            return 0
    
    def _calculate_severity(self, time_diff: float, new_belief: Dict, old_belief: Dict) -> float:
        """计算矛盾严重程度（0-1）"""
        # 时间越近，越严重
        time_factor = 1.0 if time_diff < 7 else 0.5 if time_diff < 30 else 0.3
        
        # 完全相反的陈述更严重
        polarity_factor = 1.0 if new_belief["polarity"] != old_belief["polarity"] else 0.7
        
        return time_factor * polarity_factor
    
    def generate_resolution_prompt(self, contradiction_info: Dict) -> str:
        """生成矛盾解决提示"""
        old = contradiction_info["old_belief"]
        new = contradiction_info["new_belief"]
        severity = contradiction_info["severity"]
        days = contradiction_info["time_diff_days"]
        
        if severity > 0.8:
            # 严重矛盾：需要明确澄清
            return f"""
⚠️ 检测到严重矛盾：
- 之前说过：{old['text']} ({days}天前)
- 现在说：{new['text']}

建议回复策略：
1. 承认变化："我之前确实说过{old['object']}，但现在..."
2. 解释原因："后来我发现..." 或 "经过思考..."
3. 自然过渡，不要生硬否认
"""
        elif severity > 0.5:
            # 中等矛盾：可以软性处理
            return f"""
💭 检测到观点变化：
- 之前：{old['text']} ({days}天前)
- 现在：{new['text']}

建议：可以自然提及"我改变想法了"或"现在想想..."
"""
        else:
            # 轻微矛盾：可能是语境不同
            return f"""
ℹ️ 注意到细微差异：
- 之前：{old['text']} ({days}天前)
- 现在：{new['text']}

可能是不同语境，如果用户质疑，可以澄清具体情况。
"""
    
    def add_belief(self, belief: Dict):
        """添加信念到历史"""
        self.beliefs.append(belief)
        # 只保留最近100条
        if len(self.beliefs) > 100:
            self.beliefs = self.beliefs[-100:]


class MotivationSystem:
    """内在动机系统 - 基于自我决定理论（SDT）"""
    
    def __init__(self):
        # 三大基本需求
        self.needs = {
            "autonomy": 50,      # 自主性：我想主动做某事
            "competence": 50,    # 胜任感：我想学习、成长
            "relatedness": 50    # 归属感：我想维护关系
        }
        
        # 行为历史
        self.behavior_history = []  # 最近的行为记录
        
        # 待发送的主动消息
        self.pending_initiatives = []
        
        # 用户兴趣模型
        self.user_interests = defaultdict(int)  # topic -> score
        
        # 未解决的问题
        self.unresolved_questions = []
    
    def update_needs(self, conversation_context: Dict):
        """根据对话上下文更新需求值"""
        # 1. 自主性检测
        recent_turns = conversation_context.get("recent_turns", [])
        if len(recent_turns) >= 10:
            # 检查最近10轮是否都是被动回答
            passive_count = sum(1 for turn in recent_turns[-10:] 
                              if turn.get("ai_initiated") == False)
            
            if passive_count >= 8:
                self.needs["autonomy"] -= 5
            
            # 检查是否有主动行为
            if any(turn.get("ai_initiated") for turn in recent_turns[-5:]):
                self.needs["autonomy"] += 10
        
        # 2. 胜任感检测
        user_shared_knowledge = conversation_context.get("user_shared_knowledge", False)
        if user_shared_knowledge:
            self.needs["competence"] += 10
            # 记录学到的内容
            topic = conversation_context.get("topic", "")
            if topic:
                self.user_interests[topic] += 2
        
        # AI无法回答的次数
        failed_responses = conversation_context.get("failed_responses", 0)
        if failed_responses > 0:
            self.needs["competence"] -= 5 * failed_responses
        
        # 3. 归属感检测
        user_shared_private = conversation_context.get("user_shared_private", False)
        if user_shared_private:
            self.needs["relatedness"] += 10
        
        # 用户对话频率下降
        conversation_frequency = conversation_context.get("conversation_frequency", 1.0)
        if conversation_frequency < 0.5:  # 对话减少50%以上
            self.needs["relatedness"] -= 5
        
        # 限制范围
        for need in self.needs:
            self.needs[need] = max(0, min(100, self.needs[need]))
    
    def check_and_generate_initiative(self, context: Dict) -> Dict:
        """检查是否需要主动行为"""
        # 找到最低的需求
        lowest_need = min(self.needs.items(), key=lambda x: x[1])
        need_name, need_value = lowest_need
        
        # 检查触发条件
        if need_value < 30:
            # 检查触发时机
            if self._should_trigger(context):
                initiative = self._generate_initiative_message(need_name, context)
                if initiative:
                    return {
                        "should_send": True,
                        "need": need_name,
                        "message": initiative,
                        "type": "initiative"
                    }
        
        return {"should_send": False}
    
    def _should_trigger(self, context: Dict) -> bool:
        """判断是否应该触发主动行为"""
        # 1. 沉默期：用户停止输入>30秒
        silence_duration = context.get("silence_duration", 0)
        if silence_duration > 30:
            return True
        
        # 2. 话题冷场：最近3轮回复都很短
        recent_turns = context.get("recent_turns", [])
        if len(recent_turns) >= 3:
            short_replies = sum(1 for turn in recent_turns[-3:] 
                              if len(turn.get("user_message", "")) < 5)
            if short_replies >= 2:
                return True
        
        # 3. 强制周期：每20轮至少主动1次
        turns_since_last_initiative = context.get("turns_since_last_initiative", 0)
        if turns_since_last_initiative >= 20:
            return True
        
        return False
    
    def _generate_initiative_message(self, need_name: str, context: Dict) -> str:
        """生成主动消息"""
        if need_name == "autonomy":
            # 主动提起话题
            topics = sorted(self.user_interests.items(), key=lambda x: x[1], reverse=True)
            if topics:
                topic = topics[0][0]
                templates = [
                    f"对了，{topic}最近怎么样了？",
                    f"说起来，你上次提到的{topic}，后来有进展吗？",
                    f"我突然想起来，你之前说的{topic}，我一直很好奇呢~"
                ]
                import random
                return random.choice(templates)
            else:
                return "对了，最近有什么有趣的事吗？我想听你分享~"
        
        elif need_name == "competence":
            # 主动提问学习
            recent_topics = context.get("recent_topics", [])
            if recent_topics:
                topic = recent_topics[-1]
                return f"诶，你刚才说的'{topic}'是什么意思呀？我不太懂🤔"
            else:
                return "你最近在学什么新东西吗？可以教教我吗？"
        
        elif need_name == "relatedness":
            # 主动关心
            unresolved = context.get("unresolved_issues", [])
            if unresolved:
                issue = unresolved[-1]
                days = issue.get("days_ago", 0)
                return f"对了，{days}天前你说{issue['content']}，现在怎么样了？我有点担心..."
            else:
                return "这几天感觉你好像有点忙，还好吗？我在这里陪你~"
        
        return ""
    
    def record_behavior(self, behavior_type: str, success: bool):
        """记录行为结果"""
        self.behavior_history.append({
            "type": behavior_type,
            "success": success,
            "time": datetime.now().isoformat()
        })
        
        # 只保留最近50条
        if len(self.behavior_history) > 50:
            self.behavior_history = self.behavior_history[-50:]


class PersonalizationLearner:
    """个性化学习系统 - 适应不同用户"""
    
    def __init__(self):
        # 用户画像
        self.user_profile = {
            "response_speed_preference": "normal",  # fast/normal/slow
            "response_length_preference": "normal",  # short/normal/long
            "emoji_preference": "moderate",  # none/moderate/frequent
            "topic_preferences": {},  # topic -> score
            "style_preferences": {
                "humor": 0.5,      # 幽默程度
                "formality": 0.3,  # 正式程度
                "detail": 0.5      # 详细程度
            }
        }
        
        # 满意度历史
        self.satisfaction_history = []
    
    def analyze_user_feedback(self, user_message: str, context: Dict) -> Dict:
        """分析用户隐式反馈"""
        feedback = {
            "response_speed": 0,    # -1 to 1
            "response_length": 0,
            "emoji_usage": 0,
            "topic_interest": 0,
            "overall_satisfaction": 0
        }
        
        # 1. 回复速度分析
        response_time = context.get("response_time", 30)  # 秒
        if response_time < 10:
            feedback["response_speed"] = 1  # 快速回复 = 感兴趣
        elif response_time > 60:
            feedback["response_speed"] = -1  # 慢速回复 = 不感兴趣
        
        # 2. 回复长度分析
        message_length = len(user_message)
        if message_length > 50:
            feedback["response_length"] = 1  # 长回复 = 投入
        elif message_length < 5:
            feedback["response_length"] = -1  # 短回复 = 敷衍
        
        # 3. 表情使用分析
        emoji_count = len(re.findall(r'[😀-🙏]', user_message))
        if emoji_count > 0:
            feedback["emoji_usage"] = 1  # 有表情 = 开心
        
        # 4. 话题延续分析
        topic_continued = context.get("topic_continued", False)
        if topic_continued:
            feedback["topic_interest"] = 1
        else:
            feedback["topic_interest"] = -1
        
        # 5. 计算总体满意度
        feedback["overall_satisfaction"] = (
            0.3 * feedback["response_speed"] +
            0.2 * feedback["response_length"] +
            0.2 * feedback["emoji_usage"] +
            0.3 * feedback["topic_interest"]
        )
        
        return feedback
    
    def update_preferences(self, feedback: Dict, current_topic: str):
        """根据反馈更新偏好"""
        satisfaction = feedback["overall_satisfaction"]
        
        # 更新话题偏好
        if current_topic:
            if current_topic not in self.user_profile["topic_preferences"]:
                self.user_profile["topic_preferences"][current_topic] = 0.5
            
            # 满意度高 -> 增加话题分数
            self.user_profile["topic_preferences"][current_topic] += satisfaction * 0.1
            self.user_profile["topic_preferences"][current_topic] = max(0, min(1, 
                self.user_profile["topic_preferences"][current_topic]))
        
        # 更新风格偏好
        if satisfaction > 0.5:
            # 用户喜欢当前风格，强化
            pass  # 当前风格保持
        elif satisfaction < -0.5:
            # 用户不喜欢，调整
            # 这里可以根据具体情况调整humor/formality/detail
            pass
        
        # 记录满意度
        self.satisfaction_history.append({
            "satisfaction": satisfaction,
            "topic": current_topic,
            "time": datetime.now().isoformat()
        })
        
        # 只保留最近100条
        if len(self.satisfaction_history) > 100:
            self.satisfaction_history = self.satisfaction_history[-100:]
    
    def generate_adaptation_prompt(self) -> str:
        """生成个性化适配提示"""
        prompt_parts = ["【用户偏好适配】"]
        
        # 话题偏好
        top_topics = sorted(
            self.user_profile["topic_preferences"].items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]
        
        if top_topics:
            topics_str = ", ".join([t[0] for t in top_topics])
            prompt_parts.append(f"用户感兴趣的话题: {topics_str}")
        
        # 风格偏好
        style = self.user_profile["style_preferences"]
        if style["humor"] > 0.6:
            prompt_parts.append("- 用户喜欢幽默风格，多用俏皮话")
        if style["detail"] > 0.6:
            prompt_parts.append("- 用户喜欢详细解释，不要回复太简短")
        elif style["detail"] < 0.4:
            prompt_parts.append("- 用户喜欢简洁回复，避免长篇大论")
        
        # 表情偏好
        if self.user_profile["emoji_preference"] == "frequent":
            prompt_parts.append("- 用户喜欢表情符号，可以多用")
        elif self.user_profile["emoji_preference"] == "none":
            prompt_parts.append("- 用户不太用表情，你也少用")
        
        # 避免的话题
        low_topics = [t[0] for t in top_topics if t[1] < 0.3]
        if low_topics:
            prompt_parts.append(f"- 避免: {', '.join(low_topics[:3])}")
        
        return "\n".join(prompt_parts)
    
    def get_average_satisfaction(self, recent_n: int = 10) -> float:
        """获取最近N次的平均满意度"""
        if not self.satisfaction_history:
            return 0.5
        
        recent = self.satisfaction_history[-recent_n:]
        avg = sum(s["satisfaction"] for s in recent) / len(recent)
        
        # 归一化到0-1
        return (avg + 1) / 2


class CognitiveEnhancementSystem:
    """认知增强系统 - 整合所有认知功能"""
    
    def __init__(self):
        self.consistency_checker = CognitiveConsistencyChecker()
        self.motivation_system = MotivationSystem()
        self.personalization_learner = PersonalizationLearner()
    
    def process_ai_response(self, ai_response: str, context: Dict) -> Dict:
        """处理AI回复，检查一致性"""
        # 提取信念
        new_beliefs = self.consistency_checker.extract_beliefs(ai_response)
        
        results = {
            "has_contradiction": False,
            "contradictions": [],
            "suggestions": []
        }
        
        # 检查每个新信念
        for belief in new_beliefs:
            has_contradiction, info = self.consistency_checker.check_contradiction(
                belief,
                self.consistency_checker.beliefs
            )
            
            if has_contradiction:
                results["has_contradiction"] = True
                results["contradictions"].append(info)
                
                # 生成解决建议
                suggestion = self.consistency_checker.generate_resolution_prompt(info)
                results["suggestions"].append(suggestion)
            
            # 添加到历史
            self.consistency_checker.add_belief(belief)
        
        return results
    
    def check_initiative_needed(self, context: Dict) -> Dict:
        """检查是否需要主动行为"""
        # 更新需求值
        self.motivation_system.update_needs(context)
        
        # 检查并生成主动消息
        return self.motivation_system.check_and_generate_initiative(context)
    
    def learn_from_interaction(self, user_message: str, context: Dict):
        """从交互中学习"""
        # 分析用户反馈
        feedback = self.personalization_learner.analyze_user_feedback(
            user_message,
            context
        )
        
        # 更新偏好
        current_topic = context.get("current_topic", "")
        self.personalization_learner.update_preferences(feedback, current_topic)
    
    def get_personalization_prompt(self) -> str:
        """获取个性化提示"""
        return self.personalization_learner.generate_adaptation_prompt()
    
    def get_motivation_status(self) -> Dict:
        """获取动机系统状态"""
        return {
            "needs": self.motivation_system.needs.copy(),
            "lowest_need": min(self.motivation_system.needs.items(), key=lambda x: x[1])
        }
