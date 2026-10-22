"""Very small translation layer: tr("English") -> Arabic when the UI language is Arabic."""
LANG = "en"

AR = {
    # ribbon tabs & groups
    "File": "ملف", "Home": "الرئيسية", "Comment": "تعليق", "Edit": "تحرير", "Organize": "تنظيم",
    "Forms": "نماذج", "Protect": "حماية", "Convert": "تحويل", "View": "عرض", "Tools": "أدوات",
    "Text markup": "تمييز النص", "Notes": "ملاحظات", "Drawing": "رسم", "More": "المزيد", "Draw": "رسم", "Stamps": "أختام", "Manage": "إدارة",
    "Pages": "الصفحات", "Document": "المستند", "Header & footer": "الرأس والتذييل", "Security": "الأمان",
    "Mark": "علامات", "Signatures": "التواقيع", "Layout": "التخطيط", "Display": "العرض", "Zoom": "تكبير",
    "Navigate": "تنقل", "Content": "المحتوى", "Fields": "الحقول", "Export": "تصدير", "Create": "إنشاء",
    # commands
    "Open": "فتح", "Save": "حفظ", "Save As": "حفظ باسم", "Print": "طباعة", "Close": "إغلاق",
    "Hand": "يد", "Select": "تحديد", "Snapshot": "لقطة", "Zoom in": "تكبير", "Zoom out": "تصغير",
    "Fit width": "ملء العرض", "Fit page": "ملء الصفحة", "Actual size": "الحجم الفعلي",
    "Add text": "إضافة نص", "Add image": "إضافة صورة", "Edit text": "تعديل نص", "Whiteout": "تغطية بيضاء",
    "OCR": "التعرف الضوئي", "Highlight": "تمييز", "Underline": "تسطير", "Strikeout": "شطب",
    "Squiggly": "متعرج", "Sticky note": "ملاحظة لاصقة", "Text box": "صندوق نص", "Callout": "وسيلة شرح",
    "Rectangle": "مستطيل", "Oval": "بيضاوي", "Line": "خط", "Arrow": "سهم", "Polygon": "مضلع",
    "Polyline": "خط متعدد", "Pencil": "قلم", "Stamp": "ختم", "Link": "رابط", "Attach file": "إرفاق ملف",
    "Summarize": "تلخيص", "Flatten": "تسطيح", "Delete all": "حذف الكل",
    "Insert": "إدراج", "Blank page": "صفحة فارغة", "Delete": "حذف", "Extract": "استخراج",
    "Rotate right": "تدوير يمين", "Rotate left": "تدوير يسار", "Duplicate": "تكرار", "Crop": "قص",
    "Resize": "تغيير الحجم", "N-up": "عدة صفحات بورقة", "Reverse": "عكس الترتيب", "Delete blank": "حذف الفارغة",
    "Merge": "دمج", "Split": "تقسيم", "Compress": "ضغط", "Page numbers": "ترقيم الصفحات",
    "Header/Footer": "رأس/تذييل", "Bates": "ترقيم Bates", "Watermark": "علامة مائية", "Background": "خلفية",
    "Password": "كلمة مرور", "Remove security": "إزالة الحماية", "Redact": "حجب", "Search & redact": "بحث وحجب",
    "Apply redactions": "تطبيق الحجب", "Sanitize": "تنظيف", "Signature": "توقيع", "Digital sign": "توقيع رقمي",
    "Verify": "تحقق", "Certificate": "شهادة", "Text field": "حقل نص", "Checkbox": "مربع اختيار",
    "Radio": "زر اختيار", "Combo box": "قائمة منسدلة", "List box": "قائمة", "Reset form": "تفريغ النموذج",
    "To images": "إلى صور", "To Word": "إلى Word", "To text": "إلى نص", "To HTML": "إلى HTML",
    "Extract images": "استخراج الصور", "Images to PDF": "صور إلى PDF", "Files to PDF": "ملفات إلى PDF",
    "Scan": "مسح ضوئي", "Single": "صفحة واحدة", "Continuous": "متواصل", "Two pages": "صفحتان",
    "Dark mode": "الوضع الليلي", "Night reading": "قراءة ليلية", "Full screen": "ملء الشاشة",
    "Rotate view": "تدوير العرض", "Properties": "خصائص", "Undo": "تراجع", "Redo": "إعادة",
    "Previous page": "الصفحة السابقة", "Next page": "الصفحة التالية", "First page": "الصفحة الأولى",
    "Last page": "الصفحة الأخيرة", "Batch tools": "أدوات دفعية", "Language": "اللغة",
    "Bookmarks": "العلامات المرجعية", "Comments": "التعليقات", "Search": "بحث", "Attachments": "المرفقات",
    "Thumbnails": "المصغرات", "Find in document": "بحث في المستند", "Match case": "مطابقة الحالة",
    "Whole words": "كلمات كاملة", "results": "نتيجة", "Add bookmark": "إضافة علامة", "Rename": "إعادة تسمية",
    "Apply": "تطبيق", "Cancel": "إلغاء", "OK": "موافق", "Color": "اللون", "Fill": "التعبئة",
    "Opacity": "الشفافية", "Width": "السماكة", "Author": "المؤلف", "Font size": "حجم الخط",
    "Recent files": "الملفات الأخيرة", "Quick tools": "أدوات سريعة", "Open file…": "فتح ملف…",
    "Drop PDF files here": "أسقط ملفات PDF هنا", "Settings": "الإعدادات", "Document properties": "خصائص المستند",
    "Unsaved changes": "تغييرات غير محفوظة", "Save changes to": "حفظ التغييرات في",
    "Pages to process": "الصفحات", "All pages": "كل الصفحات", "Output folder": "مجلد الإخراج",
    "Done": "تم", "Error": "خطأ", "No document": "لا يوجد مستند", "Page": "صفحة", "of": "من",
    "Find": "بحث", "Copy": "نسخ", "Select all": "تحديد الكل", "Insert pages from file": "إدراج صفحات من ملف",
    "Move": "نقل", "Text": "نص", "Image": "صورة", "Note": "ملاحظة", "Title": "العنوان",
    "Subject": "الموضوع", "Keywords": "كلمات مفتاحية", "Run": "تشغيل", "Add files": "إضافة ملفات",
    "Add folder": "إضافة مجلد", "Remove": "إزالة", "Clear": "مسح", "Actions": "الإجراءات",
    "Sequence": "التسلسل", "Report": "التقرير", "Folder monitor": "مراقبة مجلد", "Start": "بدء", "Stop": "إيقاف",
    "Save tool": "حفظ الأداة", "Load tool": "تحميل أداة", "Input files": "ملفات الإدخال",
    "Parameters": "المعطيات", "Waraq PDF Tools": "أدوات ورق PDF", "Measure": "قياس", "Distance": "مسافة",
    "Area": "مساحة", "Fill form": "تعبئة النموذج", "Form data": "بيانات النموذج", "Export data": "تصدير البيانات",
    "Import data": "استيراد البيانات", "Comments summary": "ملخص التعليقات", "Export comments": "تصدير التعليقات",
    "Import comments": "استيراد التعليقات", "Copy text": "نسخ النص", "Page labels": "تسميات الصفحات",
    "Compare": "مقارنة", "Start screen": "شاشة البداية", "Hide comments": "إخفاء التعليقات",
    "Select text": "اختيار النص", "Auto bookmarks": "إشارات تلقائية", "Pages to process": "الصفحات", "Select comments": "التعليقات التوضيحية", "Clipboard": "الحافظة",
    "Objects": "كائنات", "Add": "إضافة", "Annotations": "ملاحظات", "Typewriter": "آلة كاتبة", "Links": "المراجع",
    "Web links": "روابط الويب", "Create/edit link": "إنشاء/تحرير المرجع", "Sign document": "توقيع المستند",
    "Panes": "الأجزاء", "Previous view": "العرض السابق", "Next view": "العرض التالي", "Comments list": "قائمة التعليقات",
    "Recognize": "التعرف", "Send": "إرسال", "Email": "بريد إلكتروني", "Open containing folder": "فتح المجلد",
    "Copy file path": "نسخ مسار الملف", "Review": "مراجعة", "Compare documents": "مقارنة المستندات",
    "Verify signatures": "التحقق من التواقيع", "Word count": "عدد الكلمات", "Read aloud": "القراءة بصوت",
    "Read page": "قراءة الصفحة", "Read selection": "قراءة المحدد", "Title & language": "العنوان واللغة",
    "Bookmarks panel": "لوحة الإشارات", "Split by bookmarks": "تقسيم حسب الإشارات", "Help": "مساعدة",
    "User guide": "دليل الاستخدام", "Keyboard shortcuts": "اختصارات لوحة المفاتيح", "About": "حول البرنامج",
    "Format": "شكل", "Border color": "لون الحد", "Fill color": "لون التعبئة", "Colors": "الألوان",
    "Line": "خط", "Copy page as image": "نسخ الصفحة كصورة", "Paste image as stamp": "لصق صورة",
    "New document from clipboard": "مستند جديد من الحافظة", "Find next": "البحث التالي",
    "Create links from URLs": "إنشاء روابط من العناوين", "Remove all links": "حذف كل الروابط",
    "New signature…": "توقيع جديد…", "Copied": "تم النسخ", "Select text first (Select text tool)": "حدد النص أولاً بأداة اختيار النص",
    "No image in clipboard": "لا توجد صورة في الحافظة", "Delete all bookmarks?": "حذف كل الإشارات المرجعية؟",
    "links created": "رابط أُنشئ", "links removed": "رابط حُذف", "File path copied — attach it to the email": "تم نسخ مسار الملف — أرفقه بالرسالة",
    "Words": "الكلمات", "Characters": "الأحرف", "Inserted": "مضاف", "Deleted": "محذوف", "Changed pages": "صفحات متغيرة",
    "Text-to-speech is not available on this system.": "القراءة الصوتية غير متاحة على هذا الجهاز.",
    "PDF editor and tools": "محرر وأدوات PDF", "Use Windows title bar": "استخدام شريط عنوان ويندوز",
    "Restart Waraq PDF to apply.": "أعد تشغيل البرنامج للتطبيق.", "Hand": "يد", "Snapshot": "لقطة شاشة",
    "Search": "بحث", "Comment": "تعليق", "Stamp": "ختم", "Arrow": "سهم", "Rectangle": "مستطيل",
    "Add bookmark": "أضف إشارات مرجعية", "Highlight": "تسليط الضوء", "Underline": "تسطير", "Edit": "تحرير",
    "Select": "اختيار", "Actions": "إجراءات", "Area highlight": "تمييز منطقة", "Distance": "مسافة", "Area": "مساحة",
    "Pages": "الصفحات", "Document": "المستند", "Batch tools": "أدوات دفعية", "Start screen": "شاشة البداية",
    "Delete": "حذف", "Properties": "خصائص", "Hide comments": "إخفاء التعليقات", "Export comments": "تصدير التعليقات",
    "Import comments": "استيراد التعليقات", "Polyline": "خط متعدد", "Callout": "وسيلة شرح", "Squiggly": "متعرج",
    "Verify": "تحقق", "Signature": "توقيع يدوي", "Sanitize": "تنظيف",
}


def set_language(lang):
    global LANG
    LANG = lang


def tr(s):
    if LANG == "ar":
        return AR.get(s, s)
    return s


def is_rtl():
    return LANG == "ar"
