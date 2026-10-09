# -*- coding: utf-8 -*-
"""
独立情绪识别层 - Phase 1
使用轻量级情感分析模型 + 关键词规则融合
"""
import re
from typing import Dict, Tuple
import math


class EmotionAnalyzer:
    """情绪分析器 - 双通道架构"""
    
    def __init__(self):
        # 情感关键词库（规则匹配通道）
        self.emotion_keywords = {
            "joy": {
                "keywords": ["开心", "高兴", "快乐", "幸福", "兴奋", "欣喜", "愉快", "哈哈", "嘻嘻", "😊", "😄", "🎉"],
                "pad": {"p": 0.6, "a": 0.4, "d": 0.2}
            },
            "sadness": {
                "keywords": ["难过", "伤心", "痛苦", "悲伤", "失落", "沮丧", "郁闷", "哭", "😢", "😭"],
                "pad": {"p": -0.6, "a": -0.2, "d": -0.3}
            },
            "anger": {
                "keywords": ["生气", "愤怒", "气愤", "恼火", "火大", "讨厌", "烦", "😠", "😡", "💢"],
                "pad": {"p": -0.5, "a": 0.7, "d": 0.5}
            },
            "fear": {
                "keywords": ["害怕", "恐惧", "担心", "紧张", "焦虑", "不安", "😰", "😨"],
                "pad": {"p": -0.4, "a": 0.3, "d": -0.5}
            },
            "surprise": {
                "keywords": ["惊讶", "震惊", "意外", "没想到", "竟然", "😲", "😮"],
                "pad": {"p": 0.2, "a": 0.6, "d": 0.0}
            },
            "disgust": {
                "keywords": ["恶心", "厌恶", "反感", "恶心", "🤢", "🤮"],
                "pad": {"p": -0.6, "a": 0.2, "d": 0.3}
            },
            "trust": {
                "keywords": ["相信", "信任", "依赖", "放心", "靠谱"],
                "pad": {"p": 0.4, "a": 0.1, "d": -0.2}
            },
            "anticipation": {
                "keywords": ["期待", "盼望", "希望", "想要", "等待"],
                "pad": {"p": 0.3, "a": 0.3, "d": 0.1}
            }
        }
        
        # 情绪强度修饰词
        self.intensity_modifiers = {
            "very_high": ["超级", "非常", "特别", "极其", "太", "巨", "爆", "超"],
            "high": ["很", "挺", "蛮", "好"],
            "low": ["有点", "稍微", "略微", "一点"]
        }
        
        # Plutchik情绪轮 - 复杂情绪映射
        self.complex_emotions = {
            "love": {"primary": ["joy", "trust"], "threshold": 0.4},
            "guilt": {"primary": ["fear", "sadness"], "threshold": 0.4},
            "delight": {"primary": ["joy", "surprise"], "threshold": 0.4},
            "submission": {"primary": ["trust", "fear"], "threshold": 0.4},
            "curiosity": {"primary": ["trust", "surprise"], "threshold": 0.3},
            "sentimentality": {"primary": ["trust", "sadness"], "threshold": 0.3},
            "awe": {"primary": ["fear", "surprise"], "threshold": 0.4},
            "despair": {"primary": ["fear", "sadness"], "threshold": 0.5},
            "remorse": {"primary": ["sadness", "disgust"], "threshold": 0.4},
            "contempt": {"primary": ["anger", "disgust"], "threshold": 0.4},
            "aggressiveness": {"primary": ["anger", "anticipation"], "threshold": 0.5},
            "optimism": {"primary": ["anticipation", "joy"], "threshold": 0.3},
            "anxiety": {"primary": ["fear", "anticipation"], "threshold": 0.4},
            "disappointment": {"primary": ["surprise", "sadness"], "threshold": 0.4}
        }
    
    def analyze_text(self, text: str) -> Dict:
        """
        分析文本情绪
        
        Returns:
            {
                "basic_emotions": {emotion: score},  # 8种基础情绪
                "complex_emotions": {emotion: score},  # 复杂情绪
                "pad_prediction": {"p": x, "a": y, "d": z},
                "dominant_emotion": "joy",
                "confidence": 0.85
            }
        """
        # 通道1: 关键词匹配
        keyword_result = self._keyword_matching(text)
        
        # 通道2: 简化的情感分析（基于规则）
        # 注：真实部署时可替换为 transformers 模型
        rule_result = self._rule_based_analysis(text)
        
        # 融合两个通道
        basic_emotions = self._merge_channels(keyword_result, rule_result)
        
        # 检测复杂情绪
        complex_emotions = self._detect_complex_emotions(basic_emotions)
        
        # 计算PAD值
        pad_prediction = self._calculate_pad(basic_emotions)
        
        # 确定主导情绪
        dominant_emotion = max(basic_emotions.items(), key=lambda x: x[1])[0] if basic_emotions else "neutral"
        
        # 计算置信度
        confidence = self._calculate_confidence(basic_emotions)
        
        return {
            "basic_emotions": basic_emotions,
            "complex_emotions": complex_emotions,
            "pad_prediction": pad_prediction,
            "dominant_emotion": dominant_emotion,
            "confidence": confidence
        }
    
    def _keyword_matching(self, text: str) -> Dict[str, float]:
        """关键词匹配通道"""
        scores = {}
        
        for emotion, data in self.emotion_keywords.items():
            score = 0.0
            for keyword in data["keywords"]:
                if keyword in text:
                    # 基础分数
                    base_score = 0.3
                    
                    # 检查强度修饰词
                    for intensity, modifiers in self.intensity_modifiers.items():
                        for modifier in modifiers:
                            if modifier + keyword in text or keyword + modifier in text:
                                if intensity == "very_high":
                                    base_score = 0.9
                                elif intensity == "high":
                                    base_score = 0.6
                                elif intensity == "low":
                                    base_score = 0.2
                                break
                    
                    score = max(score, base_score)
            
            if score > 0:
                scores[emotion] = score
        
        return scores
    
    def _rule_based_analysis(self, text: str) -> Dict[str, float]:
        """基于规则的情感分析（简化版）"""
        scores = {}
        
        # 检测否定词
        negation_words = ["不", "没", "别", "无", "非", "未"]
        has_negation = any(neg in text for neg in negation_words)
        
        # 检测疑问
        is_question = "?" in text or "？" in text or any(q in text for q in ["吗", "呢", "吧"])
        
        # 检测感叹
        is_exclamation = "!" in text or "！" in text
        
        # 根据标点和语气调整
        if is_exclamation:
            scores["joy"] = scores.get("joy", 0) + 0.2
            scores["surprise"] = scores.get("surprise", 0) + 0.1
        
        if is_question:
            scores["anticipation"] = scores.get("anticipation", 0) + 0.1
        
        # 检测极端词汇
        extreme_positive = ["太好了", "完美", "棒极了", "爱死了"]
        extreme_negative = ["糟糕", "完蛋", "崩溃", "绝望"]
        
        for word in extreme_positive:
            if word in text:
                scores["joy"] = 0.8
        
        for word in extreme_negative:
            if word in text:
                scores["sadness"] = 0.7
                scores["fear"] = 0.5
        
        return scores
    
    def _merge_channels(self, keyword_scores: Dict, rule_scores: Dict) -> Dict[str, float]:
        """融合两个通道的结果"""
        merged = {}
        all_emotions = set(keyword_scores.keys()) | set(rule_scores.keys())
        
        for emotion in all_emotions:
            keyword_score = keyword_scores.get(emotion, 0)
            rule_score = rule_scores.get(emotion, 0)
            
            # 关键词权重更高（更直接）
            merged[emotion] = 0.7 * keyword_score + 0.3 * rule_score
        
        return merged
    
    def _detect_complex_emotions(self, basic_emotions: Dict[str, float]) -> Dict[str, float]:
        """检测复杂情绪（Plutchik情绪轮）"""
        complex = {}
        
        for complex_emotion, config in self.complex_emotions.items():
            primary_emotions = config["primary"]
            threshold = config["threshold"]
            
            # 检查主要情绪是否都存在且超过阈值
            scores = [basic_emotions.get(e, 0) for e in primary_emotions]
            
            if all(s >= threshold for s in scores):
                # 复杂情绪强度 = 主要情绪的平均值
                complex[complex_emotion] = sum(scores) / len(scores)
        
        return complex
    
    def _calculate_pad(self, basic_emotions: Dict[str, float]) -> Dict[str, float]:
        """根据基础情绪计算PAD值"""
        pad = {"p": 0.0, "a": 0.0, "d": 0.0}
        
        if not basic_emotions:
            return pad
        
        # 加权平均
        total_weight = sum(basic_emotions.values())
        
        for emotion, score in basic_emotions.items():
            if emotion in self.emotion_keywords:
                emotion_pad = self.emotion_keywords[emotion]["pad"]
                weight = score / total_weight
                
                pad["p"] += emotion_pad["p"] * weight
                pad["a"] += emotion_pad["a"] * weight
                pad["d"] += emotion_pad["d"] * weight
        
        # 限制范围
        pad["p"] = max(-1.0, min(1.0, pad["p"]))
        pad["a"] = max(-1.0, min(1.0, pad["a"]))
        pad["d"] = max(-1.0, min(1.0, pad["d"]))
        
        return pad
    
    def _calculate_confidence(self, basic_emotions: Dict[str, float]) -> float:
        """计算置信度"""
        if not basic_emotions:
            return 0.0
        
        # 置信度 = 最高情绪分数
        max_score = max(basic_emotions.values())
        
        # 如果有多个情绪分数接近，降低置信度
        high_scores = [s for s in basic_emotions.values() if s >= max_score * 0.8]
        if len(high_scores) > 2:
            return max_score * 0.7
        
        return max_score
    
    def verify_ai_response_consistency(self, ai_response: str, current_pad: Dict[str, float]) -> Tuple[bool, str]:
        """
        验证AI回复与当前情绪状态的一致性
        
        Args:
            ai_response: AI的回复文本
            current_pad: 当前PAD状态，支持两种格式:
                        - {"p": x, "a": y, "d": z} 或
                        - {"pleasure": x, "arousal": y, "dominance": z}
        
        Returns:
            (is_consistent, suggestion)
        """
        # 分析AI回复的情绪
        response_emotion = self.analyze_text(ai_response)
        response_pad = response_emotion["pad_prediction"]
        
        # 兼容两种PAD格式
        if "pleasure" in current_pad:
            current_p = current_pad["pleasure"]
            current_a = current_pad["arousal"]
        else:
            current_p = current_pad["p"]
            current_a = current_pad["a"]
        
        # 计算PAD差异
        p_diff = abs(current_p - response_pad["p"])
        a_diff = abs(current_a - response_pad["a"])
        
        # 如果P值差异过大（情绪极性相反）
        if p_diff > 1.0:  # 一个正一个负
            if current_p < -0.5 and response_pad["p"] > 0.3:
                return False, "当前情绪悲伤，但回复过于积极，建议添加情绪过渡"
            elif current_p > 0.5 and response_pad["p"] < -0.3:
                return False, "当前情绪愉悦，但回复过于消极，可能不符合状态"
        
        # 如果A值差异过大（能量不匹配）
        if a_diff > 0.8:
            if current_a < -0.3 and response_pad["a"] > 0.5:
                return False, "当前情绪低落，但回复过于激动，建议降低能量"
        
        return True, ""
