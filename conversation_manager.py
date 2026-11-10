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
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any  # ⭐ 添加这行导入
import random
import db
from memory_manager import MemoryManager
from memory_store import MemoryStore
from conversation_store import ConversationStore
from emotion_engine import EmotionEngine
from emotion_analyzer import EmotionAnalyzer  # ⭐ 新增
from vector_memory import DynamicMemoryGraph  # ⭐ 新增
from cognitive_system import CognitiveEnhancementSystem  # ⭐ Phase 2
from autonomous_system import AutonomousIntelligenceSystem  # ⭐ Phase 3
import daily_life

#: 她的性格底色。换对话不换人格——只有"认识你多久"会变。
DEFAULT_PERSONALITY = {
    "openness": 0.7,
    "conscientiousness": 0.6,
    "extraversion": 0.5,
    "agreeableness": 0.8,
    "neuroticism": 0.4,
}

#: 陌生人状态。只有"重新认识"的对话才从这里开始。
INITIAL_RELATIONSHIP = {"trust": 50, "intimacy": 50, "stress": 0}

#: 关系阶段：由亲密度派生，用来约束称呼、主动程度和边界感。
STAGES = ((30, "初识"), (45, "熟悉"), (65, "亲近"), (101, "依赖"))

#: 一句话短成这样、又没有情绪词，就当寒暄处理：不检索往事，只带固定事实。
#: 省下的不是那 2ms 检索时间，是注入提示词的两三百字。
_LIGHT_MAX = 5
_EMOTION_WORDS = re.compile(r"累|烦|难过|开心|生气|焦虑|压力|哭|委屈|孤单|害怕|想|爱|恨|死|疼|病")

#: 发送窗格：攒到 HARD_CAP 条才整体前移一次，前移后只留 SOFT_KEEP 条。
#: 数字大一点意味着"跳窗"更少（缓存命中更多），代价是单轮输入更长；
#: 44/26 是在 2600 token 预算下测出来的折中。
HIST_HARD_CAP = 44
HIST_SOFT_KEEP = 26


def stage_of(intimacy):
    for edge, name in STAGES:
        if intimacy < edge:
            return name
    return "依赖"


def _mood_label(mood):
    """把 PAD 翻成一句人话，给提示词和界面用。"""
    p = float((mood or {}).get("pleasure", 0))
    a = float((mood or {}).get("arousal", 0))
    if p >= 0.35 and a >= 0.2:
        return "心情不错，有点雀跃"
    if p >= 0.35:
        return "心情挺好"
    if p <= -0.35 and a >= 0.15:
        return "有点烦躁，容易急"
    if p <= -0.35:
        return "有点低落，提不起劲"
    if a <= -0.25:
        return "懒懒的，没什么精神"
    return "心情平静"


class ConversationManager:
    """对话管理器 - 增强版"""
    def __init__(self, save_dir="baocun", builtin_role_prompt=""):
        self.save_dir = save_dir
        self.conversations_path = os.path.join(save_dir, "conversations.json")
        self.db_path = os.path.join(save_dir, "hoshiori.db")
        self.builtin_role_prompt = builtin_role_prompt
        self.conversations = {}
        self.current_conversation_id = None

        # ⭐ 新的存储层：对话/消息/记忆都落 SQLite，不再整份重写 JSON
        self.conv_store = ConversationStore(self.db_path)
        self.memory_store = MemoryStore(self.db_path)

        # 语义检索是可选增强：模型和旧记忆的向量在后台补，不挡启动。
        # 补完之前 recall 只有关键词那一路，结果一样能用。
        try:
            self.memory_store.warm_up_async()
        except Exception as exc:
            print(f"⚠️ 语义索引启动失败: {exc}")

        # 她自己的日子：一天一行流水，按需补写
        self.daily_life = daily_life.get(self.db_path)

        # 初始化记忆管理器（保留旧的抽取/压缩工具，供兼容与摘要使用）
        self.memory_manager = MemoryManager(max_tokens=3000)

        # ⭐ 情绪引擎：评价 → 情绪 → PAD → 回归基线
        self.emotion_engine = EmotionEngine()

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

        # 发送窗格的起点（消息下标）。只在攒够一批时整体前移一次，
        # 这样两次前移之间发给模型的 messages 前缀完全一样，缓存才吃得到。
        self._hist_offset = 0
        
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
        
        # 她这段时间过的日子由 daily_life 记着，不在这里编模板。
        # 补写放在后台（ensure_life_async），因为它要调一次模型。
        
        # 情绪按半衰期回到她自己的基线（而不是一律归零）
        if hours_passed > 0.25:
            core = conv['psych_core']

            # 关系与心情是用户级的：先从全局取最新的，再衰减，最后写回
            if self.is_continuity():
                try:
                    us = self.conv_store.get_user_state() or {}
                    if us.get('relationship'):
                        core['relationship'] = us['relationship']
                    if us.get('mood'):
                        core['mood'] = us['mood']
                except Exception:
                    pass

            try:
                changed = self.emotion_engine.relax_by_time(core, hours_passed)
                if changed:
                    print(f"⏰ 情绪回落: 已过 {hours_passed:.1f} 小时 → "
                          f"P={core['state']['pleasure']:.2f} A={core['state']['arousal']:.2f}")
                if self.is_continuity():
                    self._sync_user_state(core)
                if changed:
                    self.save_conversations()
            except Exception as e:
                print(f"⚠️ 情绪回落失败: {e}")
    
    def update_psych_state(self, updates, user_text="", analyzer_result=None):
        """更新心理状态：评价 → 情绪 → PAD → 回归基线（并顺手记下强情绪）。"""
        if not self.current_conversation_id:
            return None
        
        conv = self.conversations[self.current_conversation_id]
        core = conv['psych_core']
        
        # 记录更新前的状态到历史（情绪过载检测要用）
        self.emotion_history.append(dict(core.get('state') or {}))
        if len(self.emotion_history) > 10:
            self.emotion_history = self.emotion_history[-10:]
        
        info = self.emotion_engine.update(
            core,
            appraisal=updates.get('appraisal'),
            user_text=user_text,
            analyzer_result=analyzer_result,
            explicit_delta=updates.get('pad_delta'),
        )
        self._last_emotion_info = info
        
        if updates.get('relationship_delta'):
            self.emotion_engine.update_relationship(core, updates['relationship_delta'])
        
        # 强情绪事件进记忆库：记住的是"为什么"，不只是"有多强"
        top_intensity = max(info['emotions'].values()) if info['emotions'] else 0
        if top_intensity >= 0.45:
            reason = (updates.get('internal_monologue') or '').strip()
            if reason:
                mood = max(info['emotions'].items(), key=lambda kv: kv[1])[0]
                try:
                    self.memory_store.remember(
                        reason,
                        kind='emotion',
                        conv_id=self.current_conversation_id,
                        importance=5.5 + top_intensity * 3,
                        pad=core['state'],
                        confidence=0.7,
                        scope=self._memory_scope(),
                    )
                except Exception as e:
                    print(f"⚠️ 情绪记忆写入失败: {e}")
        
        # 更新最后交互时间
        conv['last_interaction_time'] = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # ⭐ 清除已使用的离线生活状态
        if 'offline_life_pending' in conv:
            del conv['offline_life_pending']

        # 关系、心情、对方近况是用户级的：换话题不该换关系
        if self.is_continuity():
            self._sync_user_state(core)

        self.save_conversations()
        return core
    
    def get_offline_life_status(self) -> str:
        """她今天过成什么样，拼成一段给提示词。

        名字沿用旧的（main.py 在调），内容换成了真实流水。没有流水就返回空，
        让她别凭空编「我刚在看书」。
        """
        try:
            return self.daily_life.prompt_block()
        except Exception as exc:
            print("⚠️ 读取她的生活失败: %s" % exc)
            return ""

    def life_state(self):
        """前端「她今天」面板用。"""
        try:
            return self.daily_life.current()
        except Exception as exc:
            print("⚠️ 读取她的生活失败: %s" % exc)
            return None

    def life_hints(self, k=6):
        """写她的日子时，要提到你的什么。只用她确定记得的，不现编。"""
        if not self.current_conversation_id:
            return []
        out = []
        try:
            for m in self.memory_store.pinned(
                    self.current_conversation_id, k, scopes=self.memory_scopes()):
                c = (m.get("content") or "").strip()
                if c and c not in out:
                    out.append(c)
        except Exception:
            pass
        try:
            for item in self.memory_store.timeline(
                    self.current_conversation_id, scopes=self.memory_scopes(),
                    days=30, k=4):
                c = (item.get("content") or "").strip()
                if c and c not in out:
                    out.append(c)
        except Exception:
            pass
        return out[:k]

    def ensure_life_async(self, api_handler):
        """后台补写她今天过的日子。不挡回复，没有模型时退回本地素材。"""
        try:
            self.daily_life.ensure_async(
                api_handler,
                role_prompt=self.get_effective_role_prompt(),
                hints=self.life_hints(),
            )
        except Exception as exc:
            print("⚠️ 生活补写排队失败: %s" % exc)
    
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

        # 情绪联想：现在的心情让她想起哪几件旧事
        items = []
        try:
            items = self.memory_store.by_emotion(
                current_pad, self.current_conversation_id, k=2)
        except Exception as exc:
            print(f"⚠️ 情绪联想失败: {exc}")

        if not items:
            return ""

        lines = ["[🌙 此刻的心情让你想起]"]
        for item in items:
            lines.append("· %s %s" % (item.get("time", ""), item["content"]))
        lines.append("（如果想提，就轻轻带一句；不想提也没关系。）")
        return "\n".join(lines)
    
    # ========== 以下方法保持不变 ==========
    
    def _default_mood(self):
        """她的"平时心情"由性格算出来，不是拍一个数。"""
        try:
            base = self.emotion_engine.baseline_from_personality(DEFAULT_PERSONALITY)
        except Exception:
            base = {"pleasure": 0.2, "arousal": 0.05, "dominance": 0.15}
        return {
            "pleasure": round(float(base["pleasure"]), 3),
            "arousal": round(float(base["arousal"]), 3),
            "dominance": round(float(base["dominance"]), 3),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    def new_conversation(self, continuity=True):
        """创建新对话。

        continuity=True（延续）：关系、心情、"他最近怎么样"都接着上一段走，
        只是换了个话题。continuity=False（重新认识）：关系回到陌生人，
        也读不到之前跨对话的记忆——想重新体验一次的用户要的就是这个。
        """
        new_id = self.conv_store.next_id()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        personality = dict(DEFAULT_PERSONALITY)
        mood = self._default_mood()

        if continuity:
            try:
                us = self.conv_store.get_user_state() or {}
            except Exception:
                us = {}
            personality = dict(us.get("personality") or personality)
            relationship = dict(us.get("relationship") or INITIAL_RELATIONSHIP)
            mood = dict(us.get("mood") or mood)
            user_emotion = dict(us.get("user_emotion") or {})
            # 新话题的情绪从当前心情出发，不再从"莫名开心"起跳
            state = {
                "pleasure": float(mood.get("pleasure", 0)),
                "arousal": float(mood.get("arousal", 0)),
                "dominance": float(mood.get("dominance", 0)),
                "energy": 80,
            }
        else:
            relationship = dict(INITIAL_RELATIONSHIP)
            user_emotion = {}
            state = {"pleasure": 0.35, "arousal": 0.05, "dominance": 0.1, "energy": 80}

        conv = {
            "title": f"对话 {new_id} - {timestamp}",
            "messages": [],
            "message_count": 0,
            "custom_role_prompt": None,
            "created_at": timestamp,
            "last_interaction_time": timestamp,
            "continuity": 1 if continuity else 0,
            "psych_core": {
                "personality": personality,
                "state": state,
                "relationship": relationship,
                "mood": mood,
                "user_emotion": user_emotion,
            },
        }
        conv['_loaded'] = True

        self.conversations[new_id] = conv
        self.conv_store.create(new_id, conv['title'], conv['psych_core'],
                               continuity=continuity)
        self.current_conversation_id = new_id
        self._hist_offset = 0

        print("✓ 创建新对话: ID=%d（%s）" % (new_id, "延续" if continuity else "重新认识"))
        return new_id, conv
    
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
    
    def is_continuity(self):
        """这段对话是否延续「你们的」关系与记忆。"""
        if not self.current_conversation_id:
            return True
        conv = self.conversations.get(self.current_conversation_id) or {}
        return bool(conv.get('continuity', 1))

    def memory_scopes(self):
        """延续模式能读跨对话记忆；重新认识只读本对话。"""
        return ("conv", "user") if self.is_continuity() else ("conv",)

    def get_psych_state(self):
        """获取当前对话的完整心理状态。

        关系、心情、对方近况是**用户级**的：换话题不该换关系。所以这里把
        user_state 合进来，对话自己只保留 state（这一轮的情绪）。
        """
        if not self.current_conversation_id:
            return None

        conv = self.conversations[self.current_conversation_id]

        if 'psych_core' not in conv:
            conv['psych_core'] = {
                "personality": dict(DEFAULT_PERSONALITY),
                "state": {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0, "energy": 50},
                "relationship": dict(INITIAL_RELATIONSHIP),
                "mood": self._default_mood(),
                "user_emotion": {},
            }
            self.save_conversations()

        core = conv['psych_core']

        if self.is_continuity():
            try:
                us = self.conv_store.get_user_state() or {}
            except Exception:
                us = {}
            if us.get('relationship'):
                core['relationship'] = us['relationship']
            if us.get('mood'):
                core['mood'] = us['mood']
            if us.get('user_emotion'):
                core['user_emotion'] = us['user_emotion']
            if us.get('personality'):
                core['personality'] = us['personality']

        core.setdefault('mood', self._default_mood())
        core.setdefault('user_emotion', {})
        return core

    def _sync_user_state(self, core):
        """把用户级的状态写回全局：关系、心情、对方近况、人格。"""
        try:
            self.conv_store.save_user_state({
                "personality": core.get('personality') or DEFAULT_PERSONALITY,
                "relationship": core.get('relationship') or INITIAL_RELATIONSHIP,
                "mood": core.get('mood') or self._default_mood(),
                "user_emotion": core.get('user_emotion') or {},
            })
        except Exception as exc:
            print("⚠️ 保存用户状态失败: %s" % exc)

    def relationship_stage(self):
        """初识 / 熟悉 / 亲近 / 依赖——用来约束称呼和主动程度。"""
        core = self.get_psych_state() or {}
        intimacy = float((core.get('relationship') or {}).get('intimacy', 50))
        return stage_of(intimacy)

    def note_user_emotion(self, emotion):
        """记下对方当前的情绪，并累计"连续几轮不太好"。

        单轮没意义，连着的低落才有意义——这才是"他最近不太好"。
        """
        if not emotion or not self.current_conversation_id:
            return
        core = self.get_psych_state()
        if core is None:
            return

        name = emotion.get('dominant_emotion') or 'neutral'
        conf = float(emotion.get('confidence') or 0)
        negative = name in ('sad', 'angry', 'anxious', 'fear', 'disgust', 'frustrated')

        prev = dict(core.get('user_emotion') or {})
        streak = int(prev.get('negative_streak', 0))
        if negative and conf >= 0.3:
            streak += 1
        elif name in ('happy', 'excited', 'grateful', 'neutral') and conf >= 0.3:
            streak = 0

        core['user_emotion'] = {
            "emotion": name,
            "confidence": round(conf, 2),
            "negative_streak": streak,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        # 只改内存，随这一轮的 update_psych_state 一起落盘，减少写入次数

    def mood_summary(self):
        core = self.get_psych_state() or {}
        mood = core.get('mood') or {}
        return {
            "label": _mood_label(mood),
            "stage": self.relationship_stage(),
            "continuity": self.is_continuity(),
            "mood": mood,
            "user_emotion": core.get('user_emotion') or {},
        }
    
    def get_long_term_memory(self):
        """长期记忆的只读视图（内容已经搬进 SQLite，这里拼给旧调用方看）。"""
        if not self.current_conversation_id:
            return None
        try:
            items = self.memory_store.list_recent(self.current_conversation_id, limit=200)
        except Exception:
            items = []
        view = {
            "user_profile": {},
            "important_events": [],
            "emotional_events": [],
            "discussed_topics": [],
            "long_term_summaries": [],
        }
        for item in items:
            kind = item.get("kind")
            if kind == "profile":
                view["user_profile"].setdefault("profile_notes", []).append(
                    {"content": item["content"], "importance": item["importance"]})
            elif kind == "preference":
                view["user_profile"].setdefault("preferences", []).append(
                    {"content": item["content"], "importance": item["importance"]})
            elif kind == "event":
                view["important_events"].append(item)
            elif kind == "emotion":
                view["emotional_events"].append(item)
            elif kind == "topic":
                view["discussed_topics"].append(item["content"])
        return view
    
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
    
    
    def get_compressed_messages(self, max_tokens=2600, keep_recent=HIST_SOFT_KEEP):
        """取要发给模型的上下文：最近一段原文 + 更早对话的摘要。

        和以前不一样的地方：窗口**不是每轮滑一格**，而是攒到 HIST_HARD_CAP 条
        才整体往前跳一次。

        为什么这很重要：提示词缓存是按"前缀完全一致"命中的。以前每轮丢掉最旧
        一条、补上最新一条，整个 messages 前缀每轮都在变，缓存等于没有——一个
        聊到第 30 轮的会话，仍然为每一轮的完整历史按原价付费。改成批量前移后，
        两次跳窗之间（十几轮）前缀一字不差，那一段就是命中缓存的。

        跳窗时被丢掉的旧消息早就在摘要里了（maybe_summarize 保留的正是
        HIST_SOFT_KEEP 条），所以不会真的失忆。
        """
        if not self.current_conversation_id:
            return [], ""

        conv = self._ensure_messages_loaded(self.current_conversation_id)
        messages = conv.get('messages') or []
        if not messages:
            return [], ""

        n = len(messages)
        if self._hist_offset > n:
            self._hist_offset = max(0, n - keep_recent)
        if n - self._hist_offset > HIST_HARD_CAP:
            self._hist_offset = n - keep_recent

        recent = list(messages[self._hist_offset:])

        # 极端情况兜底：几十条长消息还是要按 token 砍，哪怕会破坏前缀
        used = 0
        while len(recent) > 4:
            cost = sum(self.memory_manager.estimate_tokens(m.get('content', ''))
                       for m in recent)
            if cost <= max_tokens:
                used = cost
                break
            recent = recent[2:]
            self._hist_offset += 2
            used = cost

        summaries = []
        try:
            summaries = self.conv_store.summaries(self.current_conversation_id, 3)
        except Exception:
            pass

        return recent, "\n".join(summaries)

    def maybe_summarize(self, api_handler, keep_recent=HIST_SOFT_KEEP):
        """把压到保留区之外的旧消息做一次摘要（每 ~20 条才触发一次）。"""
        if not self.current_conversation_id or api_handler is None:
            return False

        try:
            batch = self.conv_store.messages_to_summarize(
                self.current_conversation_id, keep_recent=keep_recent)
        except Exception as exc:
            print(f"⚠️ 读取待摘要消息失败: {exc}")
            return False

        if len(batch) < 8:
            return False

        lines = []
        for msg in batch:
            who = "用户" if msg["role"] == "user" else "星织"
            text = msg["content"].strip().replace("\n", " ")
            if len(text) > 120:
                text = text[:120] + "…"
            lines.append("%s: %s" % (who, text))
        transcript = "\n".join(lines)

        prompt = (
            "把下面这段对话整理成两样东西，给之后的你（星织）当回忆用。\n"
            "1. summary：第三人称摘要，300 字以内。保留用户说过的事实、约定、"
            "情绪转折、没聊完的话题；丢掉客套和重复。\n"
            "2. reflections：0~2 条，每条 40 字以内，写你对他这个人的理解"
            "（他在意什么、习惯怎么应对、嘴上和心里不一致的地方）。"
            "必须有对话里的依据，不能猜、不能编；没有就空数组。\n"
            "只输出 JSON：{\"summary\": \"...\", \"reflections\": [\"...\"]}\n\n"
            + transcript
        )

        try:
            ok, text = api_handler.call_api(
                [{"role": "user", "content": prompt}],
                "你是一个精准的对话整理器，只输出 JSON。",
            )
        except Exception as exc:
            print(f"⚠️ 摘要失败: {exc}")
            return False

        if not ok or not text or len(text.strip()) < 10:
            return False

        text = text.strip()
        summary, reflections = text, []
        if text.startswith("{"):
            try:
                data = json.loads(text)
                summary = (data.get("summary") or "").strip() or text
                reflections = [r for r in (data.get("reflections") or [])
                               if isinstance(r, str) and 4 <= len(r) <= 80][:2]
            except Exception:
                # 模型套了层 JSON 但没闭合：退回纯文本摘要，别把反思弄丢就整段失败
                m = re.search(r'"summary"\s*:\s*"(.*?)"\s*[,}]', text, re.DOTALL)
                if m:
                    summary = m.group(1)
                else:
                    summary = re.sub(r'^\s*\{.*?"summary"\s*:\s*"', "", text, flags=re.DOTALL)

        if not summary or len(summary.strip()) < 10:
            return False

        upto = batch[-1]["id"]
        self.conv_store.add_summary(self.current_conversation_id, summary.strip(), upto)
        self.conv_store.mark_summarized(self.current_conversation_id, upto)
        print("✓ 已摘要 %d 条旧消息" % len(batch))

        # L4：反思单独入库。它不是"发生过什么"，而是"你怎么看他"——
        # 检索到的时候会以一句判断出现在提示词里，这比十条流水账更像认识一个人。
        for line in reflections:
            try:
                self.memory_store.remember(
                    line, kind="reflection", conv_id=self.current_conversation_id,
                    importance=6.8, confidence=0.6, scope=self._memory_scope())
            except Exception as exc:
                print(f"⚠️ 反思入库失败: {exc}")
        if reflections:
            print("✓ 沉淀 %d 条反思" % len(reflections))
        return True

    # ------------------------------------------------------------ 记忆

    def recall_memories(self, query, pad=None, k=6):
        """按当前这句话取相关记忆。延续模式会带上跨对话的部分。"""
        if not self.current_conversation_id:
            return [], []
        scopes = self.memory_scopes()
        try:
            pinned = self.memory_store.pinned(
                self.current_conversation_id, 4, scopes=scopes)
            recalled = self.memory_store.recall(
                query, self.current_conversation_id, pad, k=k, scopes=scopes)
        except Exception as exc:
            print(f"⚠️ 记忆检索失败: {exc}")
            return [], []
        # 已经钉住的不再重复出现在"往事"里
        pinned_ids = {m["id"] for m in pinned}
        recalled = [m for m in recalled if m["id"] not in pinned_ids]
        return pinned, recalled

    def is_light_turn(self, text):
        """寒暄级的一轮：短、且没有情绪/事件信号。"""
        t = (text or "").strip()
        if not t or len(t) > _LIGHT_MAX:
            return False
        return _EMOTION_WORDS.search(t) is None

    def pinned_only(self):
        """只取"每次都要在场"的固定事实（名字/生日/职业）。"""
        if not self.current_conversation_id:
            return []
        try:
            return self.memory_store.pinned(
                self.current_conversation_id, 4, scopes=self.memory_scopes())
        except Exception:
            return []

    def recent_timeline(self, days=45, k=5):
        """你们最近这段日子发生过什么（按时间正序）。"""
        if not self.current_conversation_id:
            return []
        try:
            return self.memory_store.timeline(
                self.current_conversation_id, self.memory_scopes(), days=days, k=k)
        except Exception as exc:
            print(f"⚠️ 时间线读取失败: {exc}")
            return []

    def _memory_scope(self):
        return "user" if self.is_continuity() else "conv"

    def remember_from_extraction(self, extracted, ai_text="", pad=None):
        """规则抽出来的信息 → 记忆库。"""
        if not self.current_conversation_id:
            return 0
        conv_id = self.current_conversation_id
        n = 0
        try:
            info = (extracted or {}).get("user_info") or {}
            for field, label, key, imp in (
                ("name", "用户的名字是", "profile:name", 9.0),
                ("birthday", "用户的生日是", "profile:birthday", 8.0),
                ("occupation", "用户的工作是", "profile:occupation", 8.5),
            ):
                value = info.get(field)
                if value:
                    action, _ = self.memory_store.remember(
                        "%s%s" % (label, value), kind="profile", conv_id=conv_id,
                        key=key, importance=imp, confidence=0.9,
                        scope=self._memory_scope())
                    n += action in ("add", "update", "supersede")

            for pref in (extracted or {}).get("preferences") or []:
                action, _ = self.memory_store.remember(
                    pref, kind="preference", conv_id=conv_id,
                    importance=6.5, confidence=0.7, scope=self._memory_scope())
                n += action in ("add", "update")

            for topic in (extracted or {}).get("topics") or []:
                action, _ = self.memory_store.remember(
                    "聊过：%s" % topic, kind="topic", conv_id=conv_id,
                    importance=3.0, confidence=0.6, scope=self._memory_scope())
                n += action in ("add", "update")
        except Exception as exc:
            print(f"⚠️ 记忆写入失败: {exc}")
        return n

    def remember_fact(self, content, kind="event", importance=None, pad=None):
        """模型主动给的 memory_update 落库。"""
        if not self.current_conversation_id or not content:
            return False
        try:
            action, _ = self.memory_store.remember(
                content, kind=kind, conv_id=self.current_conversation_id,
                importance=importance, pad=pad, confidence=0.85,
                scope=self._memory_scope())
            return action in ("add", "update", "supersede")
        except Exception as exc:
            print(f"⚠️ 记忆写入失败: {exc}")
            return False
    
    
    def get_current_conversation(self):
        """获取当前对话"""
        if self.current_conversation_id:
            return self.conversations.get(self.current_conversation_id)
        return None
    
    def add_message(self, role, content, kind=None):
        """添加消息到当前对话：内存里留一份，同时落库（O(1)，不重写整份文件）"""
        if not self.current_conversation_id:
            return
        conv = self.conversations[self.current_conversation_id]
        self._ensure_messages_loaded(self.current_conversation_id)
        try:
            tokens = self.memory_manager.estimate_tokens(content)
        except Exception:
            tokens = 0

        # 先落库拿 id，再放进内存：前面发出去的气泡靠这个 id 才能被
        # 搜索定位到、才能"改一下重发"。拿不到 id（异常）也不影响显示。
        msg_id = None
        try:
            msg_id = self.conv_store.append_message(
                self.current_conversation_id, role, content, tokens, kind=kind)
        except Exception as exc:
            print("⚠️ 消息落库失败: %s" % exc)

        conv.setdefault('messages', []).append({
            "id": msg_id,
            "role": role,
            "content": content,
            "created_at": db.now_str(),
            "kind": kind,
        })
        conv['message_count'] = conv.get('message_count', 0) + 1

        # 第一句用户消息顺手当标题，列表里就不用再去翻消息了
        if role == "user" and conv.get('message_count', 0) == 1:
            title = re.sub(r"\s+", " ", content).strip()
            if title:
                conv['title'] = title[:22] + ('…' if len(title) > 22 else '')
                try:
                    self.conv_store.save_meta(self.current_conversation_id, conv)
                except Exception:
                    pass
    
    def delete_conversation(self, conv_id):
        """删除对话

        注意：删除后 ID 会被重排，调用方必须重新读取列表，不能沿用旧的 ID。

        Returns:
            (success: bool, message: str, current_id)
            current_id 为重排之后的当前对话 ID，可能为 None。
        """
        try:
            conv_id = int(conv_id)
        except (TypeError, ValueError):
            return False, "对话不存在", self.current_conversation_id

        if conv_id not in self.conversations:
            return False, "对话不存在", self.current_conversation_id

        if len(self.conversations) == 1:
            return False, "不能删除最后一个对话", self.current_conversation_id

        was_current = conv_id == self.current_conversation_id
        del self.conversations[conv_id]
        try:
            self.conv_store.delete(conv_id)
            self.memory_store.drop_conversation(conv_id)
        except Exception as e:
            print(f"⚠️ 删除对话数据失败: {e}")

        if was_current:
            if self.conversations:
                # 切到「最近聊过」的那一段，而不是编号最大的那一段
                self.current_conversation_id = max(
                    self.conversations.keys(),
                    key=lambda k: str(self.conversations[k].get(
                        'last_interaction_time', ''))
                )
                self._ensure_messages_loaded(self.current_conversation_id)
            else:
                self.current_conversation_id = None

        self.redraw_conversation_titles()
        self.save_conversations()
        return True, "删除成功", self.current_conversation_id

    def reorder_conversation_ids(self):
        """保留旧名字，实际只重排标题（ID 现在被消息和记忆引用，不能随便改）"""
        self.redraw_conversation_titles()

    def redraw_conversation_titles(self):
        """把「对话 N」里的编号按当前顺序对齐，ID 本身不动。"""
        for index, conv_id in enumerate(sorted(self.conversations.keys()), start=1):
            conv = self.conversations[conv_id]
            title = conv.get('title') or ''
            match = re.match(r'对话\s*(\d+)', title)
            if not match or int(match.group(1)) == index:
                continue
            conv['title'] = title.replace(match.group(0), '对话 %d' % index, 1)
            try:
                self.conv_store.save_meta(conv_id, conv)
            except Exception:
                pass
    
    def switch_conversation(self, conv_id):
        """切换对话（把目标对话的消息读进内存）"""
        if conv_id in self.conversations:
            self.current_conversation_id = conv_id
            self._ensure_messages_loaded(conv_id)
            self._hist_offset = 0
            self.apply_time_decay()
            print(f"✓ 切换到对话: ID={conv_id}")
            return True
        return False
    
    def get_all_conversations(self):
        """获取所有对话列表"""
        result = sorted(self.conversations.keys(), reverse=True)
        return result
    
    def save_conversations(self):
        """保存元数据（标题、心理状态）。

        消息在 add_message 时已经单独落库了，这里不再整份重写。
        """
        if not self.current_conversation_id:
            return
        conv = self.conversations.get(self.current_conversation_id)
        if conv is None:
            return
        try:
            self.conv_store.save_meta(self.current_conversation_id, conv)
        except Exception as e:
            print(f"✗ 保存失败: {e}")

    def truncate_from(self, msg_id):
        """从某条消息起全部作废（编辑重发用）。"""
        conv_id = self.current_conversation_id
        if not conv_id:
            return -1
        try:
            removed = self.conv_store.truncate_from(conv_id, int(msg_id))
        except Exception as exc:
            print("⚠️ 截断消息失败: %s" % exc)
            return -1
        conv = self.conversations.get(conv_id)
        if conv is not None:
            try:
                conv['messages'] = self.conv_store.load_messages(conv_id)
                conv['message_count'] = len(conv['messages'])
            except Exception:
                conv['messages'] = []
            self._hist_offset = 0
        return removed

    def _ensure_messages_loaded(self, conv_id):
        """消息按需从库里读，不在内存里堆所有对话的历史。"""
        conv = self.conversations.get(conv_id)
        if conv is None or conv.get('_loaded'):
            return conv
        try:
            conv['messages'] = self.conv_store.load_messages(conv_id)
        except Exception as e:
            print(f"⚠️ 读取消息失败: {e}")
            conv['messages'] = []
        conv['_loaded'] = True
        conv['message_count'] = len(conv['messages'])
        return conv

    def load_conversations(self):
        """从 SQLite 加载；首次运行时把旧的 conversations.json 迁移进来。"""
        legacy_memories = {}
        try:
            # 正常情况下读 conversations.json；如果它已经被迁移改名，
            # 而库又丢了（比如手动删过 hoshiori.db），就从 .bak 里恢复一次
            src = self.conversations_path
            if not os.path.exists(src) and os.path.exists(src + ".bak"):
                src = src + ".bak"
            legacy_memories = self.conv_store.import_json(src) or {}
        except Exception as e:
            print(f"⚠️ 旧数据迁移失败: {e}")

        # 万一库已经迁移过、但记忆还没搬（从 1.6 升级上来），从备份里补一次
        if not legacy_memories:
            backup = self.conversations_path + ".bak"
            if os.path.exists(backup) and self.memory_store.stats().get('total', 0) == 0:
                try:
                    with open(backup, 'r', encoding='utf-8') as f:
                        raw = json.load(f)
                    for cid, conv in raw.items():
                        mem = (conv or {}).get('memory')
                        if mem:
                            legacy_memories[int(cid)] = mem
                except Exception as e:
                    print(f"⚠️ 读取备份失败: {e}")

        if legacy_memories:
            total = 0
            for conv_id, mem in legacy_memories.items():
                try:
                    total += self.memory_store.import_legacy(mem, conv_id)
                except Exception as e:
                    print(f"⚠️ 记忆迁移失败(对话 {conv_id}): {e}")
            if total:
                print(f"✓ 旧记忆已导入: {total} 条")

        try:
            self.conversations = self.conv_store.load_all()
        except Exception as e:
            print(f"✗ 加载失败: {e}")
            self.conversations = {}

        default_core = {
            "personality": dict(DEFAULT_PERSONALITY),
            "state": {"pleasure": 0.0, "arousal": 0.0, "dominance": 0.0, "energy": 50},
            "relationship": dict(INITIAL_RELATIONSHIP),
            "mood": self._default_mood(),
            "user_emotion": {},
        }

        for conv_id, conv in self.conversations.items():
            conv.setdefault('custom_role_prompt', None)
            conv.setdefault('continuity', 1)
            if not conv.get('psych_core'):
                conv['psych_core'] = json.loads(json.dumps(default_core))
            else:
                # 补齐老数据缺的字段
                core = conv['psych_core']
                core.setdefault('personality', default_core['personality'])
                core.setdefault('state', default_core['state'])
                core.setdefault('relationship', default_core['relationship'])
                core.setdefault('mood', default_core['mood'])
                core.setdefault('user_emotion', {})
                core['state'].setdefault('energy', 50)
            conv.setdefault('last_interaction_time', datetime.now().strftime("%Y-%m-%d %H:%M"))
            conv['messages'] = []
            conv['_loaded'] = False

        if self.conversations:
            self.current_conversation_id = max(self.conversations.keys())
            self._ensure_messages_loaded(self.current_conversation_id)
            # 启动时也按时间回落一次：关机这几天她不会一直停在某个情绪里
            try:
                self.apply_time_decay()
            except Exception as exc:
                print(f"⚠️ 启动情绪回落失败: {exc}")
            stats = self.memory_store.stats()
            print(f"✓ 加载对话成功: {len(self.conversations)}个对话, 记忆 {stats['active']} 条")
        else:
            print("✓ 还没有对话，等第一条消息")