"""Document operations shared by the Editor and the batch Tools.

Every function works on a pymupdf.Document (or file paths) and has no Qt dependency,
so it can be used from the GUI, the batch processor and the folder monitor alike.
"""
import datetime as _dt
import html as _html
import os
import re

import pymupdf as fitz

PAPER = {
    "A3": fitz.paper_size("a3"), "A4": fitz.paper_size("a4"), "A5": fitz.paper_size("a5"),
    "Letter": fitz.paper_size("letter"), "Legal": fitz.paper_size("legal"),
}
MM = 72 / 25.4
ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


# ---------------------------------------------------------------- helpers
def parse_ranges(spec, count):
    """'1-3,5,8-', 'all', 'odd', 'even', 'last', '' -> sorted 0-based indices."""
    spec = (spec or "").strip().lower()
    if spec in ("", "all", "*"):
        return list(range(count))
    if spec == "odd":
        return list(range(0, count, 2))
    if spec == "even":
        return list(range(1, count, 2))
    out = []
    for part in re.split(r"[,\s;]+", spec):
        if not part:
            continue
        part = part.replace("last", str(count))
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a else 1
            b = int(b) if b else count
            if a > b:
                out.extend(range(a, b - 1, -1))
            else:
                out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    seen, res = set(), []
    for p in out:
        if 1 <= p <= count and p not in seen:
            seen.add(p)
            res.append(p - 1)
    return res


def hex_to_rgb(h):
    h = (h or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(c):
    if not c:
        return "#000000"
    return "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in c[:3])


def is_rtl(text):
    return bool(ARABIC_RE.search(text or ""))


def html_text(text, fontsize=12, color="#000000", align="left", bold=False, italic=False,
              font_family="sans-serif"):
    """Build HTML/CSS for insert_htmlbox; handles Arabic (RTL + shaping) automatically."""
    rtl = is_rtl(text)
    if rtl and align == "left":
        align = "right"
    body = "<br>".join(_html.escape(line) for line in (text or "").split("\n"))
    css = (f"* {{font-family: {font_family}; font-size: {fontsize}px; color: {color}; "
           f"text-align: {align}; margin: 0; padding: 0; line-height: 1.25;"
           f"{' font-weight: bold;' if bold else ''}{' font-style: italic;' if italic else ''}}}")
    d = ' dir="rtl"' if rtl else ""
    return f"<div{d}>{body}</div>", css


def insert_text_box(page, rect, text, fontsize=12, color="#000000", align="left", opacity=1.0,
                    bold=False, italic=False, rotate=0, overlay=True, font_family="sans-serif"):
    html, css = html_text(text, fontsize, color, align, bold, italic, font_family)
    rect = fitz.Rect(rect)
    res = page.insert_htmlbox(rect, html, css=css, opacity=opacity, rotate=rotate,
                              overlay=overlay, scale_low=0)
    return res


def expand_tokens(text, page_no, page_count, filename="", bates=None, author=""):
    now = _dt.datetime.now()
    return (text.replace("{page}", str(page_no))
            .replace("{pages}", str(page_count))
            .replace("{date}", now.strftime("%Y-%m-%d"))
            .replace("{time}", now.strftime("%H:%M"))
            .replace("{file}", os.path.splitext(os.path.basename(filename))[0])
            .replace("{author}", author or "")
            .replace("{bates}", bates or ""))


def load_annot(doc, pno, xref):
    """Load an annotation and keep its page alive (PyMuPDF unbinds annots when the page is freed)."""
    page = doc[pno]
    a = page.load_annot(xref)
    if a is not None:
        a._page_ref = page
    return a


# ---------------------------------------------------------------- pages
def rotate_pages(doc, pages, angle):
    for i in pages:
        p = doc[i]
        p.set_rotation((p.rotation + angle) % 360)


def delete_pages(doc, pages):
    pages = sorted(set(pages))
    if len(pages) >= doc.page_count:
        raise ValueError("Cannot delete every page of a document.")
    doc.delete_pages(pages)


def extract_pages(doc, pages):
    out = fitz.open()
    for i in pages:
        out.insert_pdf(doc, from_page=i, to_page=i)
    return out


def insert_blank(doc, at, count=1, size=None):
    if size is None:
        ref = doc[min(max(at - 1, 0), doc.page_count - 1)] if doc.page_count else None
        w, h = (ref.rect.width, ref.rect.height) if ref else PAPER["A4"]
    else:
        w, h = PAPER.get(size, PAPER["A4"])
    for k in range(count):
        doc.new_page(pno=at + k, width=w, height=h)


def insert_file(doc, path, at, password=None):
    src = open_any(path, password)
    doc.insert_pdf(src, start_at=at)
    n = src.page_count
    src.close()
    return n


def duplicate_pages(doc, pages):
    for i in sorted(pages, reverse=True):
        doc.fullcopy_page(i, i + 1)


def reorder(doc, order):
    doc.select(order)


def reverse_pages(doc):
    doc.select(list(range(doc.page_count - 1, -1, -1)))


def crop_pages(doc, pages, left=0, top=0, right=0, bottom=0):
    """Margins in millimetres, measured on the page as displayed."""
    for i in pages:
        p = doc[i]
        mb = p.mediabox
        r = fitz.Rect(mb.x0 + left * MM, mb.y0 + top * MM, mb.x1 - right * MM, mb.y1 - bottom * MM)
        if r.is_empty or r.width < 10 or r.height < 10:
            raise ValueError("Crop margins are larger than the page.")
        p.set_cropbox(r)


def _baked_copy(doc):
    """Copy with comments/form fields burned in, so page-imposing keeps them visible."""
    c = fitz.open("pdf", doc.tobytes())
    try:
        c.bake()
    except Exception:
        pass
    return c


def resize_pages(doc, size_name, pages=None):
    """Scale content of the selected pages onto a new paper size. Returns a new document."""
    w, h = PAPER[size_name]
    pages = set(pages if pages is not None else range(doc.page_count))
    doc = _baked_copy(doc)
    out = fitz.open()
    for i in range(doc.page_count):
        src = doc[i]
        if i not in pages:
            out.insert_pdf(doc, from_page=i, to_page=i)
            continue
        pw, ph = (h, w) if src.rect.width > src.rect.height else (w, h)
        np_ = out.new_page(width=pw, height=ph)
        np_.show_pdf_page(np_.rect, doc, i)
    return out


def nup(doc, per_sheet=2, size_name="A4"):
    w, h = PAPER[size_name]
    cols, rows = {2: (2, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 9: (3, 3), 16: (4, 4)}[per_sheet]
    if per_sheet in (2, 8):
        w, h = h, w  # landscape sheet
    doc = _baked_copy(doc)
    out = fitz.open()
    cw, ch = w / cols, h / rows
    page = None
    for i in range(doc.page_count):
        k = i % per_sheet
        if k == 0:
            page = out.new_page(width=w, height=h)
        c, r = k % cols, k // cols
        cell = fitz.Rect(c * cw, r * ch, (c + 1) * cw, (r + 1) * ch) + (6, 6, -6, -6)
        page.show_pdf_page(cell, doc, i)
    return out


def split_doc(doc, mode="every", value="1"):
    """mode: 'every' (N pages each), 'ranges' ('1-3;4-9'), 'bookmarks' (top-level), 'size' (MB, approx)."""
    parts = []
    n = doc.page_count
    if mode == "every":
        step = max(1, int(value or 1))
        for s in range(0, n, step):
            parts.append(list(range(s, min(n, s + step))))
    elif mode == "ranges":
        for chunk in re.split(r"[;|]", value):
            idx = parse_ranges(chunk, n)
            if idx:
                parts.append(idx)
    elif mode == "bookmarks":
        toc = [t for t in doc.get_toc() if t[0] == 1 and t[2] > 0]
        starts = sorted({t[2] - 1 for t in toc})
        if not starts or starts[0] != 0:
            starts = [0] + starts
        for a, b in zip(starts, starts[1:] + [n]):
            parts.append(list(range(a, b)))
    else:
        raise ValueError(mode)
    return [extract_pages(doc, p) for p in parts], parts


def merge_files(paths, add_bookmarks=True):
    out = fitz.open()
    toc = []
    for p in paths:
        src = open_any(p)
        start = out.page_count
        out.insert_pdf(src)
        if add_bookmarks:
            toc.append([1, os.path.splitext(os.path.basename(p))[0], start + 1])
            for lvl, title, pg, *_ in src.get_toc():
                if pg > 0:
                    toc.append([lvl + 1, title, start + pg])
        src.close()
    if add_bookmarks and toc:
        try:
            out.set_toc(toc)
        except Exception:
            out.set_toc([t for t in toc if t[0] == 1])
    return out


def is_blank_page(page, threshold=0.995):
    if page.get_text("text").strip():
        return False
    if page.get_images() or page.get_drawings():
        pix = page.get_pixmap(matrix=fitz.Matrix(0.3, 0.3), colorspace=fitz.csGRAY)
        s = pix.samples
        white = sum(1 for b in s if b > 240)
        return white / max(1, len(s)) >= threshold
    return True


def delete_blank_pages(doc):
    blanks = [i for i in range(doc.page_count) if is_blank_page(doc[i])]
    if blanks and len(blanks) < doc.page_count:
        doc.delete_pages(blanks)
    return len(blanks)


# ---------------------------------------------------------------- marks
def _text_stamp_doc(text, fontsize, color, opacity, bold=True):
    """One-page PDF that contains only `text`, sized tightly; used for rotated watermarks."""
    lines = text.split("\n")
    longest = max(len(l) for l in lines) or 1
    w = max(50, longest * fontsize * 0.62 + 20)
    h = len(lines) * fontsize * 1.35 + 20
    d = fitz.open()
    p = d.new_page(width=w, height=h)
    insert_text_box(p, p.rect + (10, 10, -10, -10), text, fontsize, color, "center", opacity, bold=bold)
    return d


def watermark(doc, text, fontsize=60, color="#9CA3AF", opacity=0.3, angle=45, pages=None,
              position="center", behind=False):
    stamp = _text_stamp_doc(text, fontsize, color, opacity)
    sw, sh = stamp[0].rect.width, stamp[0].rect.height
    for i in (pages if pages is not None else range(doc.page_count)):
        page = doc[i]
        r = page.rect
        import math
        a = math.radians(angle % 180)
        bw = abs(sw * math.cos(a)) + abs(sh * math.sin(a))
        bh = abs(sw * math.sin(a)) + abs(sh * math.cos(a))
        scale = min(1.0, (r.width * 0.9) / bw, (r.height * 0.9) / bh)
        bw, bh = bw * scale, bh * scale
        cx = r.x0 + r.width / 2
        cy = {"top": r.y0 + bh / 2 + 20, "bottom": r.y1 - bh / 2 - 20}.get(position, r.y0 + r.height / 2)
        target = fitz.Rect(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
        # show_pdf_page uses the unrotated page space; undo page rotation
        target = target * page.derotation_matrix
        page.show_pdf_page(target.normalize(), stamp, 0, rotate=angle + page.rotation, overlay=not behind)
    stamp.close()


def image_watermark(doc, image_path, scale=0.5, pages=None, behind=False):
    for i in (pages if pages is not None else range(doc.page_count)):
        page = doc[i]
        r = page.rect
        w, h = r.width * scale, r.height * scale
        target = fitz.Rect(r.x0 + (r.width - w) / 2, r.y0 + (r.height - h) / 2,
                           r.x0 + (r.width + w) / 2, r.y0 + (r.height + h) / 2)
        page.insert_image(target * page.derotation_matrix, filename=image_path,
                          keep_proportion=True, overlay=not behind, rotate=page.rotation)


def header_footer(doc, header=("", "", ""), footer=("", "", ""), fontsize=9, color="#374151",
                  margin_mm=10, pages=None, start=1, filename="", bates_prefix="", bates_start=1,
                  bates_digits=6, author=""):
    pages = list(pages if pages is not None else range(doc.page_count))
    total = doc.page_count
    m = margin_mm * MM
    for k, i in enumerate(pages):
        page = doc[i]
        r = page.rect
        bates = f"{bates_prefix}{str(bates_start + k).zfill(bates_digits)}"
        band_h = fontsize * 2.2
        for texts, top in ((header, True), (footer, False)):
            y0 = r.y0 + m if top else r.y1 - m - band_h
            for txt, align, frac in zip(texts, ("left", "center", "right"), (0, 1, 2)):
                if not txt:
                    continue
                s = expand_tokens(txt, start + k, total + start - 1, filename, bates, author)
                third = (r.width - 2 * m) / 3
                box = fitz.Rect(r.x0 + m + frac * third, y0, r.x0 + m + (frac + 1) * third, y0 + band_h)
                if align == "left":
                    box.x1 = r.x1 - m
                if align == "right":
                    box.x0 = r.x0 + m
                html, css = html_text(s, fontsize, color, align)
                page.insert_htmlbox(box * page.derotation_matrix, html, css=css,
                                    rotate=page.rotation)


def page_numbers(doc, fmt="Page {page} of {pages}", position="bottom-center", fontsize=10,
                 color="#374151", pages=None, start=1):
    vpos, hpos = position.split("-")
    slot = {"left": 0, "center": 1, "right": 2}[hpos]
    texts = ["", "", ""]
    texts[slot] = fmt
    if vpos == "top":
        header_footer(doc, header=tuple(texts), fontsize=fontsize, color=color, pages=pages, start=start)
    else:
        header_footer(doc, footer=tuple(texts), fontsize=fontsize, color=color, pages=pages, start=start)


def background_color(doc, color="#FFFBEB", pages=None):
    rgb = hex_to_rgb(color)
    for i in (pages if pages is not None else range(doc.page_count)):
        p = doc[i]
        p.draw_rect(p.mediabox, color=None, fill=rgb, overlay=False)


# ---------------------------------------------------------------- comments
STAMPS = ["Approved", "Not Approved", "Draft", "Final", "Confidential", "For Comment",
          "Received", "Reviewed", "Void", "Completed", "Paid", "Urgent"]
STAMP_COLORS = {"Approved": "#15803D", "Completed": "#15803D", "Paid": "#15803D", "Final": "#15803D",
                "Not Approved": "#B91C1C", "Void": "#B91C1C", "Urgent": "#B91C1C", "Confidential": "#B91C1C"}


def stamp_pixmap(label, author="", dynamic=True, color=None, image_path=None):
    """Render a stamp (rounded frame + label [+ author/date]) into a transparent pixmap."""
    if image_path:
        return fitz.Pixmap(image_path)
    color = color or STAMP_COLORS.get(label, "#1D4ED8")
    rgb = hex_to_rgb(color)
    w = max(160, len(label) * 15 + 40)
    h = 92 if dynamic else 56
    s = fitz.open()
    p = s.new_page(width=w, height=h)
    p.draw_rect(p.rect + (3, 3, -3, -3), color=rgb, width=3, radius=0.12)
    up = label if is_rtl(label) else label.upper()
    insert_text_box(p, (8, 8, w - 8, 40), up, 22, color, "center", bold=True)
    if dynamic:
        insert_text_box(p, (8, 42, w - 8, 60), _dt.datetime.now().strftime("%Y-%m-%d  %H:%M"), 10, color, "center")
        if author:
            insert_text_box(p, (8, 60, w - 8, 82), author, 10, color, "center")
    pix = p.get_pixmap(dpi=220, alpha=True)
    s.close()
    return pix


def rotate_pixmap(pix, deg):
    d = fitz.open()
    p = d.new_page(width=pix.width, height=pix.height)
    p.insert_image(p.rect, pixmap=pix)
    p.set_rotation(deg)
    out = p.get_pixmap(alpha=True, dpi=72)
    d.close()
    return out


def add_stamp(page, rect, label, author="", dynamic=True, color=None, image_path=None):
    pix = stamp_pixmap(label, author, dynamic, color, image_path)
    rect = fitz.Rect(rect)
    # keep stamp aspect ratio inside the given rect
    ar = pix.width / pix.height
    if rect.width / max(rect.height, 1) > ar:
        nw = rect.height * ar
        rect = fitz.Rect(rect.x0, rect.y0, rect.x0 + nw, rect.y1)
    else:
        nh = rect.width / ar
        rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + nh)
    if page.rotation:
        pix = rotate_pixmap(pix, (360 - page.rotation) % 360)
    a = page.add_stamp_annot(rect * page.derotation_matrix, stamp=pix)
    a.set_info(title=author, subject="Stamp", content=label)
    a.update()
    return a


def flatten(doc, annots=True, widgets=True):
    doc.bake(annots=annots, widgets=widgets)


def delete_annotations(doc, pages=None, keep_links=True):
    n = 0
    for i in (pages if pages is not None else range(doc.page_count)):
        p = doc[i]
        for a in list(p.annots()):
            p.delete_annot(a)
            n += 1
        if not keep_links:
            for l in p.get_links():
                p.delete_link(l)
    return n


def list_comments(doc):
    out = []
    for i in range(doc.page_count):
        page = doc[i]
        for a in page.annots():
            info = a.info
            out.append(dict(page=i, xref=a.xref, type=a.type[1], author=info.get("title", ""),
                            content=info.get("content", ""), date=info.get("modDate", "") or info.get("creationDate", ""),
                            rect=tuple(a.rect), color=rgb_to_hex((a.colors or {}).get("stroke"))))
    return out


def _pdf_date(s):
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", s or "")
    if not m:
        return ""
    y, mo, d, hh, mm = m.groups()
    return f"{y}-{mo}-{d}" + (f" {hh}:{mm}" if hh else "")


def summarize_comments(doc, title="Comments summary"):
    rows = list_comments(doc)
    parts = [f"<html><head><meta charset='utf-8'><title>{_html.escape(title)}</title>",
             "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#1F2937}"
             "h1{font-size:22px}table{border-collapse:collapse;width:100%}"
             "td,th{border:1px solid #E5E7EB;padding:6px 8px;text-align:start;vertical-align:top;font-size:13px}"
             "th{background:#F3F4F6}.sw{display:inline-block;width:10px;height:10px;border-radius:2px}</style></head><body>",
             f"<h1>{_html.escape(title)}</h1><p>{len(rows)} comments</p>",
             "<table><tr><th>Page</th><th>Type</th><th>Author</th><th>Date</th><th>Text</th></tr>"]
    for r in rows:
        txt = r["content"]
        if not txt and r["type"] in ("Highlight", "Underline", "StrikeOut", "Squiggly"):
            try:
                txt = "“" + doc[r["page"]].get_textbox(fitz.Rect(r["rect"])).strip() + "”"
            except Exception:
                txt = ""
        parts.append(f"<tr><td>{r['page'] + 1}</td><td><span class='sw' style='background:{r['color']}'></span> "
                     f"{r['type']}</td><td>{_html.escape(r['author'])}</td><td>{_pdf_date(r['date'])}</td>"
                     f"<td dir='auto'>{_html.escape(txt)}</td></tr>")
    parts.append("</table></body></html>")
    return "".join(parts)


# ---------------------------------------------------------------- security
PERMS = {
    "print": fitz.PDF_PERM_PRINT, "print_hq": fitz.PDF_PERM_PRINT_HQ, "modify": fitz.PDF_PERM_MODIFY,
    "copy": fitz.PDF_PERM_COPY, "annotate": fitz.PDF_PERM_ANNOTATE, "forms": fitz.PDF_PERM_FORM,
    "accessibility": fitz.PDF_PERM_ACCESSIBILITY, "assemble": fitz.PDF_PERM_ASSEMBLE,
}


def encryption_kwargs(user_pw="", owner_pw="", allow=("print", "print_hq", "copy", "annotate", "forms", "accessibility")):
    perm = 0
    for k in allow:
        perm |= PERMS[k]
    owner_pw = owner_pw or user_pw
    if not owner_pw:
        raise ValueError("A password is required.")
    return dict(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user_pw or "", owner_pw=owner_pw, permissions=perm)


def sanitize(doc, metadata=True, javascript=True, attachments=True, hidden_text=True, links=False):
    doc.scrub(metadata=metadata, xml_metadata=metadata, javascript=javascript, attached_files=attachments,
              embedded_files=attachments, hidden_text=hidden_text, remove_links=links, reset_fields=False,
              reset_responses=False, thumbnails=True, redactions=True, clean_pages=True)


def redact_text(doc, needle, pages=None, case_sensitive=False, fill="#000000"):
    n = 0
    for i in (pages if pages is not None else range(doc.page_count)):
        p = doc[i]
        hits = p.search_for(needle) if case_sensitive else p.search_for(needle, flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for r in hits:
            p.add_redact_annot(r, fill=hex_to_rgb(fill))
            n += 1
        if hits:
            p.apply_redactions()
    return n


REDACT_PATTERNS = {
    "Email addresses": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "Phone numbers": r"(?:\+?\d[\d\s().-]{7,}\d)",
    "Dates": r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b",
    "URLs": r"https?://\S+",
}


def redact_pattern(doc, pattern, pages=None, fill="#000000"):
    rx = re.compile(pattern)
    n = 0
    for i in (pages if pages is not None else range(doc.page_count)):
        p = doc[i]
        text = p.get_text("text")
        found = set(m.group(0).strip() for m in rx.finditer(text))
        for s in found:
            for r in p.search_for(s):
                p.add_redact_annot(r, fill=hex_to_rgb(fill))
                n += 1
        if found:
            p.apply_redactions()
    return n


# ---------------------------------------------------------------- optimise / props
def compress(doc, dpi=150, quality=70):
    try:
        doc.rewrite_images(dpi_threshold=dpi + 30, dpi_target=dpi, quality=quality)
    except Exception:
        pass
    try:
        doc.subset_fonts()
    except Exception:
        pass


SAVE_OPTIMIZED = dict(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True, use_objstms=1)


def set_properties(doc, **kw):
    md = dict(doc.metadata or {})
    for k in ("title", "author", "subject", "keywords", "creator", "producer"):
        if k in kw and kw[k] is not None:
            md[k] = kw[k]
    doc.set_metadata(md)


def add_attachment(doc, path, desc=""):
    with open(path, "rb") as f:
        doc.embfile_add(os.path.basename(path), f.read(), filename=os.path.basename(path), desc=desc)


def page_labels_roman_front(doc, front_pages):
    labels = []
    if front_pages > 0:
        labels.append({"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1})
    labels.append({"startpage": front_pages, "prefix": "", "style": "D", "firstpagenum": 1})
    doc.set_page_labels(labels)


# ---------------------------------------------------------------- open / convert
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".jxr", ".pnm", ".pgm", ".ppm"}
TEXT_EXT = {".txt", ".md", ".markdown", ".html", ".htm"}
OFFICE_EXT = {".doc", ".docx", ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp"}
NATIVE_EXT = {".pdf", ".xps", ".oxps", ".epub", ".cbz", ".fb2", ".mobi", ".svg"}


def open_any(path, password=None):
    """Open PDF or convert any supported file into a PDF document in memory."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        d = fitz.open(path)
        if d.needs_pass and not d.authenticate(password or ""):
            raise PermissionError(f"Password required: {os.path.basename(path)}")
        return d
    if ext in IMAGE_EXT:
        return images_to_pdf([path])
    if ext in TEXT_EXT:
        return text_to_pdf(path)
    if ext in OFFICE_EXT:
        from . import convert
        return fitz.open(convert.office_to_pdf(path))
    d = fitz.open(path)
    if d.is_pdf:
        return d
    pdf = fitz.open("pdf", d.convert_to_pdf())
    d.close()
    return pdf


def images_to_pdf(paths, page_size=None, margin_mm=0):
    out = fitz.open()
    for p in paths:
        img = fitz.open(p)
        for k in range(img.page_count):  # multi-frame TIFF
            ir = img[k].rect
            if page_size:
                w, h = PAPER[page_size]
                if ir.width > ir.height:
                    w, h = h, w
            else:
                w, h = ir.width, ir.height
            page = out.new_page(width=w, height=h)
            m = margin_mm * MM
            pdfbytes = img.convert_to_pdf(k, k + 1)
            src = fitz.open("pdf", pdfbytes)
            page.show_pdf_page(page.rect + (m, m, -m, -m), src, 0)
            src.close()
        img.close()
    return out


def text_to_pdf(path, fontsize=11):
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    if ext in (".md", ".markdown"):
        try:
            import markdown
            body = markdown.markdown(raw, extensions=["tables", "fenced_code"])
        except ImportError:
            body = "<pre>" + _html.escape(raw) + "</pre>"
    elif ext in (".html", ".htm"):
        body = raw
    else:
        body = "<pre style='white-space: pre-wrap'>" + _html.escape(raw) + "</pre>"
    d = "rtl" if is_rtl(raw[:2000]) else "ltr"
    css = (f"body {{font-family: sans-serif; font-size: {fontsize}pt; line-height: 1.4; direction: {d}}} "
           "h1{font-size:20pt} h2{font-size:16pt} h3{font-size:13pt} pre,code{font-family: monospace} "
           "table{border-collapse: collapse} td,th{border: 1px solid #999; padding: 3px}")
    story = fitz.Story(html=f"<body dir='{d}'>{body}</body>", user_css=css)
    buf = fitz.io.BytesIO() if hasattr(fitz, "io") else __import__("io").BytesIO()
    writer = fitz.DocumentWriter(buf)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (54, 54, -54, -54)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return fitz.open("pdf", buf.getvalue())


def to_images(doc, outdir, base, dpi=150, fmt="png", pages=None, jpg_quality=90):
    os.makedirs(outdir, exist_ok=True)
    files = []
    for i in (pages if pages is not None else range(doc.page_count)):
        pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
        fn = os.path.join(outdir, f"{base}_p{i + 1:03d}.{fmt}")
        if fmt in ("jpg", "jpeg"):
            pix.save(fn, jpg_quality=jpg_quality)
        else:
            pix.save(fn)
        files.append(fn)
    return files


def to_text(doc, pages=None):
    return "\n\f".join(doc[i].get_text("text", sort=True) for i in (pages if pages is not None else range(doc.page_count)))


def to_html(doc):
    parts = ["<html><head><meta charset='utf-8'></head><body style='background:#ddd'>"]
    for p in doc:
        parts.append("<div style='background:white;margin:12px auto;width:fit-content'>" + p.get_text("html") + "</div>")
    parts.append("</body></html>")
    return "".join(parts)


def extract_images(doc, outdir, base):
    os.makedirs(outdir, exist_ok=True)
    seen, files = set(), []
    for i in range(doc.page_count):
        for img in doc[i].get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                info = doc.extract_image(xref)
            except Exception:
                continue
            fn = os.path.join(outdir, f"{base}_p{i + 1:03d}_{xref}.{info['ext']}")
            with open(fn, "wb") as f:
                f.write(info["image"])
            files.append(fn)
    return files


def doc_info(doc, path=None):
    md = doc.metadata or {}
    info = {
        "File": path or "",
        "Size": f"{os.path.getsize(path) / 1024:,.1f} KB" if path and os.path.exists(path) else "",
        "Pages": doc.page_count,
        "PDF version": md.get("format", ""),
        "Title": md.get("title", ""), "Author": md.get("author", ""), "Subject": md.get("subject", ""),
        "Keywords": md.get("keywords", ""), "Creator": md.get("creator", ""), "Producer": md.get("producer", ""),
        "Created": _pdf_date(md.get("creationDate", "")), "Modified": _pdf_date(md.get("modDate", "")),
        "Encrypted": md.get("encryption") or "No",
        "Page size": f"{doc[0].rect.width / MM:.0f} × {doc[0].rect.height / MM:.0f} mm" if doc.page_count else "",
        "Form fields": sum(1 for p in doc for _ in p.widgets()),
        "Comments": sum(1 for p in doc for _ in p.annots()),
        "Attachments": doc.embfile_count(),
    }
    fonts = set()
    for p in doc:
        for f in p.get_fonts():
            fonts.add(f[3])
    info["Fonts"] = ", ".join(sorted(fonts)[:30])
    return info


# ---------------------------------------------------------------- compare
def compare_documents(a, b):
    """Word-level comparison. Returns (new doc = copy of B with changes marked, stats).
    Green highlight = text added in B, red strike-out notes = text removed from A."""
    import difflib
    out = fitz.open("pdf", b.tobytes())
    stats = dict(inserted=0, deleted=0, pages=0)
    for i in range(max(a.page_count, b.page_count)):
        wa = a[i].get_text("words") if i < a.page_count else []
        if i >= out.page_count:
            stats["pages"] += 1
            stats["deleted"] += len(wa)
            continue
        page = out[i]
        wb = page.get_text("words")
        sm = difflib.SequenceMatcher(None, [w[4] for w in wa], [w[4] for w in wb], autojunk=False)
        changed = False
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op in ("replace", "insert") and j2 > j1:
                for w in wb[j1:j2]:
                    h = page.add_highlight_annot(fitz.Rect(w[:4]))
                    h.set_colors(stroke=(0.55, 0.9, 0.55))
                    h.set_info(title="Compare", content="Inserted")
                    h.update()
                stats["inserted"] += j2 - j1
                changed = True
            if op in ("replace", "delete") and i2 > i1:
                removed = " ".join(w[4] for w in wa[i1:i2])
                anchor = fitz.Rect(wb[j1][:4]) if j1 < len(wb) else fitz.Rect(wa[i1][:4])
                n = page.add_text_annot(anchor.tl + (-12, -12), "Deleted: " + removed[:500], icon="Note")
                n.set_colors(stroke=(0.9, 0.3, 0.3))
                n.set_info(title="Compare", content="Deleted: " + removed[:500])
                n.update()
                stats["deleted"] += i2 - i1
                changed = True
        if changed:
            stats["pages"] += 1
    return out, stats
