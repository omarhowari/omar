"""Batch engine (the 'PDF-Tools' part): an action library, tools = sequences of actions, and a runner.

A tool is plain JSON:
{"name": "...", "actions": [{"id": "rotate", "params": {...}}, ...],
 "output": {"folder": "", "pattern": "{name}_out", "overwrite": false, "merge": false}}
"""
import copy
import datetime as _dt
import json
import os
import re
import tempfile
import time

import pymupdf as fitz

from . import ops, convert

# ---------------------------------------------------------------- action library
# each: id -> (category, title, [params], function(doc, ctx, **params) -> doc | None)
ACTIONS = {}


def action(aid, category, title, params=()):
    def deco(fn):
        ACTIONS[aid] = dict(id=aid, category=category, title=title, params=list(params), fn=fn)
        return fn
    return deco


P_PAGES = ("pages", "Pages", "text", "all")


@action("rotate", "Pages", "Rotate pages", [P_PAGES, ("angle", "Angle", "choice", 90, [90, 180, 270])])
def _a(doc, ctx, pages, angle):
    ops.rotate_pages(doc, ops.parse_ranges(pages, doc.page_count), int(angle))


@action("rotate_landscape", "Pages", "Rotate landscape pages to portrait", [("angle", "Angle", "choice", 90, [90, 270])])
def _a(doc, ctx, angle):
    ops.rotate_pages(doc, [i for i in range(doc.page_count) if doc[i].rect.width > doc[i].rect.height], int(angle))


@action("delete_pages", "Pages", "Delete pages", [("pages", "Pages", "text", "1")])
def _a(doc, ctx, pages):
    ops.delete_pages(doc, ops.parse_ranges(pages, doc.page_count))


@action("keep_pages", "Pages", "Keep only pages", [("pages", "Pages", "text", "1-3")])
def _a(doc, ctx, pages):
    doc.select(ops.parse_ranges(pages, doc.page_count))


@action("reverse", "Pages", "Reverse page order")
def _a(doc, ctx):
    ops.reverse_pages(doc)


@action("insert_blank", "Pages", "Insert blank pages", [("where", "Where", "choice", "end", ["start", "end", "after_each"]),
                                                       ("count", "Count", "int", 1, (1, 100))])
def _a(doc, ctx, where, count):
    if where == "start":
        ops.insert_blank(doc, 0, count)
    elif where == "end":
        ops.insert_blank(doc, doc.page_count, count)
    else:
        for i in range(doc.page_count - 1, -1, -1):
            ops.insert_blank(doc, i + 1, count)


@action("insert_file", "Pages", "Insert pages from file (cover, annex)", [("file", "File", "file_open", ""),
                                                                          ("where", "Where", "choice", "start", ["start", "end"])])
def _a(doc, ctx, file, where):
    if file:
        ops.insert_file(doc, file, 0 if where == "start" else doc.page_count)


@action("delete_blank", "Pages", "Delete blank pages")
def _a(doc, ctx):
    n = ops.delete_blank_pages(doc)
    ctx["notes"].append(f"{n} blank pages removed")


@action("crop", "Pages", "Crop margins (mm)", [P_PAGES, ("left", "Left", "float", 10), ("top", "Top", "float", 10),
                                              ("right", "Right", "float", 10), ("bottom", "Bottom", "float", 10)])
def _a(doc, ctx, pages, left, top, right, bottom):
    ops.crop_pages(doc, ops.parse_ranges(pages, doc.page_count), left, top, right, bottom)


@action("resize", "Pages", "Resize pages to paper", [("size", "Paper", "choice", "A4", list(ops.PAPER))])
def _a(doc, ctx, size):
    return ops.resize_pages(doc, size)


@action("nup", "Pages", "N-up (pages per sheet)", [("n", "Per sheet", "choice", 2, [2, 4, 6, 8, 9, 16]),
                                                    ("size", "Sheet", "choice", "A4", list(ops.PAPER))])
def _a(doc, ctx, n, size):
    return ops.nup(doc, int(n), size)


@action("watermark", "Content", "Text watermark", [("text", "Text", "text", "CONFIDENTIAL"), ("size", "Font size", "int", 60),
                                                  ("color", "Color", "color", "#9CA3AF"), ("opacity", "Opacity %", "int", 30),
                                                  ("angle", "Angle", "int", 45), ("behind", "Behind content", "bool", False), P_PAGES])
def _a(doc, ctx, text, size, color, opacity, angle, behind, pages):
    ops.watermark(doc, ops.expand_tokens(text, 1, doc.page_count, ctx["src"]), size, color, opacity / 100, angle,
                  ops.parse_ranges(pages, doc.page_count), behind=behind)


@action("image_watermark", "Content", "Image watermark / logo", [("image", "Image", "file_open", ""),
                                                                ("scale", "Scale (0-1)", "float", 0.4),
                                                                ("behind", "Behind content", "bool", True), P_PAGES])
def _a(doc, ctx, image, scale, behind, pages):
    if image:
        ops.image_watermark(doc, image, scale, ops.parse_ranges(pages, doc.page_count), behind)


@action("header_footer", "Content", "Header & footer", [("hl", "Header left", "text", ""), ("hc", "Header center", "text", ""),
                                                       ("hr", "Header right", "text", "{date}"), ("fl", "Footer left", "text", "{file}"),
                                                       ("fc", "Footer center", "text", ""), ("fr", "Footer right", "text", "{page} / {pages}"),
                                                       ("size", "Font size", "int", 9), ("color", "Color", "color", "#374151"), P_PAGES])
def _a(doc, ctx, hl, hc, hr, fl, fc, fr, size, color, pages):
    ops.header_footer(doc, (hl, hc, hr), (fl, fc, fr), size, color, pages=ops.parse_ranges(pages, doc.page_count),
                      filename=ctx["src"], author=ctx.get("author", ""))


@action("page_numbers", "Content", "Page numbers", [("fmt", "Format", "text", "Page {page} of {pages}"),
                                                   ("pos", "Position", "choice", "bottom-center",
                                                    ["bottom-center", "bottom-right", "bottom-left", "top-center", "top-right", "top-left"]),
                                                   ("size", "Font size", "int", 10), ("start", "Start", "int", 1)])
def _a(doc, ctx, fmt, pos, size, start):
    ops.page_numbers(doc, fmt, pos, size, start=start)


@action("bates", "Content", "Bates numbering (continues across files)", [("prefix", "Prefix", "text", "DOC-"),
                                                                        ("start", "Start", "int", 1), ("digits", "Digits", "int", 6),
                                                                        ("pos", "Position", "choice", "right", ["left", "center", "right"])])
def _a(doc, ctx, prefix, start, digits, pos):
    n = ctx["state"].setdefault("bates", start)
    footer = {"left": ("{bates}", "", ""), "center": ("", "{bates}", ""), "right": ("", "", "{bates}")}[pos]
    ops.header_footer(doc, footer=footer, bates_prefix=prefix, bates_start=n, bates_digits=digits)
    ctx["state"]["bates"] = n + doc.page_count


@action("background", "Content", "Background color", [("color", "Color", "color", "#FFFBEB"), P_PAGES])
def _a(doc, ctx, color, pages):
    ops.background_color(doc, color, ops.parse_ranges(pages, doc.page_count))


@action("stamp", "Content", "Stamp", [("label", "Stamp", "choice", "Approved", ops.STAMPS), ("dynamic", "Add date", "bool", True),
                                      ("page", "Page (0 = all)", "int", 1), ("corner", "Corner", "choice", "top-right",
                                                                              ["top-right", "top-left", "bottom-right", "bottom-left"])])
def _a(doc, ctx, label, dynamic, page, corner):
    targets = range(doc.page_count) if page == 0 else [min(page, doc.page_count) - 1]
    for i in targets:
        p = doc[i]
        r = p.rect
        w, h = 170, 70
        x = r.x1 - w - 30 if "right" in corner else r.x0 + 30
        y = r.y0 + 30 if "top" in corner else r.y1 - h - 30
        ops.add_stamp(p, fitz.Rect(x, y, x + w, y + h) * p.derotation_matrix, label, ctx.get("author", ""), dynamic)


@action("flatten", "Comments & forms", "Flatten comments and form fields")
def _a(doc, ctx):
    ops.flatten(doc)


@action("delete_annots", "Comments & forms", "Delete all comments")
def _a(doc, ctx):
    ops.delete_annotations(doc)


@action("fill_form", "Comments & forms", "Fill form fields from JSON", [("file", "JSON file", "file_open", "")])
def _a(doc, ctx, file):
    data = json.load(open(file, encoding="utf-8"))
    for p in doc:
        for w in p.widgets():
            if w.field_name in data:
                w.field_value = data[w.field_name]
                w.update()


@action("summarize_comments", "Comments & forms", "Export comments summary (HTML)")
def _a(doc, ctx):
    fn = os.path.join(ctx["outdir"], ctx["base"] + "_comments.html")
    open(fn, "w", encoding="utf-8").write(ops.summarize_comments(doc, ctx["base"]))
    ctx["outputs"].append(fn)


@action("encrypt", "Security", "Protect with password", [("user", "Open password", "text", ""),
                                                        ("owner", "Permissions password", "text", "owner"),
                                                        ("print", "Allow print", "bool", True), ("copy", "Allow copy", "bool", False),
                                                        ("modify", "Allow edit", "bool", False)])
def _a(doc, ctx, user, owner, print, copy, modify):
    allow = ["accessibility", "forms", "annotate"] + (["print", "print_hq"] if print else []) + \
            (["copy"] if copy else []) + (["modify", "assemble"] if modify else [])
    ctx["save_kw"].update(ops.encryption_kwargs(user, owner, allow))


@action("remove_security", "Security", "Remove security (needs password if any)")
def _a(doc, ctx):
    ctx["save_kw"].pop("encryption", None)


@action("sanitize", "Security", "Sanitize (metadata, JavaScript, attachments, hidden text)")
def _a(doc, ctx):
    ops.sanitize(doc)


@action("redact_text", "Security", "Redact words", [("words", "Words (separate with ;)", "text", "")])
def _a(doc, ctx, words):
    n = sum(ops.redact_text(doc, w.strip()) for w in words.split(";") if w.strip())
    ctx["notes"].append(f"{n} redactions")


@action("redact_patterns", "Security", "Redact emails / phones / dates", [("email", "Emails", "bool", True), ("phone", "Phones", "bool", True),
                                                                         ("dates", "Dates", "bool", False)])
def _a(doc, ctx, email, phone, dates):
    n = 0
    for on, k in ((email, "Email addresses"), (phone, "Phone numbers"), (dates, "Dates")):
        if on:
            n += ops.redact_pattern(doc, ops.REDACT_PATTERNS[k])
    ctx["notes"].append(f"{n} redactions")


@action("sign", "Security", "Digitally sign", [("pfx", "Digital ID", "file_open", ""), ("password", "Password", "text", ""),
                                              ("reason", "Reason", "text", "Approved"), ("tsa", "Timestamp URL", "text", "")])
def _a(doc, ctx, pfx, password, reason, tsa):
    ctx["sign"] = dict(pfx=pfx, password=password, reason=reason, tsa=tsa)


@action("compress", "Optimize", "Compress / optimize", [("dpi", "Image dpi", "choice", 150, [72, 96, 120, 150, 200, 300]),
                                                       ("quality", "JPEG quality", "int", 70)])
def _a(doc, ctx, dpi, quality):
    ops.compress(doc, int(dpi), quality)
    ctx["save_kw"].update(ops.SAVE_OPTIMIZED)


@action("properties", "Optimize", "Set document properties", [("title", "Title", "text", "{file}"), ("author", "Author", "text", ""),
                                                             ("subject", "Subject", "text", ""), ("keywords", "Keywords", "text", "")])
def _a(doc, ctx, title, author, subject, keywords):
    f = lambda s: ops.expand_tokens(s, 1, doc.page_count, ctx["src"]) if s else None
    ops.set_properties(doc, title=f(title), author=f(author), subject=f(subject), keywords=f(keywords))


@action("bookmarks_files", "Optimize", "Add bookmark with file name")
def _a(doc, ctx):
    toc = doc.get_toc()
    doc.set_toc([[1, ctx["base"], 1]] + [[l + 1, t, p] for l, t, p in toc])


@action("attach", "Optimize", "Attach a file", [("file", "File", "file_open", "")])
def _a(doc, ctx, file):
    if file:
        ops.add_attachment(doc, file)


@action("ocr", "Convert", "OCR — make searchable", [("lang", "Languages", "text", "ara+eng"), ("dpi", "dpi", "choice", 300, [200, 300, 400])])
def _a(doc, ctx, lang, dpi):
    return convert.ocr_document(doc, lang, int(dpi))


@action("to_images", "Convert", "Export pages as images", [("fmt", "Format", "choice", "png", ["png", "jpg"]),
                                                           ("dpi", "dpi", "choice", 150, [72, 96, 150, 200, 300, 600])])
def _a(doc, ctx, fmt, dpi):
    ctx["outputs"] += ops.to_images(doc, os.path.join(ctx["outdir"], ctx["base"]), ctx["base"], int(dpi), fmt)


@action("to_text", "Convert", "Export text (.txt)")
def _a(doc, ctx):
    fn = os.path.join(ctx["outdir"], ctx["base"] + ".txt")
    open(fn, "w", encoding="utf-8").write(ops.to_text(doc))
    ctx["outputs"].append(fn)


@action("to_html", "Convert", "Export HTML")
def _a(doc, ctx):
    fn = os.path.join(ctx["outdir"], ctx["base"] + ".html")
    open(fn, "w", encoding="utf-8").write(ops.to_html(doc))
    ctx["outputs"].append(fn)


@action("to_word", "Convert", "Export Word (.docx)", [("engine", "Engine", "choice", "auto", ["auto", "word", "layout", "structured"])])
def _a(doc, ctx, engine):
    from . import pdfconv
    tmp = os.path.join(tempfile.mkdtemp(), "in.pdf")
    doc.save(tmp)
    fn = os.path.join(ctx["outdir"], ctx["base"] + ".docx")
    import logging
    logging.disable(logging.WARNING)
    ctx["notes"].append("engine: " + pdfconv.pdf_to_docx(tmp, fn, engine))
    ctx["outputs"].append(fn)


@action("to_excel", "Convert", "Export Excel tables (.xlsx)", [("layout", "Sheets", "choice", "per_table", ["per_table", "per_page", "single"]),
                                                              ("text", "Include text outside tables", "bool", False)])
def _a(doc, ctx, layout, text):
    from . import pdfconv
    fn = os.path.join(ctx["outdir"], ctx["base"] + ".xlsx")
    st = pdfconv.pdf_to_xlsx(doc, fn, layout, text)
    ctx["notes"].append(f"{st['tables']} tables")
    ctx["outputs"].append(fn)


@action("extract_images", "Convert", "Extract embedded images")
def _a(doc, ctx):
    ctx["outputs"] += ops.extract_images(doc, os.path.join(ctx["outdir"], ctx["base"] + "_images"), ctx["base"])


@action("split", "Convert", "Split into files", [("mode", "Mode", "choice", "every", ["every", "ranges", "bookmarks"]),
                                                 ("value", "N or ranges (1-3;4-9)", "text", "1")])
def _a(doc, ctx, mode, value):
    parts, _ = ops.split_doc(doc, mode, value)
    for k, p in enumerate(parts):
        fn = os.path.join(ctx["outdir"], f"{ctx['base']}_{k + 1:03d}.pdf")
        p.save(fn, **ctx["save_kw"])
        ctx["outputs"].append(fn)
    ctx["no_save"] = True


@action("no_save", "Output", "Do not save PDF (export-only tool)")
def _a(doc, ctx):
    ctx["no_save"] = True


CATEGORIES = ["Pages", "Content", "Comments & forms", "Security", "Optimize", "Convert", "Output"]


def default_params(aid):
    return {p[0]: p[3] for p in ACTIONS[aid]["params"]}


def describe(step):
    a = ACTIONS.get(step["id"])
    if not a:
        return step["id"]
    ps = ", ".join(f"{k}={v}" for k, v in step.get("params", {}).items() if v not in ("", None))
    return a["title"] + (f"  ({ps})" if ps else "")


# ---------------------------------------------------------------- preset tools
def _t(name, steps, pattern="{name}_{tool}", merge=False):
    return dict(name=name, actions=[dict(id=a, params={**default_params(a), **p}) for a, p in steps],
                output=dict(folder="", pattern=pattern, overwrite=False, merge=merge), preset=True)


def presets():
    return [
        _t("Compress PDF", [("compress", {})], "{name}_compressed"),
        _t("Merge files into one PDF", [("bookmarks_files", {})], "Merged_{date}", merge=True),
        _t("Split: one file per page", [("split", {"mode": "every", "value": "1"})]),
        _t("Split by bookmarks", [("split", {"mode": "bookmarks", "value": ""})]),
        _t("Add page numbers", [("page_numbers", {})], "{name}_numbered"),
        _t("Add page numbers (Arabic)", [("page_numbers", {"fmt": "صفحة {page} من {pages}"})], "{name}_numbered"),
        _t("Watermark: CONFIDENTIAL", [("watermark", {})], "{name}_watermarked"),
        _t("Watermark: DRAFT / مسودة", [("watermark", {"text": "DRAFT  مسودة", "color": "#DC2626", "opacity": 20})], "{name}_draft"),
        _t("Bates numbering", [("bates", {})], "{name}_bates"),
        _t("Header & footer (file / date / page)", [("header_footer", {})], "{name}_hf"),
        _t("Rotate all pages 90°", [("rotate", {})], "{name}_rotated"),
        _t("Delete blank pages", [("delete_blank", {})], "{name}_clean"),
        _t("Resize to A4", [("resize", {"size": "A4"})], "{name}_A4"),
        _t("2 pages per sheet (print saver)", [("nup", {"n": 2})], "{name}_2up"),
        _t("Approved stamp on first page", [("stamp", {})], "{name}_approved"),
        _t("Flatten comments & forms", [("flatten", {})], "{name}_flat"),
        _t("Remove all comments", [("delete_annots", {})], "{name}_nocomments"),
        _t("Protect with password", [("encrypt", {"user": "1234", "owner": "admin"})], "{name}_protected"),
        _t("Remove security", [("remove_security", {})], "{name}_unlocked"),
        _t("Sanitize for sharing", [("sanitize", {}), ("redact_patterns", {})], "{name}_sanitized"),
        _t("OCR Arabic + English", [("ocr", {})], "{name}_ocr"),
        _t("Convert to images (PNG 150 dpi)", [("to_images", {}), ("no_save", {})]),
        _t("Convert to Word", [("to_word", {}), ("no_save", {})]),
        _t("Convert tables to Excel", [("to_excel", {}), ("no_save", {})]),
        _t("Convert to text", [("to_text", {}), ("no_save", {})]),
        _t("Extract images", [("extract_images", {}), ("no_save", {})]),
        _t("Export comments summary", [("summarize_comments", {}), ("no_save", {})]),
        _t("Files / images / Office → PDF", [], "{name}"),
        _t("Archive: OCR + compress + properties", [("ocr", {}), ("compress", {}), ("properties", {})], "{name}_archive"),
    ]


# ---------------------------------------------------------------- runner
def output_name(pattern, src, tool_name, index):
    now = _dt.datetime.now()
    base = os.path.splitext(os.path.basename(src))[0]
    s = (pattern.replace("{name}", base).replace("{tool}", re.sub(r"\W+", "_", tool_name).strip("_").lower())
         .replace("{date}", now.strftime("%Y-%m-%d")).replace("{time}", now.strftime("%H%M%S"))
         .replace("{n}", f"{index + 1:03d}"))
    return "".join(c for c in s if c not in '\\/:*?"<>|')


def _unique(path, overwrite):
    if overwrite or not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    k = 2
    while os.path.exists(f"{root} ({k}){ext}"):
        k += 1
    return f"{root} ({k}){ext}"


def run_tool(tool, files, log=lambda *a: None, progress=lambda i, n: True, author="", passwords=None):
    """Run a tool on files. Returns a list of report rows."""
    report = []
    out_cfg = tool.get("output", {})
    state = {}
    merge = out_cfg.get("merge")
    merged = fitz.open() if merge else None
    n = len(files)
    for idx, src in enumerate(files):
        if not progress(idx, n):
            break
        t0 = time.time()
        outdir = out_cfg.get("folder") or os.path.dirname(src)
        os.makedirs(outdir, exist_ok=True)
        base = output_name(out_cfg.get("pattern") or "{name}_out", src, tool.get("name", "tool"), idx)
        ctx = dict(src=src, base=base, outdir=outdir, save_kw=dict(garbage=3, deflate=True), outputs=[], notes=[],
                   state=state, author=author)
        row = dict(file=src, status="OK", outputs=[], message="", seconds=0)
        try:
            doc = ops.open_any(src, (passwords or {}).get(src))
            for step in tool.get("actions", []):
                a = ACTIONS[step["id"]]
                params = {**default_params(step["id"]), **step.get("params", {})}
                log(f"  {os.path.basename(src)}: {a['title']}")
                res = a["fn"](doc, ctx, **params)
                if isinstance(res, fitz.Document) and res is not doc:
                    doc.close()
                    doc = res
            if merge:
                merged.insert_pdf(doc)
                if any(s["id"] == "bookmarks_files" for s in tool.get("actions", [])):
                    pass
            elif not ctx.get("no_save"):
                out = _unique(os.path.join(outdir, base + ".pdf"), out_cfg.get("overwrite"))
                if os.path.abspath(out) == os.path.abspath(src):
                    tmp = out + ".tmp"
                    doc.save(tmp, **ctx["save_kw"])
                    doc.close()
                    os.replace(tmp, out)
                else:
                    doc.save(out, **ctx["save_kw"])
                ctx["outputs"].insert(0, out)
                if ctx.get("sign"):
                    s = ctx["sign"]
                    signed = out[:-4] + "_signed.pdf"
                    convert.sign_pdf(out, signed, s["pfx"], s["password"], reason=s["reason"], tsa_url=s["tsa"], visible=False)
                    os.replace(signed, out)
            try:
                doc.close()
            except Exception:
                pass
            row["outputs"] = ctx["outputs"]
            row["message"] = "; ".join(ctx["notes"])
        except Exception as e:
            row["status"] = "Error"
            row["message"] = str(e)
        row["seconds"] = round(time.time() - t0, 2)
        report.append(row)
        log(f"{'✔' if row['status'] == 'OK' else '✖'} {os.path.basename(src)} {row['message']}")
    if merge and merged.page_count:
        outdir = out_cfg.get("folder") or os.path.dirname(files[0])
        base = output_name(out_cfg.get("pattern") or "Merged", files[0], tool.get("name", "tool"), 0)
        out = _unique(os.path.join(outdir, base + ".pdf"), out_cfg.get("overwrite"))
        if any(s["id"] == "bookmarks_files" for s in tool.get("actions", [])):
            toc, start = [], 0
            for r, f in zip(report, files):
                if r["status"] == "OK":
                    d = ops.open_any(f, (passwords or {}).get(f))
                    toc.append([1, os.path.splitext(os.path.basename(f))[0], start + 1])
                    start += d.page_count
                    d.close()
            try:
                merged.set_toc(toc)
            except Exception:
                pass
        merged.save(out, garbage=3, deflate=True)
        report.append(dict(file="(merged)", status="OK", outputs=[out], message=f"{merged.page_count} pages", seconds=0))
        log(f"✔ merged → {out}")
    progress(n, n)
    return report


def report_html(tool, report):
    rows = "".join(
        f"<tr><td>{os.path.basename(r['file'])}</td><td style='color:{'#15803D' if r['status'] == 'OK' else '#B91C1C'}'>"
        f"{r['status']}</td><td>{'<br>'.join(os.path.basename(o) for o in r['outputs'][:5])}"
        f"{' …' if len(r['outputs']) > 5 else ''}</td><td>{r['message']}</td><td>{r['seconds']}s</td></tr>" for r in report)
    ok = sum(1 for r in report if r["status"] == "OK")
    return (f"<html><head><meta charset='utf-8'><style>body{{font-family:Segoe UI,Arial;margin:28px}}"
            f"table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #E5E7EB;padding:6px;font-size:13px;text-align:start}}"
            f"th{{background:#F3F4F6}}</style></head><body><h2>{tool.get('name')}</h2>"
            f"<p>{_dt.datetime.now():%Y-%m-%d %H:%M} — {ok}/{len(report)} succeeded</p>"
            f"<table><tr><th>File</th><th>Status</th><th>Output</th><th>Notes</th><th>Time</th></tr>{rows}</table></body></html>")


def clone(tool):
    t = copy.deepcopy(tool)
    t.pop("preset", None)
    return t
