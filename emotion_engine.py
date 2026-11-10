# -*- coding: utf-8 -*-
"""情绪引擎：OCC 评价 → 情绪强度 → PAD → 向基线回归。

以前的链路是模型直接吐一个 `pad_delta`，好处是简单，坏处是：

- 说不清她为什么高兴（没有"评价"这一层，只有结果）；
- 同一句话两次可能给出差很远的增量；
- 状态只加不减，聊久了会飘到极值出不来。

现在换成心理学里常用的那条路：

    事件 → 评价（合意 / 该当 / 可能性 / 谁造成的）→ 若干情绪同时被唤起
         → 每种情绪有自己的 PAD 指向 → 加权合成 ΔPAD → 向人格基线回落

好处是每一步都能查：`appraise()` 能告诉你这一轮激起的是 joy 0.4 + gratitude 0.3，
`fold()` 能告诉你为什么 pleasure 涨了 0.18。模型偶尔乱报，也会被关键词通道压回去。
"""
import math

__all__ = ["EmotionEngine", "EMOTION_PAD", "EMOTION_CN"]

#: 给提示词用的中文情绪名
EMOTION_CN = {
    "joy": "高兴", "distress": "难受", "hope": "期待", "fear": "不安",
    "satisfaction": "满足", "disappointment": "失落", "pride": "得意",
    "shame": "不好意思", "gratitude": "感激", "anger": "生气",
    "liking": "亲近", "disliking": "反感", "surprise": "意外",
    "relief": "松了口气",
}

#: OCC 情绪 → PAD 指向（P 愉悦 / A 唤醒 / D 掌控）
EMOTION_PAD = {
    "joy":          (0.75, 0.45, 0.15),
    "distress":     (-0.65, 0.25, -0.25),
    "hope":         (0.35, 0.35, 0.05),
    "fear":         (-0.50, 0.55, -0.40),
    "satisfaction": (0.55, 0.10, 0.30),
    "disappointment": (-0.50, -0.10, -0.20),
    "pride":        (0.65, 0.30, 0.50),
    "shame":        (-0.55, 0.20, -0.45),
    "gratitude":    (0.60, 0.25, -0.05),
    "anger":        (-0.60, 0.60, 0.50),
    "liking":       (0.50, 0.15, 0.00),
    "disliking":    (-0.40, 0.10, 0.10),
    "surprise":     (0.05, 0.75, -0.10),
    "relief":       (0.45, -0.30, 0.20),
}

#: 关键词通道的情绪名 → OCC 情绪名
_KEYWORD_MAP = {
    "joy": "joy", "sadness": "distress", "anger": "anger", "fear": "fear",
    "surprise": "surprise", "disgust": "disliking", "trust": "liking",
    "anticipation": "hope",
}

#: 三个维度的"回血"速度（每轮向她自己的基线靠拢的比例）
_RELAX_PER_TURN = {"pleasure": 0.10, "arousal": 0.16, "dominance": 0.08}

#: 隔了多久之后按半衰期回落（小时）
_HALF_LIFE_HOURS = {"pleasure": 8.0, "arousal": 3.0, "dominance": 14.0}


class EmotionEngine:
    """无状态的情绪计算器：状态本身存在 psych_core 里，这里只负责怎么变。"""

    # ---------------------------------------------------------------- 基线

    @staticmethod
    def baseline_from_personality(personality):
        """人格决定她"平时是什么心情"，而不是永远从 0 开始。"""
        o = float(personality.get("openness", 0.5))
        c = float(personality.get("conscientiousness", 0.5))
        e = float(personality.get("extraversion", 0.5))
        a = float(personality.get("agreeableness", 0.5))
        n = float(personality.get("neuroticism", 0.5))

        p = 0.20 + 0.30 * e + 0.20 * a - 0.25 * n
        ar = 0.10 + 0.25 * e - 0.15 * c
        d = 0.10 + 0.25 * e + 0.15 * c - 0.20 * n

        return {
            "pleasure": max(-0.2, min(0.6, p)),
            "arousal": max(-0.1, min(0.4, ar)),
            "dominance": max(-0.2, min(0.5, d)),
        }

    # ---------------------------------------------------------------- 评价

    @staticmethod
    def appraise(appraisal, user_text="", analyzer_result=None):
        """把一次评价拆成"被唤起了哪几种情绪、各多强"。

        appraisal 是模型给的结构化变量；缺字段时按中性处理，
        所以模型偶尔漏写也不会崩。
        """
        ap = appraisal or {}
        desirability = _clamp(ap.get("desirability", 0.0), -1, 1)
        likelihood = _clamp(ap.get("likelihood", 0.7), 0, 1)
        praiseworthy = _clamp(ap.get("praiseworthiness", 0.0), -1, 1)
        coping = _clamp(ap.get("coping", 0.5), 0, 1)
        unexpected = _clamp(ap.get("unexpectedness", 0.0), 0, 1)
        agency = str(ap.get("agency", "none")).lower()

        emotions = {}

        def raise_(name, value):
            if value > 0.02:
                emotions[name] = emotions.get(name, 0.0) + value

        raise_("joy", max(0.0, desirability) * likelihood * 0.95)
        raise_("distress", max(0.0, -desirability) * likelihood * 0.95)
        raise_("hope", max(0.0, desirability) * (1 - likelihood) * 0.55)
        raise_("fear", max(0.0, -desirability) * (1 - likelihood) * 0.65)
        raise_("surprise", unexpected * 0.45)

        if agency == "self":
            raise_("pride", max(0.0, praiseworthy) * 0.55)
            raise_("shame", max(0.0, -praiseworthy) * 0.60)
        elif agency == "user":
            raise_("gratitude", max(0.0, praiseworthy) * 0.55)
            raise_("anger", max(0.0, -praiseworthy) * 0.65)
        elif agency in ("other", "someone"):
            raise_("liking", max(0.0, praiseworthy) * 0.35)
            raise_("disliking", max(0.0, -praiseworthy) * 0.40)

        # 有把握应对的事，落地成满足感；没把握的，悬着
        if desirability > 0.2 and coping > 0.7:
            raise_("satisfaction", (desirability - 0.2) * coping * 0.45)
        if desirability < -0.2 and coping < 0.3:
            raise_("fear", abs(desirability) * 0.25)

        # 关键词通道兜底：模型没给评价、或给得太平，用文本本身的读数补一点
        if not emotions and analyzer_result:
            pred = analyzer_result.get("pad_prediction") or {}
            confidence = float(analyzer_result.get("confidence") or 0)
            if confidence >= 0.3:
                p = _clamp(pred.get("p", 0), -1, 1)
                if abs(p) > 0.15:
                    raise_("joy" if p > 0 else "distress", min(0.5, abs(p) * confidence))

        return emotions

    @staticmethod
    def fold(emotions, personality):
        """若干情绪 → PAD 增量。强情绪按人格放大，但总量设上限，避免一跳到底。"""
        if not emotions:
            return {"p": 0.0, "a": 0.0, "d": 0.0}

        n = float(personality.get("neuroticism", 0.5))
        e = float(personality.get("extraversion", 0.5))

        total = 0.0
        acc = {"p": 0.0, "a": 0.0, "d": 0.0}
        for name, intensity in emotions.items():
            sig = EMOTION_PAD.get(name)
            if not sig:
                continue
            if sig[0] < 0:                       # 负面情绪受神经质放大
                intensity *= 0.75 + 0.5 * n
            else:                                # 正面情绪受外向性放大
                intensity *= 0.80 + 0.4 * e
            acc["p"] += sig[0] * intensity
            acc["a"] += sig[1] * intensity
            acc["d"] += sig[2] * intensity
            total += intensity

        if total <= 0:
            return {"p": 0.0, "a": 0.0, "d": 0.0}

        # 除以 sqrt(total) 而不是 total：一个人同时被三种情绪打到，不该被平均成平淡
        norm = math.sqrt(max(1.0, total))
        scale = 0.42
        return {
            "p": _clamp(acc["p"] / norm * scale, -0.45, 0.45),
            "a": _clamp(acc["a"] / norm * scale, -0.45, 0.45),
            "d": _clamp(acc["d"] / norm * scale, -0.45, 0.45),
        }

    # ---------------------------------------------------------------- 状态

    def update(self, core, appraisal=None, user_text="", analyzer_result=None,
               explicit_delta=None, now_ts=None):
        """一轮对话之后更新 PAD；返回这一轮的诊断信息（给日志和提示词用）。"""
        state = core.setdefault("state", {"pleasure": 0.0, "arousal": 0.0,
                                          "dominance": 0.0, "energy": 60})
        personality = core.get("personality") or {}
        baseline = self.baseline_from_personality(personality)

        emotions = self.appraise(appraisal, user_text, analyzer_result)
        delta = self.fold(emotions, personality)

        # 模型如果还是给了 pad_delta（老格式），按 0.4 的权重并进来
        if explicit_delta:
            for key, field in (("p", "pleasure"), ("a", "arousal"), ("d", "dominance")):
                delta[key] = _clamp(delta[key] + float(explicit_delta.get(key, 0)) * 0.4,
                                    -0.5, 0.5)

        # 交叉校验：文本明显消极、模型却说很开心 → 把正向压回去一半
        contradicted = False
        if analyzer_result:
            pred = analyzer_result.get("pad_prediction") or {}
            confidence = float(analyzer_result.get("confidence") or 0)
            text_p = float(pred.get("p", 0))
            if confidence >= 0.45 and text_p < -0.25 and delta["p"] > 0.12:
                delta["p"] *= 0.45
                delta["a"] = max(delta["a"], 0.05)
                contradicted = True
            elif confidence >= 0.45 and text_p > 0.25 and delta["p"] < -0.12:
                delta["p"] *= 0.55
                contradicted = True

        for key, field in (("p", "pleasure"), ("a", "arousal"), ("d", "dominance")):
            state[field] = _clamp(float(state.get(field, 0)) + delta[key], -1.0, 1.0)

        # 向她自己的基线回落：强情绪回得慢一点，像人一样"缓一缓"
        for field in ("pleasure", "arousal", "dominance"):
            relax = _RELAX_PER_TURN[field]
            intensity = abs(float(state.get(field, 0)) - baseline[field])
            relax *= max(0.35, 1.0 - intensity * 0.5)
            state[field] = baseline[field] + (float(state[field]) - baseline[field]) * (1 - relax)

        # 未消化完的情绪：留着给下一轮的语气做"余味"
        lingering = core.get("lingering") or {}
        if lingering:
            left = float(lingering.get("intensity", 0)) * 0.55
            if left < 0.08:
                lingering = {}
            else:
                lingering["intensity"] = left
        if emotions:
            top, top_i = max(emotions.items(), key=lambda kv: kv[1])
            if top_i >= 0.45 and (not lingering or top_i * 0.8 > lingering.get("intensity", 0)):
                lingering = {"emotion": top, "intensity": round(top_i * 0.8, 2)}
        core["lingering"] = lingering
        core["baseline"] = {k: round(v, 3) for k, v in baseline.items()}
        core["mood"] = self._tick_mood(core.get("mood"), state, baseline, now_ts)

        return {
            "emotions": {k: round(v, 2) for k, v in emotions.items()},
            "delta": {k: round(v, 3) for k, v in delta.items()},
            "state": {k: round(float(state.get(k, 0)), 3) for k in
                      ("pleasure", "arousal", "dominance")},
            "baseline": core["baseline"],
            "contradicted": contradicted,
            "lingering": lingering,
        }

    # ---------------------------------------------------------------- 心情
    #
    # 三层时间尺度：emotion（这一轮，秒~分）/ mood（这一两天，小时~天）/
    # personality baseline（她本来是谁，基本不变）。
    # emotion 已经由 update() 算好；这里把它低通滤成 mood，并让 mood 随时间
    # 自己往基线回落——所以"昨天吵完架，今天还有点闷"是自然发生的。

    MOOD_FOLLOW = 0.22        # 每轮向当前情绪靠多少
    MOOD_HALF_LIFE_H = 18.0   # 没有对话时，心情回落到基线的半衰期

    def _tick_mood(self, mood, state, baseline, now_ts=None):
        from datetime import datetime

        mood = dict(mood or {})
        p = float(mood.get("pleasure", baseline["pleasure"]))
        a = float(mood.get("arousal", baseline["arousal"]))
        d = float(mood.get("dominance", baseline["dominance"]))

        now = datetime.fromtimestamp(now_ts) if now_ts else datetime.now()

        # 1) 隔了多久 → 先往基线退一截
        stamp = mood.get("updated_at")
        hours = 0.0
        if stamp:
            try:
                hours = (now - datetime.strptime(str(stamp)[:16],
                                                 "%Y-%m-%d %H:%M")).total_seconds() / 3600.0
            except Exception:
                hours = 0.0
        if hours > 0.2:
            k = 1.0 - math.exp(-hours / self.MOOD_HALF_LIFE_H)
            p += (baseline["pleasure"] - p) * k
            a += (baseline["arousal"] - a) * k
            d += (baseline["dominance"] - d) * k

        # 2) 再叠这一轮的情绪（低通：单句不会把整天带跑）
        p += (float(state.get("pleasure", 0)) - p) * self.MOOD_FOLLOW
        a += (float(state.get("arousal", 0)) - a) * self.MOOD_FOLLOW
        d += (float(state.get("dominance", 0)) - d) * self.MOOD_FOLLOW

        return {
            "pleasure": round(_clamp(p, -1, 1), 3),
            "arousal": round(_clamp(a, -1, 1), 3),
            "dominance": round(_clamp(d, -1, 1), 3),
            "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        }

    # ---------------------------------------------------------------- 关系

    def update_relationship(self, core, deltas):
        """信任/亲密/压力：慢变量，涨得慢、掉得也慢。"""
        rel = core.setdefault("relationship", {"trust": 50, "intimacy": 50, "stress": 0})
        if not deltas:
            return rel

        for field, cap in (("trust", 3), ("intimacy", 3), ("stress", 5)):
            step = float(deltas.get(field, 0) or 0)
            step = max(-cap, min(cap, step))
            if field == "stress":
                rel[field] = _clamp(rel.get(field, 0) + step, 0, 100)
            else:
                # 越往上越难涨：80 分之后每点的效果打六折
                current = float(rel.get(field, 50))
                if step > 0 and current > 60:
                    step *= max(0.4, 1.0 - (current - 60) / 100.0)
                rel[field] = _clamp(current + step, 0, 100)

        return rel

    # ---------------------------------------------------------------- 时间

    def relax_by_time(self, core, hours):
        """隔了一段时间没聊，情绪自然淡下去（按半衰期，且回到基线而不是 0）。"""
        if hours is None or hours <= 0:
            return None
        state = core.get("state") or {}
        baseline = self.baseline_from_personality(core.get("personality") or {})

        changed = False
        for field in ("pleasure", "arousal", "dominance"):
            half = _HALF_LIFE_HOURS[field]
            factor = 0.5 ** (hours / half)
            old = float(state.get(field, 0))
            new = baseline[field] + (old - baseline[field]) * factor
            if abs(new - old) > 0.005:
                changed = True
            state[field] = round(new, 4)

        rel = core.setdefault("relationship", {"trust": 50, "intimacy": 50, "stress": 0})
        stress = float(rel.get("stress", 0))
        if stress > 0:
            rel["stress"] = round(stress * (0.5 ** (hours / 2.0)), 2)

        core["state"] = state
        core["baseline"] = {k: round(v, 3) for k, v in baseline.items()}

        # 心情也随时间回落（它本来就该比情绪慢）
        mood = core.get("mood")
        if mood:
            core["mood"] = self.decay_mood(mood, baseline, hours)

        return changed

    def decay_mood(self, mood, baseline, hours):
        """心情按半衰期往基线退——没聊的这些小时里，她自己也会缓过来。"""
        mood = dict(mood or {})
        if hours is None or hours <= 0:
            return mood
        k = 1.0 - math.exp(-float(hours) / self.MOOD_HALF_LIFE_H)
        for field in ("pleasure", "arousal", "dominance"):
            cur = float(mood.get(field, baseline[field]))
            mood[field] = round(_clamp(cur + (baseline[field] - cur) * k, -1, 1), 3)
        return mood

    # ---------------------------------------------------------------- 描述

    @staticmethod
    def describe(state):
        """给提示词和日志用的一句中文描述。"""
        p = float(state.get("pleasure", 0))
        a = float(state.get("arousal", 0))
        d = float(state.get("dominance", 0))

        if p > 0.35 and a > 0.25:
            mood = "兴致很高，说话会带点跳跃"
        elif p > 0.25 and a <= 0.25:
            mood = "心情松快，语调是暖的"
        elif p < -0.35 and a > 0.25:
            mood = "有点绷紧，可能带着火气"
        elif p < -0.3 and a < -0.1:
            mood = "情绪低，话会变少"
        elif a > 0.5:
            mood = "心跳有点快，容易惊讶"
        else:
            mood = "平静，注意力在你身上"

        tail = ""
        if d < -0.2:
            tail = "，气势上偏软，不太会反驳你"
        elif d > 0.35:
            tail = "，语气会更笃定一点"
        return mood + tail


def _clamp(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, value))
