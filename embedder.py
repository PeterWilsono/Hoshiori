# -*- coding: utf-8 -*-
"""本地语义向量（bge-small-zh-v1.5，ONNX，CPU）。

它只干一件事：把句子变成 512 维向量，用来做记忆检索的"意思相近"判断。
不联网、不花 token、不占用聊天模型的额度。

设计上的几个取舍：

1. **懒加载**。第一次真正要检索时才建 session（约 200~400ms），启动不受影响。
2. **失败即降级**。模型文件缺失、onnxruntime 没装、内存不足——任何一步出错都
   只是让 `available` 变 False，上层自动退回纯关键词检索，不会崩。
3. **单条长度 96 token**。记忆条目和用户这句话都在这个量级，截短能省一半时间，
   长文本的语义也基本由前半段决定。

分数校准：bge 对中文短句的余弦普遍偏高（不相关的两句也有 0.3~0.5），
所以对外给的是 `similarity()` 里做过减基线的值，不是原始余弦。
"""
import os
import threading

import numpy as np

__all__ = ["Embedder", "get_embedder", "DIM"]

DIM = 512

#: 原始余弦 → 可用相似度的基线。低于它就当"没关系"。
#: 这两个数是用真实记忆对量出来的：中文短句里毫无关系的两句余弦也在 0.29~0.44
#: （"在吗""hello"这种），真正相关的从 0.56 起。所以 0.46 以下一律算 0，
#: 0.80 以上算完全命中。
_BASE = 0.43
_SPAN = 0.32

#: BGE 官方在长文档检索时会建议给 query 加指令前缀。这里**故意不加**：
#: 记忆条目和用户那句话都是十几字的短句，是对称匹配，加了指令反而把 query
#: 拉到另一个分布（实测 top1 余弦从 0.57 掉到 0.50，区分度也更差）。
QUERY_PREFIX = ""


class Embedder:
    """一个模型实例。线程安全（session.run 本身就是并发安全的）。"""

    def __init__(self, model_dir, max_len=96, threads=0):
        self.model_dir = model_dir
        self.max_len = max_len
        self.threads = threads
        self._session = None
        self._tokenizer = None
        self._failed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 加载

    @property
    def model_path(self):
        for name in ("model_quantized.onnx", "model.onnx"):
            path = os.path.join(self.model_dir, name)
            if os.path.exists(path):
                return path
        return None

    def _load(self):
        """返回 True 表示可用。失败只记一次，不反复重试。"""
        if self._session is not None:
            return True
        if self._failed:
            return False

        with self._lock:
            if self._session is not None:
                return True
            if self._failed:
                return False
            try:
                import onnxruntime as ort
            except Exception as exc:
                print("ℹ️ 未安装 onnxruntime，语义检索关闭: %s" % exc)
                self._failed = True
                return False

            path = self.model_path
            if not path:
                print("ℹ️ 没找到语义模型（%s），退回关键词检索" % self.model_dir)
                self._failed = True
                return False

            try:
                import bert_tokenizer

                opts = ort.SessionOptions()
                # 陪伴聊天是单条短文本，线程开太多反而互相抢
                opts.intra_op_num_threads = self.threads or max(1, min(4, (os.cpu_count() or 4) // 2))
                opts.inter_op_num_threads = 1
                opts.log_severity_level = 3
                self._session = ort.InferenceSession(
                    path, sess_options=opts, providers=["CPUExecutionProvider"])
                self._inputs = {i.name for i in self._session.get_inputs()}
                self._tokenizer = bert_tokenizer.load(
                    os.path.join(self.model_dir, "vocab.txt"), self.max_len)
                if self._tokenizer is None:
                    raise RuntimeError("vocab.txt 缺失")
                # 预热：避免第一次真正检索时多花几百毫秒
                self._run(["你好"])
                print("✓ 语义检索就绪（bge-small-zh / ONNX）")
                return True
            except Exception as exc:
                print("⚠️ 语义模型加载失败，退回关键词检索: %s" % exc)
                self._session = None
                self._failed = True
                return False

    @property
    def available(self):
        return self._load()

    # ------------------------------------------------------------ 推理

    def _run(self, texts):
        ids, mask, types = self._tokenizer.batch(texts, self.max_len)
        feed = {
            "input_ids": np.asarray(ids, dtype=np.int64),
            "attention_mask": np.asarray(mask, dtype=np.int64),
        }
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.asarray(types, dtype=np.int64)
        hidden = self._session.run(None, feed)[0]
        # BGE 用 [CLS] 位置的向量做句表示
        vec = hidden[:, 0, :].astype(np.float32)
        norm = np.linalg.norm(vec, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        return vec / norm

    def encode(self, texts, is_query=False):
        """文本列表 → (n, 512) 已归一化的 float32 矩阵；不可用时返回 None。"""
        if isinstance(texts, str):
            texts = [texts]
        texts = [t or "" for t in texts]
        if not texts or not self._load():
            return None
        if is_query and QUERY_PREFIX:
            texts = [QUERY_PREFIX + t for t in texts]
        try:
            return self._run(texts)
        except Exception as exc:
            print("⚠️ 语义向量计算失败: %s" % exc)
            return None

    def encode_one(self, text, is_query=False):
        mat = self.encode([text], is_query=is_query)
        return None if mat is None else mat[0]

    # ------------------------------------------------------------ 打分

    @staticmethod
    def similarity(cos):
        """原始余弦 → 0~1。砍掉"随便两句都有的相似度"，让 0 真的表示无关。"""
        return float(max(0.0, min(1.0, (cos - _BASE) / _SPAN)))

    @staticmethod
    def cos_to_all(vec, matrix):
        """一条向量对一堆向量（已归一化）的余弦。"""
        if vec is None or matrix is None or len(matrix) == 0:
            return np.zeros(0, dtype=np.float32)
        return matrix @ vec


# ---------------------------------------------------------------- 单例

_INSTANCE = None
_INSTANCE_LOCK = threading.Lock()


def get_embedder(model_dir=None):
    """全局单例。传 None 时按打包/开发两种布局自己找。"""
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = Embedder(model_dir or default_model_dir())
    return _INSTANCE


def default_model_dir():
    try:
        import app_paths
        for base in (app_paths.resource_root(), app_paths.app_root()):
            path = os.path.join(base, "models", "bge-small-zh")
            if os.path.isdir(path):
                return path
    except Exception:
        pass
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "models", "bge-small-zh")
