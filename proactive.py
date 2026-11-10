# -*- coding: utf-8 -*-
"""她会先开口。

以前这块是 `cognitive_system.MotivationSystem`：算出一个 0~1 的"想念值"，
超过阈值就往回复尾巴上追加一句模板。问题是它只在**你说话的时候**才跑，
所以永远是她回完话顺带补一句，不是真的"找你"。

这里换成一个真正的定时器：
- 每 40 秒看一次表，判断"现在该不该开口"；
- 该不该，由开关、静音时段、每日上限、距上次说话多久共同决定；
- 开口的由头有三个：她今天想说的话、上次没聊完的事、她自己琢磨的事；
- 话是现写的（一次小调用），不是模板。

默认关。会打扰人的功能不该替用户决定。
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta

import db

__all__ = ["ProactiveScheduler"]

#: 多久检查一次（秒）。太密没必要，主动消息的时间精度到分钟级就够了。
LOOP_SECONDS = 40
#: 距上次"用户说话"至少多久才可能开口
DEFAULT_GAP_HOURS = 6.0
#: 一天最多几条
DEFAULT_DAILY_CAP = 2
#: 静音时段
DEFAULT_QUIET = "23:30-07:30"
#: 两条主动消息之间至少隔这么久（防止改配置后连发）
MIN_SELF_GAP_MIN = 90


def _parse_hm(text, default):
    m = re.match(r"^\s*(\d{1,2})\s*[:：]\s*(\d{2})\s*$", text or "")
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h < 24 and 0 <= mi < 60:
        return h * 60 + mi
    return default


def _in_quiet(now, spec):
    """静音时段，支持跨零点（23:30-07:30）。"""
    spec = spec or DEFAULT_QUIET
    parts = re.split(r"\s*[-~—]\s*", spec.strip())
    if len(parts) != 2:
        spec = DEFAULT_QUIET
        parts = spec.split("-")
    start = _parse_hm(parts[0], 23 * 60 + 30)
    end = _parse_hm(parts[1], 7 * 60 + 30)
    cur = now.hour * 60 + now.minute
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end


class ProactiveScheduler:
    """定时判断"要不要先说话"，并且真的写出来。"""

    def __init__(self, app):
        self.app = app
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._busy = False
        self._meta_conn = None
        self.last_result = ""       # 给界面看的一句话："上次：昨晚 21:40 说了…"

    # ---------------------------------------------------------------- 生命周期
    def _conn(self):
        if self._meta_conn is None:
            self._meta_conn = db.init_db(self.app.conversation_manager.db_path)
        return self._meta_conn

    def _meta_get(self, key, default=""):
        try:
            row = self._conn().execute(
                "SELECT v FROM meta WHERE k=?", (key,)).fetchone()
            return row["v"] if row else default
        except Exception:
            return default

    def _meta_set(self, key, value):
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO meta(k, v) VALUES(?,?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, str(value)))
            conn.commit()
        except Exception as exc:
            print("⚠️ 主动消息状态写入失败: %s" % exc)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("🌙 主动消息调度器已启动（%s）" % (
            "开启" if self._enabled() else "关闭，用户没开"))

    def stop(self):
        self._stop.set()

    def _loop(self):
        # 启动后先等一会儿：别刚打开软件就蹦出一句，那是最吓人的时机
        self._stop.wait(25)
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                print("⚠️ 主动消息检查出错: %s" % exc)
            self._stop.wait(LOOP_SECONDS)

    # ---------------------------------------------------------------- 配置
    @property
    def config(self):
        return self.app.config_manager

    def _enabled(self):
        return bool(getattr(self.config, "proactive_enabled", False))

    # ---------------------------------------------------------------- 状态
    def _today(self):
        return datetime.now().strftime("%Y-%m-%d")

    def sent_today(self):
        try:
            return int(self._meta_get("proactive_sent:" + self._today(), "0") or 0)
        except (TypeError, ValueError):
            return 0

    def _bump_sent(self, text):
        key = "proactive_sent:" + self._today()
        self._meta_set(key, self.sent_today() + 1)
        self._meta_set("proactive_last_at", db.now_str())
        self.last_result = "%s 说了：%s" % (
            datetime.now().strftime("%H:%M"), (text or "")[:40])

    def last_sent_at(self):
        """上次主动开口的时间（datetime 或 None）。"""
        raw = self._meta_get("proactive_last_at", "")
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                continue
        return None

    def last_user_at(self):
        """上次用户说话的时间。查库，不依赖内存里的对话对象。"""
        conv_id = self.app.conversation_manager.current_conversation_id
        if not conv_id:
            return None
        try:
            row = self._conn().execute(
                "SELECT MAX(created_at) AS t FROM messages "
                "WHERE conv_id=? AND role='user'", (conv_id,)).fetchone()
            if not row or not row["t"]:
                return None
            return datetime.strptime(row["t"][:16], "%Y-%m-%d %H:%M")
        except Exception:
            return None

    def status(self):
        """给前端的完整状态，顺便解释"为什么现在没说话"。"""
        now = datetime.now()
        last_user = self.last_user_at()
        gap_h = (now - last_user).total_seconds() / 3600 if last_user else None
        gap_need = float(getattr(self.config, "proactive_gap_hours",
                                 DEFAULT_GAP_HOURS) or DEFAULT_GAP_HOURS)
        cap = int(getattr(self.config, "proactive_daily_cap",
                          DEFAULT_DAILY_CAP) or DEFAULT_DAILY_CAP)

        if not self._enabled():
            why = "没打开。打开之后她才会主动找你。"
        elif _in_quiet(now, getattr(self.config, "proactive_quiet", DEFAULT_QUIET)):
            why = "现在是静音时段，她不会出声。"
        elif self.sent_today() >= cap:
            why = "今天已经说过 %d 次了，明天吧。" % self.sent_today()
        elif gap_h is not None and gap_h < gap_need:
            left = gap_need - gap_h
            why = "你刚说过话。再过约 %d 小时她才可能先开口。" % max(1, round(left))
        else:
            why = "她随时可能开口。"

        return {
            "enabled": self._enabled(),
            "sent_today": self.sent_today(),
            "daily_cap": cap,
            "gap_hours": gap_need,
            "gap_now": round(gap_h, 1) if gap_h is not None else None,
            "quiet": getattr(self.config, "proactive_quiet", DEFAULT_QUIET),
            "quiet_now": _in_quiet(now, getattr(self.config, "proactive_quiet",
                                                 DEFAULT_QUIET)),
            "last_result": self.last_result,
            "why": why,
        }

    # ---------------------------------------------------------------- 判断
    def _pick(self):
        """挑一个开口的由头。返回 None 表示这轮算了。"""
        cm = self.app.conversation_manager
        life = getattr(cm, "daily_life", None)

        # 1) 她今天有句话想说
        if life is not None:
            thought = life.peek_thought()
            if thought:
                return {"kind": "thought", "hint": thought, "weight": 3}

        # 2) 她今天做的事里，有一条跟你有关
        if life is not None:
            cur = life.current()
            for e in reversed(cur.get("entries") or []):
                note = (e.get("note") or "").strip()
                if note and len(note) >= 6:
                    return {"kind": "life", "hint": "%s %s（%s）" % (
                        e.get("t", ""), e.get("act", ""), note), "weight": 2}

        # 3) 上次没聊完的事：几天内的计划/事件
        try:
            items = cm.memory_store.timeline(
                cm.current_conversation_id, scopes=cm.memory_scopes(), days=4, k=4)
        except Exception:
            items = []
        for it in items:
            content = (it.get("content") or "").strip()
            if content and it.get("kind") in ("plan", "event", "emotion"):
                return {"kind": "followup", "hint": content, "weight": 2}

        # 4) 单纯很久没说话
        gap = self.status().get("gap_now")
        if gap is not None and gap >= 20:
            return {"kind": "miss", "hint": "已经快一天没联系了", "weight": 1}

        return None

    def _should_speak(self):
        now = datetime.now()
        if not self._enabled():
            return None, "没打开"
        if self._busy:
            return None, "正在写"
        if _in_quiet(now, getattr(self.config, "proactive_quiet", DEFAULT_QUIET)):
            return None, "静音时段"

        cap = int(getattr(self.config, "proactive_daily_cap",
                          DEFAULT_DAILY_CAP) or DEFAULT_DAILY_CAP)
        if self.sent_today() >= cap:
            return None, "今天够了"

        last = self.last_sent_at()
        if last and (now - last).total_seconds() < MIN_SELF_GAP_MIN * 60:
            return None, "刚说过"

        # 用户已经很久没说话
        gap_need = float(getattr(self.config, "proactive_gap_hours",
                                 DEFAULT_GAP_HOURS) or DEFAULT_GAP_HOURS)
        last_user = self.last_user_at()
        if last_user:
            gap_h = (now - last_user).total_seconds() / 3600.0
            if gap_h < gap_need:
                return None, "刚说过话（%.1f 小时前）" % gap_h
        else:
            gap_h = 999.0

        picked = self._pick()
        if not picked:
            return None, "没找到由头"
        picked["gap_hours"] = gap_h
        return picked, ""

    # ---------------------------------------------------------------- 生成
    def _compose(self, ctx):
        """让她自己写这一两句。"""
        cm = self.app.conversation_manager
        api_config = self.config.get_current_api_config()
        from api_handler import APIHandler

        now = datetime.now()
        psych = cm.get_psych_state()
        life_block = ""
        try:
            life_block = cm.daily_life.prompt_block()
        except Exception:
            pass

        kind = ctx.get("kind")
        if kind == "thought":
            reason = "你今天一直想着这句话，现在想说给他：%s" % ctx["hint"]
        elif kind == "life":
            reason = "你今天做的这件事跟他有关，你想提一句：%s" % ctx["hint"]
        elif kind == "followup":
            reason = "他前阵子提过这件事，你想问问后来怎么样了：%s" % ctx["hint"]
        else:
            reason = "你们已经很久没说话了。没有具体的事，就是想找他。"

        gap = ctx.get("gap_hours")
        gap_txt = ("他上次说话是 %.0f 小时前" % gap) if gap and gap < 300 else "你们很久没联系了"

        prompt = (
            "现在是 %s。%s。\n\n%s\n\n%s\n\n"
            "你要先发一条消息给他。写一到两句，像微信那样短。\n\n"
            "规矩：\n"
            "1. 不要用「在吗」「最近怎么样」「好久不见」这种开场。有话直说。\n"
            "2. 开口的由头必须是具体的东西：你今天在做什么、他之前说过的事、外面的天气。\n"
            "3. 不许催他回，不许说「你怎么不回我」，也不许说「我等了你好久」。\n"
            "4. 如果他上次情绪不好，别一上来就提那件事。\n"
            "5. 只写你会发出去的话，不要解释、不要加括号里的动作。\n"
        ) % (
            now.strftime("%m月%d日 %H:%M"), gap_txt,
            life_block or "（你今天没记下什么特别的事）",
            reason,
        )

        handler = APIHandler(
            api_config["api_key"], api_config["api_endpoint"], api_config["model"],
            "disabled", False, api_config.get("provider", ""))
        ok, raw = handler.call_api(
            [{"role": "user", "content": prompt}],
            cm.get_effective_role_prompt()[:1200],
            psych,
            max_tokens=180,
        )
        if not ok or not raw:
            return ""
        text = self._clean(raw)
        if len(text) < 2:
            return ""
        return text

    @staticmethod
    def _clean(raw):
        """去掉 JSON 尾巴、括号动作、前后引号。"""
        text = (raw or "").strip()
        text = re.sub(r"```[\s\S]*?```", "", text)
        text = re.sub(r"\{[\s\S]*?\}", "", text)
        text = re.sub(r"（[^）]{0,20}(心想|悄悄|停顿|笑|叹气)[^）]{0,20}）", "", text)
        text = re.sub(r"\*[^*\n]{1,20}\*", "", text)
        text = text.strip().strip('"“”「」')
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    # ---------------------------------------------------------------- 出口
    def fire(self, force=False):
        """现在就说一句。force=True 时无视间隔和上限（用户手动点的）。"""
        with self._lock:
            if self._busy:
                return {"ok": False, "reason": "正在写，等一下"}

            if force:
                if not self._enabled():
                    return {"ok": False, "reason": "先把主动消息打开"}
                ctx = self._pick() or {"kind": "miss", "hint": "", "gap_hours": 999}
            else:
                ctx, why = self._should_speak()
                if ctx is None:
                    return {"ok": False, "reason": why}

            self._busy = True
            try:
                text = self._compose(ctx)
            except Exception as exc:
                print("⚠️ 主动消息生成失败: %s" % exc)
                text = ""
            finally:
                self._busy = False

            if not text:
                return {"ok": False, "reason": "这次没写出来（模型没回或返回空）"}

            cm = self.app.conversation_manager
            try:
                cm.add_message("assistant", text, kind="proactive")
            except Exception as exc:
                print("⚠️ 主动消息存档失败: %s" % exc)

            bridge = getattr(self.app, "web_bridge", None)
            if bridge:
                try:
                    bridge.push_proactive(text)
                except Exception as exc:
                    print("⚠️ 主动消息推送失败: %s" % exc)

            if ctx.get("kind") == "thought":
                try:
                    cm.daily_life.take_thought()
                except Exception:
                    pass

            self._bump_sent(text)
            print("🌙 她先开口了（%s）：%s" % (ctx.get("kind"), text[:40]))
            return {"ok": True, "text": text, "kind": ctx.get("kind")}

    def tick(self):
        if not self._enabled():
            return None
        ctx, _why = self._should_speak()
        if ctx is None:
            return None
        return self.fire(force=False)
