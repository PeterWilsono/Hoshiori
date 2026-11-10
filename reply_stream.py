# -*- coding: utf-8 -*-
"""把 AI 的回复切成一条条可以依次弹出的短句。

两件事：
1. `split_segments()`：一次性把整段文本切成气泡（非流式路径用）。
2. `ReplyStreamer`：喂 token 片段，边生成边吐出完整气泡（流式路径用）。

切片规则刻意做得保守——太短的碎片不单独成泡，会跟后面的句子并起来；
太长的在逗号处断开。这样一屏的气泡数量接近真人打字节奏，而不是一句一个。
"""
import re

__all__ = ["split_segments", "ReplyStreamer", "DEFAULT_MAX", "DEFAULT_MIN"]
#: 单个气泡的字数上限（超过就在标点处断开）
DEFAULT_MAX = 50
#: 少于这个字数不单独成泡，等着和下一条合并
DEFAULT_MIN = 14

#: 句末标点：这些字符之后可以断句
_SENT_END = "。！？!?…～~"
#: 模型自带的 $ 分段符
_SEP = "$"

#: 判断一段是不是「心理状态 JSON」的特征字段
_JSON_MARKS = ('"pad_delta"', '"internal_monologue"', '"dominant_emotion"',
               '"relationship_delta"', '"user_intent_analysis"', '"appraisal"',
               '"memory_update"')

_COMMA = ("，", "、", ",", "；", ";")

#: 断句后紧跟的这些字符一并吞掉，避免「!」「”」单独成泡
_PUNCT_RUN = "。！？!?…～~”’』）)】」》》\"'"


def _has_words(s):
    """有没有实际的文字/数字（纯 emoji 或纯标点不该单独成泡）。"""
    return re.search(r"[0-9A-Za-z\u4e00-\u9fff]", s) is not None


def _cut_at_comma(buf, max_len):
    """在逗号处断开超长句，返回 (前半, 后半)。"""
    cut = max(buf.rfind(c) for c in _COMMA)
    if cut >= max_len // 2:
        return buf[:cut + 1], buf[cut + 1:]
    return buf, ""


def _hard_cut(text, max_len):
    """把一段文本按句末标点切成原始片段（不做长度合并）。"""
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _SENT_END or ch == "\n":
            if buf.strip():
                out.append(buf)
                buf = ""
        elif len(buf) >= max_len:
            head, buf = _cut_at_comma(buf, max_len)
            out.append(head)
    if buf.strip():
        out.append(buf)
    return [s.strip() for s in out if s.strip()]


def _pack(block, max_len, min_len):
    """把一个「硬边界」（$ 或空行）之间的文本打包成气泡。"""
    parts = _hard_cut(block, max_len)
    out, hold = [], ""
    for part in parts:
        hold = (hold + part) if hold else part
        if len(hold) >= min_len:
            out.append(hold)
            hold = ""
    if hold:
        if out and len(out[-1]) + len(hold) <= max_len * 1.6:
            out[-1] += hold
        else:
            out.append(hold)
    return out


def split_segments(text, max_len=DEFAULT_MAX, min_len=DEFAULT_MIN):
    """整段文本 → 气泡列表。

    `$` 和空行是模型明确表达的停顿，跨过它们的片段不再合并。
    """
    text = (text or "").replace("\r", "")
    out = []
    for block in re.split(r"\$|\n{2,}", text):
        if block.strip():
            out.extend(_pack(block, max_len, min_len))
    return out


class ReplyStreamer:
    """把流式 token 变成「一条一条冒出来」的气泡。

    开头那段 ```json {...}``` 心理状态块会被整块吞掉，不会漏到界面上；
    正文里正常的代码块原样保留。
    """

    def __init__(self, emit, min_len=DEFAULT_MIN, max_len=DEFAULT_MAX, patch=None):
        self._emit = emit
        self._patch = patch
        self.min_len = min_len
        self.max_len = max_len
        self.buf = ""
        self.state = "head"      # head: 判断有没有 JSON 前缀；body: 正文
        self.any_emitted = False
        self.segments = []

    # ---------------- 对外 ----------------
    def feed(self, delta):
        if not delta:
            return
        self.buf += delta
        if self.state == "head" and not self._strip_head():
            return
        self._body()

    def finish(self, final_text=None):
        """把缓冲区剩下的推出去（可能没有正文，这时用最终文本兜底）。"""
        if self.state == "head":
            self.buf = ""
            self.state = "body"

        tail = self.buf
        self.buf = ""
        if tail.strip():
            self._body(tail)

        leftover = self.buf            # _body 里又攒下来的尾巴
        self.buf = ""
        if leftover.strip():
            # 只剩一个 emoji / 标点时，补到上一条气泡尾巴上，别让它单独成泡
            if self.segments and not _has_words(leftover) and callable(self._patch):
                try:
                    self._patch(leftover.strip())
                except Exception:
                    self._push(leftover)
            else:
                self._push(leftover)

        if not self.any_emitted and final_text:
            for seg in split_segments(final_text, self.max_len, self.min_len):
                self._push(seg)
        return self.segments

    # ---------------- 内部 ----------------
    def _push(self, seg):
        seg = (seg or "").strip()
        seg = seg.lstrip(_SENT_END)      # 上一句的 !! 别跑到下一泡开头
        seg = re.sub(r"[ \t]*\n[ \t]*", "\n", seg)
        seg = re.sub(r"\n{2,}", "\n", seg)
        seg = seg.strip()
        if not seg:
            return

        # 纯 emoji / 纯标点：补到上一条气泡尾巴上，别单独占一泡
        if not _has_words(seg):
            if self.segments and callable(self._patch):
                try:
                    self._patch(seg)
                    return
                except Exception:
                    pass
            if not self.segments:
                self.buf = seg + self.buf   # 开头就是 emoji，等正文一起推
                return
        self.segments.append(seg)
        self.any_emitted = True
        try:
            self._emit(seg)
        except Exception as exc:          # 推送失败不能影响后面的生成
            print("⚠️ 气泡推送失败: %s" % exc)

    def _strip_head(self):
        """吃掉开头的 JSON 块。返回 True 表示可以处理正文了。"""
        text = self.buf.lstrip()
        if not text:
            self.buf = ""
            return False

        if text.startswith("```"):
            end = text.find("```", 3)
            if end == -1:
                self.buf = text            # 还没闭合，等
                return False
            block = text[:end + 3]
            if "{" in block:
                self.buf = text[end + 3:]
                self.state = "body"
                return True
            self.buf = text               # 不是 JSON 块，当正文
            self.state = "body"
            return True

        if text.startswith("{"):
            depth, end = 0, -1
            for i, ch in enumerate(text):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end == -1:
                if len(text) > 900:       # 明显不是我们的 JSON，别等了
                    self.buf = text
                    self.state = "body"
                    return True
                self.buf = text
                return False
            block = text[:end + 1]
            if any(mark in block for mark in _JSON_MARKS):
                self.buf = text[end + 1:]
            else:
                self.buf = text
            self.state = "body"
            return True

        self.buf = text
        self.state = "body"
        return True

    def _body(self, chunk=None):
        """切句并推送；不完整的尾巴留在 self.buf。"""
        text = self.buf if chunk is None else chunk
        if chunk is None:
            self.buf = ""

        # 正文里夹着 JSON 代码块（多数模型放在结尾）：先攒到闭合再判断
        fence = text.find("```")
        if fence != -1:
            end = text.find("```", fence + 3)
            if end == -1:
                self._emit_pieces(text[:fence])
                self.buf = self.buf + text[fence:]
                return
            block = text[fence:end + 3]
            if any(mark in block for mark in _JSON_MARKS):
                self._emit_pieces(text[:fence])
                self.buf = self.buf + text[end + 3:]
            else:
                self._emit_pieces(text[:end + 3])
                self.buf = self.buf + text[end + 3:]
            return

        self._emit_pieces(text)

    def _emit_pieces(self, text):
        buf = ""
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch == _SEP:
                if buf.strip():
                    self._push(buf)
                buf = ""
                i += 1
                continue

            buf += ch
            i += 1

            if ch in _SENT_END:
                # 吞掉紧跟的一串标点/右引号，别让「!」自己占一个气泡
                while i < n and text[i] in _PUNCT_RUN:
                    buf += text[i]
                    i += 1
                if len(buf.strip()) >= self.min_len and _has_words(buf):
                    self._push(buf)
                    buf = ""
            elif ch == "\n" and buf.endswith("\n\n"):
                if len(buf.strip()) >= 2:
                    self._push(buf)
                    buf = ""
            elif ch != "\n" and len(buf) >= self.max_len:
                head, rest = _cut_at_comma(buf, self.max_len)
                self._push(head)
                buf = rest
        if buf.strip():
            self.buf = buf + self.buf
