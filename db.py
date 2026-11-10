# -*- coding: utf-8 -*-
"""SQLite 数据层：对话、消息、摘要、长期记忆共用同一个库文件。

为什么换掉 conversations.json：
- 它每次 `add_message` 都要把**整个文件**重写一遍，聊天越长越慢（几千条时单次
  保存几十毫秒，且随条数线性增长）；
- 所有记忆、心理状态、消息混在一个 dict 里，想按话题检索只能全量遍历。

SQLite 这边：追加一条消息是 O(1)；记忆有索引和全文检索；进程崩了也不会把
整份历史写坏（WAL）。
"""
import os
import re
import sqlite3
import threading
from datetime import datetime

__all__ = ["connect", "init_db", "now_str", "bigrams", "build_match_query",
           "concepts_of", "concept_terms", "SCHEMA_VERSION"]

SCHEMA_VERSION = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    k TEXT PRIMARY KEY,
    v TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id                INTEGER PRIMARY KEY,
    title             TEXT,
    role_prompt       TEXT,
    created_at        TEXT,
    last_interaction  TEXT,
    message_count     INTEGER DEFAULT 0,
    psych_core        TEXT,
    extra             TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id    INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT,
    tokens     INTEGER DEFAULT 0,
    -- 'proactive' = 她主动开口的那条；空 = 普通回复
    kind       TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id, id);

CREATE TABLE IF NOT EXISTS summaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id      INTEGER NOT NULL,
    content      TEXT NOT NULL,
    covered_upto INTEGER DEFAULT 0,
    created_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sum_conv ON summaries(conv_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id       INTEGER,
    kind          TEXT NOT NULL,
    mkey          TEXT,
    content       TEXT NOT NULL,
    importance    REAL DEFAULT 5,
    confidence    REAL DEFAULT 0.6,
    status        TEXT DEFAULT 'active',
    superseded_by INTEGER,
    created_at    TEXT,
    updated_at    TEXT,
    last_used_at  TEXT,
    use_count     INTEGER DEFAULT 0,
    pad_p         REAL,
    pad_a         REAL,
    pad_d         REAL,
    search        TEXT,
    scope         TEXT DEFAULT 'conv',
    concept       TEXT,
    event_at      TEXT,
    -- 512 维 float32 的语义向量（bge-small-zh）。没有模型时留空，检索退回关键词。
    embedding     BLOB
);
CREATE INDEX IF NOT EXISTS idx_mem_conv ON memories(conv_id, status);
CREATE INDEX IF NOT EXISTS idx_mem_key  ON memories(conv_id, mkey, status);

-- 用户级状态：关系、心情、对方最近的情绪。跨对话的「连续性」全在这张表里。
CREATE TABLE IF NOT EXISTS user_state (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    psych_core TEXT,
    updated_at TEXT
);

-- 她自己的日子。一天一行，entries 是这一天里若干条「几点在做什么」。
-- 按天存而不是按次存，是因为她要能回答「你今天上午干嘛了」这类问题，
-- 而不是只有「刚才在做什么」。
CREATE TABLE IF NOT EXISTS daily_life (
    day        TEXT PRIMARY KEY,
    weather    TEXT,
    mood       TEXT,
    entries    TEXT,
    thought    TEXT,
    thought_used INTEGER DEFAULT 0,
    gen_count  INTEGER DEFAULT 0,
    gen_at     TEXT,
    created_at TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(search);
"""


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def connect(db_path):
    """打开连接（每线程一个，WAL 模式，避免长事务卡住 UI）。"""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=8000")
    except sqlite3.Error:
        pass
    return conn


def init_db(db_path):
    """建表 + 迁移；返回连接。"""
    conn = connect(db_path)
    with conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        cur = conn.execute("SELECT v FROM meta WHERE k='schema'")
        row = cur.fetchone()
        if row is None:
            conn.execute("INSERT INTO meta(k, v) VALUES('schema', ?)",
                         (str(SCHEMA_VERSION),))
        elif row["v"] != str(SCHEMA_VERSION):
            conn.execute("UPDATE meta SET v=? WHERE k='schema'", (str(SCHEMA_VERSION),))
    return conn


def _columns(conn, table):
    try:
        return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
    except sqlite3.Error:
        return set()


def _migrate(conn):
    """给旧库补列。必须幂等，而且要在建索引之前——旧表还没有这些列。"""
    cols = _columns(conn, "memories")
    for name, decl in (("scope", "TEXT DEFAULT 'conv'"),
                       ("concept", "TEXT"),
                       ("event_at", "TEXT"),
                       ("embedding", "BLOB")):
        if name not in cols:
            conn.execute("ALTER TABLE memories ADD COLUMN %s %s" % (name, decl))

    mcols = _columns(conn, "messages")
    if "kind" not in mcols:
        conn.execute("ALTER TABLE messages ADD COLUMN kind TEXT")

    ccols = _columns(conn, "conversations")
    if "continuity" not in ccols:
        conn.execute("ALTER TABLE conversations ADD COLUMN continuity INTEGER DEFAULT 1")

    conn.execute("UPDATE memories SET scope='conv' WHERE scope IS NULL")
    conn.execute("UPDATE conversations SET continuity=1 WHERE continuity IS NULL")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope ON memories(scope, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_event ON memories(event_at)")


# ---------------------------------------------------------------- 概念 / 同义词
#
# 不上向量模型也能跨过"上班 vs 工作"这道坎：中文的日常近义词其实高度集中在
# 十来个大类里。每类给一组代表词，查询命中任意一个就把整组词都拿去检索，
# 命中的记忆再按"同概念"加一点分。零下载、零依赖、查询仍是 5ms 级。

CONCEPTS = {
    "work": ("工作", "上班", "职业", "公司", "单位", "打工", "加班", "同事", "老板",
             "领导", "离职", "辞职", "跳槽", "面试", "工资", "薪水", "项目", "实习",
             "简历", "offer", "部门", "开会"),
    "study": ("学习", "考试", "学校", "上课", "老师", "论文", "作业", "毕业", "考研",
              "专业", "课程", "复习", "成绩", "自学"),
    "health": ("身体", "健康", "生病", "医院", "看病", "吃药", "失眠", "睡不着",
               "头疼", "锻炼", "运动", "减肥", "感冒", "体检", "熬夜"),
    "emotion": ("难过", "开心", "焦虑", "压力", "烦", "累", "委屈", "孤独", "害怕",
                "生气", "兴奋", "低落", "抑郁", "崩溃", "放松", "踏实"),
    "family": ("家人", "爸爸", "妈妈", "父母", "老婆", "老公", "孩子", "家里",
               "弟弟", "妹妹", "哥哥", "姐姐", "亲戚"),
    "social": ("朋友", "聚会", "同学", "社交", "约会", "聊天", "室友", "邻居"),
    "hobby": ("游戏", "电影", "音乐", "看书", "读书", "旅行", "摄影", "动漫",
              "咖啡", "猫", "狗", "健身", "追剧", "画画"),
    "plan": ("计划", "打算", "准备", "目标", "约定", "下周", "明天", "周末",
             "今年", "以后", "将来"),
    "money": ("钱", "存款", "房租", "花销", "理财", "买房", "买车", "贷款"),
    "home": ("住在", "搬家", "城市", "房子", "租房", "老家", "小区"),
}

#: 词 → 概念，反查用
_WORD_TO_CONCEPT = {}
for _key, _words in CONCEPTS.items():
    for _w in _words:
        _WORD_TO_CONCEPT.setdefault(_w, _key)


def concepts_of(text):
    """这句话落在哪几个概念上（写入记忆时打标签用）。"""
    text = (text or "").lower()
    return {key for key, words in CONCEPTS.items()
            if any(w.lower() in text for w in words)}


def concept_terms(text):
    """查询扩展：命中一个词，就把同组的其他说法也带上。"""
    text = (text or "").lower()
    extra = []
    for key, words in CONCEPTS.items():
        if any(w.lower() in text for w in words):
            extra.extend(words)
    seen, out = set(), []
    for w in extra:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


# ---------------------------------------------------------------- 检索用分词

_LATIN = re.compile(r"[a-zA-Z][a-zA-Z0-9_+#.-]*")
_CJK = re.compile(r"[\u4e00-\u9fff]+")
#: 没有信息量、不该参与检索的虚词（只在整词级别剔除）
_STOP = {
    "的", "了", "是", "我", "你", "他", "她", "它", "在", "有", "和", "就",
    "都", "也", "很", "太", "吗", "呢", "吧", "啊", "呀", "哦", "嗯",
    "什么", "怎么", "这个", "那个", "一个", "我们", "你们", "他们",
}


def bigrams(text):
    """把中文切成二元组、英文按词切，作为检索 token。

    用二元组而不是整句，是因为 FTS5 的 unicode61 会把一整句中文当成一个词，
    「咖啡」这种短查询永远匹配不上。二元组能救回这类短词召回。
    """
    text = (text or "").lower()
    tokens = []

    for word in _LATIN.findall(text):
        if len(word) >= 2:
            tokens.append(word)

    for run in _CJK.findall(text):
        if len(run) == 1:
            if run not in _STOP:
                tokens.append(run)
            continue
        # 整词也放进去，命中时权重更高
        if run not in _STOP and len(run) <= 6:
            tokens.append(run)
        for i in range(len(run) - 1):
            pair = run[i:i + 2]
            if pair in _STOP:
                continue
            tokens.append(pair)

    seen, out = set(), []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_match_query(text, limit=32, extra=()):
    """检索串 → FTS5 MATCH 表达式；没有可用词时返回空串。

    extra 是查询扩展词（同概念的其他说法）——"上班"会带上"工作/公司/加班"，
    这样字面不同、意思相同的记忆也能被捞出来。
    """
    tokens = bigrams(text)
    for word in extra or ():
        tokens.extend(bigrams(word))
    seen, uniq = set(), []
    for t in tokens:
        if t and t not in seen:
            seen.add(t)
            uniq.append(t)
    if not uniq:
        return ""
    return " OR ".join('"%s"' % t.replace('"', '""') for t in uniq[:limit])


def thread_local_connection(db_path):
    """每个线程一个连接（sqlite3 连接不能跨线程随便用）。"""
    local = threading.local()

    def get():
        conn = getattr(local, "conn", None)
        if conn is None:
            conn = init_db(db_path)
            local.conn = conn
        return conn

    return get
