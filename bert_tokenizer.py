# -*- coding: utf-8 -*-
"""BERT WordPiece 分词器（只依赖标准库）。

为什么不直接用 transformers / tokenizers：
- 那两个包加起来要几十 MB，而这里只需要"把一句话变成 id 数组"这一件事；
- 中文 BERT 词表的切法是"每字一个候选，再贪心合并"，逻辑很短，自己写反而可控。

行为对齐 HuggingFace 的 BertTokenizer（do_lower_case=True，strip_accents），
`test_embedder.py` 里拿官方 tokenizer.json 做过逐条比对。
"""
import os
import unicodedata

__all__ = ["BertTokenizer"]


def _is_whitespace(ch):
    if ch in (" ", "\t", "\n", "\r"):
        return True
    return unicodedata.category(ch) == "Zs"


def _is_control(ch):
    if ch in ("\t", "\n", "\r"):
        return False
    return unicodedata.category(ch).startswith("C")


def _is_punctuation(ch):
    cp = ord(ch)
    if 33 <= cp <= 47 or 58 <= cp <= 64 or 91 <= cp <= 96 or 123 <= cp <= 126:
        return True
    return unicodedata.category(ch).startswith("P")


def _is_cjk(cp):
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0x20000 <= cp <= 0x2A6DF or 0x2A700 <= cp <= 0x2B73F or
            0x2B740 <= cp <= 0x2B81F or 0x2B820 <= cp <= 0x2CEAF or
            0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


def _strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


class BertTokenizer:
    """加载 vocab.txt；`encode()` 返回 (input_ids, attention_mask, token_type_ids)。"""

    def __init__(self, vocab_path, do_lower_case=True, max_len=128):
        self.vocab = {}
        with open(vocab_path, "r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                self.vocab[line.rstrip("\n")] = idx
        self.lower = do_lower_case
        self.max_len = max_len
        self.unk_id = self.vocab.get("[UNK]", 100)
        self.cls_id = self.vocab.get("[CLS]", 101)
        self.sep_id = self.vocab.get("[SEP]", 102)
        self.pad_id = self.vocab.get("[PAD]", 0)

    # ------------------------------------------------------------ 基本切分

    def _basic_tokenize(self, text):
        """按空白/标点/ CJK 边界切成"词"，这是 WordPiece 之前的粗切。"""
        text = text.strip()
        if not text:
            return []
        cleaned = []
        for ch in text:
            if ch == "\u0000" or ch == "\ufffd":
                continue
            if _is_control(ch):
                continue
            if _is_whitespace(ch):
                cleaned.append(" ")
            else:
                cleaned.append(ch)
        text = "".join(cleaned)

        if self.lower:
            text = text.lower()
        text = _strip_accents(text)

        out = []
        for word in text.split():
            buf = []
            for ch in word:
                if _is_cjk(ord(ch)):
                    if buf:
                        out.append("".join(buf))
                        buf = []
                    out.append(ch)
                elif _is_punctuation(ch):
                    if buf:
                        out.append("".join(buf))
                        buf = []
                    out.append(ch)
                else:
                    buf.append(ch)
            if buf:
                out.append("".join(buf))
        return out

    def _wordpiece(self, word, max_chars=100):
        """贪心最长匹配；整词超长或含未知字符时退化成 [UNK]。"""
        if len(word) > max_chars:
            return [self.unk_id]
        ids, start = [], 0
        while start < len(word):
            end, cur = len(word), None
            while start < end:
                piece = word[start:end]
                if start > 0:
                    piece = "##" + piece
                if piece in self.vocab:
                    cur = self.vocab[piece]
                    break
                end -= 1
            if cur is None:
                return [self.unk_id]
            ids.append(cur)
            start = end
        return ids

    # ------------------------------------------------------------ 对外

    def encode(self, text, max_len=None):
        """单句 → (ids, mask, types)，已截断到 max_len。"""
        limit = (max_len or self.max_len) - 2
        ids = []
        for word in self._basic_tokenize(text or ""):
            ids.extend(self._wordpiece(word))
            if len(ids) >= limit:
                break
        ids = ids[:limit]
        full = [self.cls_id] + ids + [self.sep_id]
        return full, [1] * len(full), [0] * len(full)

    def batch(self, texts, max_len=None):
        """多句 → 等长 padding 后的三个数组。"""
        rows = [self.encode(t, max_len) for t in texts]
        width = max((len(r[0]) for r in rows), default=2)
        ids, mask, types = [], [], []
        for i, m, t in rows:
            pad = width - len(i)
            ids.append(i + [self.pad_id] * pad)
            mask.append(m + [0] * pad)
            types.append(t + [0] * pad)
        return ids, mask, types


def load(vocab_path, max_len=128):
    """vocab.txt 不存在时返回 None，调用方据此降级。"""
    if not vocab_path or not os.path.exists(vocab_path):
        return None
    try:
        return BertTokenizer(vocab_path, max_len=max_len)
    except Exception as exc:
        print("⚠️ 分词器加载失败: %s" % exc)
        return None
