"""Tiny translation table (Arabic / English)."""

_LANG = "ar"

STRINGS = {
    "app_title": ("TDA - مراسل الشبكة المحلية", "TDA - LAN Messenger"),
    "users": ("المستخدمون", "Users"),
    "search_users": ("بحث عن مستخدم...", "Search users..."),
    "status_available": ("متاح", "Available"),
    "status_away": ("بعيد", "Away"),
    "status_busy": ("مشغول", "Busy"),
    "status_offline": ("غير متصل", "Offline"),
    "send": ("إرسال", "Send"),
    "send_file": ("إرسال ملف", "Send file"),
    "send_folder": ("إرسال مجلد", "Send folder"),
    "type_message": ("اكتب رسالتك... (Enter للإرسال، Shift+Enter لسطر جديد)",
                     "Type a message... (Enter to send, Shift+Enter for new line)"),
    "broadcast": ("رسالة جماعية", "Broadcast"),
    "broadcast_title": ("رسالة إلى عدة مستخدمين", "Message to several users"),
    "select_all": ("تحديد الكل", "Select all"),
    "select_none": ("إلغاء التحديد", "Select none"),
    "recipients": ("المستلمون", "Recipients"),
    "settings": ("الإعدادات", "Settings"),
    "transfers": ("نقل الملفات", "File transfers"),
    "history_search": ("بحث في السجل", "Search history"),
    "about": ("حول", "About"),
    "quit": ("خروج", "Quit"),
    "show": ("إظهار", "Show"),
    "my_status": ("حالتي", "My status"),
    "welcome_title": ("أهلاً بك في {name}", "Welcome to {name}"),
    "welcome_body": ("انقر مرتين على أي مستخدم لبدء المحادثة.\nيظهر تلقائياً كل من يشغّل TDA على نفس الشبكة.",
                     "Double-click a user to start chatting.\nEveryone running TDA on the same network appears automatically."),
    "name": ("اسمي", "Display name"),
    "group": ("المجموعة / القسم", "Group / department"),
    "language": ("اللغة", "Language"),
    "download_dir": ("مجلد الملفات المستلمة", "Received files folder"),
    "browse": ("استعراض...", "Browse..."),
    "password": ("كلمة سر الشبكة (تشفير AES-256)", "Network password (AES-256 encryption)"),
    "password_hint": ("يجب أن تكون نفسها عند جميع المستخدمين. اتركها فارغة لإلغاء التشفير.",
                      "Must be identical on every computer. Leave empty to disable encryption."),
    "extra_hosts": ("عناوين إضافية (شبكات فرعية أخرى)", "Extra addresses (other subnets)"),
    "extra_hosts_hint": ("عنوان IP أو عنوان بث في كل سطر، مثال: 192.168.2.255",
                         "One IP or broadcast address per line, e.g. 192.168.2.255"),
    "ports": ("المنافذ (UDP / TCP)", "Ports (UDP / TCP)"),
    "auto_away": ("الحالة «بعيد» تلقائياً بعد (دقائق، 0 = معطّل)", "Auto-away after (minutes, 0 = off)"),
    "notify": ("إظهار إشعار عند وصول رسالة", "Show notification on new message"),
    "sound": ("صوت تنبيه", "Sound alert"),
    "start_minimized": ("التشغيل مصغّراً في شريط المهام", "Start minimized to tray"),
    "autostart": ("التشغيل مع بدء Windows", "Start with Windows"),
    "restart_needed": ("بعض التغييرات تتطلب إعادة تشغيل البرنامج.", "Some changes need a restart."),
    "ok": ("موافق", "OK"),
    "cancel": ("إلغاء", "Cancel"),
    "accept": ("قبول", "Accept"),
    "decline": ("رفض", "Decline"),
    "open_folder": ("فتح المجلد", "Open folder"),
    "clear": ("مسح المنتهية", "Clear finished"),
    "file": ("الملف", "File"),
    "user": ("المستخدم", "User"),
    "size": ("الحجم", "Size"),
    "state": ("الحالة", "Status"),
    "progress": ("التقدّم", "Progress"),
    "sending_to": ("إرسال إلى", "To"),
    "receiving_from": ("من", "From"),
    "tr_offered_in": ("بانتظار موافقتك", "Waiting for you"),
    "tr_offered_out": ("بانتظار الموافقة", "Waiting for approval"),
    "tr_accepted": ("جارٍ البدء...", "Starting..."),
    "tr_active": ("جارٍ النقل", "Transferring"),
    "tr_done": ("اكتمل", "Completed"),
    "tr_failed": ("فشل", "Failed"),
    "tr_declined": ("مرفوض", "Declined"),
    "tr_canceled": ("ملغى", "Canceled"),
    "files_n": ("{n} ملفات", "{n} files"),
    "incoming_files": ("{name} يريد إرسال: {title}\u200f ({size})\u200f", "{name} wants to send: {title} ({size})"),
    "you_sent_files": ("أرسلت: {title}\u200f ({size})\u200f", "You offered: {title} ({size})"),
    "new_message_from": ("رسالة جديدة من {name}", "New message from {name}"),
    "not_delivered": ("لم تُسلَّم", "Not delivered"),
    "delivered": ("تم التسليم", "Delivered"),
    "multi_tag": ("رسالة جماعية", "Broadcast"),
    "peer_offline": ("المستخدم غير متصل حالياً", "User is offline"),
    "clear_history": ("مسح سجل المحادثة", "Clear chat history"),
    "close_tab": ("إغلاق", "Close"),
    "start_error": ("تعذّر تشغيل الشبكة:\n{err}\n\nربما هناك نسخة أخرى من TDA تعمل، أو المنفذ محجوز.",
                    "Could not start networking:\n{err}\n\nAnother TDA instance may be running or the port is in use."),
    "tray_running": ("TDA يعمل في الخلفية", "TDA is running in the background"),
    "online_count": ("{n} متصل", "{n} online"),
    "info": ("معلومات", "Info"),
    "computer": ("الحاسب", "Computer"),
    "address": ("العنوان", "Address"),
    "system": ("النظام", "System"),
    "about_text": ("<h2>TDA {v}</h2><p>مراسل فوري للشبكة المحلية بدون خادم.<br>"
                   "مفتوح المصدر بترخيص MIT.</p><ul><li>اكتشاف تلقائي للمستخدمين</li>"
                   "<li>محادثات فردية ورسائل جماعية</li><li>إرسال الملفات والمجلدات</li>"
                   "<li>تشفير AES-256-GCM اختياري</li><li>سجل محادثات محلي</li></ul>",
                   "<h2>TDA {v}</h2><p>Serverless instant messenger for local networks.<br>"
                   "Open source, MIT license.</p><ul><li>Automatic user discovery</li>"
                   "<li>Private chats and broadcast messages</li><li>File and folder transfer</li>"
                   "<li>Optional AES-256-GCM encryption</li><li>Local chat history</li></ul>"),
    "branding": ("الهوية والشعار", "Branding"),
    "branding_btn": ("🔒  تخصيص الشعار والصور...", "🔒  Customize logo and images..."),
    "branding_hint": ("محمي بكلمة سر المدير.", "Protected by the administrator password."),
    "admin_pw_create": ("إنشاء كلمة سر المدير", "Create administrator password"),
    "admin_pw_create_text": ("هذه أول مرة. اختر كلمة سر للمدير لحماية إعدادات الهوية:",
                             "First time: choose an administrator password to protect branding:"),
    "admin_pw_confirm": ("أعد كتابة كلمة السر للتأكيد:", "Type the password again to confirm:"),
    "admin_pw_enter": ("أدخل كلمة سر المدير:", "Enter the administrator password:"),
    "admin_pw_wrong": ("كلمة السر غير صحيحة.", "Wrong password."),
    "admin_pw_mismatch": ("كلمتا السر غير متطابقتين.", "Passwords do not match."),
    "admin_pw_short": ("يجب أن تكون كلمة السر 4 أحرف على الأقل.", "Password must be at least 4 characters."),
    "admin_pw_change": ("تغيير كلمة سر المدير", "Change administrator password"),
    "admin_pw_new": ("كلمة السر الجديدة:", "New password:"),
    "admin_pw_saved": ("تم حفظ كلمة السر.", "Password saved."),
    "admin_locked": ("محاولات كثيرة خاطئة. حاول بعد دقيقة.", "Too many wrong attempts. Try again in a minute."),
    "logo": ("أيقونة / شعار التطبيق", "App icon / logo"),
    "logo_hint": ("PNG أو JPG، ويفضّل مربعة بخلفية شفافة (512×512). تظهر في النافذة وشريط المهام واختصارات سطح المكتب.",
                  "PNG or JPG, ideally square with transparent background (512×512). Used for window, tray and shortcuts."),
    "welcome_image": ("صورة شاشة الترحيب", "Welcome screen picture"),
    "app_name_shown": ("اسم التطبيق الظاهر", "Displayed app name"),
    "choose_image": ("اختيار صورة...", "Choose image..."),
    "restore_default": ("استعادة الافتراضي", "Restore default"),
    "bad_image": ("تعذّر قراءة الصورة.", "Could not read the image."),
    "images": ("صور", "Images"),
    "default": ("(الافتراضي)", "(default)"),
    "branding_saved": ("تم تطبيق الهوية الجديدة.", "New branding applied."),
    "call": ("مكالمة", "Call"),
    "call_btn": ("📞 اتصال", "📞 Call"),
    "answer": ("رد", "Answer"),
    "hang_up": ("إنهاء", "Hang up"),
    "mute": ("كتم الميكروفون", "Mute microphone"),
    "call_incoming": ("مكالمة صوتية واردة...", "Incoming voice call..."),
    "call_calling": ("جارٍ الاتصال...", "Calling..."),
    "audio_problem": ("تعذّر فتح الميكروفون أو السماعة. تحقق من إعدادات الصوت والخصوصية في Windows.",
                      "Could not open microphone or speaker. Check Windows sound and privacy settings."),
    "call_busy_now": ("أنت في مكالمة الآن.", "You are already in a call."),
    "call_log_out": ("مكالمة صادرة", "Outgoing call"),
    "call_log_in": ("مكالمة واردة", "Incoming call"),
    "call_log_missed": ("مكالمة فائتة", "Missed call"),
    "call_log_no_answer": ("لم يتم الرد", "No answer"),
    "call_log_declined": ("رُفضت المكالمة", "Call declined"),
    "call_log_busy": ("المستخدم مشغول بمكالمة أخرى", "User is busy on another call"),
    "call_log_unreachable": ("تعذّر الوصول إلى المستخدم", "User unreachable"),
    "call_log_lost": ("انقطع الاتصال", "Connection lost"),
    "call_log_canceled": ("أُلغيت المكالمة", "Call canceled"),
    "incoming_call_from": ("مكالمة من {name}", "Call from {name}"),
    "open": ("فتح", "Open"),
    "sent_ok": ("تم الإرسال", "Sent"),
    "drop_here": ("أفلِت الملفات هنا لإرسالها إلى {name}", "Drop files here to send to {name}"),
    "search": ("بحث", "Search"),
    "results": ("النتائج", "Results"),
    "me": ("أنا", "Me"),
    "today": ("اليوم", "Today"),
    "drop_hint": ("اسحب أي ملف أو مجلد إلى المحادثة لإرساله، أو الصقه بـ Ctrl+V", "Drag any file or folder into the chat, or paste with Ctrl+V"),
}


def set_language(lang: str):
    global _LANG
    _LANG = "en" if lang == "en" else "ar"


def lang() -> str:
    return _LANG


def tr(key: str, **kw) -> str:
    pair = STRINGS.get(key)
    if not pair:
        return key
    s = pair[0] if _LANG == "ar" else pair[1]
    return s.format(**kw) if kw else s


def human_size(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            txt = f"{f:.0f} {u}" if u == "B" else f"{f:.1f} {u}"
            return "\u202a" + txt + "\u202c"   # keep "2.3 MB" left-to-right inside Arabic text
        f /= 1024
    return f"{n} B"
