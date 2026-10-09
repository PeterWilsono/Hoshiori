# -*- coding: utf-8 -*-
"""
智能记忆管理系统 - 情绪驱动增强版
新增功能：
1. 情绪相似度触发记忆
2. 情绪阈值判断(极端情绪特殊处理)
3. 情绪惯性与反弹机制
"""
import json
import re
import math
from datetime import datetime
from typing import List, Dict, Any, Tuple


class MemoryManager:
    """记忆管理器 - 实现"记住点点滴滴"的核心"""
    
    def __init__(self, max_tokens=3000):
        self.max_tokens = max_tokens
        self.safe_threshold = int(max_tokens * 0.65)
        self.compress_target = int(max_tokens * 0.40)
        
        # 记忆权重配置
        self.importance_weights = {
            "profile": 10,
            "preference": 8,
            "event": 9,
            "emotional_event": 7,
            "milestone": 9,
            "user_info": 10,
            "normal": 3
        }
        
        # ⭐ 新增：情绪阈值配置
        self.emotion_thresholds = {
            "extreme_happiness": {"pleasure": 0.7, "arousal": 0.6},  # 极度开心
            "extreme_sadness": {"pleasure": -0.7, "arousal": -0.3},  # 极度悲伤
            "extreme_anger": {"pleasure": -0.6, "arousal": 0.7, "dominance": 0.5},  # 愤怒
            "burnout": {"arousal": 0.8, "duration": 3},  # 情绪过载(需要冷静)
            "depression": {"pleasure": -0.5, "arousal": -0.4, "duration": 2}  # 低落期
        }
    
    # ========== 新功能：情绪相似度计算 ==========
    
    def calculate_emotion_similarity(self, current_pad: Dict, memory_pad: Dict) -> float:
        """
        ⭐ 计算当前情绪与记忆情绪的相似度
        
        使用欧几里得距离的归一化版本
        相似度范围: 0(完全不同) - 1(完全相同)
        
        Args:
            current_pad: 当前PAD值 {"pleasure": x, "arousal": y, "dominance": z}
            memory_pad: 记忆中的PAD值
        
        Returns:
            相似度分数 (0-1)
        """
        p_diff = (current_pad.get("pleasure", 0) - memory_pad.get("pleasure", 0)) ** 2
        a_diff = (current_pad.get("arousal", 0) - memory_pad.get("arousal", 0)) ** 2
        d_diff = (current_pad.get("dominance", 0) - memory_pad.get("dominance", 0)) ** 2
        
        # 欧几里得距离
        distance = math.sqrt(p_diff + a_diff + d_diff)
        
        # 最大距离约为sqrt(3*4) = 3.46 (每个维度-1到1,差值最大2)
        # 归一化到0-1,并反转(距离越小,相似度越高)
        max_distance = math.sqrt(12)  # sqrt(3 * 2^2)
        similarity = 1 - (distance / max_distance)
        
        return max(0, min(1, similarity))  # 确保在0-1范围内
    
    def find_similar_emotion_memories(
        self, 
        current_pad: Dict, 
        long_term_memory: Dict,
        threshold: float = 0.75
    ) -> List[Dict]:
        """
        ⭐ 根据情绪相似度检索记忆
        
        心理学原理：情绪一致性效应(Mood Congruence Effect)
        人在某种情绪下,更容易回忆起相似情绪的往事
        
        Args:
            current_pad: 当前PAD状态
            long_term_memory: 长期记忆数据
            threshold: 相似度阈值(默认0.75,即75%以上相似)
        
        Returns:
            相似情绪的记忆列表,按相似度降序
        """
        similar_memories = []
        
        # 检索情感事件
        emotional_events = long_term_memory.get("emotional_events", [])
        for event in emotional_events:
            if "pad_snapshot" not in event:
                continue
            
            memory_pad = event["pad_snapshot"]
            similarity = self.calculate_emotion_similarity(current_pad, memory_pad)
            
            if similarity >= threshold:
                similar_memories.append({
                    "memory": event,
                    "similarity": similarity,
                    "type": "emotional_event"
                })
        
        # 检索重要事件
        important_events = long_term_memory.get("important_events", [])
        for event in important_events:
            if "pad_snapshot" in event:
                memory_pad = event["pad_snapshot"]
                similarity = self.calculate_emotion_similarity(current_pad, memory_pad)
                
                if similarity >= threshold:
                    similar_memories.append({
                        "memory": event,
                        "similarity": similarity,
                        "type": "important_event"
                    })
        
        # 按相似度降序排序
        similar_memories.sort(key=lambda x: x["similarity"], reverse=True)
        
        return similar_memories[:5]  # 最多返回5个最相似的
    
    # ========== 新功能：情绪状态判断 ==========
    
    def detect_extreme_emotion(self, pad_state: Dict, history: List[Dict] = None) -> Dict:
        """
        ⭐ 检测极端情绪状态
        
        心理学依据：
        - 情绪过载理论：持续高强度情绪会导致疲劳
        - 情绪调节理论：需要识别何时需要"降温"
        
        Args:
            pad_state: 当前PAD状态
            history: 最近的情绪历史(用于判断持续时间)
        
        Returns:
            {
                "state": "extreme_happiness" | "burnout" | "normal",
                "severity": 0-1,  # 严重程度
                "suggestion": "建议的应对策略"
            }
        """
        p = pad_state.get("pleasure", 0)
        a = pad_state.get("arousal", 0)
        d = pad_state.get("dominance", 0)
        
        result = {
            "state": "normal",
            "severity": 0,
            "suggestion": None
        }
        
        # 检测极度开心
        if p > 0.7 and a > 0.6:
            result["state"] = "extreme_happiness"
            result["severity"] = min(1, (p + a) / 2)
            result["suggestion"] = "情绪高涨,可以更活泼表达"
        
        # 检测极度悲伤
        elif p < -0.7 and a < -0.3:
            result["state"] = "extreme_sadness"
            result["severity"] = min(1, abs(p))
            result["suggestion"] = "深度共情,提供情绪支持,不要说教"
        
        # 检测愤怒
        elif p < -0.6 and a > 0.7 and d > 0.5:
            result["state"] = "extreme_anger"
            result["severity"] = min(1, (abs(p) + a) / 2)
            result["suggestion"] = "情绪激动,需要冷静,可以适度辩护但不要对抗"
        
        # 检测情绪过载(Burnout)
        elif abs(a) > 0.8:
            # 检查是否持续高强度
            if history:
                high_arousal_count = sum(1 for h in history[-3:] if abs(h.get("arousal", 0)) > 0.7)
                if high_arousal_count >= 2:
                    result["state"] = "burnout"
                    result["severity"] = abs(a)
                    result["suggestion"] = "建议换个轻松话题,避免继续刺激"
        
        # 检测低落期
        elif p < -0.5 and abs(a) < 0.3:
            result["state"] = "depression"
            result["severity"] = abs(p)
            result["suggestion"] = "低能量状态,回复可以简短,陪伴即可"
        
        return result
    
    # ========== 情绪记忆上下文构建(增强版) ==========
    
    def build_memory_context(self, long_term_memory: Dict, recent_summary: str = "", 
                           current_pad: Dict = None) -> str:
        """
        ⭐ 动态上下文注入(情绪驱动增强版)
        
        新增逻辑：
        1. 如果current_pad提供,优先注入情绪相似的记忆
        2. 根据情绪状态调整记忆选择策略
        """
        context_parts = []
        
        # 1. 用户档案(完整注入)
        profile = long_term_memory.get('user_profile', {})
        if profile:
            context_parts.append("【你记住的用户信息】")
            
            if 'name' in profile:
                context_parts.append(f"- 姓名：{profile['name']}")
            if 'birthday' in profile:
                context_parts.append(f"- 生日：{profile['birthday']}")
            if 'occupation' in profile:
                context_parts.append(f"- 职业：{profile['occupation']}")
            
            if 'profile_notes' in profile and profile['profile_notes']:
                context_parts.append("\n基本信息：")
                for note in profile['profile_notes'][-5:]:
                    if isinstance(note, dict):
                        context_parts.append(f"• {note['content']}")
                    else:
                        context_parts.append(f"• {note}")
            
            if 'preferences' in profile and profile['preferences']:
                context_parts.append("\n喜好偏好：")
                prefs = profile['preferences']
                if prefs and isinstance(prefs[0], dict):
                    sorted_prefs = sorted(
                        prefs,
                        key=lambda x: x.get('importance', 0),
                        reverse=True
                    )[:10]
                    for pref in sorted_prefs:
                        context_parts.append(f"• {pref['content']}")
                else:
                    for pref in prefs[:10]:
                        context_parts.append(f"• {pref}")
        
        # 2. ⭐ 情绪驱动的记忆检索
        if current_pad:
            similar_memories = self.find_similar_emotion_memories(
                current_pad, 
                long_term_memory,
                threshold=0.7
            )
            
            if similar_memories:
                context_parts.append("\n【💭 类似心情下的往事】")
                context_parts.append("(你的当前情绪让你想起了这些...)")
                
                for mem_data in similar_memories[:3]:  # 最多3个
                    memory = mem_data["memory"]
                    similarity = mem_data["similarity"]
                    
                    time_str = memory.get('time', '').split()[0]
                    event_text = memory.get('event') or memory.get('content', '')
                    
                    # 标注相似度
                    similarity_emoji = "🔥" if similarity > 0.9 else "⚡" if similarity > 0.8 else "✨"
                    context_parts.append(f"{similarity_emoji} {time_str}: {event_text}")
        
        # 3. 讨论过的话题
        topics = long_term_memory.get('discussed_topics', [])
        if topics:
            context_parts.append(f"\n【你们讨论过的话题】{', '.join(topics[:10])}")
        
        # 4. 重要事件(动态选择)
        important_events = long_term_memory.get('important_events', [])
        if important_events:
            context_parts.append("\n【重要的共同回忆】")
            high_importance = [e for e in important_events if e.get('importance', 0) >= 7]
            selected = high_importance[:5] if high_importance else important_events[:5]
            
            for event in selected:
                time_str = event.get('time', '').split()[0]
                context_parts.append(f"- {time_str}: {event['content']}")
        
        # 5. 情感事件(最近的高强度事件)
        emotional_events = long_term_memory.get('emotional_events', [])
        if emotional_events:
            high_emotion = [e for e in emotional_events if e.get('importance', 0) >= 6]
            if high_emotion:
                context_parts.append("\n【情感记忆】")
                for event in high_emotion[-3:]:
                    time_str = event.get('time', '').split()[0]
                    context_parts.append(f"- {time_str}: {event['event']}")
        
        # 6. 关系历程
        relationship_history = long_term_memory.get('relationship_history', [])
        if relationship_history:
            context_parts.append("\n【我们之间的关系历程】")
            for milestone in relationship_history[-3:]:
                if isinstance(milestone, dict):
                    context_parts.append(f"- {milestone.get('content', milestone)}")
                else:
                    context_parts.append(f"- {milestone}")
        
        # 7. 历史摘要(Keep Last 3)
        summaries = long_term_memory.get('long_term_summaries', [])
        if summaries:
            context_parts.append("\n【更早的对话回顾】")
            for summary in summaries[-3:]:
                if isinstance(summary, dict):
                    context_parts.append(f"• {summary['summary']}")
                else:
                    context_parts.append(f"• {summary}")
        
        # 8. 最近摘要
        if recent_summary:
            context_parts.append(f"\n【最近对话】\n{recent_summary}")
        
        return "\n".join(context_parts) if context_parts else ""
    
    # ========== 以下是原有方法,保持不变 ==========
    
    def estimate_tokens(self, text: str) -> int:
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))
        others = len(text) - chinese_chars - english_words
        return int(chinese_chars / 1.5 + english_words + others / 3)
    
    def calculate_messages_tokens(self, messages: List[Dict]) -> int:
        total = 0
        for msg in messages:
            total += self.estimate_tokens(msg.get('content', ''))
        return total
    
    def extract_memory_from_json(self, json_data: Dict) -> Dict[str, Any]:
        extracted = {
            "has_update": False,
            "type": None,
            "content": None,
            "importance": 3
        }
        
        if "memory_update" in json_data:
            mem_update = json_data["memory_update"]
            
            if mem_update and isinstance(mem_update, dict):
                mem_type = mem_update.get("type")
                mem_content = mem_update.get("content")
                
                if mem_type and mem_content:
                    extracted["has_update"] = True
                    extracted["type"] = mem_type
                    extracted["content"] = mem_content
                    extracted["importance"] = self.importance_weights.get(mem_type, 5)
        
        return extracted
    
    def extract_key_information(self, message: str, ai_response: str) -> Dict[str, Any]:
        extracted = {
            "user_info": {},
            "preferences": [],
            "emotional_events": [],
            "topics": []
        }
        
        combined_text = message + " " + ai_response
        
        # 提取用户姓名
        # 提取用户姓名
        # ⭐ 优化: 排除"我是说"、"如果"等常见误判
        name_patterns = [
            r'(?:我是|我叫|叫我)(?!(?:说|如果|想|要|觉得|认为))(.{2,6})(?=$|[，。！？])',
            r'我的名字[是叫](.{2,6})(?=$|[，。！？])',
            r'你可以叫我(.{2,6})(?=$|[，。！？])',
            r'大家都叫我(.{2,6})(?=$|[，。！？])'
        ]
        for pattern in name_patterns:
            match = re.search(pattern, message)
            if match:
                name = match.group(1).strip()
                stop_names = {'小明', '小红', '什么', '谁', '你', '我', '他', '她', '它'}
                if name not in stop_names and len(name) >= 2:
                    extracted["user_info"]["name"] = name
                    break
        
        # 提取生日
        birthday_patterns = [
            r'我的?生日[是在]?(\d{4})年?(\d{1,2})月(\d{1,2})[日号]?',
            r'生日[是在]?(\d{1,2})月(\d{1,2})[日号]?',
            r'(\d{4})[年-](\d{1,2})[月-](\d{1,2})[日号]?.{0,5}生日',
            r'(\d{1,2})月(\d{1,2})[日号]?.{0,5}生日'
        ]
        for pattern in birthday_patterns:
            match = re.search(pattern, message)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    year = groups[0] if groups[0].isdigit() and len(groups[0]) == 4 else None
                    month = groups[1] if year else groups[0]
                    day = groups[2] if year else groups[1]
                    if year:
                        extracted["user_info"]["birthday"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    else:
                        extracted["user_info"]["birthday"] = f"--{month.zfill(2)}-{day.zfill(2)}"
                elif len(groups) == 2:
                    extracted["user_info"]["birthday"] = f"--{groups[0].zfill(2)}-{groups[1].zfill(2)}"
                break
        
        # 提取职业/身份
        occupation_patterns = [
            r'我是[一个]?(.{2,10})',
            r'我的职业是(.{2,15})',
            r'我在(.{2,15})工作',
            r'我做(.{2,10})的?',
            r'我[从事](.{2,15})'
        ]
        for pattern in occupation_patterns:
            match = re.search(pattern, message)
            if match:
                occupation = match.group(1).strip()
                if occupation not in {'什么', '谁', '哪里', '怎么', '为什么'} and len(occupation) >= 2:
                    if any(kw in occupation for kw in ['师', '员', '家', '手', '生', '人员', '工程', '设计', '开发', '经理', '主管']):
                        extracted["user_info"]["occupation"] = occupation
                        break
        
        # 提取喜好和厌恶
        preference_patterns = [
            (r'我[很]?喜欢(.{2,20})', 'like'),
            (r'我[很]?爱(.{2,20})', 'like'),
            (r'我最喜欢(.{2,20})', 'like'),
            (r'我超喜欢(.{2,20})', 'like'),
            (r'我[很]?讨厌(.{2,20})', 'dislike'),
            (r'我[很]?不喜欢(.{2,20})', 'dislike'),
            (r'我[很]?害怕(.{2,20})', 'dislike'),
            (r'我最讨厌(.{2,20})', 'dislike')
        ]
        for pattern, sentiment in preference_patterns:
            matches = re.finditer(pattern, message)
            for match in matches:
                pref = match.group(1).strip()
                pref = re.sub(r'[的了吗呢啊,，。！？]$', '', pref)
                if len(pref) >= 2 and pref not in {'什么', '谁', '哪个'}:
                    pref_text = f"{'喜欢' if sentiment == 'like' else '不喜欢'}{pref}"
                    extracted["preferences"].append(pref_text)
        
        # 识别话题
        topic_keywords = {
            "工作": ["工作", "上班", "加班", "同事", "老板", "项目", "公司", "职场", "会议", "任务"],
            "学习": ["学习", "考试", "作业", "课程", "老师", "学校", "培训", "技能", "知识"],
            "感情": ["喜欢", "爱", "恋爱", "男朋友", "女朋友", "分手", "表白", "约会", "情侣", "暗恋"],
            "家庭": ["爸爸", "妈妈", "父母", "家人", "兄弟", "姐妹", "孩子", "家里", "亲人"],
            "健康": ["生病", "医院", "身体", "健康", "难受", "疼", "药", "医生", "治疗"],
            "旅行": ["旅游", "旅行", "出去玩", "景点", "游玩", "度假", "风景", "出行"],
            "美食": ["好吃", "美食", "餐厅", "做饭", "菜", "饭", "食物", "料理", "味道"],
            "娱乐": ["电影", "游戏", "音乐", "看剧", "综艺", "动漫", "小说", "唱歌"],
            "运动": ["跑步", "健身", "运动", "锻炼", "篮球", "足球", "游泳", "瑜伽"],
            "金钱": ["钱", "工资", "收入", "花钱", "买", "贵", "便宜", "省钱", "理财"]
        }
        for topic, keywords in topic_keywords.items():
            if any(kw in combined_text for kw in keywords):
                extracted["topics"].append(topic)
        
        # 识别情感事件
        emotional_keywords = {
            "开心": ["开心", "高兴", "快乐", "幸福", "兴奋", "欣喜", "愉快"],
            "难过": ["难过", "伤心", "痛苦", "悲伤", "失落", "沮丧", "郁闷"],
            "生气": ["生气", "愤怒", "气愤", "恼火", "火大", "讨厌"],
            "焦虑": ["焦虑", "担心", "紧张", "害怕", "恐惧", "不安", "压力"],
            "感动": ["感动", "温暖", "暖心", "感激", "感谢", "珍惜"]
        }
        for emotion, keywords in emotional_keywords.items():
            if any(kw in combined_text for kw in keywords):
                event_desc = message[:50] + "..." if len(message) > 50 else message
                extracted["emotional_events"].append({
                    "event": f"[{emotion}] {event_desc}",
                    "emotion": emotion,
                    "importance": 6 if emotion in ["开心", "感动"] else 7
                })
                break
        
        return extracted
    
    def merge_extracted_info_to_memory(self, extracted: Dict, long_term_memory: Dict) -> Dict:
        if "user_profile" not in long_term_memory:
            long_term_memory["user_profile"] = {}
        
        if extracted.get("user_info"):
            for key, value in extracted["user_info"].items():
                if value:
                    long_term_memory["user_profile"][key] = value
        
        if extracted.get("preferences"):
            if "preferences" not in long_term_memory["user_profile"]:
                long_term_memory["user_profile"]["preferences"] = []
            
            existing_prefs = [p["content"] if isinstance(p, dict) else p 
                            for p in long_term_memory["user_profile"]["preferences"]]
            
            for pref in extracted["preferences"]:
                if pref not in existing_prefs:
                    long_term_memory["user_profile"]["preferences"].append({
                        "content": pref,
                        "time": datetime.now().strftime("%Y-%m-%d"),
                        "importance": 7
                    })
            
            long_term_memory["user_profile"]["preferences"] = \
                long_term_memory["user_profile"]["preferences"][-50:]
        
        if extracted.get("topics"):
            if "discussed_topics" not in long_term_memory:
                long_term_memory["discussed_topics"] = []
            
            existing_topics = long_term_memory["discussed_topics"]
            new_topics = list(set(existing_topics + extracted["topics"]))
            long_term_memory["discussed_topics"] = new_topics[-30:]
        
        if extracted.get("emotional_events"):
            if "emotional_events" not in long_term_memory:
                long_term_memory["emotional_events"] = []
            
            for event in extracted["emotional_events"]:
                long_term_memory["emotional_events"].append({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "event": event["event"],
                    "emotion": event.get("emotion", "neutral"),
                    "importance": event.get("importance", 6)
                })
            
            long_term_memory["emotional_events"] = sorted(
                long_term_memory["emotional_events"],
                key=lambda x: x.get("importance", 0),
                reverse=True
            )[:50]
        
        return long_term_memory
    
    def merge_memory_to_storage(self, extracted: Dict, long_term_memory: Dict) -> Dict:
        if not extracted["has_update"]:
            return long_term_memory
        
        mem_type = extracted["type"]
        content = extracted["content"]
        importance = extracted["importance"]
        
        if "user_profile" not in long_term_memory:
            long_term_memory["user_profile"] = {}
        
        if mem_type == "profile":
            if "名字" in content or "叫" in content:
                name_match = re.search(r'(?:名字是|叫)(.{2,10})', content)
                if name_match:
                    long_term_memory["user_profile"]["name"] = name_match.group(1).strip()
            
            if "profile_notes" not in long_term_memory["user_profile"]:
                long_term_memory["user_profile"]["profile_notes"] = []
            long_term_memory["user_profile"]["profile_notes"].append({
                "content": content,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "importance": importance
            })
            long_term_memory["user_profile"]["profile_notes"] = \
                long_term_memory["user_profile"]["profile_notes"][-20:]
        
        elif mem_type == "preference":
            if "preferences" not in long_term_memory["user_profile"]:
                long_term_memory["user_profile"]["preferences"] = []
            
            existing = [p["content"] if isinstance(p, dict) else p 
                       for p in long_term_memory["user_profile"]["preferences"]]
            if content not in existing:
                long_term_memory["user_profile"]["preferences"].append({
                    "content": content,
                    "time": datetime.now().strftime("%Y-%m-%d"),
                    "importance": importance
                })
                long_term_memory["user_profile"]["preferences"] = \
                    long_term_memory["user_profile"]["preferences"][-50:]
        
        elif mem_type == "event":
            if "important_events" not in long_term_memory:
                long_term_memory["important_events"] = []
            
            long_term_memory["important_events"].append({
                "content": content,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "importance": importance
            })
            long_term_memory["important_events"] = sorted(
                long_term_memory["important_events"],
                key=lambda x: x.get("importance", 0),
                reverse=True
            )[:50]
        
        return long_term_memory
    
    def compress_messages_with_llm(self, messages: List[Dict], api_handler) -> Tuple[List[Dict], str]:
        if len(messages) <= 6:
            return messages, ""
        
        recent_messages = messages[-5:]
        old_messages = messages[:-5]
        
        conversation_text = ""
        for msg in old_messages:
            role = "用户" if msg["role"] == "user" else "星织"
            conversation_text += f"{role}: {msg['content']}\n\n"
        
        summary_prompt = f"""请将以下对话总结为简洁的第三人称摘要（150字以内），包含：
1. 讨论的主要话题
2. 重要的事实信息
3. 情绪变化的关键点

对话内容：
{conversation_text}

要求：
- 使用第三人称描述
- 突出重要信息和情感转折
- 不要包含"他们讨论了"等废话，直接陈述内容
"""
        
        try:
            success, summary = api_handler.call_api(
                messages=[{"role": "user", "content": summary_prompt}],
                system_prompt="你是一个专业的对话摘要助手，擅长提取关键信息。",
                psych_core=None
            )
            
            if success:
                summary = summary.strip()
                print(f"✅ LLM摘要生成成功: {len(summary)}字符")
            else:
                summary = self._generate_fallback_summary(old_messages)
                print(f"⚠️ LLM摘要失败，使用备用方案")
        
        except Exception as e:
            print(f"⚠️ 摘要生成异常: {e}，使用备用方案")
            summary = self._generate_fallback_summary(old_messages)
        
        if summary:
            summary_msg = {
                "role": "system",
                "content": f"【历史对话摘要】\n{summary}"
            }
            compressed = [summary_msg] + recent_messages
        else:
            compressed = recent_messages
        
        return compressed, summary
    
    def compress_messages(self, messages: List[Dict], target_tokens: int) -> Tuple[List[Dict], str]:
        if len(messages) <= 5:
            return messages, ""
        
        recent_messages = messages[-5:]
        old_messages = messages[:-5]
        
        summary = self._generate_fallback_summary(old_messages)
        
        if summary:
            summary_msg = {
                "role": "system",
                "content": f"【历史对话摘要】\n{summary}"
            }
            compressed = [summary_msg] + recent_messages
        else:
            compressed = recent_messages
        
        return compressed, summary
    
    def _generate_fallback_summary(self, messages: List[Dict]) -> str:
        if not messages:
            return ""
        
        all_text = " ".join([msg.get("content", "") for msg in messages])
        keywords = self._extract_keywords(all_text)
        
        if keywords:
            return f"讨论了关于 {', '.join(keywords[:5])} 的话题"
        return "进行了一段对话"
    
    def _extract_keywords(self, text: str) -> List[str]:
        stopwords = {'的', '了', '在', '是', '我', '你', '他', '她', '它', '们',
                     '这', '那', '有', '和', '就', '都', '而', '及', '与', '或',
                     '吗', '呢', '吧', '啊', '哦', '嗯', '哈'}
        
        words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        keywords = [w for w in words if w not in stopwords and len(w) >= 2]
        
        return list(dict.fromkeys(keywords))[:5]
    
    def should_compress(self, current_tokens: int) -> bool:
        return current_tokens > self.safe_threshold
    
    def calculate_importance(self, event_type: str, pad_state: Dict) -> int:
        base_importance = self.importance_weights.get(event_type, 3)
        
        arousal = abs(pad_state.get('arousal', 0))
        pleasure = pad_state.get('pleasure', 0)
        
        if arousal > 0.7 and abs(pleasure) > 0.5:
            base_importance = min(10, base_importance + 2)
        
        return base_importance
    
    def should_keep_forever(self, importance: int, event_type: str) -> bool:
        if event_type in ["user_info", "profile", "milestone"] or importance >= 8:
            return True
        return False