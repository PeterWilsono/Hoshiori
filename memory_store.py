# -*- coding: utf-8 -*-
"""长期记忆：写入时去重、冲突时失效、读取时按话题检索。

和以前最大的区别在这三件事上：

1. **写入不再是无脑 append**。同一条事实第二次出现不会变成两条；同一个槽位
   （比如"职业"）换了值，旧记录标成 superseded 而不是删掉——所以她还答得出
   "你以前是做什么的"。
2. **读取按当前这句话检索**，不再把整本档案塞进提示词。分数由「语义相似 +
   关键词命中 + 重要度 + 新近度 + 情绪相似度」合成，够用的记忆才会被取出来。
3. **会忘**。长期没被用到的低价值记忆降到 archived，不再占预算，但没删。

语义那一路用的是本地 bge-small-zh（ONNX，CPU，见 `embedder.py`）：把每条记忆
和用户这句话都变成 512 维向量，余弦越近越相关。它不联网、不花 token。
模型缺失或 onnxruntime 装不上时，`_vec_ready` 一直是 False，自动退回纯关键词，
分数公式里语义项的权重让给关键词项——所以两种模式都能跑。

所有分数都在 0~1 之间，方便直接调参。
"""
import math
import re
import threading
from datetime import datetime, timedelta

import numpy as np

import db

try:
    import embedder as _embedder_mod
except Exception:                     # numpy 之外没有硬依赖
    _embedder_mod = None

__all__ = ["MemoryStore"]

#: 各类记忆的初始重要度
KIND_IMPORTANCE = {
    "profile": 9.0,      # 姓名、生日、职业这类稳定事实
    "reflection": 6.8,   # 批量整理时沉淀的"对他的理解"，不是事实而是判断
    "preference": 7.0,   # 喜欢 / 讨厌
    "plan": 7.5,         # 约定、计划
    "event": 7.0,        # 发生过的事
    "emotion": 6.0,      # 强烈情绪事件
    "topic": 3.5,        # 聊过的话题
    "note": 4.0,
}

#: 同一槽位重复出现时，视为「同一件事的不同说法」。
#: 只认显式句式——早先按关键词猜（"做"也算职业），会把"在做AI项目"误判成职业。
_SLOT_PATTERNS = (
    ("profile:name", r"(名字|称呼)(是|叫)|^\s*(?:我|用户)?叫[^，,。]{1,6}$"),
    ("profile:occupation", r"(职业|职位|工作)(是|为)|在.{0,10}工作|做.{0,6}(工程师|开发|设计|运营)"),
    ("profile:birthday", r"生日(是|在|为)"),
    ("profile:city", r"(住在|搬到了|城市是)"),
)


def _norm(text):
    return re.sub(r"[\s，。！？、,.!?~…]+", "", (text or "")).strip().lower()


def _tokens(text):
    return set(db.bigrams(text))


def _dice(a, b):
    """二元组 Dice 相似度，对中文短句比 Jaccard 更宽容。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return 2.0 * inter / (len(a) + len(b))


def _pad_sim(pad, row):
    """当前情绪与记忆里那份情绪的距离 → 0~1 相似度。"""
    if not pad or row["pad_p"] is None:
        return 0.0
    p = float(row["pad_p"])
    a = float(row["pad_a"] or 0)
    d = float(row["pad_d"] or 0)
    dist = math.sqrt((pad.get("pleasure", 0) - p) ** 2 +
                     (pad.get("arousal", 0) - a) ** 2 +
                     (pad.get("dominance", 0) - d) ** 2)
    return max(0.0, 1.0 - dist / math.sqrt(12))


_REL_DAY = {"大前天": 3, "前天": 2, "昨天": 1, "今天": 0, "今早": 0, "今晚": 0}


def _event_time(content):
    """从句子里猜"这事发生在哪天"，猜不到返回 None。

    只认明确的时间词，不猜。没有时间词的记忆保留 NULL，检索时按记录时间算。
    """
    content = content or ""
    today = datetime.now()
    for word, days in _REL_DAY.items():
        if word in content:
            return (today - timedelta(days=days)).strftime("%Y-%m-%d")
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", content)
    if m:
        try:
            return today.replace(month=int(m.group(1)), day=int(m.group(2))).strftime("%Y-%m-%d")
        except ValueError:
            return None
    if "上周" in content:
        return (today - timedelta(days=7)).strftime("%Y-%m-%d")
    if "上个月" in content:
        return (today - timedelta(days=30)).strftime("%Y-%m-%d")
    if "去年" in content:
        return (today - timedelta(days=365)).strftime("%Y-%m-%d")
    return None


#: 语义检索的候选宽度（先粗筛这么多，再逐条算综合分）
SEM_CANDIDATES = 40

#: 两条记忆的语义余弦超过这个值就当重复（比字面 0.82 更早拦住换句话说的同一件事）
SEM_DUP = 0.86


class MemoryStore:
    """记忆库。所有写入都走 `remember()`，它负责决定是新增、更新还是让旧的失效。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = db.init_db(db_path)

        # ---- 语义向量索引（内存里一份，随写入增量更新）
        self._dim = getattr(_embedder_mod, "DIM", 512) if _embedder_mod else 512
        self._vec_buf = np.zeros((0, self._dim), dtype=np.float32)
        self._vec_ids = []            # 下标 → 记忆 id
        self._vec_rows = {}           # 记忆 id → 下标
        self._vec_is_user = np.zeros(0, dtype=bool)     # 是否跨对话记忆
        self._vec_conv = np.zeros(0, dtype=np.int64)    # 所属对话，-1 表示不属于任何对话
        self._vec_n = 0
        self._vec_ready = False       # 冷启动补算完成后才置 True
        self._warm_lock = threading.Lock()
        self._warmed = False

    # ------------------------------------------------------------ 语义层

    @staticmethod
    def _get_embedder():
        if _embedder_mod is None:
            return None
        try:
            emb = _embedder_mod.get_embedder()
            return emb if emb.available else None
        except Exception as exc:
            print("⚠️ 语义模型不可用: %s" % exc)
            return None

    def _embed(self, texts):
        emb = self._get_embedder()
        if emb is None:
            return None
        return emb.encode(texts)

    def _embed_one(self, text, is_query=False):
        emb = self._get_embedder()
        if emb is None:
            return None
        return emb.encode_one(text, is_query=is_query)

    def _vec_put(self, mem_id, vec, scope="conv", conv_id=None):
        """把一条向量塞进内存索引（容量按需翻倍）。调用方自己持有锁。

        顺便记住它属于哪段对话——语义粗筛要按 scope 掩码，否则几个对话混着用
        的时候，top40 会被别的对话占满，当前对话的记忆根本挤不进来。
        """
        if vec is None:
            return
        vec = np.asarray(vec, dtype=np.float32).reshape(-1)
        if vec.shape[0] != self._dim:
            return
        idx = self._vec_rows.get(mem_id)
        if idx is None:
            if self._vec_n >= self._vec_buf.shape[0]:
                cap = max(64, self._vec_buf.shape[0] * 2)
                buf = np.zeros((cap, self._dim), dtype=np.float32)
                buf[:self._vec_n] = self._vec_buf[:self._vec_n]
                self._vec_buf = buf
                is_user = np.zeros(cap, dtype=bool)
                is_user[:self._vec_n] = self._vec_is_user[:self._vec_n]
                self._vec_is_user = is_user
                conv = np.zeros(cap, dtype=np.int64)
                conv[:self._vec_n] = self._vec_conv[:self._vec_n]
                self._vec_conv = conv
            idx = self._vec_n
            self._vec_n += 1
            self._vec_rows[mem_id] = idx
            self._vec_ids.append(mem_id)
            self._vec_is_user[idx] = (scope == "user")
            self._vec_conv[idx] = -1 if conv_id is None else int(conv_id)
        self._vec_buf[idx] = vec

    def _vec_drop(self, ids):
        """删掉的记忆不必立刻搬动矩阵——它已经查不到行，索引里留着也不会被选中。"""
        for mem_id in ids or ():
            idx = self._vec_rows.pop(mem_id, None)
            if idx is not None:
                self._vec_buf[idx] = 0.0

    def warm_up_async(self):
        """后台把模型加载 + 旧记忆向量补齐 + 建索引。不挡启动。"""
        if self._warmed:
            return
        with self._warm_lock:
            if self._warmed:
                return
            self._warmed = True
        threading.Thread(target=self._warm_up, daemon=True).start()

    def _warm_up(self):
        emb = self._get_embedder()
        if emb is None:
            return
        try:
            filled = self._backfill(emb)
            with self._lock:
                rows = self._conn.execute(
                    "SELECT id, embedding, scope, conv_id FROM memories "
                    "WHERE embedding IS NOT NULL").fetchall()
                for row in rows:
                    vec = np.frombuffer(row["embedding"], dtype=np.float32)
                    if vec.shape[0] == self._dim:
                        self._vec_put(row["id"], vec, row["scope"], row["conv_id"])
                self._vec_ready = True
            print("✓ 语义索引就绪：%d 条（新补 %d 条）" % (len(self._vec_ids), filled))
        except Exception as exc:
            print("⚠️ 语义索引构建失败，退回关键词检索: %s" % exc)

    def _backfill(self, emb, batch=32):
        """给没有向量的旧记忆补算。分批查、批量推、分批提交。"""
        filled = 0
        while True:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT id, content, scope, conv_id FROM memories "
                    "WHERE embedding IS NULL ORDER BY id LIMIT ?", (batch,)).fetchall()
            if not rows:
                break
            mat = emb.encode([r["content"] for r in rows])
            if mat is None:
                break
            with self._lock:
                for row, vec in zip(rows, mat):
                    self._conn.execute("UPDATE memories SET embedding=? WHERE id=?",
                                       (vec.astype(np.float32).tobytes(), row["id"]))
                    self._vec_put(row["id"], vec, row["scope"], row["conv_id"])
                self._conn.commit()
            filled += len(rows)
            if len(rows) < batch:
                break
        return filled

    def _semantic_hits(self, query, conv_id=None, scopes=("conv", "user"),
                       limit=SEM_CANDIDATES):
        """语义粗筛：返回 {id: 原始余弦}。索引没就绪时返回空。"""
        if not self._vec_ready or self._vec_n == 0:
            return {}
        qv = self._embed_one(query, is_query=True)
        if qv is None:
            return {}
        with self._lock:
            n = self._vec_n
            mat = self._vec_buf[:n]
            ids = self._vec_ids[:n]
            is_user = self._vec_is_user[:n]
            convs = self._vec_conv[:n]

        scopes = tuple(scopes or ("conv", "user"))
        cid = -1 if conv_id is None else int(conv_id)
        if "user" in scopes and "conv" in scopes:
            allow = is_user | (convs == cid)
        elif "user" in scopes:
            allow = is_user.copy()
        elif "conv" in scopes:
            allow = (convs == cid)
        else:
            return {}
        total = int(allow.sum())
        if total == 0:
            return {}

        sims = np.where(allow, mat @ qv, -2.0)
        k = min(limit, total)
        idx = np.argpartition(-sims, k - 1)[:k]
        return {ids[int(i)]: float(sims[int(i)]) for i in idx if sims[int(i)] > -1.5}

    @property
    def semantic_ready(self):
        return self._vec_ready

    # ------------------------------------------------------------ 写入

    def remember(self, content, kind="note", conv_id=None, key=None,
                 importance=None, pad=None, confidence=0.6, source="chat",
                 scope="conv", concept=None, event_at=None):
        """记一条。返回 (action, id)，action ∈ add / update / supersede / noop。

        scope='user' 的记忆跨对话共享（画像、偏好、长期事件）；scope='conv'
        只属于某一段对话——"重新认识"模式下写的就是这种，不污染全局。
        """
        content = (content or "").strip()
        if len(content) < 2:
            return "noop", None

        scope = "user" if scope == "user" else "conv"
        kind = kind if kind in KIND_IMPORTANCE else "note"
        base = KIND_IMPORTANCE[kind]
        if importance is None:
            importance = base
        importance = float(max(0.0, min(10.0, importance)))

        if concept is None:
            concept = ",".join(sorted(db.concepts_of(content)))
        if event_at is None:
            event_at = _event_time(content)

        tokens = _tokens(content)
        if not tokens:
            return "noop", None

        # 向量在锁外算：1~2ms，别让它挡住别人读
        vec = self._embed_one(content)
        vec_blob = vec.astype(np.float32).tobytes() if vec is not None else None

        # 去重只在同一个 scope 内比较：全局的"用户是工程师"和某段对话里的
        # 临时说法不该互相覆盖。
        where = "status='active' AND kind=? AND scope=?"
        params = [kind, scope]
        if scope == "conv":
            where += " AND conv_id IS ?"
            params.append(conv_id)

        with self._lock:
            conn = self._conn
            rows = conn.execute(
                "SELECT * FROM memories WHERE " + where +
                " ORDER BY id DESC LIMIT 80", params
            ).fetchall()

            best, best_sim = None, 0.0
            sem_best, sem_best_cos = None, 0.0
            for row in rows:
                sim = _dice(tokens, _tokens(row["content"]))
                if sim > best_sim:
                    best, best_sim = row, sim
                if vec is not None and row["embedding"]:
                    old = np.frombuffer(row["embedding"], dtype=np.float32)
                    if old.shape[0] == self._dim:
                        cos = float(old @ vec)
                        if cos > sem_best_cos:
                            sem_best, sem_best_cos = row, cos

            now = db.now_str()

            slot = key or self._slot_of(kind, content)
            old_slot = None
            if slot:
                old_slot = conn.execute(
                    "SELECT id FROM memories WHERE " + where +
                    " AND mkey=? ORDER BY id DESC LIMIT 1",
                    params + [slot]
                ).fetchone()

            # 1) 同一句话，或者换了种说法但意思几乎一样：刷新重要度和时间。
            #    但"会换值的槽位"（职业/城市/生日…）要走下面那条——那是新值，
            #    不是重复。否则"产品经理"会直接把"数据分析师"覆盖掉，历史就没了。
            same = None
            if best is not None and best_sim >= 0.82:
                same = best
            elif sem_best is not None and sem_best_cos >= SEM_DUP and old_slot is None:
                same = sem_best
            if same is not None:
                new_imp = max(float(same["importance"]), importance)
                conn.execute(
                    "UPDATE memories SET importance=?, updated_at=?, content=?,"
                    " concept=?, embedding=COALESCE(?, embedding),"
                    " event_at=COALESCE(event_at, ?) WHERE id=?",
                    (new_imp, now, content, concept, vec_blob, event_at, same["id"])
                )
                self._index(same["id"], content, tokens)
                if vec is not None:
                    self._vec_put(same["id"], vec, scope, conv_id)
                conn.commit()
                return "update", same["id"]

            # 2) 同一槽位换了值（职业从 A 变成 B）：旧的失效，新的接上
            if old_slot is not None:
                cur = conn.execute(
                    "INSERT INTO memories(conv_id, kind, mkey, content, importance,"
                    " confidence, status, created_at, updated_at, pad_p, pad_a, pad_d,"
                    " search, scope, concept, event_at, embedding)"
                    " VALUES(?,?,?,?,?,?, 'active', ?,?,?,?,?,?,?,?,?,?)",
                    (conv_id, kind, slot, content, importance, confidence, now, now,
                     pad.get("pleasure") if pad else None,
                     pad.get("arousal") if pad else None,
                     pad.get("dominance") if pad else None,
                     " ".join(sorted(tokens)), scope, concept, event_at, vec_blob)
                )
                new_id = cur.lastrowid
                conn.execute(
                    "UPDATE memories SET status='superseded', superseded_by=? "
                    "WHERE id=?", (new_id, old_slot["id"])
                )
                self._index(new_id, content, tokens)
                self._vec_put(new_id, vec, scope, conv_id)
                conn.commit()
                return "supersede", new_id

            # 3) 新的一条
            cur = conn.execute(
                "INSERT INTO memories(conv_id, kind, mkey, content, importance, confidence,"
                " status, created_at, updated_at, pad_p, pad_a, pad_d, search,"
                " scope, concept, event_at, embedding)"
                " VALUES(?,?,?,?,?,?, 'active', ?,?,?,?,?,?,?,?,?,?)",
                (conv_id, kind, slot, content, importance, confidence, now, now,
                 pad.get("pleasure") if pad else None,
                 pad.get("arousal") if pad else None,
                 pad.get("dominance") if pad else None,
                 " ".join(sorted(tokens)), scope, concept, event_at, vec_blob)
            )
            new_id = cur.lastrowid
            self._index(new_id, content, tokens)
            self._vec_put(new_id, vec, scope, conv_id)
            conn.commit()
            return "add", new_id

    def _slot_of(self, kind, content):
        """猜这句话属于哪个"槽位"（用于识别同一事实的新旧版本）。

        只对短句生效：像"用户叫阿哲，在做AI陪伴项目，常熬夜"这种复合事实
        不该覆盖名字槽位，它本身就是一条独立记忆。
        """
        if kind not in ("profile", "plan"):
            return None
        if len(content) > 24:
            return None
        for slot, pattern in _SLOT_PATTERNS:
            if re.search(pattern, content):
                return slot
        return None

    def _index(self, mem_id, content, tokens):
        self._conn.execute("DELETE FROM memories_fts WHERE rowid=?", (mem_id,))
        self._conn.execute(
            "INSERT INTO memories_fts(rowid, search) VALUES(?,?)",
            (mem_id, " ".join(sorted(tokens)))
        )

    # ------------------------------------------------------------ 读取

    def _scope_where(self, conv_id, scopes):
        """把 scope 需求翻成 SQL 片段：本对话 / 跨对话 / 两者。"""
        scopes = tuple(scopes or ("conv", "user"))
        parts, params = [], []
        if "conv" in scopes:
            parts.append("(scope='conv' AND conv_id IS ?)")
            params.append(conv_id)
        if "user" in scopes:
            parts.append("scope='user'")
        if not parts:
            return "0", []
        return "(" + " OR ".join(parts) + ")", params

    def recall(self, query, conv_id=None, pad=None, k=6, min_score=0.20,
               scopes=("conv", "user")):
        """按当前这句话取相关记忆；分数不够的不返回（宁缺毋滥）。

        两路候选并行：FTS 关键词命中 + 语义近邻，取并集再逐条算综合分。
        语义那一路能捞到"字面完全不同、意思却是同一件事"的记忆，比如用户说
        "老板又发火"，能召回"用户和主管关系不好"。
        """
        now = datetime.now()
        with self._lock:
            conn = self._conn

            match_scores = {}
            sem_hits = self._semantic_hits(query, conv_id, scopes)
            # 有语义那一路时，不再拿整组近义词去查 FTS：
            # 概念扩展是"没有向量时的拐杖"，一旦用上，判断"猫"属于爱好组就会把
            # 同组的"旅行""咖啡"全拉成命中，反而盖过真正相关的那条。
            extra = () if sem_hits else db.concept_terms(query)
            expr = db.build_match_query(query, extra=extra)
            if expr:
                try:
                    for row in conn.execute(
                        "SELECT rowid, bm25(memories_fts) AS rank FROM memories_fts "
                        "WHERE memories_fts MATCH ? ORDER BY rank LIMIT 40",
                        (expr,)
                    ):
                        # bm25 越小越相关；压成 0~1
                        match_scores[row["rowid"]] = 1.0 / (1.0 + math.exp(row["rank"] * 0.6))
                except Exception as exc:
                    print("⚠️ 记忆检索失败: %s" % exc)

            scope_sql, scope_params = self._scope_where(conv_id, scopes)
            cand_ids = set(match_scores) | set(sem_hits)

            if not cand_ids:
                candidates = conn.execute(
                    "SELECT * FROM memories WHERE status='active' AND " + scope_sql +
                    " ORDER BY importance DESC, id DESC LIMIT 12", scope_params
                ).fetchall()
                min_score = max(min_score, 0.32)   # 既没命中关键词也没语义近邻，别硬塞
            else:
                ids = list(cand_ids)
                marks = ",".join("?" * len(ids))
                candidates = conn.execute(
                    "SELECT * FROM memories WHERE id IN (%s) AND status='active' AND %s"
                    % (marks, scope_sql),
                    ids + scope_params
                ).fetchall()

            q_concepts = db.concepts_of(query or "")
            scored = []
            for row in candidates:
                hit = match_scores.get(row["id"], 0.0)
                cos = sem_hits.get(row["id"], 0.0)
                sem = _embedder_mod.Embedder.similarity(cos) if (cos and _embedder_mod) else 0.0
                imp = float(row["importance"]) / 10.0
                recency = self._recency(row["updated_at"] or row["created_at"], now)
                emo = _pad_sim(pad, row)
                score = 0.34 * sem + 0.30 * hit + 0.18 * imp + 0.11 * recency + 0.07 * emo
                if q_concepts and set((row["concept"] or "").split(",")) & q_concepts:
                    score += 0.06          # 同一概念（工作/健康/家人…）的额外加权
                if max(hit, sem) < 0.05:
                    score *= 0.4           # 两条路都没对上，只当背景补充
                if score >= min_score:
                    scored.append((score, row))

            scored.sort(key=lambda x: x[0], reverse=True)
            picked = scored[:k]

            if picked:
                self._touch([r["id"] for _, r in picked])

            return [{
                "id": r["id"],
                "kind": r["kind"],
                "content": r["content"],
                "importance": r["importance"],
                "time": (r["created_at"] or "")[:16],
                "scope": r["scope"],
                "event_at": r["event_at"] or "",
                "score": round(s, 3),
            } for s, r in picked]

    def timeline(self, conv_id=None, scopes=("conv", "user"), days=45, k=5):
        """最近这段日子真正发生过的事，按时间正序——用来回答"这阵子"。

        只取重要度够的：日常寒暄不该出现在回忆里。
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        scope_sql, scope_params = self._scope_where(conv_id, scopes)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE status='active' AND importance>=6 "
                "AND kind IN ('event','plan','emotion','note') "
                "AND COALESCE(event_at, substr(created_at,1,10)) >= ? AND " + scope_sql +
                " ORDER BY COALESCE(event_at, created_at) DESC LIMIT ?",
                [since] + scope_params + [k]
            ).fetchall()
        out = [{
            "id": r["id"],
            "content": r["content"],
            "date": (r["event_at"] or (r["created_at"] or "")[:10]),
            "kind": r["kind"],
            "scope": r["scope"],
        } for r in rows]
        out.reverse()
        return out

    def pinned(self, conv_id=None, limit=4, scopes=("conv", "user")):
        """每次都要在场的事实：只钉带槽位的那几条（名字/生日/职业），
        避免和检索出来的长句记忆重复占预算。"""
        scope_sql, scope_params = self._scope_where(conv_id, scopes)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE status='active' AND " + scope_sql +
                " AND kind='profile' AND mkey IS NOT NULL"
                " ORDER BY importance DESC, id DESC LIMIT ?",
                scope_params + [limit]
            ).fetchall()
            if not rows:
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE status='active' AND " + scope_sql +
                    " AND kind='profile' ORDER BY importance DESC, id DESC LIMIT 2",
                    scope_params
                ).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "content": r["content"],
                 "time": "", "scope": r["scope"]} for r in rows]

    def _recency(self, stamp, now):
        try:
            t = datetime.strptime(stamp[:16], "%Y-%m-%d %H:%M")
        except Exception:
            return 0.3
        days = max(0.0, (now - t).total_seconds() / 86400.0)
        return math.exp(-days / 45.0)     # 45 天半衰，长期不用的自然变淡

    def _touch(self, ids):
        if not ids:
            return
        try:
            now = db.now_str()
            self._conn.executemany(
                "UPDATE memories SET last_used_at=?, use_count=use_count+1 WHERE id=?",
                [(now, i) for i in ids]
            )
            self._conn.commit()
        except Exception:
            pass

    # ------------------------------------------------------------ 维护

    def by_emotion(self, pad, conv_id=None, k=2, min_sim=0.72,
                   scopes=("conv", "user")):
        """情绪联想：现在的心情让她想起哪几件旧事（情绪一致性效应）。"""
        if not pad:
            return []
        scope_sql, scope_params = self._scope_where(conv_id, scopes)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE status='active' AND pad_p IS NOT NULL AND "
                + scope_sql + " ORDER BY id DESC LIMIT 200", scope_params
            ).fetchall()
        scored = []
        for row in rows:
            sim = _pad_sim(pad, row)
            if sim >= min_sim:
                scored.append((sim, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = scored[:k]
        if picked:
            self._touch([r["id"] for _, r in picked])
        return [{"id": r["id"], "content": r["content"],
                 "time": (r["created_at"] or "")[:10], "score": round(s, 2)}
                for s, r in picked]

    def prune(self, archive_below=2.0, idle_days=120):
        """长期没被召回、又不重要的记忆降级为 archived（可恢复，不删除）。"""
        with self._lock:
            cutoff = datetime.now().timestamp() - idle_days * 86400
            rows = self._conn.execute(
                "SELECT id, importance, last_used_at, updated_at FROM memories "
                "WHERE status='active'"
            ).fetchall()
            ids = []
            for r in rows:
                if float(r["importance"]) >= archive_below:
                    continue
                stamp = r["last_used_at"] or r["updated_at"]
                try:
                    ts = datetime.strptime(stamp[:16], "%Y-%m-%d %H:%M").timestamp()
                except Exception:
                    continue
                if ts < cutoff:
                    ids.append(r["id"])
            if ids:
                self._conn.executemany(
                    "UPDATE memories SET status='archived' WHERE id=?",
                    [(i,) for i in ids]
                )
                self._conn.commit()
            return len(ids)

    def forget(self, mem_id):
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE id=?", (mem_id,))
            self._conn.execute("DELETE FROM memories_fts WHERE rowid=?", (mem_id,))
            self._vec_drop([mem_id])
            self._conn.commit()

    def drop_conversation(self, conv_id, include_user=False):
        """删掉某段对话的记忆。

        默认只删这段对话自己的（scope='conv'）——跨对话的记忆属于"她和你"，
        不该因为关掉一个话题就消失。include_user=True 才是彻底清空。
        """
        with self._lock:
            if include_user:
                ids = [r["id"] for r in self._conn.execute(
                    "SELECT id FROM memories WHERE conv_id=?", (conv_id,))]
                self._conn.execute("DELETE FROM memories WHERE conv_id=?", (conv_id,))
            else:
                ids = [r["id"] for r in self._conn.execute(
                    "SELECT id FROM memories WHERE conv_id=? AND scope='conv'", (conv_id,))]
                self._conn.execute(
                    "DELETE FROM memories WHERE conv_id=? AND scope='conv'", (conv_id,))
            if ids:
                self._conn.executemany("DELETE FROM memories_fts WHERE rowid=?",
                                       [(i,) for i in ids])
                self._vec_drop(ids)
            self._conn.commit()
        return len(ids)

    def supersede(self, mem_id, new_content):
        """用户手动改一条记忆：旧的失效，新的接上。"""
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (mem_id,)).fetchone()
        if row is None:
            return None
        _, new_id = self.remember(new_content, kind=row["kind"], conv_id=row["conv_id"],
                                  key=row["mkey"], importance=row["importance"],
                                  confidence=row["confidence"],
                                  scope=row["scope"], event_at=row["event_at"])
        with self._lock:
            if new_id and new_id != mem_id:
                self._conn.execute(
                    "UPDATE memories SET status='superseded', superseded_by=? WHERE id=?",
                    (new_id, mem_id)
                )
                self._conn.commit()
        return new_id

    def list_recent(self, conv_id=None, limit=40, include_archived=False,
                    include_superseded=False, scope=None):
        """记忆面板用。scope: None=这段对话能看到的全部、'user'=跨对话、'conv'=仅本对话。"""
        if scope == "user":
            where = "scope='user'"
            params = []
        elif scope == "conv":
            where = "scope='conv' AND conv_id IS ?"
            params = [conv_id]
        else:
            where = "(scope='user' OR (scope='conv' AND conv_id IS ?))"
            params = [conv_id]

        if not include_archived and not include_superseded:
            where += " AND status='active'"
        elif include_superseded and not include_archived:
            where += " AND status IN ('active','superseded')"
        q = "SELECT * FROM memories WHERE " + where
        q += " ORDER BY importance DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [{
            "id": r["id"], "kind": r["kind"], "content": r["content"],
            "importance": r["importance"], "status": r["status"],
            "time": (r["created_at"] or "")[:16],
            "scope": r["scope"], "concept": r["concept"] or "",
            "event_at": r["event_at"] or "",
        } for r in rows]

    def stats(self, conv_id=None, all_conversations=False):
        """统计条数。不传 conv_id 时默认统计全库（日志和设置页都用它）。"""
        where = ""
        params = ()
        if conv_id is not None and not all_conversations:
            where = " WHERE conv_id IS ?"
            params = (conv_id,)
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n, "
                "SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active, "
                "SUM(CASE WHEN status='superseded' THEN 1 ELSE 0 END) AS superseded "
                "FROM memories" + where, params
            ).fetchone()
        return {"total": row["n"] or 0, "active": row["active"] or 0,
                "superseded": row["superseded"] or 0}

    # ------------------------------------------------------------ 迁移

    def import_legacy(self, memory, conv_id, pad=None):
        """把旧的 conversations.json 里的 memory 字典搬进来。返回导入条数。"""
        if not memory:
            return 0
        n = 0

        profile = memory.get("user_profile") or {}
        for field, label in (("name", "用户的名字"), ("birthday", "用户的生日"),
                             ("occupation", "用户的职业")):
            value = profile.get(field)
            if value:
                action, _ = self.remember(
                    "%s是%s" % (label, value), kind="profile", conv_id=conv_id,
                    key="profile:%s" % field, importance=9.0, confidence=0.95,
                    scope="user")
                n += action in ("add", "update", "supersede")

        for note in (profile.get("profile_notes") or [])[-20:]:
            text = note["content"] if isinstance(note, dict) else str(note)
            if text:
                action, _ = self.remember(text, kind="profile", conv_id=conv_id,
                                          importance=7.0, confidence=0.8, scope="user")
                n += action in ("add", "update")

        for pref in (profile.get("preferences") or [])[-30:]:
            text = pref["content"] if isinstance(pref, dict) else str(pref)
            if text:
                action, _ = self.remember(text, kind="preference", conv_id=conv_id,
                                          importance=7.0, confidence=0.8, scope="user")
                n += action in ("add", "update")

        for event in (memory.get("important_events") or [])[-30:]:
            text = event.get("content") if isinstance(event, dict) else str(event)
            if text:
                action, _ = self.remember(
                    text, kind="event", conv_id=conv_id,
                    importance=float(event.get("importance", 7)),
                    pad=event.get("pad_snapshot"), confidence=0.8, scope="user")
                n += action in ("add", "update")

        for event in (memory.get("emotional_events") or [])[-30:]:
            text = event.get("event") if isinstance(event, dict) else str(event)
            if text:
                action, _ = self.remember(
                    text, kind="emotion", conv_id=conv_id,
                    importance=float(event.get("importance", 6)),
                    pad=event.get("pad_snapshot"), confidence=0.7, scope="user")
                n += action in ("add", "update")

        for topic in (memory.get("discussed_topics") or [])[-20:]:
            if topic:
                action, _ = self.remember(str(topic), kind="topic", conv_id=conv_id,
                                          scope="user")
                n += action in ("add", "update")

        return n
