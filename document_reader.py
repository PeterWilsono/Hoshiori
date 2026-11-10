# -*- coding: utf-8 -*-
"""文档读取：把用户上传的文件变成纯文本，喂给模型。

设计原则
--------
1. **零依赖**：docx / xlsx / pptx 本质都是 zip + XML，用标准库解析就够了。
   不引入 python-docx（会连带 lxml），也不引入 openpyxl——桌面软件多 20MB
   换不来什么。只有 .doc（97-2003 老格式）和 .pdf 需要外部能力，见下。
2. **不猜**：读不出来就明确告诉用户「这是二进制/加密/需要 Word」，而不是
   把一堆乱码塞进对话，让模型对着乱码瞎编。
3. **有上限**：文档再长也只取前 N 万字，并返回 truncated 标记，前端会提示。
   否则一份 300 页的 Word 能把上下文一次打满。
"""

import os
import re
import zipfile

#: 单个文档最多取多少字符（约 4~6 万 token，够一份长报告）
MAX_CHARS = 60000

#: 表格单表最多取多少行
MAX_ROWS = 800

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".log", ".csv", ".tsv", ".json", ".xml",
    ".yaml", ".yml", ".ini", ".toml", ".py", ".js", ".ts", ".html", ".htm",
    ".css", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".sql", ".sh", ".bat",
}

#: 给文件对话框用的分组（顺序即显示顺序）
#: Tk 的 filetypes 多个通配符之间要用空格（Windows 下分号不会展开）
FILETYPES = [
    ("Word 文档", "*.docx *.docm *.doc"),
    ("文本 / 代码", "*.txt *.md *.markdown *.log *.csv *.tsv *.json *.xml "
                    "*.yaml *.yml *.ini *.toml *.py *.js *.ts *.html *.css "
                    "*.java *.c *.cpp *.h *.go *.rs *.sql *.sh *.bat"),
    ("Excel 表格", "*.xlsx *.xlsm"),
    ("PPT 演示", "*.pptx"),
    ("PDF", "*.pdf"),
    ("所有文件", "*.*"),
]

_KIND_LABEL = {
    ".docx": "Word 文档", ".docm": "Word 文档", ".doc": "Word 文档",
    ".xlsx": "Excel 表格", ".xlsm": "Excel 表格",
    ".pptx": "PPT 演示", ".pdf": "PDF",
}


class DocumentError(Exception):
    """读不出来，且原因可以原样告诉用户。"""


# ------------------------------------------------------------------ 工具
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _tidy(text):
    """压缩空行：转换出来的文档常常一堆连续空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_bytes(raw):
    """按常见编码试，全失败就 replace（宁可丢几个字也不要报错）。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        # 解出来一堆控制字符说明猜错了，继续试下一个
        if text.count("\x00") > len(text) * 0.01:
            continue
        return text
    return raw.decode("utf-8", errors="replace")


def _looks_binary(head):
    if b"\x00" in head[:4096]:
        return True
    printable = sum(1 for b in head[:4096] if 32 <= b < 127 or b in (9, 10, 13) or b >= 128)
    return printable < len(head[:4096]) * 0.85


# ------------------------------------------------------------------ Word
def _docx_paragraph_text(p):
    parts = []
    for node in p.iter():
        tag = _local(node.tag)
        if tag == "t":
            parts.append(node.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag in ("br", "cr"):
            parts.append("\n")
        elif tag == "noBreakHyphen":
            parts.append("-")
    return "".join(parts)


def _docx_table_text(tbl):
    lines = []
    for tr in tbl.findall(_W + "tr"):
        cells = []
        for tc in tr.findall(_W + "tc"):
            cell = " ".join(
                _docx_paragraph_text(p).strip()
                for p in tc.findall(_W + "p")
            ).strip()
            cells.append(cell)
        line = " | ".join(cells).strip(" |")
        if line.strip(" |"):
            lines.append(line)
    return "\n".join(lines)


def _docx_walk(container, out):
    """按文档顺序取段落与表格；sdt（内容控件）结构里还套着一层。"""
    for child in container:
        tag = _local(child.tag)
        if tag == "p":
            text = _docx_paragraph_text(child)
            if text.strip():
                out.append(text)
        elif tag == "tbl":
            text = _docx_table_text(child)
            if text.strip():
                out.append(text)
        elif tag in ("sdt", "sdtContent", "body"):
            _docx_walk(child, out)


def _read_docx(path):
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise DocumentError("这个文件里没有正文（可能是别的格式改了后缀）")
            xml = zf.read("word/document.xml")

            # 页眉页脚里也常有关键信息，但放正文后面避免打断阅读
            extras = []
            for name in sorted(names):
                if re.match(r"word/(header|footer)\d*\.xml$", name):
                    extras.append((name, zf.read(name)))
    except zipfile.BadZipFile:
        raise DocumentError("文件已损坏，或者不是真正的 .docx")

    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise DocumentError("Word 正文解析失败（XML 不完整）")

    body = root.find(_W + "body")
    out = []
    if body is not None:
        _docx_walk(body, out)

    text = _tidy("\n".join(out))

    # 页眉页脚：去重后补一小段
    heads = set()
    for _name, data in extras:
        try:
            sub = ET.fromstring(data)
        except ET.ParseError:
            continue
        parts = []
        _docx_walk(sub, parts)
        for part in parts:
            part = part.strip()
            if part and part not in text and part not in heads:
                heads.add(part)
    if heads:
        text += "\n\n（页眉页脚）\n" + "\n".join(list(heads)[:10])

    return text


def _read_doc(path):
    """97-2003 的 .doc 是 OLE 复合文档，纯标准库啃不下来。

    装了 Word 就借它转一道；没装就给明确建议，别硬读成乱码。
    """
    tmp = None
    try:
        import win32com.client as win32  # pywin32 已经在依赖里
        import pythoncom
    except Exception:
        win32 = None

    if win32 is not None:
        try:
            pythoncom.CoInitialize()
            word = win32.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = False
            doc = None
            try:
                doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True,
                                          AddToRecentFiles=False)
                return _tidy(doc.Content.Text)
            finally:
                if doc is not None:
                    doc.Close(False)
                word.Quit()
                pythoncom.CoUninitialize()
        except Exception as exc:
            print("⚠️ 用 Word 打开 .doc 失败: %s" % exc)

    raise DocumentError(
        "旧版 .doc 需要本机安装 Word 才能读取。"
        "请用 Word 打开后「另存为」.docx（或 .txt）再上传。"
    )


# ------------------------------------------------------------------ Excel
def _col_index(ref):
    """A1 → 0，用于把稀疏的空单元格位置补齐。"""
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    if not letters:
        return 0
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _read_xlsx(path):
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(_S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(_S + "t")))

        sheets = [n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
        sheets.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))

        out = []
        for sheet in sheets[:8]:
            root = ET.fromstring(zf.read(sheet))
            out.append("【工作表 %s】" % os.path.basename(sheet).replace(".xml", ""))
            rows_taken = 0
            for row in root.iter(_S + "row"):
                cells = []
                for c in row.findall(_S + "c"):
                    ctype = c.get("t")
                    if ctype == "inlineStr":
                        val = "".join(t.text or "" for t in c.iter(_S + "t"))
                    elif ctype == "s":
                        v = c.find(_S + "v")
                        try:
                            val = shared[int(v.text)] if v is not None else ""
                        except (ValueError, IndexError):
                            val = ""
                    else:
                        v = c.find(_S + "v")
                        val = v.text if v is not None and v.text else ""
                        if ctype == "b":
                            val = "TRUE" if val == "1" else "FALSE"
                    cells.append((_col_index(c.get("r", "")), val))
                if not cells:
                    continue
                width = max(i for i, _ in cells) + 1
                line = [""] * width
                for i, val in cells:
                    if 0 <= i < width:
                        line[i] = (val or "").replace("\n", " ").strip()
                joined = "\t".join(line).rstrip()
                if joined.strip():
                    out.append(joined)
                    rows_taken += 1
                if rows_taken >= MAX_ROWS:
                    out.append("…（表格太长，只取了前 %d 行）" % MAX_ROWS)
                    break
    return _tidy("\n".join(out))


# ------------------------------------------------------------------ PPT
def _read_pptx(path):
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        slides = [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        slides.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        if not slides:
            raise DocumentError("这个 PPT 里没有幻灯片")

        out = []
        for i, name in enumerate(slides, 1):
            root = ET.fromstring(zf.read(name))
            lines = []
            for p in root.iter(_A + "p"):
                text = "".join(t.text or "" for t in p.iter(_A + "t")).strip()
                if text:
                    lines.append(text)
            if lines:
                out.append("【第 %d 页】\n%s" % (i, "\n".join(lines)))
    return _tidy("\n\n".join(out))


# ------------------------------------------------------------------ PDF
def _read_pdf(path):
    for mod in ("pypdf", "PyPDF2"):
        try:
            module = __import__(mod)
            reader = module.PdfReader(path)
            pages = []
            for i, page in enumerate(reader.pages[:120], 1):
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if text.strip():
                    pages.append("【第 %d 页】\n%s" % (i, text.strip()))
            if not pages:
                raise DocumentError(
                    "这份 PDF 没有文字层（多半是扫描件或图片），"
                    "需要先做 OCR。建议从原文档导出文字版，或截图后另存。"
                )
            return _tidy("\n\n".join(pages))
        except DocumentError:
            raise
        except ImportError:
            continue
        except Exception as exc:
            raise DocumentError("PDF 解析失败：%s" % exc)

    raise DocumentError(
        "读取 PDF 需要额外的解析组件（pypdf），当前版本没有内置。"
        "可以先在阅读器里「另存为文本」，或直接把内容复制到输入框。"
    )


# ------------------------------------------------------------------ 主入口
def read_document(path):
    """把一个文件读成文本。

    返回 dict：text / kind / truncated / original_chars / warning
    失败抛 DocumentError（message 可以直接给用户看）。
    """
    if not path or not os.path.isfile(path):
        raise DocumentError("文件不存在")

    ext = os.path.splitext(path)[1].lower()
    kind = _KIND_LABEL.get(ext, "文本文件")

    if ext in (".docx", ".docm"):
        text = _read_docx(path)
    elif ext == ".doc":
        text = _read_doc(path)
    elif ext in (".xlsx", ".xlsm"):
        text = _read_xlsx(path)
    elif ext == ".pptx":
        text = _read_pptx(path)
    elif ext == ".pdf":
        text = _read_pdf(path)
    elif ext == ".xls":
        raise DocumentError(
            "旧版 .xls 需要 Excel 才能读取，请在 Excel 里「另存为」.xlsx 再上传。"
        )
    elif ext == ".ppt":
        raise DocumentError(
            "旧版 .ppt 需要 PowerPoint 才能读取，请另存为 .pptx 再上传。"
        )
    else:
        with open(path, "rb") as f:
            raw = f.read()
        if _looks_binary(raw[:4096]):
            raise DocumentError(
                "这个文件是二进制格式，当前只支持文本、Word(.docx)、"
                "Excel(.xlsx)、PPT(.pptx) 和 PDF。"
            )
        text = _decode_bytes(raw)
        kind = "文本文件"

    text = _tidy(text or "")
    if not text:
        raise DocumentError("这个文件里没有可读的文字（可能是空文档或纯图片）")

    original = len(text)
    truncated = original > MAX_CHARS
    warning = ""
    if truncated:
        text = text[:MAX_CHARS]
        warning = "文档较长，只取前 %d 字（原文 %d 字）" % (MAX_CHARS, original)

    return {
        "text": text,
        "kind": kind,
        "truncated": truncated,
        "original_chars": original,
        "warning": warning,
    }


__all__ = ["read_document", "DocumentError", "FILETYPES", "MAX_CHARS"]
