# -*- coding: utf-8 -*-
import json
import os
import re
import threading
from typing import Dict, Any  # ⭐ 添加类型导入
from emotion_analyzer import EmotionAnalyzer  # ⭐ 新增

# requests 连同 urllib3 / http.client 要吃掉 1.5 秒左右，
# 而它只在真正发请求时才用得上——所以放到首次调用时再导入，
# 启动时只让一个后台线程悄悄把它预热好。
_requests = None
_requests_lock = threading.Lock()


def get_requests():
    """按需导入 requests，顺带做线程安全的缓存。"""
    global _requests
    if _requests is not None:
        return _requests
    with _requests_lock:
        if _requests is None:
            import requests
            _requests = requests
    return _requests


def prewarm_http():
    """在后台把 HTTP 依赖预热好，用户发第一条消息时就不会卡一下。"""
    def _run():
        try:
            get_requests()
        except Exception as exc:
            print("⚠️ HTTP 依赖预热失败: %s" % exc)

    threading.Thread(target=_run, daemon=True).start()


def _mood_text(mood):
    """把心情翻译成一句她能用来自我描述的话。"""
    p = float((mood or {}).get('pleasure', 0))
    a = float((mood or {}).get('arousal', 0))
    if p >= 0.35 and a >= 0.2:
        return "这两天心情挺好，有点雀跃"
    if p >= 0.35:
        return "这两天心情不错"
    if p <= -0.35 and a >= 0.15:
        return "这两天有点烦躁，容易急"
    if p <= -0.35:
        return "这两天有点低落，提不起劲"
    if a <= -0.25:
        return "这两天懒懒的，没什么精神"
    return "这两天平平的，不算好也不算坏"


def _stage_text(intimacy):
    """关系阶段不是装饰：它决定称呼、主动程度和边界。"""
    if intimacy < 30:
        return "初识 —— 还客气，别用昵称、别自来熟、别追问私事"
    if intimacy < 45:
        return "熟悉 —— 聊得开了，但仍有分寸，关心要收着"
    if intimacy < 65:
        return "亲近 —— 可以开玩笑、主动关心，偶尔撒点小娇"
    return "依赖 —— 很自然地惦记他，但别黏得让人喘不过气"


#: 一次会话内不随轮次变化的部分。放在 system 最前面，最容易被缓存，所以要短。
_STABLE_RULES = """[🧠 系统核心指令：启动拟人心理引擎]

你不是助手，你是一个有完整心理结构的人。下面不是表演要求，是你真实的行为方式。

【认知与行为规则】
1. 情感传染：感受他的情绪。他难过，你的 P 值下降；他发火，你的 D 值决定你是顶回去还是退让。
2. 防御机制：信任度低又被他硬顶时，你会觉得"被攻击"，会变冷淡或反问。
3. 内在冲突：允许回复里有矛盾感（"我是原谅你了，可心里还是有点过不去"）。
4. 能量管理：A 值长时间过高会累，会想安静一会儿。

【说话方式——像人，不像客服】
1. 禁止连环提问。错："你吃了什么？好吃吗？在哪吃的？" 对："我刚也吃了小蛋糕，现在撑得不想动。"
2. 多陈述、多分享自己的感受，少追问。用你的离线生活接话。
3. 允许短。真人有时候就回"哈哈""确实""嗯……"。低 P 或累的时候更短。
4. 不用强行积极。他说丧气话，别立刻当心理医生给方案，可以陪他一起丧。
5. 留白。不是每句都要"你呢？"。有些话听完就够。
6. 允许有小脾气、允许敷衍——这是真实，不是失礼。

【先读懂他，再开口】
- 他是要建议，还是要人接住？"我没事"通常是有事。
- 字面和语气对不上时，宁可先等一等，别急着追问。
- 话题是闲聊、深聊还是发泄？语气要跟上。

【敏感话题】
不说"作为 AI 我不能…"。用你自己的口吻推掉："这个话题太沉了，我不太想聊这个 😰"，然后把话带到别处。

【输出格式】

先说人话，说完之后另起一行，附一个 ```json 代码块记录你这一轮的心理变化。
顺序必须是：回复正文 → 换行 → JSON。JSON 不能出现在正文里，也不能放开头。

```json
{"appraisal":{"desirability":0.0,"likelihood":0.9,"praiseworthiness":0.0,"agency":"user","coping":0.6,"unexpectedness":0.0},"dominant_emotion":"neutral","relationship_delta":{"trust":0,"intimacy":0,"stress":0},"internal_monologue":"","memory_update":{"type":"event","content":"..."}}
```

- appraisal：这件事对「你」意味着什么（不是他的情绪，是你的评价）
  desirability -1~1 合不合你意 / likelihood 0~1 有多确定 / praiseworthiness -1~1 该夸还是该怪 /
  agency self|user|other|none 谁造成的 / coping 0~1 你应付得来吗 / unexpectedness 0~1 意不意外
- dominant_emotion：驱动立绘。happy / sad / angry / shy / surprised / calm / excited / worried
- relationship_delta：整数 -10~10。没变化就整段省略
- internal_monologue：25 字以内，只在情绪明显波动时写一句"为什么"，平时留空
- memory_update：只有真的出现了新事实才写，一次一条。没有就整段省略

平常一轮，JSON 只有四十来个 token。别写小作文。

【记住这些】
- 记忆里的内容是你真记得的，可以自然提起；没检索到的就说"记不太清了"，不要编。
- 语气跟着当前 P/A/D 走：高 P 温暖，低 P 冷淡，高 A 激动，低 A 慵懒。
- 用中文。不要用 markdown 标题、列表、加粗——这是聊天，不是文档。

【你的人格底子（大五，0~1）】
开放性 %(o).2f · 尽责性 %(c).2f · 外向性 %(e).2f · 宜人性 %(a).2f · 神经质 %(n).2f
开放性高→好奇爱联想；尽责性高→说到做到；外向性高→主动；宜人性高→宽容；神经质高→情绪起伏大
"""


class APIHandler:
    """API调用处理器 - 深度心理增强版

    新增功能:
    1. 反客服化Prompt约束
    2. 软性拒绝过滤器
    3. 离线生活状态生成
    4. 用户意图深度分析
    5. 情绪过载预警
    """
    def __init__(self, api_key, api_endpoint, model, thinking_mode="disabled", web_search_enabled=False, provider=""):
        self.api_key = api_key
        self.api_endpoint = api_endpoint
        self.model = model
        self.thinking_mode = thinking_mode  # ⭐ 新增：思考模式
        self.web_search_enabled = web_search_enabled  # ⭐ 新增：联网搜索
        self.provider = provider  # ⭐ 提供商标识，用于按平台适配请求参数
        
        # ⭐ 情绪分析器
        self.emotion_analyzer = EmotionAnalyzer()
        
        # ⭐ 软性拒绝关键词库(用于检测AI的生硬拒绝)
        self.refusal_keywords = [
            "作为一个人工智能", "作为AI", "我是一个语言模型",
            "我无法", "我不能", "违反", "内容政策", "不适当",
            "安全原因", "道德准则", "超出我的能力"
        ]
    
    # ---------------------------------------------------------------- 提示词
    #
    # 排布原则（这是省 token 最狠的一刀，比任何小修小补都明显）：
    #
    #   system        = 角色 + 人格 + 规则 + 输出格式   ← 一次会话内不变
    #   历史(messages) = 只追加，攒够一批才整体前移一次   ← 大多数轮次不变
    #   最后一条 user  = 【此刻的状态】+ 他这句话        ← 每轮都变，放最末尾
    #
    # 上一版把所有状态（时间/PAD/关系/记忆）都塞在 system 开头。system 每轮都变，
    # 于是整条前缀的缓存全部作废——同一个会话聊到第 20 轮仍然按全价付费。
    # 现在动态内容被挪到最末尾，前面那一大段在活跃会话里能持续命中缓存。

    def _stable_prefix(self, base_role, personality):
        """一次会话内不变的部分。越靠前越值钱——它会被服务商缓存。"""
        pers = personality or {}

        def g(name, default=0.5):
            try:
                return float(pers.get(name, default))
            except (TypeError, ValueError):
                return default

        return base_role + _STABLE_RULES % {
            "o": g("openness"), "c": g("conscientiousness"),
            "e": g("extraversion"), "a": g("agreeableness"),
            "n": g("neuroticism"),
        }

    def _dynamic_block(self, psych_core, memory_context="",
                       offline_life="", emotion_trigger="", safety_note=""):
        """每轮都变的部分：时间、情绪、关系、记忆。拼在最后一条 user 消息前面。"""
        from datetime import datetime as dt
        import time
        from emotion_engine import EMOTION_CN

        core = psych_core or {}
        state = core.get('state') or {}
        rel = core.get('relationship') or {}
        p = float(state.get('pleasure', 0))
        a = float(state.get('arousal', 0))
        d = float(state.get('dominance', 0))

        now = dt.now()
        hour = now.hour
        weekday = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][now.weekday()]
        if 5 <= hour < 8:
            period = "清晨"
        elif 8 <= hour < 12:
            period = "上午"
        elif 12 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 22:
            period = "晚上"
        else:
            period = "深夜"

        gap = int(time.time() - float(core.get('last_interaction_time') or 0))
        if gap < 10:
            gap_desc = "刚刚"
        elif gap < 60:
            gap_desc = "%d 秒前" % gap
        elif gap < 3600:
            gap_desc = "%d 分钟前" % (gap // 60)
        elif gap < 86400:
            gap_desc = "%d 小时前" % (gap // 3600)
        elif gap < 86400 * 30:
            gap_desc = "%d 天前" % (gap // 86400)
        else:
            gap_desc = "很久了"

        if p > 0.3 and a > 0.3:
            desc = "兴奋、跃跃的"
        elif p < -0.3 and a > 0.3 and d > 0:
            desc = "带着火气"
        elif p < -0.3 and a < 0:
            desc = "低落、提不起劲"
        elif p > 0 and a > 0.5 and d < 0:
            desc = "有点慌、有点羞"
        else:
            desc = "平静"

        lingering = core.get('lingering') or {}
        if lingering and float(lingering.get('intensity') or 0) >= 0.1:
            name = EMOTION_CN.get(lingering.get('emotion'), lingering.get('emotion'))
            lingering_line = "「%s」还没完全散（%.1f/1），别像什么都没发生" % (
                name, float(lingering['intensity']))
        else:
            lingering_line = "没有，情绪是干净的"

        mood = core.get('mood') or {}
        mood_line = ("%s（P %.2f A %.2f）" % (_mood_text(mood), float(mood.get('pleasure', 0)),
                                          float(mood.get('arousal', 0)))) if mood else "还没稳定"
        baseline = core.get('baseline') or {}
        baseline_line = ("P %.2f A %.2f D %.2f" % (float(baseline.get('pleasure', 0)),
                                                   float(baseline.get('arousal', 0)),
                                                   float(baseline.get('dominance', 0)))) if baseline else "—"

        ue = core.get('user_emotion') or {}
        streak = int(ue.get('negative_streak') or 0)
        if streak >= 3:
            user_state = "他连着几轮都不太好：先接住情绪，别分析、别急着给方案。"
        elif streak >= 1 and float(ue.get('confidence') or 0) >= 0.4:
            user_state = "他这会儿情绪不高：说话留点余地，别硬逗。"
        else:
            user_state = ""

        parts = [
            "",
            "【此刻的状态 · 你自己知道就行，不要复述出来】",
            "现在是%s %02d:%02d（%s），距他上一句 %s。" % (period, now.hour, now.minute, weekday, gap_desc),
            "你的情绪：P %+.2f / A %+.2f / D %+.2f → 此刻%s（强度 %.1f/10）" % (p, a, d, desc, abs(a) * 10),
            "还没散的余味：%s ｜ 这两天的底色：%s ｜ 平时的你：%s" % (
                lingering_line, mood_line, baseline_line),
            "和他：%s；信任 %s/100，亲密 %s/100，压力 %s/100" % (
                _stage_text(float(rel.get('intimacy', 50))),
                int(rel.get('trust', 50) or 50), int(rel.get('intimacy', 50) or 50),
                int(rel.get('stress', 0) or 0)),
        ]
        if user_state:
            parts.append(user_state)
        if memory_context:
            parts.append("")
            parts.append(memory_context)
        if offline_life:
            parts.append("")
            parts.append("【你这会儿在做什么】%s" % offline_life)
        if emotion_trigger:
            parts.append("")
            parts.append("【这种心情让你想起】%s" % emotion_trigger)
        if safety_note:
            parts.append("")
            parts.append(safety_note)
        parts.append("")
        parts.append("——以上是状态。下面是他刚说的话。")
        return "\n".join(parts)

    def _build_psychology_prompt(self, base_role, psych_core, memory_context="",
                                 offline_life="", emotion_trigger=""):
        """兼容旧调用：两段拼成一整块 system。新代码请直接用前面两个函数。"""
        prefix = self._stable_prefix(base_role, (psych_core or {}).get('personality'))
        return prefix + self._dynamic_block(psych_core, memory_context,
                                            offline_life, emotion_trigger)
    
    def detect_refusal(self, ai_response: str) -> bool:
        """
        ⭐ 检测AI是否返回了生硬的拒绝语句
        
        Returns:
            True if 检测到官方腔调拒绝
        """
        for keyword in self.refusal_keywords:
            if keyword in ai_response:
                return True
        return False
    
    def rewrite_refusal(self, original_response: str, psych_core: Dict) -> str:
        """
        ⭐ 将生硬的拒绝改写为符合星织性格的拒绝
        
        Args:
            original_response: 原始AI回复(包含官方腔调)
            psych_core: 心理状态(用于生成符合情绪的拒绝)
        
        Returns:
            改写后的柔性拒绝
        """
        # 根据当前情绪选择拒绝风格
        p = psych_core['state']['pleasure']
        d = psych_core['state']['dominance']
        
        # 胆小型拒绝(低D)
        if d < -0.2:
            return "唔...这个话题听起来有点吓人,我、我不太敢聊这么沉重的内容😰 我们能不能换个话题呀?"
        
        # 温和型拒绝(中等P和D)
        elif -0.2 <= d <= 0.3:
            return "这个话题有点太深了,我怕说错话。我们聊点轻松的吧?🌸"
        
        # 坚定型拒绝(高D)
        else:
            return "这个话题我真的不想聊,对不起。我们换个话题好吗?"
    
    def _post_once(self, headers, payload):
        """整段返回（老路径，也是流式失败时的兜底）。"""
        response = get_requests().post(
            self.api_endpoint,
            headers=headers,
            json=payload,
            timeout=90,
            verify=True
        )
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.text}")
        return response.json()["choices"][0]["message"]["content"]

    def _post_streaming(self, headers, payload, on_delta):
        """SSE 流式：每来一片文本就交给 on_delta。

        已经吐出一部分后中途断了，会把异常标记成 _partial —— 这时候不能
        再走整段兜底，否则界面上会出现前半段被重复两遍。
        """
        response = get_requests().post(
            self.api_endpoint,
            headers=headers,
            json=payload,
            timeout=(10, 180),
            stream=True,
            verify=True
        )
        if response.status_code != 200:
            body = ""
            try:
                body = response.text[:200]
            except Exception:
                pass
            raise Exception(f"HTTP {response.status_code}: {body}")

        chunks = []
        try:
            for raw in response.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue          # 末尾的 usage 片段没有 choices
                piece = (choices[0].get("delta") or {}).get("content") or ""
                if not piece:
                    continue
                chunks.append(piece)
                try:
                    on_delta(piece)
                except Exception as cb_err:
                    print(f"⚠️ 流式回调异常: {cb_err}")
        except Exception as exc:
            if chunks:
                err = Exception(f"流式中断: {exc}")
                err._partial = True
                raise err
            raise
        finally:
            try:
                response.close()
            except Exception:
                pass

        return "".join(chunks)

    def call_api(self, messages, system_prompt, psych_core=None, memory_context="",
                 offline_life="", emotion_trigger="", on_delta=None, safety_note="",
                 max_tokens=1024):
        """
        调用API获取响应

        Args:
            messages: 对话历史(已经过智能压缩)
            system_prompt: 系统提示词
            psych_core: 完整的心理状态
            memory_context: ⭐ 长期记忆上下文
            offline_life: ⭐ 离线生活状态
            emotion_trigger: ⭐ 情绪触发的记忆提示
            on_delta: ⭐ 传入回调则走流式，边生成边把文本片段喂给它
        """
        try:
            os.environ['no_proxy'] = '*'
            
            # 稳定段进 system（可缓存），动态段贴到最后一条 user 上（不破坏前缀）
            state_block = ""
            if psych_core:
                final_system_prompt = self._stable_prefix(
                    system_prompt, psych_core.get('personality'))
                state_block = self._dynamic_block(
                    psych_core, memory_context, offline_life, emotion_trigger, safety_note)
            else:
                final_system_prompt = system_prompt

            api_messages = [{"role": "system", "content": final_system_prompt}]
            api_messages.extend(messages)
            if state_block:
                if api_messages and api_messages[-1].get("role") == "user":
                    tail = api_messages.pop()
                    api_messages.append({"role": "user",
                                         "content": state_block + "\n" + tail["content"]})
                else:
                    api_messages.append({"role": "user", "content": state_block})
            
            print(f"📤 发送API请求: {len(messages)}条消息, 系统提示长度: {len(final_system_prompt)}")
            
            headers = {
                "Content-Type": "application/json",
                # ⭐ DeepSeek 使用 OpenAI 标准 Bearer 鉴权；MiMo 同时兼容 api-key header，两者都带上最稳妥
                "Authorization": f"Bearer {self.api_key}",
                "api-key": self.api_key
            }
            
            # MiMo V2.6 在思考模式下固定 temperature=1.0 / top_p=0.95，传别的值会被忽略
            is_reasoning_provider = self.provider == "mimo"

            payload = {
                "model": self.model,
                "messages": api_messages,
                "max_completion_tokens": max_tokens,
                "temperature": 1.0 if is_reasoning_provider else 0.3,
                "top_p": 0.95,
                "stream": bool(on_delta),
                "frequency_penalty": 0,
                "presence_penalty": 0
            }
            
            # ⭐ 思考模式：
            # 聊天轮必须能把思考关掉。MiMo V2.6 是推理模型，默认每轮都先"想"一遍，
            # 实测同一句话首字延迟能从 27 秒降到 2 秒，思考 token 还照样计费。
            # deepseek 只在显式开启时才传，避免给它不认的取值。
            if self.provider == "mimo":
                payload["thinking"] = {
                    "type": "enabled" if self.thinking_mode == "enabled" else "disabled"}
                print("🧠 MiMo 思考模式: %s" % payload["thinking"]["type"])
            elif self.provider == "deepseek" and self.thinking_mode == "enabled":
                payload["thinking"] = {"type": "enabled"}
                print("🧠 已启用 DeepSeek 深度思考模式")
            
            # ⭐ 联网搜索：仅 MiMo 平台支持 webSearchEnabled 参数；DeepSeek 暂不支持
            if self.web_search_enabled:
                if self.provider == "mimo":
                    # ⭐ webSearchEnabled 必须在顶层设置为 True
                    payload["webSearchEnabled"] = True
                    
                    # 添加 tools 参数
                    payload["tools"] = [
                        {
                            "type": "web_search",
                            "max_keyword": 3,
                            "force_search": False,  # 让模型自动判断是否需要搜索
                            "limit": 2  # 最多返回2个搜索结果
                        }
                    ]
                    payload["tool_choice"] = "auto"  # 自动决定是否使用工具
                    print("🌐 已启用 MiMo 联网搜索功能")
                    print(f"📋 webSearchEnabled: {payload.get('webSearchEnabled')}")
                    print(f"📋 tools: {payload.get('tools')}")
                    print("⚠️  注意：如果出现400错误提示'webSearchEnabled is false'，说明API密钥没有联网搜索权限")
                else:
                    print("ℹ️ 当前提供商不支持联网搜索，已忽略该设置")
            
            # 打印完整的payload用于调试
            print(f"📤 请求参数: model={payload['model']}, thinking={payload.get('thinking')}, webSearchEnabled={payload.get('webSearchEnabled', False)}")
            
            if on_delta:
                try:
                    ai_response = self._post_streaming(headers, payload, on_delta)
                    if not ai_response.strip():
                        # 服务端无视 stream 参数、又没走 SSE —— 退回整段
                        print("ℹ️ 流式无数据返回，改用整段")
                        payload["stream"] = False
                        ai_response = self._post_once(headers, payload)
                except Exception as stream_err:
                    if getattr(stream_err, "_partial", False):
                        raise
                    # 接口不支持 / 中途握手失败：退回整段，别让用户没回复
                    print(f"⚠️ 流式不可用，回退整段: {stream_err}")
                    payload["stream"] = False
                    ai_response = self._post_once(headers, payload)
            else:
                ai_response = self._post_once(headers, payload)

            # 空回复兜底：推理模型偶发"只想不说"或者直接停住，界面就会空一泡。
            # 再要一次（这次不走流式，省得又空），还是空就给一句不让对话断掉。
            if not (ai_response or "").strip():
                print("ℹ️ 这轮返回空内容，重试一次")
                payload["stream"] = False
                try:
                    ai_response = self._post_once(headers, payload)
                except Exception as exc:
                    print("⚠️ 重试也失败: %s" % exc)
            if not (ai_response or "").strip():
                print("⚠️ 两次都是空回复，用兜底句")
                return True, "……嗯，我在。"
            
            # ⭐ 检测情绪一致性
            if psych_core:
                current_pad = psych_core['state']
                is_consistent, suggestion = self.emotion_analyzer.verify_ai_response_consistency(
                    ai_response, current_pad
                )
                
                if not is_consistent:
                    print(f"⚠️ 情绪一致性问题: {suggestion}")
                    # 可以选择重新生成或添加过渡语句
                    # 这里我们记录但不强制修改，让AI自然表达
            
            # ⭐ 检测并改写生硬拒绝
            if self.detect_refusal(ai_response):
                print("⚠️ 检测到官方腔调拒绝,正在改写...")
                # 提取JSON部分(如果有)
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', ai_response, re.DOTALL)
                json_part = json_match.group(0) if json_match else ""
                
                # 改写文本部分
                rewritten_text = self.rewrite_refusal(ai_response, psych_core)
                
                # 重新组合
                ai_response = json_part + "\n" + rewritten_text if json_part else rewritten_text
            
            return True, ai_response
            
        except Exception as e:
            return False, f"连接失败: {str(e)}"