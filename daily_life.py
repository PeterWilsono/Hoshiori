# -*- coding: utf-8 -*-
"""她自己的日子。

以前这块是 `autonomous_system.OfflineActivitySimulator`：从三条写死的模板里
随机挑一句"看到一条关于{topic}的新闻"。问题不在假，在于**空**——她说"我刚在
看书"，你问"看什么书"她就露馅了。

这里改成真的记一天：
- 一天一行，`entries` 是这一天里「几点在做什么」的流水；
- 一天分几次写（初次 3~5 条，之后每次补 1~2 条），所以她上午和晚上说的不一样；
- 写的时候带上她的角色设定和你说过的事，所以她过的日子跟"她是谁""你是谁"有关；
- 她说"我刚泡了茶"时，库里真的有这一条 14:05 的记录。

没有 API / 没有网的时候不硬编，退回一份本地素材（source='local'），
注入提示词时也照用——这类"把碗洗了""风把窗帘吹起来"的细节不需要大模型。

所有写入都在后台线程里做，不挡回复。
"""
import json
import os
import random
import re
import threading
from datetime import datetime, timedelta

import db

__all__ = ["DailyLife", "period_of", "period_hint"]

#: 一天最多写几次。再多就是拿 token 换热闹了。
MAX_GEN_PER_DAY = 4
#: 两次续写之间至少隔多久（小时）
MIN_GAP_HOURS = 3.5

#: 本地兜底素材：短、具体、不需要上下文也成立
_LOCAL_BITS = (
    ("把杯子洗了，桌面擦了一遍", ""),
    ("翻了两页书，没看进去", "有点走神"),
    ("泡了杯茶，等它凉", ""),
    ("窗帘被风吹得鼓起来，看了一会儿", ""),
    ("把歌单换成以前常听的那几张", ""),
    ("在窗边站了一会儿，外面没什么人", ""),
    ("把昨天没收拾的东西归了位", ""),
    ("写了几行字，又删掉了", "算了"),
    ("煮了碗面，加了个蛋", ""),
    ("把灯关了又打开，觉得太安静", ""),
)


def period_of(dt=None):
    """时段。前端 sessionLabel 用的是同一套说法，别各说各的。"""
    h = (dt or datetime.now()).hour
    if h < 5:
        return "凌晨"
    if h < 11:
        return "上午"
    if h < 14:
        return "午后"
    if h < 18:
        return "黄昏"
    if h < 23:
        return "夜里"
    return "深夜"


def period_hint(dt=None):
    """给提示词用的一句话，带一点这个时段的生理感。"""
    p = period_of(dt)
    return {
        "凌晨": "已经很晚了，你有点困，但还醒着",
        "上午": "白天刚开始，你脑子还比较清醒",
        "午后": "刚过中午，人有点懒",
        "黄昏": "天在暗下来，这个时候你容易想事情",
        "夜里": "天黑了，房间里只有屏幕亮着",
        "深夜": "夜很深了，你说话会比白天轻",
    }.get(p, "")


def _extract_json(text):
    """从模型输出里挖 JSON 对象（不依赖 main 的那个，避免循环 import）。"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start = text.find("{")
    while start != -1:
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
                    try:
                        return json.loads(text[start:i + 1])
                    except Exception:
                        break
        start = text.find("{", start + 1)
    return None


class DailyLife:
    """一天的流水。读写都在这，调用方只管问「她现在在做什么」。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = db.init_db(db_path)
        self._generating = False
        self._mem = None            # 最近一次 today() 的缓存，省得每轮查库

    # ---------------------------------------------------------------- 读
    def _row(self, day=None):
        day = day or datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM daily_life WHERE day=?", (day,)).fetchone()

    def entries(self, day=None, upto_now=True):
        row = self._row(day)
        if row is None:
            return []
        try:
            items = json.loads(row["entries"] or "[]")
        except Exception:
            items = []
        if not isinstance(items, list):
            return []
        items = [e for e in items if isinstance(e, dict) and e.get("t")]
        if upto_now and (day is None or day == datetime.now().strftime("%Y-%m-%d")):
            now_hm = datetime.now().strftime("%H:%M")
            items = [e for e in items if str(e.get("t")) <= now_hm]
        return items

    def current(self):
        """给前端 / 提示词用的当前状态。"""
        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        row = self._row(day)
        items = self.entries(day)
        last = items[-1] if items else None

        now_text = ""
        if last:
            try:
                t = datetime.strptime("%s %s" % (day, last["t"]), "%Y-%m-%d %H:%M")
                gap_h = (now - t).total_seconds() / 3600.0
            except Exception:
                gap_h = 99
            if gap_h <= 2.5:
                now_text = last.get("a") or ""
        return {
            "day": day,
            "label": "%d月%d日 · %s" % (now.month, now.day, period_of(now)),
            "period": period_of(now),
            "weather": (row["weather"] if row else "") or "",
            "mood": (row["mood"] if row else "") or "",
            "now": now_text,
            "entries": [
                {"t": e.get("t", ""), "act": e.get("a", ""), "note": e.get("i", "")}
                for e in items
            ],
            "thought": (row["thought"] if row else "") or "",
            "empty": not bool(items),
        }

    def prompt_block(self):
        """拼进提示词的那一段。没有流水就返回空，别让她凭空编。"""
        cur = self.current()
        if cur["empty"]:
            return ""

        lines = ["【你今天】%s，%s" % (
            cur["label"], cur["weather"] or "天气说不上来")]
        if cur["mood"]:
            lines.append("今天的心情：%s" % cur["mood"])
        for e in cur["entries"][-6:]:
            line = "- %s %s" % (e["t"], e["act"])
            if e["note"]:
                line += "（%s）" % e["note"]
            lines.append(line)
        if cur["now"]:
            lines.append("现在你在：%s" % cur["now"])
        else:
            lines.append("现在你在：手边没什么事，刚好看到他的消息")
        lines.append("（他问起来就照实说，别一次倒完；他没问就不用主动交代。）")
        return "\n".join(lines)

    def take_thought(self):
        """取走"她今天想跟他说的一句话"。取过就作废，不能天天说同一句。"""
        row = self._row()
        if row is None or not row["thought"] or row["thought_used"]:
            return ""
        with self._lock:
            self._conn.execute(
                "UPDATE daily_life SET thought_used=1 WHERE day=?", (row["day"],))
            self._conn.commit()
        return row["thought"]

    def peek_thought(self):
        row = self._row()
        if row is None or not row["thought"] or row["thought_used"]:
            return ""
        return row["thought"]

    # ---------------------------------------------------------------- 写
    def _save(self, day, weather, mood, items, thought):
        now = db.now_str()
        with self._lock:
            row = self._row(day)
            if row is None:
                self._conn.execute(
                    "INSERT INTO daily_life(day, weather, mood, entries, thought,"
                    " thought_used, gen_count, gen_at, created_at)"
                    " VALUES(?,?,?,?,?,0,1,?,?)",
                    (day, weather, mood, json.dumps(items, ensure_ascii=False),
                     thought, now, now))
            else:
                try:
                    old = json.loads(row["entries"] or "[]")
                except Exception:
                    old = []
                merged = old + [e for e in items if e not in old]
                merged.sort(key=lambda e: str(e.get("t", "")))
                self._conn.execute(
                    "UPDATE daily_life SET weather=?, mood=?, entries=?, thought=?,"
                    " gen_count=gen_count+1, gen_at=? WHERE day=?",
                    (weather or row["weather"], mood or row["mood"],
                     json.dumps(merged, ensure_ascii=False),
                     thought or row["thought"], now, day))
            self._conn.commit()
        self._mem = self.current()

    def _local_fill(self, day):
        """没有模型时的兜底：两三条碎事，别装作是一整天。"""
        now = datetime.now()
        items = []
        n = random.randint(2, 3)
        for i in range(n):
            when = now - timedelta(minutes=random.randint(40, 200) * (n - i))
            act, note = random.choice(_LOCAL_BITS)
            items.append({"t": when.strftime("%H:%M"), "a": act, "i": note})
        self._save(day, "", "", items, "")

    def needs_refresh(self):
        """该不该补写一段：跨天了，或者距上次写已经够久。"""
        now = datetime.now()
        row = self._row()
        if row is None:
            return True
        if (row["gen_count"] or 0) >= MAX_GEN_PER_DAY:
            return False
        try:
            last = datetime.strptime(row["gen_at"], "%Y-%m-%d %H:%M")
        except Exception:
            return True
        return (now - last).total_seconds() >= MIN_GAP_HOURS * 3600

    def ensure_async(self, api_handler, role_prompt="", hints=None):
        """后台补写，不挡任何东西。重复调用只会跑一次。"""
        if self._generating or not self.needs_refresh():
            return
        self._generating = True

        def run():
            try:
                self.ensure(api_handler, role_prompt, hints)
            except Exception as exc:
                print("⚠️ 她的生活没写出来: %s" % exc)
            finally:
                self._generating = False

        threading.Thread(target=run, daemon=True).start()

    def ensure(self, api_handler, role_prompt="", hints=None):
        """同步补写一段。返回 True 表示真的写了新内容。"""
        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        row = self._row(day)
        done = self.entries(day) if row else []
        first_time = not done

        if api_handler is None:
            if first_time:
                self._local_fill(day)
                return True
            return False

        # 已经写到哪儿了：第一句从起床开始，之后接着最后一条写
        if done:
            span = "从 %s 到现在（%s）" % (done[-1]["t"], now.strftime("%H:%M"))
            count = "1 到 2 条"
        else:
            span = "从起床到现在（%s）" % now.strftime("%H:%M")
            count = "3 到 5 条"

        persona = (role_prompt or "").strip()
        if len(persona) > 700:
            persona = persona[:700] + "…"

        mem_lines = ""
        if hints:
            mem_lines = "\n你知道的关于他的事：\n" + "\n".join(
                "- %s" % h for h in hints[:6] if h)

        already = ""
        if done:
            already = "\n你已经写过的（别重复）：\n" + "\n".join(
                "- %s %s" % (e["t"], e["a"]) for e in done[-5:])

        prompt = (
            "现在是 %s %s（%s）。\n%s\n\n"
            "写你%s这几小时过的日子。\n"
            "写 %s。\n\n"
            "要求：\n"
            "1. 每条都要有具体的东西——在吃什么、手上在做什么、看到什么。"
            "不要写「思考人生」「整理思绪」这类空话。\n"
            "2. 至少有一条跟他有关：想起他说过的话、他去过的地方、他的某个习惯。\n"
            "   只能用上面「你知道的关于他的事」里列出的内容，**不许编他姓什么、住在哪、"
            "说过什么没列出来的话**。（如果他还没说过什么，这条省略，别硬凑。）\n"
            "3. 时间要顺着来，别倒回去。\n"
            "4. 用你自己的语气，不要写成日记范文。短句就行。\n"
            "5. 只输出 JSON，不要解释。\n\n"
            "格式：\n"
            '{"weather":"窗外什么样，一句话",'
            '"mood":"今天的心情，六个字内",'
            '"entries":[{"t":"09:10","a":"在做什么","i":"心里冒出的一句，可空"}],'
            '"thought":"今天想问他的话，20 字内，没有就空"}\n'
            "%s"
        ) % (
            now.strftime("%Y年%m月%d日"), period_of(now), period_hint(now),
            persona + mem_lines,
            span, count, already,
        )

        ok, raw = api_handler.call_api(
            [{"role": "user", "content": prompt}],
            "你在写一个人的日常流水。只输出 JSON。",
            max_tokens=460,
        )
        if not ok:
            if first_time:
                self._local_fill(day)
                return True
            return False

        data = _extract_json(raw)
        if not isinstance(data, dict):
            if first_time:
                self._local_fill(day)
                return True
            return False

        items = []
        for e in (data.get("entries") or [])[:6]:
            if not isinstance(e, dict):
                continue
            t = str(e.get("t") or "").strip()
            act = str(e.get("a") or e.get("act") or "").strip()
            if not act:
                continue
            m = re.match(r"^(\d{1,2})[:：.]?(\d{2})?", t)
            if m:
                t = "%02d:%s" % (int(m.group(1)), m.group(2) or "00")
            else:
                t = now.strftime("%H:%M")
            items.append({"t": t, "a": act[:60], "i": str(e.get("i") or "").strip()[:40]})

        if not items:
            if first_time:
                self._local_fill(day)
                return True
            return False

        self._save(day,
                   str(data.get("weather") or "")[:30],
                   str(data.get("mood") or "")[:16],
                   items,
                   str(data.get("thought") or "")[:40])
        print("🌤 她的今天 +%d 条：%s" % (len(items), " / ".join(i["a"][:12] for i in items)))
        return True


# ------------------------------------------------------------------ 单例
_instances = {}


def get(db_path):
    inst = _instances.get(db_path)
    if inst is None:
        inst = DailyLife(db_path)
        _instances[db_path] = inst
    return inst
