"""Inline stroke icons (24x24) rendered to QIcon via QtSvg."""
from PySide6.QtCore import QByteArray, Qt, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

P = {
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
    "saveas": '<path d="M5 3h11l3 3v6M7 3v5h8V3M7 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2"/><path d="M14 21l1-3 5-5 2 2-5 5z"/>',
    "print": '<path d="M6 9V3h12v6M6 18H4v-7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v7h-2"/><rect x="6" y="14" width="12" height="7"/>',
    "hand": '<path d="M8 13V5a1.5 1.5 0 0 1 3 0v6M11 11V4a1.5 1.5 0 0 1 3 0v7M14 11V5.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-1a6 6 0 0 1-5-3l-2.5-4a1.5 1.5 0 0 1 2.5-1.7L8 15"/>',
    "select": '<path d="M5 3l14 7-6 2-2 6z"/>',
    "snapshot": '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><circle cx="12" cy="12" r="3"/>',
    "zoomin": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5M11 8v6M8 11h6"/>',
    "zoomout": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5M8 11h6"/>',
    "fitwidth": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "fitpage": '<rect x="6" y="3" width="12" height="18"/><path d="M9 8h6M9 12h6"/>',
    "text": '<path d="M4 7V5h16v2M12 5v14M9 19h6"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "extracttext": '<path d="M6 3h8l4 4v14H6zM9 9h3M9 13h6M9 17h6"/>',
    "highlight": '<path d="M15 5l4 4-9 9H6v-4z"/><path d="M4 21h9" stroke="#CA8A04" stroke-width="3"/>',
    "underline": '<path d="M7 4v7a5 5 0 0 0 10 0V4M5 20h14"/>',
    "strike": '<path d="M5 12h14M16 7a4 4 0 0 0-4-2c-2.5 0-4 1.3-4 3 0 1.4 1 2.3 3 3M8 17a4 4 0 0 0 4 2c2.5 0 4-1.3 4-3"/>',
    "note": '<path d="M5 3h14a2 2 0 0 1 2 2v10l-6 6H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M15 21v-6h6"/>',
    "textbox": '<rect x="3" y="5" width="18" height="14"/><path d="M7 9h10M12 9v6"/>',
    "stamp": '<path d="M9 13V9a3 3 0 1 1 6 0v4M4 17h16v3H4zM6 13h12l1 4H5z"/>',
    "rect": '<rect x="4" y="6" width="16" height="12"/>',
    "oval": '<ellipse cx="12" cy="12" rx="8" ry="6"/>',
    "line": '<path d="M5 19L19 5"/>',
    "arrow": '<path d="M5 19L19 5M10 5h9v9"/>',
    "pencil": '<path d="M4 20l1-4L16 5l3 3L8 19z"/>',
    "insert": '<path d="M6 3h8l4 4v14H6zM12 11v6M9 14h6"/>',
    "blank": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "delete": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "extract": '<path d="M14 3H6v18h6M14 3l4 4v5M15 17h6M18 14l3 3-3 3"/>',
    "rotate": '<path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/>',
    "rotateleft": '<path d="M4 12a8 8 0 1 0 2.3-5.7M4 4v5h5"/>',
    "merge": '<path d="M6 4v5a3 3 0 0 0 3 3h6a3 3 0 0 1 3 3v5M18 4v5a3 3 0 0 1-3 3"/>',
    "split": '<path d="M12 3v18M6 8l-3 4 3 4M18 8l3 4-3 4"/>',
    "compress": '<path d="M4 14l4 4 4-4M8 18V4M20 10l-4-4-4 4M16 6v14"/>',
    "toimages": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
    "imagestopdf": '<path d="M6 3h8l4 4v14H6zM9 13h6M9 17h4"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "unlock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
    "redact": '<rect x="3" y="9" width="18" height="6" fill="currentColor"/>',
    "watermark": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "sign": '<path d="M3 17c3 0 4-8 6-8s0 8 3 8 3-4 5-4 2 2 4 2M3 21h18"/>',
    "pagenum": '<path d="M6 3h8l4 4v14H6z"/><path d="M10 17h4M12 13v4"/>',
    "single": '<rect x="7" y="3" width="10" height="18"/>',
    "continuous": '<rect x="7" y="2" width="10" height="9"/><rect x="7" y="13" width="10" height="9"/>',
    "twopage": '<rect x="2" y="5" width="9" height="14"/><rect x="13" y="5" width="9" height="14"/>',
    "dark": '<path d="M20 14A8 8 0 1 1 10 4a6 6 0 0 0 10 10z"/>',
    "fullscreen": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "thumbs": '<rect x="4" y="4" width="7" height="7"/><rect x="13" y="4" width="7" height="7"/><rect x="4" y="13" width="7" height="7"/><rect x="13" y="13" width="7" height="7"/>',
    "bookmark": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "comments": '<path d="M4 5h16v11H9l-5 4z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    "prev": '<path d="M15 6l-6 6 6 6"/>',
    "next": '<path d="M9 6l6 6-6 6"/>',
    "first": '<path d="M17 6l-6 6 6 6M7 6v12"/>',
    "last": '<path d="M7 6l6 6-6 6M17 6v12"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "home": '<path d="M3 11l9-7 9 7v9H3z"/>',
    "attach": '<path d="M20 11l-8.5 8.5a5 5 0 0 1-7-7L13 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L14 7"/>',
    "crop": '<path d="M6 2v16h16M2 6h16v16"/>',
}

P.update({
    "email": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>',
    "back": '<circle cx="12" cy="12" r="9"/><path d="M13 8l-4 4 4 4M9 12h7"/>',
    "forward": '<circle cx="12" cy="12" r="9"/><path d="M11 8l4 4-4 4M15 12H8"/>',
    "clipboard": '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 10h6M9 14h6M9 18h3"/>',
    "typewriter": '<path d="M4 7V5h11v2M9.5 5v14M7 19h5"/><path d="M17 9v10M15 9h4M15 19h4"/>',
    "web": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "linkchain": '<path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1"/><path d="M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1"/>',
    "bookmark_add": '<path d="M6 3h10v18l-5-4-5 4z"/><path d="M18 8v6M15 11h6"/>',
    "compare": '<rect x="3" y="4" width="8" height="16"/><rect x="13" y="4" width="8" height="16"/><path d="M5 9h4M15 9h4M5 13h4M15 13h2"/>',
    "speaker": '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7M12 16.5v.5"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h1M10 10h1M14 10h1M18 10h0M7 14h10"/>',
    "panel": '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M9 4v16"/>',
    "selectcomment": '<rect x="3" y="3" width="13" height="10" rx="1"/><path d="M6 7h7"/><path d="M13 12l7 3.5-3 1-1 3z"/>',
    "selecttext": '<path d="M3 6V4h9v2M7.5 4v12M5 16h5"/><path d="M14 9l7 3.5-3 1-1 3z"/>',
    "fitvisible": '<rect x="6" y="3" width="12" height="18"/><path d="M3 9V6M3 18v-3M21 9V6M21 18v-3"/>',
    "comparedoc": '<path d="M4 4h7v16H4zM13 4h7v16h-7z"/><path d="M7 12h10M15 10l2 2-2 2"/>',
    "properties": '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "folderopen": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H7l-4 9z"/><path d="M3 19l4-9h16l-4 9z"/>',
    "about": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "language": '<path d="M4 5h9M8.5 3v2M6 5c0 4 3 7 6 8M11 5c0 3-3 7-7 8"/><path d="M13 21l4-9 4 9M14.5 18h5"/>',
})

# accent colour per icon for the colourful ribbon style (stroke colour, fill colour or None)
ACCENT = {
    "open": ("#B7791F", "#F6C343"), "folderopen": ("#B7791F", "#F6C343"), "save": ("#2B6CB0", "#90CDF4"),
    "saveas": ("#2B6CB0", "#90CDF4"), "print": ("#4A5568", "#CBD5E0"), "email": ("#2B6CB0", "#BEE3F8"),
    "hand": ("#8B5A2B", "#F3D6B3"), "select": ("#2D3748", None), "selecttext": ("#2D3748", None),
    "selectcomment": ("#B7791F", "#FAF089"), "snapshot": ("#4A5568", None), "zoomin": ("#2B6CB0", None),
    "zoomout": ("#2B6CB0", None), "fitwidth": ("#2B6CB0", None), "fitpage": ("#2B6CB0", "#E2E8F0"),
    "fitvisible": ("#2B6CB0", "#E2E8F0"), "text": ("#2D3748", None), "typewriter": ("#2D3748", None),
    "image": ("#2F855A", "#C6F6D5"), "extracttext": ("#4A5568", "#EDF2F7"), "highlight": ("#B7791F", "#FAF089"),
    "underline": ("#2B6CB0", None), "strike": ("#C53030", None), "note": ("#B7791F", "#FAF089"),
    "textbox": ("#2B6CB0", "#E2E8F0"), "stamp": ("#C53030", "#FED7D7"), "rect": ("#C53030", None),
    "oval": ("#C53030", None), "line": ("#C53030", None), "arrow": ("#C53030", None), "pencil": ("#2F855A", "#C6F6D5"),
    "insert": ("#2F855A", "#C6F6D5"), "blank": ("#4A5568", "#FFFFFF"), "delete": ("#C53030", "#FED7D7"),
    "extract": ("#2B6CB0", "#BEE3F8"), "rotate": ("#2F855A", None), "rotateleft": ("#2F855A", None),
    "merge": ("#6B46C1", None), "split": ("#6B46C1", None), "compress": ("#DD6B20", None),
    "toimages": ("#2F855A", "#C6F6D5"), "imagestopdf": ("#C53030", "#FED7D7"), "lock": ("#B7791F", "#FAF089"),
    "unlock": ("#B7791F", "#FAF089"), "redact": ("#1A202C", None), "watermark": ("#3182CE", "#BEE3F8"),
    "sign": ("#2B6CB0", None), "pagenum": ("#4A5568", "#EDF2F7"), "single": ("#4A5568", "#EDF2F7"),
    "continuous": ("#4A5568", "#EDF2F7"), "twopage": ("#4A5568", "#EDF2F7"), "dark": ("#4A5568", "#CBD5E0"),
    "fullscreen": ("#2B6CB0", None), "thumbs": ("#2B6CB0", "#BEE3F8"), "bookmark": ("#3182CE", "#BEE3F8"),
    "bookmark_add": ("#3182CE", "#BEE3F8"), "comments": ("#B7791F", "#FAF089"), "search": ("#4A5568", None),
    "undo": ("#2B6CB0", None), "redo": ("#2B6CB0", None), "back": ("#2F855A", None), "forward": ("#2F855A", None),
    "info": ("#2B6CB0", None), "attach": ("#4A5568", None), "crop": ("#2D3748", None), "clipboard": ("#8B5A2B", "#F3D6B3"),
    "web": ("#2B6CB0", "#BEE3F8"), "linkchain": ("#DD6B20", None), "compare": ("#6B46C1", "#E9D8FD"),
    "comparedoc": ("#6B46C1", "#E9D8FD"), "speaker": ("#2F855A", "#C6F6D5"), "stop": ("#C53030", "#FED7D7"),
    "help": ("#2B6CB0", "#BEE3F8"), "keyboard": ("#4A5568", "#EDF2F7"), "panel": ("#4A5568", "#EDF2F7"),
    "properties": ("#4A5568", "#EDF2F7"), "about": ("#2B6CB0", None), "language": ("#2B6CB0", None),
    "home": ("#2B6CB0", None), "first": ("#2B6CB0", None), "last": ("#2B6CB0", None), "prev": ("#2B6CB0", None),
    "next": ("#2B6CB0", None), "polygon": ("#C53030", None),
}

P.update({
    "rulers": '<path d="M3 8h18v8H3z"/><path d="M6 8v3M9 8v2M12 8v3M15 8v2M18 8v3"/>',
    "grid": '<rect x="3" y="3" width="18" height="18"/><path d="M9 3v18M15 3v18M3 9h18M3 15h18"/>',
    "eraser": '<path d="M15 4l5 5-9 9H7l-3-3z"/><path d="M9 10l5 5M7 18h13"/>',
    "cloud": '<path d="M7 18a4 4 0 0 1-.5-8 5 5 0 0 1 9.6-1.5A4 4 0 1 1 17 18z"/>',
    "caret": '<path d="M5 18l7-12 7 12"/><path d="M4 21h16"/>',
    "replace": '<path d="M4 7h10M4 7l3-3M4 7l3 3"/><path d="M20 17H10M20 17l-3-3M20 17l-3 3"/>',
    "perimeter": '<path d="M4 18l4-12 8 3 4 9z"/><circle cx="4" cy="18" r="1.5"/><circle cx="20" cy="18" r="1.5"/>',
    "facing": '<rect x="2" y="5" width="9" height="14"/><rect x="13" y="5" width="9" height="14"/>',
    "facingcont": '<rect x="2" y="2" width="9" height="9"/><rect x="13" y="2" width="9" height="9"/><rect x="2" y="13" width="9" height="9"/><rect x="13" y="13" width="9" height="9"/>',
    "button": '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M8 12h8"/>',
    "date": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M7 14h2M11 14h2M15 14h2M7 17h2M11 17h2"/>',
    "checkfield": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12l3 3 5-6"/>',
    "radiofield": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5" fill="currentColor"/>',
    "listfield": '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M6 8h9M6 12h9M6 16h9M18 8l1 1-1 1"/>',
    "combofield": '<rect x="3" y="7" width="18" height="10" rx="1"/><path d="M15 7v10M17 11l1 1.5 1-1.5"/>',
    "sigfield": '<rect x="3" y="6" width="18" height="12" rx="1"/><path d="M6 14c2 0 2-4 4-4s0 4 2 4 2-2 3-2 1 1 3 1"/>',
    "toc": '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M8 7h8M8 11h6M10 15h6M8 19h4"/>',
    "sort": '<path d="M7 4v16M4 17l3 3 3-3M14 6h6M14 11h4M14 16h2"/>',
    "case": '<path d="M3 18l4-11 4 11M4.5 14h5"/><circle cx="17" cy="15" r="3"/><path d="M20 12v6"/>',
    "overlay": '<rect x="3" y="3" width="12" height="14"/><rect x="9" y="7" width="12" height="14"/>',
    "swap": '<rect x="3" y="4" width="7" height="10"/><rect x="14" y="10" width="7" height="10"/><path d="M12 6h5l-2-2M12 18H7l2 2"/>',
    "grayscale": '<circle cx="12" cy="12" r="9"/><path d="M12 3v18" /><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>',
    "enhance": '<path d="M6 3h8l4 4v14H6z"/><path d="M9 16l2-5 2 3 1-2 2 4z"/><path d="M19 2l.5 1.5L21 4l-1.5.5L19 6l-.5-1.5L17 4l1.5-.5z"/>',
    "ppt": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 16V8h4a2.5 2.5 0 0 1 0 5H8"/>',
    "excel": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 8l8 8M16 8l-8 8"/>',
    "word": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M6 8l2 8 2-6 2 6 2-8"/>',
    "timestamp": '<path d="M6 3h9l4 4v6"/><path d="M6 3v18h6"/><circle cx="17" cy="17" r="4"/><path d="M17 15v2l1.5 1"/>',
    "cert": '<path d="M5 3h14v12H5z"/><circle cx="12" cy="13" r="3"/><path d="M10.5 15.5L9 21l3-1.5 3 1.5-1.5-5.5"/>',
    "access": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="7.5" r="1.3"/><path d="M7 10h10M12 10v4l-2.5 4M12 14l2.5 4"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "nav": '<path d="M5 12h14M9 8l-4 4 4 4M15 8l4 4-4 4"/>',
    "tools": '<path d="M14 6a4 4 0 0 0 5 5l-8 8a2 2 0 1 1-3-3l8-8a4 4 0 0 1-2-2z"/>',
    "exclusive": '<path d="M5 9l3-4 4 3 4-3 3 4v8H5z"/>',
    "smooth": '<path d="M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4"/>',
    "barcode": '<path d="M4 5v14M7 5v14M9 5v14M12 5v14M15 5v14M17 5v14M20 5v14"/>',
    "tabs": '<path d="M3 8h6l1-3h4l1 3h6v11H3z"/>',
    "update": '<path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/>',
    "bug": '<rect x="7" y="8" width="10" height="12" rx="5"/><path d="M12 8v12M4 12h3M17 12h3M5 18l2-2M19 18l-2-2M9 6l1 2M15 6l-1 2"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    "default": '<path d="M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z"/>',
})
ACCENT.update({
    "rulers": ("#B7791F", "#FAF089"), "grid": ("#4A5568", None), "eraser": ("#C53030", "#FED7D7"),
    "cloud": ("#C53030", None), "caret": ("#2B6CB0", None), "replace": ("#C53030", None), "perimeter": ("#C53030", None),
    "facing": ("#4A5568", "#EDF2F7"), "facingcont": ("#4A5568", "#EDF2F7"), "button": ("#4A5568", "#E2E8F0"),
    "date": ("#2B6CB0", "#BEE3F8"), "checkfield": ("#2D3748", "#FFFFFF"), "radiofield": ("#2D3748", "#FFFFFF"),
    "listfield": ("#2D3748", "#FFFFFF"), "combofield": ("#2D3748", "#FFFFFF"), "sigfield": ("#2B6CB0", "#FFFFFF"),
    "toc": ("#3182CE", "#BEE3F8"), "sort": ("#3182CE", None), "case": ("#3182CE", None), "overlay": ("#6B46C1", "#E9D8FD"),
    "swap": ("#2B6CB0", "#BEE3F8"), "grayscale": ("#4A5568", None), "enhance": ("#2F855A", "#C6F6D5"),
    "ppt": ("#C05621", "#FBD38D"), "excel": ("#276749", "#9AE6B4"), "word": ("#2B6CB0", "#90CDF4"),
    "timestamp": ("#C53030", "#FED7D7"), "cert": ("#C53030", "#FED7D7"), "access": ("#2B6CB0", None),
    "check": ("#2F855A", None), "nav": ("#2B6CB0", None), "tools": ("#4A5568", None), "exclusive": ("#B7791F", "#FAF089"),
    "smooth": ("#2B6CB0", None), "barcode": ("#1A202C", None), "tabs": ("#4A5568", "#EDF2F7"), "update": ("#2F855A", None),
    "bug": ("#2F855A", "#C6F6D5"), "terminal": ("#2D3748", "#E2E8F0"), "default": ("#B7791F", "#FAF089"),
})

_cache = {}
THEME_COLOR = "#1F2937"   # default icon colour; switched by the theme
DARK_ICONS = False


def cicon(name: str, size: int = 64) -> QIcon:
    """Colourful two-tone icon (ribbon style)."""
    stroke, fill = ACCENT.get(name, (THEME_COLOR, None))
    if DARK_ICONS and stroke in ("#2D3748", "#1A202C", "#4A5568"):
        stroke = "#D6DEE8"
    key = ("c", name, size, DARK_ICONS)
    if key in _cache:
        return _cache[key]
    body = P.get(name, P["info"]).replace("currentColor", stroke)
    fill_attr = f'fill="{fill}"' if fill else 'fill="none"'
    # fills only make sense on closed shapes: draw a filled copy underneath (rect/ellipse/circle/closed paths)
    import re
    closed = "".join(m for m in re.findall(r"<(?:rect|ellipse|circle)[^>]*/>", body))
    closed += "".join(m for m in re.findall(r'<path d="[^"]*z"\s*/>', body))
    under = closed.replace("/>", f' {fill_attr} stroke="none"/>') if fill else ""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{stroke}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{under}{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def set_icon_color(c):
    global THEME_COLOR
    THEME_COLOR = c


def icon(name: str, color: str = None, size: int = 48) -> QIcon:
    color = color or THEME_COLOR
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    body = P.get(name, P["info"]).replace("currentColor", color)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic
