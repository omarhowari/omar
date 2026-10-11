# دليل المطوّر — تعديل TDA في Visual Studio وبناء نسخة جديدة

## 1) تجهيز الجهاز (مرة واحدة)

| البرنامج | لماذا | من أين |
|---|---|---|
| **Visual Studio 2022** (Community مجاني) | تعديل الكود وتشغيله وتتبّع الأخطاء | visualstudio.microsoft.com — عند التثبيت اختر **Python development** و **Desktop development with C++** |
| **Python 3.13** (64-bit) | تشغيل البرنامج من الكود | python.org — فعّل *Add python.exe to PATH* |
| **NSIS 3** | صنع ملف التثبيت `TDA-Setup.exe` | nsis.sourceforge.io |

(يمكن استخدام **VS Code** بدل Visual Studio: افتح المجلد مباشرة، فالإعدادات جاهزة في `.vscode/`.)

## 2) فتح المشروع

1. فك ضغط `TDA-source.zip` في مجلد، مثلاً `C:\TDA`.
2. افتح **`TDA.sln`** في Visual Studio.
3. أول مرة فقط: من نافذة **Python Environments** اختر Python 3.13، ثم افتح Terminal (View → Terminal) واكتب:
   ```
   python -m pip install -r requirements-dev.txt
   ```
4. اضغط **F5**: يعمل TDA من الكود مباشرة، ويمكنك وضع نقاط توقف (Breakpoints) في أي ملف.

> لتجربة شخصين على نفس الجهاز: شغّل نسخة ثانية بإعدادات منفصلة:
> `set TDA_CONFIG_DIR=C:\TDA\.profile2 && python main.py` (وغيّر المنافذ من الإعدادات في النسخة الثانية).

## 3) أين أعدّل ماذا؟

```
main.py                    نقطة البدء
tda/__init__.py            رقم النسخة APP_VERSION  ← غيّره عند كل إصدار
tda/i18n.py                كل نصوص الواجهة (عربي / English)
tda/ui/theme.py            الألوان والخطوط وشكل الأزرار (QSS) والشعار الافتراضي
tda/ui/main_window.py      النافذة الرئيسية، القائمة، شريط التحديث
tda/ui/chat.py             نافذة المحادثة وفقاعات الرسائل وبطاقات الملفات والصور
tda/ui/dialogs.py          الإعدادات، الشعار، نشر المظهر، إنشاء مجموعة، معاينة الصور
tda/ui/group_info.py       إدارة المجموعة (المشرفون، التجميد، المنع...)
tda/ui/share_picker.py     اختيار ما تتم مشاركته (شاشة / نافذة / مجلد)
tda/ui/share_app.py        مشاركة التطبيق (تلغرام، واتساب، بريد، بلوتوث...)
tda/ui/call_window.py      نافذة المكالمة والفيديو
tda/network.py             الشبكة: الاكتشاف، الرسائل، الملفات، الإرسال لغير المتصلين، المجموعات، التحديثات
tda/groups.py              قواعد صلاحيات المجموعات
tda/calls.py / video.py    المكالمات الصوتية والفيديو ومشاركة الشاشة
tda/winshare.py            التقاط نافذة تطبيق في Windows
tda/theme_share.py         توقيع مظهر المدير والتحقق منه (Ed25519)
tda/updates.py             التحديث عبر الشبكة
tda/config.py              الإعدادات المحفوظة (في %APPDATA%\TDA)
assets/                    الشعار والأيقونة وصورة الزخرفة
packaging/windows/         بناء ملف التثبيت
tests/                     الاختبارات
```

## 4) الاختبارات (قبل كل إصدار)

```
python -m tests.test_groups
python -m tests.test_network
python -m tests.test_update
python -m tests.test_calls
python -m tests.ui_smoke ar .shots      (يحفظ لقطات شاشة للواجهة في مجلد .shots)
```
في Visual Studio Code هي موجودة أيضاً في قائمة Run and Debug.

## 5) بناء ملف التثبيت

1. ارفع رقم النسخة في `tda/__init__.py` (مثلاً `1.5.1`)، وفي `packaging/windows/installer.nsi` (`VERSION` و `VIProductVersion`).
2. شغّل **`build_windows.bat`** (أو في VS Code: `Ctrl+Shift+B`).
3. الناتج في `dist\`:
   - `TDA-Setup.exe` ملف التثبيت.
   - `TDA-portable.zip` نسخة محمولة بدون تثبيت.

السكربت يحمّل Python المضمّن الرسمي ومكتبات PySide6 تلقائياً (يحتاج إنترنت أثناء البناء فقط)، ويبني `TDA.exe` بمترجم Visual Studio.

بدائل: من Linux/WSL: `packaging/windows/build_portable.sh dist` — أو من GitHub: Actions → Build Windows → Run workflow.

## 6) نشر التحديث على كل الأجهزة (بدون إلغاء تثبيت)

1. ثبّت `TDA-Setup.exe` الجديد على **جهاز واحد** فقط (فوق النسخة القديمة مباشرة، لا داعي لإلغاء التثبيت).
2. كل جهاز على الشبكة فيه نسخة أقدم يظهر له شريط أصفر: **«نسخة جديدة من TDA متوفرة» → تحديث الآن**.
3. عند الضغط: يُنزَّل المثبّت من الزميل عبر الشبكة الداخلية (مشفّر)، ويُغلق TDA، ويُثبَّت التحديث بصمت، ثم يفتح TDA من جديد. الرسائل والإعدادات والمجموعات تبقى كما هي (محفوظة في `%APPDATA%\TDA`).
4. كل جهاز تحدّث يصبح بدوره مصدراً للتحديث، فينتشر بسرعة حتى في شبكة كبيرة.

يمكن أيضاً: الإعدادات → إظهار الخيارات المتقدمة → «تثبيت تحديث من ملف…»، أو للمسؤول عن الشبكة توزيعه بصمت:
`TDA-Setup.exe /S` (يحافظ على اختيارات التثبيت الأولى ويعيد تشغيل TDA).

## 7) ملاحظات تقنية

- لا يوجد خادم: كل جهاز يعلن عن نفسه ببث UDP مشفّر، والرسائل والملفات عبر TCP مشفّر (AES-256-GCM).
- رسالة `hello` تحمل: النسخة `v`، وهل يملك ملف التثبيت `upd`، ونسخة مظهر المدير `thv`.
- التحديث: `update_req` ← يرسل الزميل المثبّت كنقل ملف داخلي (`purpose: "update"`) لا يُقبل إلا إذا طلبناه نحن.
- المظهر: `theme_req` ← `theme` (حزمة موقّعة بمفتاح Ed25519 مشتق من كلمة سر المدير). أول مفتاح يُقبل يُثبَّت، فلا يمكن لغير المدير تغيير مظهر الجميع.
