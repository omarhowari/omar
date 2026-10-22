"""PDF-XChange-style ribbon: large buttons, stacked small buttons, icon grids, a zoom box,
a red File tab, a contextual "Format" tab and a custom title bar with a quick-access toolbar."""
from PySide6.QtCore import Qt, QSize, QPoint, QRect, QEvent, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QAction
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QToolButton, QLabel, QFrame,
                               QTabWidget, QTabBar, QComboBox, QMenu, QSizePolicy, QSlider, QSpinBox,
                               QDoubleSpinBox, QScrollArea, QApplication)

from .i18n import tr
from .icons import cicon, icon

RIBBON_H = 108

# ----------------------------------------------------------------------------- spec
# Items:  ("L", cmd, label, icon, menu)   large button (menu: list of (cmd,label,icon) or a callable name)
#         ("S", [(cmd,label,icon,menu), ...])   column of up to 3 small buttons with text
#         ("I", [[(cmd,icon,tip), ...], ...])  rows of icon-only buttons
#         ("Z",)                               zoom out / zoom box / zoom in row (+ icon rows follow)


def L(cmd, label, ic, menu=None):
    return ("L", cmd, label, ic, menu)


def S(*rows):
    return ("S", [r if len(r) == 4 else (r[0], r[1], r[2], None) for r in rows])


def auto(items):
    """first two as large buttons, the rest as stacked small buttons (3 per column)."""
    out = []
    big = items[:2] if len(items) > 4 else items
    rest = items[2:] if len(items) > 4 else []
    for c, l, i in big:
        out.append(L(c, l, i))
    for k in range(0, len(rest), 3):
        out.append(S(*rest[k:k + 3]))
    return out


def A(en, ar):
    from . import i18n
    return ar if i18n.LANG == "ar" else en


def TOOLS_GROUP():
    return (A("Tools", "أدوات"), [S(("hand", A("Hand", "يد"), "hand"), ("select", A("Select text", "اختيار النص"), "selecttext"),
                                    ("other_tools", A("Other tools", "أدوات أخرى"), "tools", "other_tools_menu"))])


def spec():
    return [
        ("Home", [
            (A("Tools", "أدوات"), [L("hand", A("Hand", "يد"), "hand"), L("select", A("Select text", "اختيار النص"), "selecttext"),
                                   L("select_comments", A("Edit comments", "تحرير التعليقات التوضيحية"), "selectcomment"),
                                   S(("snapshot", A("Snapshot", "لقطة شاشة"), "snapshot"),
                                     ("clipboard", A("Clipboard", "الحافظة"), "clipboard", "clipboard_menu"),
                                     ("find", A("Search", "بحث"), "search", "search_menu"))]),
            (A("View", "عرض"), [("Z",),
                                ("I", [[("actual", "single", A("Actual size", "الحجم الفعلي")),
                                        ("fitpage", "fitpage", A("Fit page", "اضبط على حجم الصفحة")),
                                        ("fitwidth", "fitwidth", A("Fit width", "ضبط العرض")),
                                        ("fitvisible", "fitvisible", A("Fit visible", "التكيف مع المحتوى")),
                                        ("rotate_view_left", "rotateleft", A("Rotate view left", "تدوير العرض لليسار")),
                                        ("rotate_view_right", "rotate", A("Rotate view right", "تدوير العرض لليمين"))],
                                       [("panel_bookmarks", "bookmark", A("Bookmarks", "الإشارات المرجعية")),
                                        ("panel_thumbs", "thumbs", A("Pages", "الصفحات")),
                                        ("panel_comments", "comments", A("Comments", "التعليقات")),
                                        ("panel_attach", "attach", A("Attachments", "المرفقات")),
                                        ("properties", "properties", A("Document properties", "خصائص المستند")),
                                        ("settings", "tools", A("Settings", "الإعدادات"))]])]),
            (A("Objects", "كائنات"), [L("select_objects", A("Select", "اختيار"), "select"),
                                      L("addtext", A("Add", "إضافة"), "image", [("addtext", A("Add text", "إضافة نص"), "text"),
                                                                               ("addimage", A("Add image", "إضافة صورة"), "image"),
                                                                               ("textbox", A("Text box", "مربع نص"), "textbox"),
                                                                               ("insert_blank", A("Blank page", "صفحة فارغة"), "blank")]),
                                      L("edittext", A("Edit", "تحرير"), "typewriter", [("edittext", A("Edit text", "تحرير النص"), "typewriter"),
                                                                                       ("whiteout", A("Whiteout", "تغطية بيضاء"), "rect"),
                                                                                       ("crop", A("Crop", "قص"), "crop")])]),
            (A("Annotations", "ملاحظات"), [S(("addtext", A("Typewriter", "آلة كاتبة"), "typewriter"),
                                             ("highlight", A("Highlight", "تسليط الضوء"), "highlight"),
                                             ("underline", A("Underline", "تسطير"), "underline")),
                                           S(("note", A("Comment", "تعليق"), "note"), ("arrow", A("Arrow", "سهم"), "arrow"),
                                             ("rect", A("Rectangle", "مستطيل"), "rect")),
                                           L("stamp", A("Stamp", "ختم"), "stamp", "stamp_menu")]),
            (A("Links", "المراجع"), [S(("web_links", A("Web links", "روابط الويب"), "web", "weblinks_menu"),
                                       ("link", A("Create/edit link", "إنشاء/تحرير المرجع"), "linkchain"),
                                       ("add_bookmark", A("Add bookmark", "أضف إشارات مرجعية"), "bookmark_add"))]),
            (A("Protect", "يحمي"), [L("digital_sign", A("Sign document", "توقيع المستند"), "cert")]),
        ]),
        ("View", [
            TOOLS_GROUP(),
            (A("Navigation", "التنقل"), [("N",), S(("back", A("Previous view", "العرض الأخير"), "back"),
                                                   ("forward", A("Next view", "العرض التالي"), "forward"))]),
            (A("Zoom", "الحجم"), [L("actual", A("Actual size", "الحجم الفعلي"), "single"),
                                  S(("fitpage", A("Fit page", "اضبط على حجم الصفحة"), "fitpage"),
                                    ("fitwidth", A("Fit width", "ضبط العرض"), "fitwidth"),
                                    ("fitvisible", A("Fit visible", "التكيف مع المحتوى"), "fitvisible")),
                                  ("Z2",),
                                  L("zoom_tool", A("Zoom", "تكبير"), "zoomin"),
                                  S(("loupe", A("Loupe", "مكبرة"), "search"), ("snapshot", A("Snapshot", "لقطة شاشة"), "snapshot"))]),
            (A("Page display", "عرض الصفحة"), [L("rotate_view_right", A("Rotate view", "تدوير العرض"), "rotate", "rotateview_menu"),
                                              ("I", [[("layout_single", "single", A("Single page", "صفحة واحدة")),
                                                      ("layout_continuous", "continuous", A("Continuous", "متواصل"))],
                                                     [("layout_single2", "facing", A("Facing", "صفحتان")),
                                                      ("layout_two", "facingcont", A("Facing continuous", "صفحتان متواصلتان"))]]),
                                              S(("rulers", A("Rulers", "المساطر"), "rulers"), ("grid", A("Grid", "شبكة"), "grid"),
                                                ("night", A("Night reading", "قراءة ليلية"), "dark")),
                                              S(("dark", A("Dark mode", "الوضع الليلي"), "dark"),
                                                ("hide_comments", A("Hide comments", "إخفاء التعليقات"), "comments"),
                                                ("fullscreen", A("Full screen", "ملء الشاشة"), "fullscreen"))]),
            (A("Window", "نافذة"), [S(("doc_tabs", A("Document tabs", "علامات تبويب المستندات"), "tabs"),
                                      ("recent", A("Recent", "الأخيرة"), "open", "recent_menu"),
                                      ("panes", A("Panes", "الأجزاء"), "panel", "panes_menu"))]),
        ]),
        ("Comment", [
            TOOLS_GROUP(),
            (A("Text", "نص"), [S(("addtext", A("Typewriter", "آلة كاتبة"), "typewriter"),
                                 ("textbox", A("Text box", "حقل النص"), "textbox"),
                                 ("callout", A("Callout", "وسيلة شرح"), "arrow"))]),
            (A("Notes", "ملاحظات"), [S(("note", A("Comment", "تعليق"), "note"), ("attach", A("Attachment", "مرفق"), "attach"),
                                       ("link", A("Link", "رابط"), "linkchain"))]),
            (A("Text markup", "علامة نصية"), [S(("highlight", A("Highlight", "تسليط الضوء"), "highlight"),
                                                ("underline", A("Underline", "تسطير"), "underline"),
                                                ("strike", A("Strikeout", "شطب"), "strike")),
                                              S(("insert_text", A("Insert text", "أدخل النص"), "caret"),
                                                ("replace_text", A("Replace text", "استبدال النص"), "replace"),
                                                ("squiggly", A("Squiggly", "متعرج"), "underline")),
                                              L("replace_text", A("Text correction", "تصحيح النص"), "enhance")]),
            (A("Drawing", "للرسم"), [("I", [[("line", "line", A("Line", "خط")), ("oval", "oval", A("Oval", "بيضاوي")),
                                             ("polygon", "fitpage", A("Polygon", "مضلع"))],
                                            [("arrow", "arrow", A("Arrow", "سهم")), ("cloud", "cloud", A("Cloud", "سحابة")),
                                             ("polyline", "sign", A("Polyline", "خط متعدد"))],
                                            [("rect", "rect", A("Rectangle", "مستطيل")),
                                             ("area_highlight", "highlight", A("Area highlight", "تمييز منطقة")),
                                             ("whiteout", "blank", A("Whiteout", "تغطية بيضاء"))]]),
                                     L("stamp", A("Stamp", "ختم"), "stamp", "stamp_menu"),
                                     S(("ink", A("Pencil", "قلم جاف"), "pencil"), ("eraser", A("Eraser", "ممحاة"), "eraser"))]),
            (A("Measure", "قياس"), [S(("measure", A("Distance", "مسافة"), "line"), ("perimeter", A("Perimeter", "محيط"), "perimeter"),
                                      ("area_measure", A("Area", "مساحة"), "polygon"))]),
            (A("Manage comments", "إدارة التعليقات التوضيحية"), [
                L("summarize", A("Summarize comments", "تلخيص التعليقات التوضيحية"), "comments"),
                S(("import_comments", A("Import", "استيراد"), "insert"), ("export_comments", A("Export", "تصدير"), "extract"),
                  ("show_comments", A("Show", "إظهار"), "comments", "show_menu")),
                S(("flatten", A("Flatten", "تضمين"), "compress"), ("panel_comments", A("Comments list", "ملاحظات"), "note"),
                  ("toggle_props", A("Comment styles", "تنسيقات التعليقات التوضيحية"), "properties"))]),
        ]),
        ("Protect", [
            TOOLS_GROUP(),
            (A("Digital signature", "توقيع رقمي"), [L("digital_sign", A("Sign document", "توقيع المستند"), "cert"),
                                                   L("field_signature", A("Place signature", "أدخل التوقيع"), "sigfield"),
                                                   L("create_cert", A("Certificate", "شهادة"), "cert"),
                                                   L("invisible_sign", A("Certify (invisible)", "شهادة (غير مرئية)"), "cert"),
                                                   L("timestamp", A("Timestamp", "الطابع الزمني"), "timestamp")]),
            (A("Signatures", "التوقيعات"), [L("remove_signatures", A("Clear all signatures", "حذف جميع التوقيعات"), "delete"),
                                           L("verify", A("Validate all", "التحقق من جميع التواقيع"), "check"), ("SIGLIST",)]),
            (A("Signatures & initials", "التوقيعات والأحرف الأولى"), [
                S(("signature", A("Manage", "إدارة"), "pencil", "signature_menu"),
                  ("sign_all_pages", A("Apply to all pages", "تطبيق الكل"), "sign"),
                  ("delete_hand_signatures", A("Remove all", "تجاهل الجميع"), "delete"))]),
            (A("Redact", "سواد"), [S(("redact", A("Mark for redaction", "علامة على السواد"), "redact"),
                                     ("apply_redactions", A("Apply", "تطبيق"), "check"),
                                     ("clear_redactions", A("Remove marks", "إزالة العلامات"), "delete")),
                                   L("search_redact", A("Search & redact", "البحث والسواد"), "search"),
                                   L("sanitize", A("Sanitize document", "مستند نظيف"), "enhance")]),
            (A("Document security", "أمن المستند"), [L("password", A("Security settings", "إعدادات الأمان"), "lock"),
                                                    L("remove_security", A("Remove security", "إزالة الأمان"), "unlock")]),
        ]),
        ("Form", [
            TOOLS_GROUP(),
            (A("Form fields", "حقول النموذج"), [L("select_objects", A("Select field", "حدد الحقل"), "select"),
                                               L("field_text", A("Text", "نص"), "textbox"),
                                               L("field_button", A("Button", "زر"), "button"),
                                               L("field_check", A("Check box", "حقل الاختيار (مربع)"), "checkfield"),
                                               L("field_radio", A("Radio button", "حقل الاختيار (زر)"), "radiofield"),
                                               L("field_list", A("List box", "قائمة"), "listfield"),
                                               L("field_combo", A("Combo box", "القائمة المنسدلة"), "combofield"),
                                               L("field_signature", A("Signature", "التوقيع"), "sigfield"),
                                               L("field_date", A("Date", "تاريخ"), "date"),
                                               L("field_image", A("Image", "صورة"), "image"),
                                               S(("highlight_fields", A("Highlight fields", "قم بتمييز الحقول"), "highlight"),
                                                 ("grid", A("Grid", "شبكة"), "grid"),
                                                 ("rulers", A("Rulers", "المساطر"), "rulers"))]),
            (A("Form data", "بيانات النموذج"), [L("reset_form", A("Reset form", "إعادة تعيين النموذج"), "undo"),
                                               S(("import_form", A("Import form data", "استيراد بيانات النموذج"), "insert"),
                                                 ("export_form", A("Export form data", "تصدير بيانات النموذج"), "extract"),
                                                 ("email_form", A("Email form data", "إرسال بيانات النموذج عبر البريد الإلكتروني"), "email")),
                                               L("fill_forms", A("Fill forms", "املأ النماذج"), "enhance"),
                                               L("flatten_forms", A("Flatten fields", "تسطيح الحقول"), "compress")]),
        ]),
        ("Organize", [
            TOOLS_GROUP(),
            (A("Pages", "صفحات"), [L("insert_file", A("Insert", "إدراج"), "insert", [("insert_file", A("Pages from file", "صفحات من ملف"), "insert"),
                                                                                    ("insert_blank", A("Blank pages", "صفحات فارغة"), "blank"),
                                                                                    ("paste_page", A("From clipboard", "من الحافظة"), "clipboard")]),
                                   L("delete_pages", A("Delete", "حذف"), "delete", [("delete_pages", A("Delete pages", "حذف صفحات"), "delete"),
                                                                                  ("delete_blank", A("Delete blank pages", "حذف الصفحات الفارغة"), "blank")]),
                                   L("extract_pages", A("Extract pages", "استخراج الصفحات"), "extract"),
                                   S(("move_pages", A("Move pages", "نقل الصفحات"), "nav"), ("merge", A("Merge pages", "دمج الصفحات"), "merge"),
                                     ("split", A("Split", "انقسام"), "split", [("split", A("Split document", "تقسيم المستند"), "split"),
                                                                              ("split_bookmarks", A("Split by bookmarks", "تقسيم حسب الإشارات"), "bookmark")])),
                                   S(("duplicate", A("Duplicate pages", "صفحات مكررة"), "insert"),
                                     ("replace_pages", A("Replace pages", "استبدل الصفحات"), "replace"),
                                     ("swap_pages", A("Swap pages", "صفحات التبادل"), "swap")),
                                   L("overlay", A("Overlay", "تراكب"), "overlay")]),
            (A("Page transform", "تحويل الصفحات"), [L("resize", A("Resize", "تغيير الحجم"), "fitpage"), L("crop", A("Crop", "قطع"), "crop"),
                                                   L("rotate_right", A("Rotate", "تدوير"), "rotate",
                                                     [("rotate_right", A("Rotate right", "تدوير لليمين"), "rotate"),
                                                      ("rotate_left", A("Rotate left", "تدوير لليسار"), "rotateleft"),
                                                      ("rotate_180", A("Rotate 180°", "تدوير 180°"), "rotate")]),
                                                   S(("nup", A("N-up", "عدة صفحات بورقة"), "facing"), ("reverse", A("Reverse", "عكس الترتيب"), "sort"),
                                                     ("compress", A("Compress", "ضغط"), "compress"))]),
            (A("Page marks", "علامات الصفحة"), [L("watermark", A("Watermark", "علامة مائية"), "watermark",
                                                  [("watermark", A("Add watermark", "إضافة علامة مائية"), "watermark")]),
                                                L("background", A("Background", "خلفية"), "image"),
                                                L("header_footer", A("Headers & footers", "الرؤوس والتذييلات"), "fitwidth"),
                                                L("page_numbers", A("Page numbers", "ترقيم الصفحات"), "pagenum",
                                                  [("page_numbers", A("Page numbers", "ترقيم الصفحات"), "pagenum"),
                                                   ("bates", A("Bates numbering", "ترقيم Bates"), "pagenum")]),
                                                L("page_labels", A("Number pages", "عدد الصفحات"), "toc")]),
        ]),
        ("Convert", [
            TOOLS_GROUP(),
            (A("Create", "إنشاء"), [L("new_blank", A("Blank", "فارغ"), "blank"),
                                    L("files_to_pdf", A("From files", "من الملفات"), "insert",
                                      [("files_to_pdf", A("Combine files", "دمج ملفات"), "merge"),
                                       ("images_to_pdf", A("From images", "من صور"), "imagestopdf")]),
                                    L("scan", A("Scan", "مسح ضوئي"), "snapshot")]),
            (A("Convert", "تحويل المحتوى"), [L("rasterize", A("Content to images", "تحويل المحتوى إلى صور"), "toimages"),
                                             L("compress", A("Recompress images", "إعادة ضغط الصور"), "compress")]),
            (A("Export", "تصدير"), [L("to_ppt", A("To PowerPoint", "إلى PowerPoint"), "ppt"),
                                    L("to_excel", A("To Excel", "إلى Excel"), "excel"),
                                    L("to_word", A("To Word", "إلى Word"), "word"),
                                    L("to_images", A("To image", "إلى صورة"), "toimages"),
                                    S(("to_text", A("To text", "إلى نص"), "text"), ("to_html", A("To HTML", "إلى HTML"), "web"),
                                      ("extract_images", A("Extract images", "استخراج الصور"), "image"))]),
            (A("Text recognition", "التعرف على النص"), [L("ocr", A("Recognize text", "التعرف على النص في الصفحات"), "selecttext")]),
            (A("Enhance pages", "تحسين الصفحات"), [L("delete_blank", A("Skip blank pages", "تجاهل الصفحات"), "blank"),
                                                  L("enhance", A("Enhance scanned pages", "تحسين الصفحات الممسوحة ضوئياً"), "enhance")]),
            (A("Convert colors", "تحويل الألوان"), [L("grayscale", A("Convert colors", "تحويل الألوان"), "grayscale")]),
            (A("Batch", "أدوات دفعية"), [L("batch", A("Batch tools", "أدوات دفعية"), "compress")]),
        ]),
        ("Share", [
            TOOLS_GROUP(),
            (A("Send to", "أرسل إلى"), [L("email", A("Email", "بريد إلكتروني"), "email",
                                          [("email", A("Email document", "إرسال المستند"), "email"),
                                           ("email_form", A("Email form data", "إرسال بيانات النموذج"), "email")])]),
            (A("File", "ملف"), [S(("open_folder", A("Open containing folder", "فتح المجلد"), "folderopen"),
                                  ("copy_path", A("Copy file path", "نسخ مسار الملف"), "clipboard"),
                                  ("print", A("Print", "طباعة"), "print"))]),
        ]),
        ("Review", [
            TOOLS_GROUP(),
            (A("Proofing", "تدقيق"), [L("replace_text", A("Text correction", "تصحيح النص"), "enhance"),
                                      L("word_count", A("Word count", "رقم الكلمة"), "text"),
                                      L("compare", A("Compare documents", "مقارنة المستندات"), "comparedoc")]),
            (A("Comments", "ملاحظات"), [L("summarize", A("Summarize comments", "تضمين التعليقات التوضيحية"), "comments"),
                                        L("show_comments", A("Show", "تبين"), "comments", "show_menu"),
                                        L("panel_comments", A("Comments", "ملاحظات"), "note"),
                                        L("next_comment", A("Next", "التالي"), "forward"),
                                        L("prev_comment", A("Previous", "السابق"), "back"),
                                        L("delete_comments", A("Delete comments", "حذف التعليقات التوضيحية"), "delete"),
                                        L("note", A("Add comment", "أضف تعليقات توضيحية"), "note")]),
        ]),
        ("Accessibility", [
            TOOLS_GROUP(),
            (A("Edit", "تحرير"), [L("properties", A("Title & language", "العنوان واللغة"), "properties"),
                                  L("bookmarks_from_text", A("Structure from headings", "البنية من العناوين"), "toc")]),
            (A("Accessibility check", "التحقق من إمكانية الوصول"), [L("access_report", A("Accessibility report", "تقرير إمكانية الوصول"), "access"),
                                                                   L("access_check", A("Accessibility check", "التحقق من إمكانية الوصول"), "check")]),
            (A("Read aloud", "القراءة بصوت"), [L("read_aloud", A("Read page", "قراءة الصفحة"), "speaker"),
                                               L("read_selection", A("Read selection", "قراءة المحدد"), "speaker"),
                                               L("stop_reading", A("Stop", "إيقاف"), "stop")]),
        ]),
        ("Bookmarks", [
            TOOLS_GROUP(),
            (A("Create", "إنشاء"), [L("bm_from_text", A("From page text", "من نص الصفحة"), "bookmark_add"),
                                    L("bm_each", A("Bookmark every nth page", "إشارة مرجعية لكل صفحة nth"), "bookmark"),
                                    L("bm_from_links", A("From links", "من الروابط"), "linkchain"),
                                    L("bm_import_txt", A("From text file", "من ملف نصي"), "text")]),
            (A("Modify", "تعديل"), [L("bm_add_text", A("Add text", "أضف نصاً"), "bookmark_add"),
                                    L("bm_case", A("Change case", "أحرف كبيرة/صغيرة"), "case"),
                                    L("bm_find_replace", A("Find & replace", "البحث والاستبدال"), "replace"),
                                    L("bm_sort", A("Sort", "فرز"), "sort"),
                                    L("bm_check", A("Check", "التحقق من"), "check"),
                                    L("bm_merge_dups", A("Merge duplicates", "دمج المكرر"), "merge"),
                                    L("delete_bookmarks", A("Remove all", "إزالة الكل"), "delete")]),
            (A("Convert", "تحويل"), [L("toc_page", A("Create table of contents", "إنشاء جدول المحتويات"), "toc"),
                                     L("sort_pages_bm", A("Sort pages by bookmarks", "فرز الصفحات"), "sort"),
                                     L("bm_export_html", A("Export as HTML", "تصدير بتنسيق HTML"), "web"),
                                     L("bm_export_txt", A("Export as text", "تصدير كملف نصي"), "text")]),
        ]),
        ("Help", [
            (A("Program", "برنامج"), [L("help", A("Home page", "الصفحة الرئيسية"), "home"),
                                      L("set_default", A("Set as default", "تعيين كبرنامج افتراضي"), "default"),
                                      L("about", A("About", "حول"), "about")]),
            (A("Help", "مساعدة"), [L("cmdline_help", A("Command line help", "مساعدة سطر الأوامر"), "terminal"),
                                   L("report_problem", A("Report a problem", "الإبلاغ عن مشكلة"), "bug"),
                                   L("shortcuts", A("Shortcuts", "الاختصارات"), "keyboard"),
                                   L("help", A("Help", "مساعدة"), "help")]),
            (A("Interface", "الواجهة"), [L("language", A("Language", "اللغة"), "language"),
                                         L("settings", A("Customize UI", "ضبط الواجهة"), "tools")]),
        ]),
    ]


TAB_TITLES = {"Home": "بدء", "View": "عرض", "Comment": "تعليقات", "Protect": "حماية", "Form": "شكل",
              "Organize": "بنية المستند", "Convert": "تحويل", "Share": "مشاركة", "Review": "التحقق من",
              "Accessibility": "إمكانية الوصول", "Bookmarks": "الإشارات المرجعية", "Help": "مساعدة"}


def tab_title(key):
    from . import i18n
    return TAB_TITLES[key] if i18n.LANG == "ar" else {"Form": "Form", "Organize": "Document"}.get(key, key)


# ----------------------------------------------------------------------------- tab bar with contextual tab
class RibbonTabBar(QTabBar):
    def __init__(self):
        super().__init__()
        self.contextual = -1
        self.context_title = ""
        self.setDrawBase(False)

    def tabSizeHint(self, i):
        s = super().tabSizeHint(i)
        if i == self.contextual:
            s.setWidth(max(s.width(), 110))
        return s

    def paintEvent(self, e):
        if 0 <= self.contextual < self.count() and self.isTabVisible(self.contextual):
            p = QPainter(self)
            r = self.tabRect(self.contextual)
            p.fillRect(QRect(r.x(), 0, r.width(), self.height()), QColor("#F1E3C3"))
            p.end()
        super().paintEvent(e)


class Ribbon(QTabWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("ribbon")
        self.bar = RibbonTabBar()
        self.setTabBar(self.bar)
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)


# ----------------------------------------------------------------------------- builders
def _big(main, cmd, label, ic, menu):
    b = QToolButton()
    b.setObjectName("big")
    a = main._action(cmd, label, ic)
    b.setDefaultAction(a)
    fm = b.fontMetrics()
    text = label
    if fm.horizontalAdvance(label) > 64 and " " in label:
        # PDF-XChange style: long captions wrap onto two lines under the icon
        sp = [i for i, ch in enumerate(label) if ch == " "]
        mid = min(sp, key=lambda i: abs(i - len(label) / 2))
        text = label[:mid] + "\n" + label[mid + 1:]
    b._caption = text
    b.setText(text)
    a.changed.connect(lambda b=b: b.setText(b._caption))
    b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    b.setIconSize(QSize(32, 32))
    b.setAutoRaise(True)
    b.setMinimumHeight(74)
    b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    _attach_menu(main, b, menu)
    w = max(fm.horizontalAdvance(line) for line in text.split("\n")) + 16 + (12 if menu else 0)
    b.setMinimumWidth(max(48, w))
    return b


def _small(main, cmd, label, ic, menu):
    b = QToolButton()
    b.setObjectName("small")
    a = main._action(cmd, label, ic)
    b.setDefaultAction(a)
    b.setText(label)
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setIconSize(QSize(18, 18))
    b.setAutoRaise(True)
    b.setFixedHeight(24)
    b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    _attach_menu(main, b, menu)
    return b


def _icon_btn(main, cmd, ic, tip):
    b = QToolButton()
    b.setObjectName("iconbtn")
    a = main._action(cmd, tip, ic)
    b.setDefaultAction(a)
    b.setToolButtonStyle(Qt.ToolButtonIconOnly)
    b.setIconSize(QSize(18, 18))
    b.setAutoRaise(True)
    b.setFixedSize(26, 26)
    b.setToolTip(tip)
    return b


def _attach_menu(main, b, menu):
    if not menu:
        return
    if isinstance(menu, str):
        m = getattr(main, "_" + menu)()
    else:
        m = QMenu(main)
        for c, l, i in menu:
            m.addAction(main._action(c, l, i))
    b.setMenu(m)
    b.setPopupMode(QToolButton.MenuButtonPopup)


def _zoom_row(main):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(2)
    h.addWidget(_icon_btn(main, "zoomout", "zoomout", tr("Zoom out")))
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(["25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%", tr("Fit width"), tr("Fit page")])
    combo.setFixedWidth(110)
    combo.setLayoutDirection(Qt.LeftToRight)
    combo.activated.connect(lambda *_: main._zoom_from(combo))
    combo.lineEdit().returnPressed.connect(lambda: main._zoom_from(combo))
    main.zoom_boxes.append(combo)
    h.addWidget(combo)
    h.addWidget(_icon_btn(main, "zoomin", "zoomin", tr("Zoom in")))
    return w


def _page_nav(main):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    h = QHBoxLayout()
    h.setSpacing(1)
    w.setLayoutDirection(Qt.LeftToRight)
    for c, i, t in (("first", "first", A("First page", "الصفحة الأولى")), ("prev", "prev", A("Previous page", "الصفحة السابقة"))):
        h.addWidget(_icon_btn(main, c, i, t))
    box = QLineEdit_()
    box.setFixedWidth(84)
    box.setAlignment(Qt.AlignCenter)
    box.returnPressed.connect(lambda: main._goto_from_box(box))
    main.page_boxes.append(box)
    h.addWidget(box)
    for c, i, t in (("next", "next", A("Next page", "الصفحة التالية")), ("last", "last", A("Last page", "الصفحة الأخيرة"))):
        h.addWidget(_icon_btn(main, c, i, t))
    v.addLayout(h)
    v.addStretch()
    return w


def QLineEdit_():
    from PySide6.QtWidgets import QLineEdit
    e = QLineEdit()
    e.setObjectName("ribbonedit")
    return e


def _zoom_col(main):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(0)
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(["25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%"])
    combo.setFixedWidth(96)
    combo.setLayoutDirection(Qt.LeftToRight)
    combo.activated.connect(lambda *_: main._zoom_from(combo))
    combo.lineEdit().returnPressed.connect(lambda: main._zoom_from(combo))
    main.zoom_boxes.append(combo)
    v.addWidget(combo)
    v.addWidget(_small(main, "zoomin", A("Zoom in", "تكبير"), "zoomin", None))
    v.addWidget(_small(main, "zoomout", A("Zoom out", "تخفيض"), "zoomout", None))
    return w


def _sig_list(main):
    from PySide6.QtWidgets import QListWidget
    lw = QListWidget()
    lw.setObjectName("siglist")
    lw.setFixedSize(130, 70)
    main.sig_lists.append(lw)
    return lw


def build_group(main, title, items):
    g = QFrame()
    g.setObjectName("group")
    v = QVBoxLayout(g)
    v.setContentsMargins(4, 2, 4, 0)
    v.setSpacing(0)
    row = QHBoxLayout()
    row.setSpacing(2)
    k = 0
    while k < len(items):
        it = items[k]
        kind = it[0]
        if kind == "L":
            row.addWidget(_big(main, *it[1:]))
        elif kind == "S":
            col = QVBoxLayout()
            col.setSpacing(0)
            for c, l, i, m in it[1]:
                col.addWidget(_small(main, c, l, i, m))
            col.addStretch()
            row.addLayout(col)
        elif kind == "N":
            row.addWidget(_page_nav(main))
        elif kind == "Z2":
            row.addWidget(_zoom_col(main))
        elif kind == "SIGLIST":
            row.addWidget(_sig_list(main))
        elif kind == "Z" or kind == "I":
            col = QVBoxLayout()
            col.setSpacing(1)
            if kind == "Z":
                col.addWidget(_zoom_row(main))
                if k + 1 < len(items) and items[k + 1][0] == "I":
                    k += 1
                    it = items[k]
                else:
                    it = ("I", [])
            for r in it[1]:
                rw = QHBoxLayout()
                rw.setSpacing(1)
                for c, i, tip in r:
                    rw.addWidget(_icon_btn(main, c, i, tip))
                rw.addStretch()
                col.addLayout(rw)
            col.addStretch()
            row.addLayout(col)
        k += 1
    v.addLayout(row, 1)
    lab = QLabel(title)
    lab.setAlignment(Qt.AlignCenter)
    lab.setObjectName("grouplabel")
    v.addWidget(lab)
    return g


def build_ribbon(main):
    rib = Ribbon()
    for key, groups in spec():
        page = QWidget()
        page.setObjectName("ribbonpage")
        h = QHBoxLayout(page)
        h.setContentsMargins(4, 3, 4, 1)
        h.setSpacing(0)
        for title, items in groups:
            h.addWidget(build_group(main, title, items))
        h.addStretch()
        sc = QScrollArea()
        sc.setWidget(page)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setFixedHeight(RIBBON_H)
        rib.addTab(sc, tab_title(key))
    # contextual Format tab (always present, like PDF-XChange: tool name above, "Format" below)
    from PySide6.QtWidgets import QStackedWidget
    rib.format_page = FormatPage(main)
    rib.hand_page = HandPage(main)
    rib.ctx_stack = QStackedWidget()
    rib.ctx_stack.addWidget(rib.hand_page)
    rib.ctx_stack.addWidget(rib.format_page)
    sc = QScrollArea()
    sc.setWidget(rib.ctx_stack)
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.NoFrame)
    sc.setFixedHeight(RIBBON_H)
    idx = rib.addTab(sc, A("Format", "شكل"))
    rib.bar.contextual = idx
    # search buttons on the tab row (opposite corner)
    corner = QWidget()
    ch = QHBoxLayout(corner)
    ch.setContentsMargins(0, 0, 4, 0)
    ch.setSpacing(2)
    for cmd, ic, label in (("find", "search", A("Search…", "البحث...")), ("quick_find", "search", A("Quick search…", "بحث سريع..."))):
        b = QToolButton()
        b.setObjectName("small")
        b.setIcon(cicon(ic))
        b.setText(label)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.clicked.connect(lambda _=False, c=cmd: main.cmd(c))
        ch.addWidget(b)
    rib.setCornerWidget(corner, Qt.TopRightCorner)
    # red File tab
    fb = QToolButton()
    fb.setObjectName("filebtn")
    fb.setText(tr("File"))
    fb.setPopupMode(QToolButton.InstantPopup)
    main.file_menu = QMenu(main)
    main.file_menu.aboutToShow.connect(main._fill_file_menu)
    fb.setMenu(main.file_menu)
    rib.setCornerWidget(fb, Qt.TopLeftCorner)
    rib.setCurrentIndex(0)
    return rib


# ----------------------------------------------------------------------------- contextual "Format" page
class FormatPage(QWidget):
    def __init__(self, main):
        super().__init__()
        from .panels import ColorButton
        self.main = main
        self.setObjectName("ribbonpage")
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 3, 4, 1)
        h.setSpacing(0)
        st = main.style

        def group(title, widget):
            g = QFrame()
            g.setObjectName("group")
            v = QVBoxLayout(g)
            v.setContentsMargins(8, 4, 8, 0)
            v.addWidget(widget, 1)
            lab = QLabel(title)
            lab.setAlignment(Qt.AlignCenter)
            lab.setObjectName("grouplabel")
            v.addWidget(lab)
            h.addWidget(g)

        cw = QWidget()
        cg = QGridLayout(cw)
        cg.setContentsMargins(0, 0, 0, 0)
        self.stroke = ColorButton(st["color"])
        self.fill = ColorButton(st["fill"], allow_none=True)
        cg.addWidget(QLabel(tr("Border color")), 0, 0)
        cg.addWidget(self.stroke, 0, 1)
        cg.addWidget(QLabel(tr("Fill color")), 1, 0)
        cg.addWidget(self.fill, 1, 1)
        group(tr("Colors"), cw)

        lw = QWidget()
        lg = QGridLayout(lw)
        lg.setContentsMargins(0, 0, 0, 0)
        self.width = QDoubleSpinBox()
        self.width.setRange(0, 20)
        self.width.setSingleStep(0.5)
        self.width.setValue(st["width"])
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(int(st["opacity"] * 100))
        self.opacity.setFixedWidth(120)
        self.op_label = QLabel(f"{self.opacity.value()}%")
        lg.addWidget(QLabel(tr("Width")), 0, 0)
        lg.addWidget(self.width, 0, 1)
        lg.addWidget(QLabel(tr("Opacity")), 1, 0)
        lg.addWidget(self.opacity, 1, 1)
        lg.addWidget(self.op_label, 1, 2)
        group(tr("Line"), lw)

        tw = QWidget()
        tg = QGridLayout(tw)
        tg.setContentsMargins(0, 0, 0, 0)
        self.fontsize = QSpinBox()
        self.fontsize.setRange(4, 120)
        self.fontsize.setValue(st["fontsize"])
        tg.addWidget(QLabel(tr("Font size")), 0, 0)
        tg.addWidget(self.fontsize, 0, 1)
        group(tr("Text"), tw)

        aw = QWidget()
        ag = QHBoxLayout(aw)
        ag.setContentsMargins(0, 0, 0, 0)
        b1 = _big(main, "toggle_props", tr("Properties"), "panel", None)
        b2 = _big(main, "delete_selected", tr("Delete"), "delete", None)
        ag.addWidget(b1)
        ag.addWidget(b2)
        group(tr("Actions"), aw)
        h.addStretch()

        self.stroke.colorChanged.connect(self._changed)
        self.fill.colorChanged.connect(self._changed)
        self.width.valueChanged.connect(self._changed)
        self.opacity.valueChanged.connect(lambda v: (self.op_label.setText(f"{v}%"), self._changed()))
        self.fontsize.valueChanged.connect(self._changed)
        self._silent = False

    def load(self, color, fill, width, opacity, fontsize):
        self._silent = True
        self.stroke.set_color(color or "#000000")
        self.fill.set_color(fill or "")
        self.width.setValue(width)
        self.opacity.setValue(int(opacity * 100))
        self.op_label.setText(f"{int(opacity * 100)}%")
        self.fontsize.setValue(int(fontsize))
        self._silent = False

    def values(self):
        return dict(color=self.stroke.color() or "#000000", fill=self.fill.color(), width=self.width.value(),
                    opacity=self.opacity.value() / 100, fontsize=self.fontsize.value())

    def _changed(self, *_):
        if not self._silent:
            self.main.format_changed(self.values())


class HandPage(QWidget):
    """Contextual page for Hand / Select tools (PDF-XChange: Properties, Exclusive mode, smooth scrolling...)."""

    def __init__(self, main):
        super().__init__()
        self.setObjectName("ribbonpage")
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 3, 4, 1)
        h.setSpacing(0)
        h.addWidget(build_group(main, A("Properties", "خصائص"), [
            L("toggle_props", A("Properties", "خصائص"), "properties"),
            S(("exclusive", A("Exclusive mode", "الوضع الحصري"), "exclusive"),
              ("smooth_scroll", A("Smooth scrolling", "التمرير البطيء"), "smooth"),
              ("hand_text", A("Select text or images", "حدد نصاً أو صوراً"), "selecttext"))]))
        h.addStretch()


# ----------------------------------------------------------------------------- title bar
class TitleBar(QWidget):
    """Custom title bar: app icon, quick-access toolbar, centred title, window buttons."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.setObjectName("titlebar")
        self.setFixedHeight(34)
        self.setLayoutDirection(Qt.LeftToRight)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 0, 0, 0)
        h.setSpacing(1)
        logo = QLabel()
        from .mainwindow import app_icon
        logo.setPixmap(app_icon().pixmap(22, 22))
        h.addWidget(logo)
        h.addSpacing(6)
        for cmd, ic, tip, menu in (("open", "open", tr("Open"), "recent_menu"), ("save", "save", tr("Save"), None),
                                   ("print", "print", tr("Print"), None), ("email", "email", tr("Email"), None),
                                   ("scan", "snapshot", tr("Scan"), None), (None, None, None, None),
                                   ("undo", "undo", tr("Undo"), None), ("redo", "redo", tr("Redo"), None),
                                   (None, None, None, None), ("back", "back", tr("Previous view"), None),
                                   ("forward", "forward", tr("Next view"), None)):
            if cmd is None:
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setObjectName("tbsep")
                h.addWidget(sep)
                continue
            b = QToolButton()
            b.setObjectName("qa")
            b.setIcon(cicon(ic))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, c=cmd: main.cmd(c))
            if menu:
                b.setMenu(getattr(main, "_" + menu)())
                b.setPopupMode(QToolButton.MenuButtonPopup)
            h.addWidget(b)
        h.addStretch(1)
        self.title = QLabel("Waraq PDF")
        self.title.setObjectName("wintitle")
        h.addWidget(self.title)
        h.addStretch(1)
        from PySide6.QtWidgets import QLineEdit, QCompleter
        self.quick = QLineEdit()
        self.quick.setObjectName("quickstart")
        self.quick.setPlaceholderText(A("Quick launch (Ctrl+.)", "بداية سريعة (Ctrl+.)"))
        self.quick.setFixedWidth(200)
        self.quick.setLayoutDirection(Qt.RightToLeft if A("en", "ar") == "ar" else Qt.LeftToRight)
        self.quick.returnPressed.connect(lambda: main.quick_launch(self.quick.text()))
        h.addWidget(self.quick)
        h.addSpacing(8)
        self.btns = []
        for name, slot in (("min", main.showMinimized), ("max", self._toggle_max), ("close", main.close)):
            b = QToolButton()
            b.setObjectName("win_" + name)
            b.setFixedSize(46, 34)
            b.setText({"min": "—", "max": "☐", "close": "✕"}[name])
            b.clicked.connect(slot)
            h.addWidget(b)
            self.btns.append(b)

    def _toggle_max(self):
        if self.main.isMaximized():
            self.main.showNormal()
        else:
            self.main.showMaximized()

    def set_title(self, t):
        self.title.setText(t)

    def setup_completer(self, names):
        from PySide6.QtWidgets import QCompleter
        c = QCompleter(sorted(set(names)), self)
        c.setCaseSensitivity(Qt.CaseInsensitive)
        c.setFilterMode(Qt.MatchContains)
        c.activated.connect(lambda s: self.main.quick_launch(s))
        self.quick.setCompleter(c)

    def paintEvent(self, e):
        super().paintEvent(e)
        rib = getattr(self.main, "ribbon", None)
        if rib is None:
            return
        idx = rib.bar.contextual
        if idx < 0 or not rib.isTabVisible(idx):
            return
        tr_ = rib.bar.tabRect(idx)
        tl = rib.bar.mapTo(self.window(), tr_.topLeft())
        x = self.mapFrom(self.window(), tl).x()
        p = QPainter(self)
        p.fillRect(QRect(x, 0, tr_.width(), self.height()), QColor("#F1E3C3" if not _dark() else "#5C4A26"))
        p.setPen(QColor("#5A4214" if not _dark() else "#F1E3C3"))
        p.drawText(QRect(x, 0, tr_.width(), self.height()), Qt.AlignCenter, getattr(self.main, "context_title", ""))
        p.end()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggle_max()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.main.windowHandle():
            self.main.windowHandle().startSystemMove()


def _dark():
    from . import icons
    return icons.DARK_ICONS


def install_edge_resize(window, margin=6):
    from PySide6.QtCore import QObject

    class F(QObject):
        def eventFilter(self, obj, ev):
            try:
                return self._filter(obj, ev)
            except RuntimeError:
                return False

        def _filter(self, obj, ev):
            if window.isMaximized() or window.isFullScreen() or not window.isVisible():
                return False
            t = ev.type()
            if t not in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.HoverMove):
                return False
            if not hasattr(ev, "globalPosition"):
                return False
            gp = ev.globalPosition().toPoint()
            r = window.frameGeometry()
            edges = Qt.Edges()
            if abs(gp.x() - r.left()) <= margin:
                edges |= Qt.LeftEdge
            if abs(gp.x() - r.right()) <= margin:
                edges |= Qt.RightEdge
            if abs(gp.y() - r.top()) <= margin // 2:
                edges |= Qt.TopEdge
            if abs(gp.y() - r.bottom()) <= margin:
                edges |= Qt.BottomEdge
            if not r.adjusted(-margin, -margin, margin, margin).contains(gp):
                return False
            if t == QEvent.MouseButtonPress and edges and ev.button() == Qt.LeftButton:
                window.windowHandle().startSystemResize(edges)
                return True
            if t in (QEvent.MouseMove, QEvent.HoverMove):
                cur = None
                if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
                    cur = Qt.SizeFDiagCursor
                elif edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
                    cur = Qt.SizeBDiagCursor
                elif edges & (Qt.LeftEdge | Qt.RightEdge):
                    cur = Qt.SizeHorCursor
                elif edges & (Qt.TopEdge | Qt.BottomEdge):
                    cur = Qt.SizeVerCursor
                if cur is not None:
                    if not getattr(window, "_edge_cursor", False):
                        QApplication.setOverrideCursor(cur)
                        window._edge_cursor = True
                    else:
                        QApplication.changeOverrideCursor(cur)
                elif getattr(window, "_edge_cursor", False):
                    QApplication.restoreOverrideCursor()
                    window._edge_cursor = False
            return False

    f = F(window)
    QApplication.instance().installEventFilter(f)
    window._edge_filter = f
