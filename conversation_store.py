# -*- coding: utf-8 -*-
"""对话与消息的存储：元数据在 conversations 表，消息一条一行。

旧版把「消息 + 记忆 + 心理状态」全塞进一个 conversations.json，每发一句话就
整份重写。这里改成：发消息 = 插一行（O(1)），只有元数据（标题、心理状态）
变化时才回写那一行。
"""
import json
import os
import shutil
import threading
from datetime import datetime

import db

__all__ = ["ConversationStore"]


class ConversationStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = db.init_db(db_path)

    # ------------------------------------------------------------ 迁移

    def import_json(self, json_path):
        """把旧 conversations.json 搬进库；成功后改名备份，不删除。

        返回 {conv_id: 旧 memory 字典}，方便调用方把记忆搬进 MemoryStore。
        """
        if not os.path.exists(json_path):
            return {}
        if self._migrated():
            return {}

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print("⚠️ 旧对话文件读取失败，跳过迁移: %s" % exc)
            return 0

        if not isinstance(data, dict) or not data:
            self._mark_migrated()
            return {}

        count = 0
        legacy_memory = {}
        with self._lock:
            conn = self._conn
            for raw_id, conv in data.items():
                try:
                    conv_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                title = conv.get("title") or ("对话 %d" % conv_id)
                psych = conv.get("psych_core") or {}
                last = conv.get("last_interaction_time") or db.now_str()
                role = conv.get("custom_role_prompt")
                created = conv.get("created_at") or last

                conn.execute(
                    "INSERT OR REPLACE INTO conversations"
                    "(id, title, role_prompt, created_at, last_interaction,"
                    " message_count, psych_core, extra) VALUES(?,?,?,?,?,?,?,?)",
                    (conv_id, title, role, created, last, 0,
                     json.dumps(psych, ensure_ascii=False), "{}")
                )

                messages = conv.get("messages") or []
                rows = []
                for msg in messages:
                    content = msg.get("content", "")
                    if not content:
                        continue
                    rows.append((conv_id, msg.get("role", "user"), content,
                                 msg.get("time") or last, msg.get("tokens") or 0))
                if rows:
                    conn.executemany(
                        "INSERT INTO messages(conv_id, role, content, created_at, tokens)"
                        " VALUES(?,?,?,?,?)", rows
                    )
                conn.execute(
                    "UPDATE conversations SET message_count=? WHERE id=?",
                    (len(rows), conv_id)
                )

                for summary in (conv.get("memory", {}) or {}).get("long_term_summaries", [])[-10:]:
                    text = summary.get("summary") if isinstance(summary, dict) else str(summary)
                    if text:
                        conn.execute(
                            "INSERT INTO summaries(conv_id, content, covered_upto, created_at)"
                            " VALUES(?,?,?,?)", (conv_id, text, 0, db.now_str())
                        )

                memory = conv.get("memory")
                if memory:
                    legacy_memory[conv_id] = memory
                count += 1

            conn.commit()

        self._mark_migrated()
        self._backup(json_path)
        print("✓ 已迁移 %d 个对话到 SQLite" % count)
        return legacy_memory

    def _migrated(self):
        row = self._conn.execute("SELECT v FROM meta WHERE k='migrated_json'").fetchone()
        return row is not None

    def _mark_migrated(self):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(k, v) VALUES('migrated_json', ?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M"),)
            )
            self._conn.commit()

    def _backup(self, json_path):
        try:
            if not json_path.endswith("conversations.json"):
                return           # 备份文件本身不再改名
            target = json_path + ".bak"
            if os.path.exists(json_path):
                shutil.move(json_path, target)
                print("✓ 旧文件已备份为 %s" % os.path.basename(target))
        except Exception as exc:
            print("⚠️ 备份旧对话文件失败: %s" % exc)

    # ------------------------------------------------------------ 对话元数据

    def load_all(self):
        """返回 {id: 元数据字典}，不带消息（消息按需再取）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM conversations ORDER BY id"
            ).fetchall()
        out = {}
        for r in rows:
            try:
                psych = json.loads(r["psych_core"]) if r["psych_core"] else {}
            except Exception:
                psych = {}
            out[r["id"]] = {
                "title": r["title"],
                "messages": [],
                "message_count": r["message_count"] or 0,
                "custom_role_prompt": r["role_prompt"],
                "created_at": r["created_at"],
                "last_interaction_time": r["last_interaction"],
                "psych_core": psych,
                "continuity": 1 if r["continuity"] is None else int(r["continuity"]),
            }
        return out

    def create(self, conv_id, title, psych_core, role_prompt=None, continuity=1):
        with self._lock:
            now = db.now_str()
            self._conn.execute(
                "INSERT OR REPLACE INTO conversations"
                "(id, title, role_prompt, created_at, last_interaction,"
                " message_count, psych_core, extra, continuity)"
                " VALUES(?,?,?,?,?,0,?, '{}', ?)",
                (conv_id, title, role_prompt, now, now,
                 json.dumps(psych_core, ensure_ascii=False), 1 if continuity else 0)
            )
            self._conn.commit()

    def set_continuity(self, conv_id, continuity):
        with self._lock:
            self._conn.execute("UPDATE conversations SET continuity=? WHERE id=?",
                               (1 if continuity else 0, conv_id))
            self._conn.commit()

    # ------------------------------------------------------------ 用户级状态

    def get_user_state(self):
        """跨对话的关系与心情。整个软件只有这一份。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT psych_core FROM user_state WHERE id=1").fetchone()
        if not row or not row["psych_core"]:
            return {}
        try:
            return json.loads(row["psych_core"])
        except Exception:
            return {}

    def save_user_state(self, state):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO user_state(id, psych_core, updated_at)"
                " VALUES(1, ?, ?)",
                (json.dumps(state or {}, ensure_ascii=False), db.now_str())
            )
            self._conn.commit()

    def save_meta(self, conv_id, conv):
        """只回写元数据，不碰消息。"""
        if conv is None:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE conversations SET title=?, role_prompt=?, last_interaction=?,"
                " psych_core=? WHERE id=?",
                (conv.get("title"), conv.get("custom_role_prompt"),
                 conv.get("last_interaction_time") or db.now_str(),
                 json.dumps(conv.get("psych_core") or {}, ensure_ascii=False),
                 conv_id)
            )
            self._conn.commit()

    def delete(self, conv_id):
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
            self._conn.execute("DELETE FROM summaries WHERE conv_id=?", (conv_id,))
            self._conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
            self._conn.commit()

    def next_id(self):
        row = self._conn.execute("SELECT MAX(id) AS m FROM conversations").fetchone()
        return (row["m"] or 0) + 1

    # ------------------------------------------------------------ 消息

    def load_messages(self, conv_id, limit=None):
        with self._lock:
            if limit:
                rows = self._conn.execute(
                    "SELECT id, role, content FROM messages WHERE conv_id=? "
                    "ORDER BY id DESC LIMIT ?", (conv_id, limit)
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = self._conn.execute(
                    "SELECT id, role, content FROM messages WHERE conv_id=? ORDER BY id",
                    (conv_id,)
                ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def append_message(self, conv_id, role, content, tokens=0):
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(conv_id, role, content, created_at, tokens)"
                " VALUES(?,?,?,?,?)", (conv_id, role, content, db.now_str(), tokens)
            )
            self._conn.execute(
                "UPDATE conversations SET message_count=message_count+1,"
                " last_interaction=? WHERE id=?",
                (db.now_str(), conv_id)
            )
            self._conn.commit()
            return cur.lastrowid

    def messages_to_summarize(self, conv_id, keep_recent=20, batch=24):
        """还没被摘要覆盖、又不在"最近保留区"里的旧消息。"""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(covered_upto), 0) AS c FROM summaries WHERE conv_id=?",
            (conv_id,)
        ).fetchone()
        covered = row["c"] or 0

        rows = self._conn.execute(
            "SELECT id, role, content FROM messages WHERE conv_id=? AND id>? AND id NOT IN ("
            "  SELECT id FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?"
            ") ORDER BY id LIMIT ?",
            (conv_id, covered, conv_id, keep_recent, batch)
        ).fetchall()
        return [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]

    def mark_summarized(self, conv_id, upto_id):
        with self._lock:
            self._conn.execute(
                "UPDATE summaries SET covered_upto=MAX(covered_upto, ?) WHERE conv_id=?",
                (upto_id, conv_id)
            )
            self._conn.commit()

    def message_total_tokens(self, conv_id):
        row = self._conn.execute(
            "SELECT SUM(tokens) AS t FROM messages WHERE conv_id=?", (conv_id,)
        ).fetchone()
        return row["t"] or 0

    def old_message_tokens(self, conv_id, keep_recent):
        """除最近 keep_recent 条之外，其余消息的 token 合计。"""
        row = self._conn.execute(
            "SELECT SUM(tokens) AS t FROM messages WHERE conv_id=? AND id NOT IN ("
            " SELECT id FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?)",
            (conv_id, conv_id, keep_recent)
        ).fetchone()
        return row["t"] or 0

    # ------------------------------------------------------------ 摘要

    def summaries(self, conv_id, limit=3):
        rows = self._conn.execute(
            "SELECT content FROM summaries WHERE conv_id=? ORDER BY id DESC LIMIT ?",
            (conv_id, limit)
        ).fetchall()
        return [r["content"] for r in reversed(rows)]

    def add_summary(self, conv_id, content, covered_upto=0):
        with self._lock:
            self._conn.execute(
                "INSERT INTO summaries(conv_id, content, covered_upto, created_at)"
                " VALUES(?,?,?,?)", (conv_id, content, covered_upto, db.now_str())
            )
            self._conn.commit()
