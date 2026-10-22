"""High-accuracy PDF -> Excel / Word conversion with proper Arabic (RTL) support.

Key points
- Arabic lam-alef ligatures are often extracted in the wrong order (e.g. "األسر" instead of "الأسر").
  PyMuPDF reports the ligature's alef as a zero-width char placed before the lam; we swap it back.
  Presentation-form glyphs (U+FB50–U+FEFF) are normalised to normal letters (NFKC).
- Tables: bordered tables come from PyMuPDF's line detection (geometry only); cell text is rebuilt from
  words so Arabic is never reversed. Borderless tables are found with a column-gutter analysis.
- Merged cells, right-to-left tables, multi-line cells, numbers / percentages / dates are handled.
- Scanned pages are OCR'd first (Tesseract) when available.
"""
import contextlib
import datetime as _dt
import os
import re
import unicodedata

import pymupdf as fitz

AR = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
ALEFS = set("اأإآ")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def has_ar(s):
    return bool(AR.search(s or ""))


def is_rtl_words(ws):
    """Majority of *alphabetic* words are Arabic (numbers/punctuation don't vote)."""
    alpha = [w for w in ws if re.search(r"[^\W\d_]", w["text"])]
    if not alpha:
        return False
    return sum(1 for w in alpha if has_ar(w["text"])) * 2 >= len(alpha)


def space_gap(words):
    """Typical inter-word gap on this page (used to tell word spaces from column gaps)."""
    gaps = []
    by_line = {}
    for w in words:
        by_line.setdefault((w["block"], w["line"]), []).append(w)
    for ws in by_line.values():
        ws = sorted(ws, key=lambda w: w["bbox"].x0)
        for a, b in zip(ws, ws[1:]):
            g = b["bbox"].x0 - a["bbox"].x1
            if 0 < g < a["size"]:
                gaps.append(g)
    return sorted(gaps)[len(gaps) // 2] if gaps else 3.0


def norm(s):
    if not s:
        return s
    if any("ﭐ" <= ch <= "﻿" for ch in s):
        s = unicodedata.normalize("NFKC", s)
    return s.replace(" ", " ")


# ------------------------------------------------------------------ rawdict repair
def fix_chars(chars):
    """Swap zero-width alef that precedes lam (broken lam-alef ligature) and normalise glyphs."""
    out = list(chars)
    i = 0
    while i < len(out) - 1:
        c, n = out[i], out[i + 1]
        if c["c"] in ALEFS and n["c"] == "ل" and (c["bbox"][2] - c["bbox"][0]) < 0.2:
            out[i], out[i + 1] = n, c
            i += 2
            continue
        i += 1
    for ch in out:
        if "ﭐ" <= ch["c"] <= "﻿":
            ch["c"] = unicodedata.normalize("NFKC", ch["c"])
    return out


def fix_rawdict(raw):
    for b in raw.get("blocks", []):
        for ln in b.get("lines", []):
            for sp in ln.get("spans", []):
                if "chars" in sp and any(has_ar(c["c"]) for c in sp["chars"]):
                    sp["chars"] = fix_chars(sp["chars"])
    return raw


_orig_get_text = fitz.Page.get_text


@contextlib.contextmanager
def arabic_fix():
    """Temporarily patch Page.get_text so other libraries (pdf2docx) receive repaired Arabic."""
    def patched(self, option="text", *a, **kw):
        res = _orig_get_text(self, option, *a, **kw)
        if option == "rawdict" and isinstance(res, dict):
            fix_rawdict(res)
        return res
    fitz.Page.get_text = patched
    try:
        yield
    finally:
        fitz.Page.get_text = _orig_get_text


# ------------------------------------------------------------------ words & lines
def page_words(page, textpage=None):
    """Words (dicts) with correct Arabic text, size, bold, colour and bbox."""
    kw = dict(flags=fitz.TEXT_MEDIABOX_CLIP | fitz.TEXT_DEHYPHENATE)
    if textpage is not None:
        kw["textpage"] = textpage
    raw = fix_rawdict(_orig_get_text(page, "rawdict", **kw))
    words = []
    for bi, b in enumerate(raw.get("blocks", [])):
        for li, ln in enumerate(b.get("lines", [])):
            if abs(ln.get("dir", (1, 0))[1]) > 0.2:
                continue  # skip rotated text (watermarks)
            for sp in ln.get("spans", []):
                cur, box = [], None
                for ch in sp["chars"] + [{"c": " ", "bbox": None}]:
                    if ch["c"].isspace():
                        if cur:
                            words.append(dict(text="".join(cur), bbox=fitz.Rect(box), size=sp["size"],
                                              bold=bool(sp["flags"] & 16) or "bold" in sp["font"].lower(),
                                              italic=bool(sp["flags"] & 2), color=sp["color"], font=sp["font"],
                                              block=bi, line=li))
                        cur, box = [], None
                        continue
                    cur.append(ch["c"])
                    r = fitz.Rect(ch["bbox"])
                    box = r if box is None else box | r
    return words


def join_words(ws, rtl=None):
    """Words -> text: group into visual lines, order each line RTL or LTR."""
    if not ws:
        return ""
    if rtl is None:
        rtl = is_rtl_words(ws)
    lines = []
    for w in sorted(ws, key=lambda w: (w["bbox"].y0 + w["bbox"].y1) / 2):
        yc = (w["bbox"].y0 + w["bbox"].y1) / 2
        h = w["bbox"].height or 1
        if lines and abs(lines[-1][0] - yc) < h * 0.5:
            lines[-1][1].append(w)
        else:
            lines.append([yc, [w]])
    out = []
    for _, lw in lines:
        lw.sort(key=lambda w: w["bbox"].x0, reverse=rtl)
        out.append(fix_rtl_punct(" ".join(w["text"] for w in lw)) if rtl else " ".join(w["text"] for w in lw))
    return "\n".join(out)


PUNCT = ".،,:;!؟?"


def fix_rtl_punct(line):
    """In RTL text, sentence punctuation is often extracted at the wrong end ('. 2026' / '2026 .')."""
    line = line.strip()
    m = re.match(r"^([%s]+)\s*(.*)$" % re.escape(PUNCT), line)
    if m and m.group(2):
        line = m.group(2) + m.group(1)
    m = re.match(r"^(.*?)\s([%s])\s(\S+)$" % re.escape(PUNCT), line)
    if m and not has_ar(m.group(3)):
        line = f"{m.group(1)} {m.group(3)}{m.group(2)}"
    return re.sub(r"\s+([%s])(?=\s|$)" % re.escape(PUNCT), r"\1", line)


# ------------------------------------------------------------------ tables
class Table:
    def __init__(self, bbox, grid, merges, rtl, page, bordered):
        self.bbox = fitz.Rect(bbox)
        self.grid = grid          # list of rows, each a list of str/None (None = covered by merge)
        self.merges = merges      # list of (r0, c0, r1, c1)
        self.rtl = rtl
        self.page = page
        self.bordered = bordered

    @property
    def ncols(self):
        return max((len(r) for r in self.grid), default=0)


def _edges(values, tol=1.5):
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _idx(edges, v, tol=1.5):
    for k, e in enumerate(edges):
        if abs(e - v) <= tol:
            return k
    return min(range(len(edges)), key=lambda k: abs(edges[k] - v))


def bordered_tables(page, words):
    out = []
    try:
        found = page.find_tables(strategy="lines").tables
    except Exception:
        found = []
    for tb in found:
        cells = [fitz.Rect(c) for c in tb.cells if c]
        if len(cells) < 2:
            continue
        xs = _edges([c.x0 for c in cells] + [c.x1 for c in cells])
        ys = _edges([c.y0 for c in cells] + [c.y1 for c in cells])
        ncol, nrow = len(xs) - 1, len(ys) - 1
        if ncol < 1 or nrow < 1:
            continue
        inside = [w for w in words if fitz.Rect(tb.bbox).contains((w["bbox"].tl + w["bbox"].br) / 2)]
        rtl = is_rtl_words(inside)
        grid = [[None] * ncol for _ in range(nrow)]
        merges = []
        filled = [[False] * ncol for _ in range(nrow)]
        size = sorted(w["size"] for w in inside)[len(inside) // 2] if inside else 10
        multi = 0
        for c in cells:
            c0, c1 = _idx(xs, c.x0), _idx(xs, c.x1) - 1
            r0, r1 = _idx(ys, c.y0), _idx(ys, c.y1) - 1
            if c1 < c0 or r1 < r0:
                continue
            if rtl:
                c0, c1 = ncol - 1 - c1, ncol - 1 - c0
            if filled[r0][c0]:
                continue
            ws = [w for w in inside if c.contains((w["bbox"].tl + w["bbox"].br) / 2)]
            if any(len(_segments(r["w"], max(space_gap(inside) * 2.2, size * 0.45))) >= 2 for r in _rows(ws)):
                multi += 1
            grid[r0][c0] = join_words(ws, rtl)
            for r in range(r0, r1 + 1):
                for cc in range(c0, c1 + 1):
                    filled[r][cc] = True
            if r1 > r0 or c1 > c0:
                merges.append((r0, c0, r1, c1))
        for r in range(nrow):
            for cc in range(ncol):
                if not filled[r][cc]:
                    grid[r][cc] = ""
        if multi > max(2, len(cells) * 0.3):
            continue  # ruling lines don't describe the real columns -> leave it to the borderless detector
        # drop fully empty rows/cols
        keep_rows = [r for r in range(nrow) if any((grid[r][c] or "") for c in range(ncol)) or any(m[0] == r for m in merges)]
        if not keep_rows:
            continue
        out.append(Table(tb.bbox, [grid[r] for r in keep_rows],
                         [(keep_rows.index(m[0]), m[1], keep_rows.index(m[2]) if m[2] in keep_rows else keep_rows.index(m[0]), m[3])
                          for m in merges if m[0] in keep_rows], rtl, page.number, True))
    return out


def _rows(words):
    rows = []
    for w in sorted(words, key=lambda w: (w["bbox"].y0 + w["bbox"].y1) / 2):
        yc = (w["bbox"].y0 + w["bbox"].y1) / 2
        if rows and abs(rows[-1]["yc"] - yc) < max(2.0, w["bbox"].height * 0.45):
            rows[-1]["w"].append(w)
            rows[-1]["y1"] = max(rows[-1]["y1"], w["bbox"].y1)
        else:
            rows.append(dict(yc=yc, y0=w["bbox"].y0, y1=w["bbox"].y1, w=[w]))
    return rows


def _segments(row_words, gap):
    ws = sorted(row_words, key=lambda w: w["bbox"].x0)
    segs = []
    for w in ws:
        if segs and w["bbox"].x0 - segs[-1]["x1"] <= gap:
            segs[-1]["w"].append(w)
            segs[-1]["x1"] = max(segs[-1]["x1"], w["bbox"].x1)
        else:
            segs.append(dict(x0=w["bbox"].x0, x1=w["bbox"].x1, w=[w]))
    return segs


def borderless_tables(page, words, min_rows=3):
    """Column-gutter analysis for tables without ruling lines."""
    if not words:
        return []
    size = sorted(w["size"] for w in words)[len(words) // 2]
    gap = max(space_gap(words) * 2.2, size * 0.45)
    rows = _rows(words)
    for r in rows:
        r["segs"] = _segments(r["w"], gap)
    tables = []
    block = []

    def flush():
        if len(block) >= min_rows or (len(block) >= 2 and max(len(r["segs"]) for r in block) >= 3):
            t = _build_borderless(page, block)
            if t:
                tables.append(t)
    lh = size * 2.6
    for r in rows:
        tablelike = len(r["segs"]) >= 2
        if tablelike and block and r["y0"] - block[-1]["y1"] > lh:
            flush()
            block = []
        if tablelike:
            block.append(r)
        elif block and len(r["segs"]) == 1 and r["y0"] - block[-1]["y1"] < size * 0.8 and len(block) >= 1:
            block.append(r)  # wrapped cell text line inside a table
        else:
            flush()
            block = []
    flush()
    return tables


def _build_borderless(page, block):
    # column clusters from segment x-ranges (only rows with >=2 segments define columns)
    ivs = sorted([(s["x0"], s["x1"]) for r in block if len(r["segs"]) >= 2 for s in r["segs"]])
    cols = []
    for a, b in ivs:
        if cols and a <= cols[-1][1] + 1:
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    if len(cols) < 2:
        return None
    words = [w for r in block for w in r["w"]]
    rtl = is_rtl_words(words)
    ncol = len(cols)
    if ncol > 20:
        return None
    grid, merges = [], []
    for r in block:
        row = [""] * ncol
        for s in r["segs"]:
            hit = [k for k, (a, b) in enumerate(cols) if s["x1"] > a and s["x0"] < b]
            if not hit:
                continue
            k0, k1 = hit[0], hit[-1]
            txt = join_words(s["w"], rtl)
            if rtl:
                k0, k1 = ncol - 1 - k1, ncol - 1 - k0
            row[k0] = (row[k0] + " " + txt).strip() if row[k0] else txt
            if k1 > k0:
                merges.append((len(grid), k0, len(grid), k1))
                for k in range(k0 + 1, k1 + 1):
                    row[k] = None
        # continuation line: key column empty and only one cell filled -> append to previous row
        filled = [k for k, v in enumerate(row) if v]
        if grid and len(filled) == 1 and not row[0] and len(r["segs"]) == 1:
            k = filled[0]
            prev = grid[-1]
            prev[k] = ((prev[k] or "") + "\n" + row[k]).strip()
            continue
        grid.append(row)
    if len(grid) < 2:
        return None
    # validate: a real table has most rows with 2+ filled cells and short-ish cells
    multi = sum(1 for r in grid if sum(1 for v in r if v) >= 2)
    if multi < max(2, len(grid) * 0.5):
        return None
    cells = [v for r in grid for v in r if v]
    if cells and sum(len(v) for v in cells) / len(cells) > 80:
        return None
    x0 = min(w["bbox"].x0 for w in words)
    x1 = max(w["bbox"].x1 for w in words)
    return Table((x0, block[0]["y0"], x1, block[-1]["y1"]), grid, merges, rtl, page.number, False)


def find_tables(page, words=None, borderless=True):
    words = words if words is not None else page_words(page)
    tabs = bordered_tables(page, words)
    if borderless:
        rest = [w for w in words if not any(t.bbox.contains((w["bbox"].tl + w["bbox"].br) / 2) for t in tabs)]
        tabs += borderless_tables(page, rest)
    tabs.sort(key=lambda t: t.bbox.y0)
    return tabs


# ------------------------------------------------------------------ values
NUM_RE = re.compile(r"^[-+(]?\d{1,3}([,٬]\d{3})+([.٫]\d+)?\)?$|^[-+(]?\d+([.٫]\d+)?\)?$")
DATE_FMTS = [("%Y-%m-%d", "yyyy-mm-dd"), ("%d/%m/%Y", "dd/mm/yyyy"), ("%d-%m-%Y", "dd-mm-yyyy"), ("%Y/%m/%d", "yyyy/mm/dd"),
             ("%d.%m.%Y", "dd.mm.yyyy")]


def convert_value(s):
    """Return (value, number_format or None)."""
    if s is None:
        return None, None
    t = s.strip().translate(AR_DIGITS)
    if not t:
        return "", None
    pct = t.endswith("%") or t.endswith("٪")
    core = t.rstrip("%٪").strip()
    cur = ""
    m = re.match(r"^([$€£]|SYP|TRY|USD)\s*(.+)$", core)
    if m:
        cur, core = m.group(1), m.group(2)
    if NUM_RE.match(core):
        digits = re.sub(r"[^\d]", "", core)
        if (len(digits) > 1 and digits.startswith("0") and not re.search(r"[.٫]", core)) or len(digits) > 15:
            return s.strip(), "@"  # IDs, phone numbers, codes keep leading zeros
        neg = core.startswith("(") and core.endswith(")") or core.startswith("-")
        num = core.strip("()+-").replace(",", "").replace("٬", "").replace("٫", ".")
        try:
            v = float(num)
        except ValueError:
            return s.strip(), None
        v = -v if neg else v
        if pct:
            return v / 100, "0.##%" if v != int(v) else "0%"
        dec = len(num.split(".")[1]) if "." in num else 0
        if v == int(v) and dec == 0:
            fmt = "#,##0" if ("," in core or "٬" in core) else "0"
            return int(v), fmt
        return v, ("#,##0." if ("," in core or "٬" in core) else "0.") + "0" * dec
    for pf, xf in DATE_FMTS:
        try:
            return _dt.datetime.strptime(t, pf), xf
        except ValueError:
            pass
    return s.strip(), None


# ------------------------------------------------------------------ OCR helper
def ocr_if_needed(doc, language="ara+eng", progress=None):
    """Return a document whose scanned pages carry an (invisible) OCR text layer, plus a flag."""
    from . import convert
    scanned = [i for i in range(doc.page_count)
               if len(doc[i].get_text("text").strip()) < 20 and (doc[i].get_images() or doc[i].get_drawings())]
    if not scanned:
        return doc, False
    langs = convert.ocr_languages()
    if not langs:
        return doc, False
    lang = "+".join(l for l in language.split("+") if l in langs) or langs[0]
    return convert.ocr_document(doc, lang, 300, scanned, progress), True


# ------------------------------------------------------------------ Excel
def pdf_to_xlsx(doc, out_path, layout="per_table", include_text=False, merge_continued=True, borderless=True,
                convert_numbers=True, pages=None, ocr=True, progress=None):
    """layout: 'per_table' | 'per_page' | 'single'. Returns dict(stats)."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    if ocr:
        doc, _ = ocr_if_needed(doc)
    pages = list(pages if pages is not None else range(doc.page_count))
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="A6A6A6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    stats = dict(tables=0, rows=0, sheets=0)
    sheet = None
    state = dict(row=1, last_cols=None, last_header=None)
    all_rtl = []

    def new_sheet(title):
        nonlocal sheet
        title = re.sub(r"[\[\]:*?/\\]", "_", title)[:31] or "Sheet"
        base, k = title, 2
        while title in wb.sheetnames:
            title = f"{base[:28]}_{k}"
            k += 1
        sheet = wb.create_sheet(title)
        stats["sheets"] += 1
        state.update(row=1, last_cols=None, last_header=None)
        return sheet

    def looks_header(row):
        vals = [v for v in row if v]
        return bool(vals) and all(convert_value(v)[1] in (None,) for v in vals)

    def write_table(t, continued=False):
        ws = sheet
        r0 = state["row"]
        rows = t.grid
        if continued and rows and state["last_header"] and [x or "" for x in rows[0]] == state["last_header"]:
            rows = rows[1:]
        header_row = None
        if not continued and rows and looks_header(rows[0]) and len(rows) > 1:
            header_row = r0
        for ri, row in enumerate(rows):
            for ci, v in enumerate(row):
                if v is None:
                    continue
                c = ws.cell(row=r0 + ri, column=ci + 1)
                if convert_numbers and not (header_row == r0 + ri):
                    val, fmt = convert_value(v)
                else:
                    val, fmt = v, None
                c.value = val
                if fmt:
                    c.number_format = fmt
                c.border = border
                c.alignment = Alignment(wrap_text=True, vertical="top",
                                        horizontal="right" if (t.rtl and isinstance(val, str)) else None)
            for ci in range(len(row)):
                ws.cell(row=r0 + ri, column=ci + 1).border = border
        shift = len(t.grid) - len(rows)
        for (a, b, c, d) in t.merges:
            a2, c2 = a - shift, c - shift
            if a2 < 0 or c2 < a2:
                continue
            if c2 > a2 or d > b:
                ws.merge_cells(start_row=r0 + a2, start_column=b + 1, end_row=r0 + c2, end_column=d + 1)
        if header_row:
            for ci in range(t.ncols):
                cell = ws.cell(row=header_row, column=ci + 1)
                cell.font = Font(bold=True)
                cell.fill = head_fill
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if header_row == 1 and ws.freeze_panes is None:
                ws.freeze_panes = "A2"
            state["last_header"] = [x or "" for x in t.grid[0]]
        state["row"] = r0 + len(rows) + (0 if layout == "single" and merge_continued else 1)
        state["last_cols"] = t.ncols
        stats["tables"] += 1
        stats["rows"] += len(rows)
        all_rtl.append(t.rtl)

    for k, pno in enumerate(pages):
        page = doc[pno]
        words = page_words(page)
        tabs = find_tables(page, words, borderless)
        if progress and not progress(k + 1, len(pages)):
            break
        items = [("t", t.bbox.y0, t) for t in tabs]
        if include_text:
            rest = [w for w in words if not any(t.bbox.contains((w["bbox"].tl + w["bbox"].br) / 2) for t in tabs)]
            for r in _rows(rest):
                items.append(("l", r["y0"], join_words(r["w"])))
        items.sort(key=lambda x: x[1])
        if layout == "per_page" and items:
            new_sheet(f"Page {pno + 1}")
        for kind, _, obj in items:
            if kind == "l":
                if sheet is None or layout == "per_table":
                    if sheet is None:
                        new_sheet(f"Page {pno + 1}")
                sheet.cell(row=state["row"], column=1, value=obj)
                state["row"] += 1
                continue
            t = obj
            continued = (layout == "single" and merge_continued and state["last_cols"] == t.ncols)
            if layout == "per_table":
                if merge_continued and sheet is not None and state["last_cols"] == t.ncols and \
                        t.page == getattr(sheet, "_last_page", -9) + 1 and t.bbox.y0 < doc[t.page].rect.height * 0.3:
                    continued = True
                else:
                    new_sheet(f"P{t.page + 1}_T{stats['tables'] + 1}")
            elif layout == "single" and sheet is None:
                new_sheet("Tables")
            write_table(t, continued)
            sheet._last_page = t.page
    if not wb.sheetnames:
        ws = new_sheet("Text")
        for pno in pages:
            for r in _rows(page_words(doc[pno])):
                ws.append([pno + 1, join_words(r["w"])])
    # column widths & direction
    for ws in wb.worksheets:
        widths = {}
        rtl_cells = 0
        total = 0
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                s = str(c.value)
                total += 1
                if has_ar(s):
                    rtl_cells += 1
                L = max(len(x) for x in s.split("\n")) if s else 0
                widths[c.column] = max(widths.get(c.column, 0), min(60, L))
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = max(8, w * 1.15 + 2)
        if total and rtl_cells * 3 >= total:
            ws.sheet_view.rightToLeft = True
    wb.save(out_path)
    return stats


# ------------------------------------------------------------------ Word
def word_available():
    import sys
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application")
        return True
    except Exception:
        return False


def pdf_to_docx_word(pdf_path, out_path):
    """Microsoft Word's own PDF reflow (best layout fidelity on Windows)."""
    import winreg
    import win32com.client
    for ver in ("16.0", "15.0"):
        try:
            k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Office\{ver}\Word\Options")
            winreg.SetValueEx(k, "DisableConvertPdfWarning", 0, winreg.REG_DWORD, 1)
        except Exception:
            pass
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        d = word.Documents.Open(FileName=os.path.abspath(pdf_path), ConfirmConversions=False, ReadOnly=True,
                                AddToRecentFiles=False, Visible=False)
        d.SaveAs2(FileName=os.path.abspath(out_path), FileFormat=16)
        d.Close(False)
    finally:
        word.Quit()
    return out_path


def pdf_to_docx_layout(pdf_path, out_path, pages=None):
    """pdf2docx (keeps layout) + Arabic ligature repair."""
    from pdf2docx import Converter
    import logging
    logging.disable(logging.WARNING)
    with arabic_fix():
        cv = Converter(pdf_path)
        try:
            cv.convert(out_path, pages=pages)
        finally:
            cv.close()
    return out_path


def _rtl_paragraph(p, rtl):
    from docx.oxml.ns import qn
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    if rtl:
        pPr = p._p.get_or_add_pPr()
        pPr.append(pPr.makeelement(qn("w:bidi"), {}))
        if p.alignment is None:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _rtl_run(run, rtl):
    from docx.oxml.ns import qn
    if rtl:
        rPr = run._r.get_or_add_rPr()
        rPr.append(rPr.makeelement(qn("w:rtl"), {}))
        # complex-script size/bold so Arabic gets the same formatting
        if run.font.size:
            sz = rPr.makeelement(qn("w:szCs"), {qn("w:val"): str(int(run.font.size.pt * 2))})
            rPr.append(sz)
        if run.font.bold:
            rPr.append(rPr.makeelement(qn("w:bCs"), {}))


def pdf_to_docx_structured(doc, out_path, pages=None, ocr=True, include_images=True, progress=None):
    """Waraq engine: accurate text, headings, RTL paragraphs and real Word tables (incl. borderless)."""
    import docx
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor, Emu
    import io

    if ocr:
        doc, _ = ocr_if_needed(doc)
    pages = list(pages if pages is not None else range(doc.page_count))
    D = docx.Document()
    st = D.styles["Normal"]
    st.font.name = "Arial"
    st.element.rPr.rFonts.set(qn("w:cs"), "Arial")
    sec = D.sections[0]
    p0 = doc[pages[0]].rect if pages else fitz.paper_rect("a4")
    sec.page_width, sec.page_height = Emu(int(p0.width * 12700)), Emu(int(p0.height * 12700))
    if p0.width > p0.height:
        sec.orientation = WD_ORIENT.LANDSCAPE
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, m, Emu(int(42 * 12700)))
    sizes = []
    for pno in pages[:5]:
        sizes += [w["size"] for w in page_words(doc[pno])]
    body = sorted(sizes)[len(sizes) // 2] if sizes else 11
    stats = dict(paragraphs=0, tables=0, images=0)

    for k, pno in enumerate(pages):
        page = doc[pno]
        words = page_words(page)
        tabs = find_tables(page, words)
        items = [("t", t.bbox.y0, t) for t in tabs]
        rest = [w for w in words if not any(t.bbox.contains((w["bbox"].tl + w["bbox"].br) / 2) for t in tabs)]
        # paragraphs = rawdict blocks (by block id), split into visual lines
        blocks = {}
        for w in rest:
            blocks.setdefault(w["block"], []).append(w)
        for bw in blocks.values():
            for para in _split_paragraphs(bw):
                items.append(("p", min(w["bbox"].y0 for w in para), para))
        if include_images:
            for info in page.get_image_info():
                r = fitz.Rect(info["bbox"]) & page.rect
                if r.width > 20 and r.height > 20 and r.width * r.height < page.rect.width * page.rect.height * 0.9:
                    items.append(("i", r.y0, r))
        items.sort(key=lambda x: x[1])
        for kind, _, obj in items:
            if kind == "p":
                bw = obj
                rtl = sum(1 for w in bw if has_ar(w["text"])) * 2 >= len(bw)
                text = join_words(bw, rtl)
                lines = text.split("\n")
                # merge wrapped lines into one paragraph (keep real line breaks for short lines)
                para_text = " ".join(l.strip() for l in lines) if len(lines) > 1 and \
                    max(len(l) for l in lines) > 40 else "\n".join(lines)
                size = sorted(w["size"] for w in bw)[len(bw) // 2]
                bold = sum(1 for w in bw if w["bold"]) * 2 > len(bw)
                color = sorted(w["color"] for w in bw)[len(bw) // 2]
                x0 = min(w["bbox"].x0 for w in bw)
                x1 = max(w["bbox"].x1 for w in bw)
                heading = size >= body * 1.25 and len(para_text) < 150
                if heading:
                    lvl = 1 if size >= body * 1.6 else 2
                    p = D.add_heading(level=lvl)
                else:
                    p = D.add_paragraph()
                cx = (x0 + x1) / 2
                if abs(cx - page.rect.width / 2) < page.rect.width * 0.06 and (x1 - x0) < page.rect.width * 0.7:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _rtl_paragraph(p, rtl)
                parts = para_text.split("\n")
                for li, part in enumerate(parts):
                    run = p.add_run(part)
                    run.font.size = Pt(round(size * 2) / 2)
                    run.font.bold = bold or None
                    if color and not heading:
                        run.font.color.rgb = RGBColor((color >> 16) & 255, (color >> 8) & 255, color & 255)
                    _rtl_run(run, rtl)
                    if li < len(parts) - 1:
                        run.add_break()
                stats["paragraphs"] += 1
            elif kind == "t":
                t = obj
                nrows, ncols = len(t.grid), t.ncols
                tbl = D.add_table(rows=nrows, cols=ncols)
                tbl.style = "Table Grid"
                if t.rtl:
                    tblPr = tbl._tbl.tblPr
                    tblPr.append(tblPr.makeelement(qn("w:bidiVisual"), {}))
                for (a, b, c, d) in t.merges:
                    try:
                        tbl.cell(a, b).merge(tbl.cell(c, d))
                    except Exception:
                        pass
                for ri, row in enumerate(t.grid):
                    for ci, v in enumerate(row):
                        if v is None:
                            continue
                        cell = tbl.cell(ri, ci)
                        cell.text = ""
                        p = cell.paragraphs[0]
                        rtl = has_ar(v) or t.rtl
                        _rtl_paragraph(p, rtl)
                        run = p.add_run(v)
                        run.font.size = Pt(max(7, min(12, body)))
                        if ri == 0 and nrows > 1 and all(convert_value(x)[1] is None for x in row if x):
                            run.font.bold = True
                        _rtl_run(run, rtl)
                D.add_paragraph()
                stats["tables"] += 1
            elif kind == "i":
                r = obj
                pix = page.get_pixmap(clip=r, dpi=200, alpha=False)
                bio = io.BytesIO(pix.tobytes("png"))
                p = D.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.add_run().add_picture(bio, width=Emu(int(min(r.width, p0.width - 84) * 12700)))
                stats["images"] += 1
        if k < len(pages) - 1:
            D.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        if progress and not progress(k + 1, len(pages)):
            break
    D.save(out_path)
    return stats


def _split_paragraphs(bw):
    """Split a text block into paragraphs where font size / weight changes or a vertical gap appears."""
    rows = _rows(bw)
    paras, cur, prev = [], [], None
    for r in rows:
        size = sorted(w["size"] for w in r["w"])[len(r["w"]) // 2]
        bold = sum(1 for w in r["w"] if w["bold"]) * 2 > len(r["w"])
        if prev is not None:
            psize, pbold, py1 = prev
            if abs(size - psize) > 0.6 or bold != pbold or r["y0"] - py1 > size * 0.9:
                paras.append(cur)
                cur = []
        cur += r["w"]
        prev = (size, bold, r["y1"])
    if cur:
        paras.append(cur)
    return paras


def postfix_docx(path):
    """Repair Arabic punctuation order in a .docx produced by another engine."""
    import docx
    d = docx.Document(path)
    paras = list(d.paragraphs)
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                paras += c.paragraphs
    changed = False
    for p in paras:
        for run in p.runs:
            if has_ar(run.text):
                for line in run.text.split("\n"):
                    pass
                new = "\n".join(fix_rtl_punct(l) if has_ar(l) else l for l in run.text.split("\n"))
                if new != run.text:
                    run.text = new
                    changed = True
    if changed:
        d.save(path)


def has_borderless_tables(doc, max_pages=5):
    for i in range(min(doc.page_count, max_pages)):
        pg = doc[i]
        w = page_words(pg)
        b = bordered_tables(pg, w)
        rest = [x for x in w if not any(t.bbox.contains((x["bbox"].tl + x["bbox"].br) / 2) for t in b)]
        if borderless_tables(pg, rest):
            return True
    return False


def is_scanned(doc, max_pages=5):
    n = min(doc.page_count, max_pages)
    return n > 0 and sum(1 for i in range(n) if len(doc[i].get_text().strip()) < 20 and doc[i].get_images()) * 2 >= n


def pdf_to_docx(pdf_path, out_path, engine="auto", pages=None, progress=None):
    """engine: 'auto' | 'word' | 'layout' | 'structured'. Returns the engine actually used."""
    doc = fitz.open(pdf_path)
    if engine == "auto":
        if is_scanned(doc):
            engine = "structured"
        elif word_available():
            engine = "word"
        elif has_borderless_tables(doc):
            engine = "structured"
        else:
            engine = "layout"
    if engine == "word":
        try:
            pdf_to_docx_word(pdf_path, out_path)
            return "word"
        except Exception:
            engine = "layout"
    if engine == "layout":
        pdf_to_docx_layout(pdf_path, out_path, pages)
        try:
            postfix_docx(out_path)
        except Exception:
            pass
        return "layout"
    pdf_to_docx_structured(doc, out_path, pages, progress=progress)
    return "structured"
