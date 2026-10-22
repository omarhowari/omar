"""Waraq PDF Tools window: tool library, action-sequence editor, batch runner, report and folder monitor."""
import json
import os
import shutil
import time

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QLineEdit, QCheckBox, QTabWidget,
                               QProgressBar, QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
                               QMessageBox, QInputDialog, QSpinBox, QComboBox, QFormLayout, QGroupBox, QAbstractItemView,
                               QApplication)

from . import batch
from .dialogs import ask, FileListWidget, app_data_dir, _PathEdit
from .i18n import tr
from .icons import icon

INPUT_EXT = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".docx", ".doc", ".xlsx",
             ".xls", ".pptx", ".ppt", ".odt", ".rtf", ".txt", ".md", ".html", ".htm", ".xps", ".epub", ".csv")


def tools_dir():
    d = os.path.join(app_data_dir(), "tools")
    os.makedirs(d, exist_ok=True)
    return d


class Worker(QThread):
    log = Signal(str)
    prog = Signal(int, int)
    done = Signal(object)

    def __init__(self, tool, files, author=""):
        super().__init__()
        self.tool, self.files, self.author = tool, files, author
        self.cancel = False

    def run(self):
        import logging
        logging.disable(logging.WARNING)

        def progress(i, n):
            self.prog.emit(i, n)
            return not self.cancel
        rep = batch.run_tool(self.tool, self.files, self.log.emit, progress, self.author)
        self.done.emit(rep)


class ToolsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("Waraq PDF Tools"))
        self.resize(1250, 800)
        self.tool = None
        self.worker = None
        tabs = QTabWidget()
        tabs.setObjectName("ribbon")
        tabs.addTab(self._build_runner(), icon("compress"), tr("Batch tools"))
        tabs.addTab(self._build_monitor(), icon("search"), tr("Folder monitor"))
        self.setCentralWidget(tabs)
        self._load_tools()

    # ---------------------------------------------------------------- runner tab
    def _build_runner(self):
        w = QWidget()
        h = QHBoxLayout(w)
        split = QSplitter(Qt.Horizontal)
        h.addWidget(split)

        # tools list
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(self._title(tr("Tools")))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search") + "…")
        self.search.textChanged.connect(self._filter_tools)
        lv.addWidget(self.search)
        self.tool_list = QListWidget()
        self.tool_list.currentItemChanged.connect(self._tool_selected)
        lv.addWidget(self.tool_list)
        row = QHBoxLayout()
        for label, slot in (("New", self.new_tool), ("Clone", self.clone_tool), (tr("Delete"), self.delete_tool)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        lv.addLayout(row)
        row2 = QHBoxLayout()
        for label, slot in (("Import…", self.import_tool), ("Export…", self.export_tool)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row2.addWidget(b)
        lv.addLayout(row2)
        split.addWidget(left)

        # sequence editor + action library
        mid = QWidget()
        mv = QVBoxLayout(mid)
        self.tool_name = QLineEdit()
        self.tool_name.setPlaceholderText("Tool name")
        self.tool_name.editingFinished.connect(self._rename)
        mv.addWidget(self._title(tr("Sequence")))
        mv.addWidget(self.tool_name)
        self.seq = QListWidget()
        self.seq.setDragDropMode(QAbstractItemView.InternalMove)
        self.seq.model().rowsMoved.connect(lambda *a: QTimer.singleShot(0, self._seq_moved))
        self.seq.itemDoubleClicked.connect(self.edit_step)
        mv.addWidget(self.seq, 2)
        r = QHBoxLayout()
        for label, slot in (("Edit…", lambda: self.edit_step(self.seq.currentItem())), ("↑", lambda: self.move_step(-1)),
                            ("↓", lambda: self.move_step(1)), (tr("Remove"), self.remove_step)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            r.addWidget(b)
        mv.addLayout(r)
        mv.addWidget(self._title(tr("Actions") + " — double-click to add"))
        self.lib = QTreeWidget()
        self.lib.setHeaderHidden(True)
        for cat in batch.CATEGORIES:
            ci = QTreeWidgetItem(self.lib, [cat])
            for aid, a in batch.ACTIONS.items():
                if a["category"] == cat:
                    it = QTreeWidgetItem(ci, [a["title"]])
                    it.setData(0, Qt.UserRole, aid)
        self.lib.expandAll()
        self.lib.itemDoubleClicked.connect(self.add_step)
        mv.addWidget(self.lib, 3)
        split.addWidget(mid)

        # input / output / run / report
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(self._title(tr("Input files")))
        self.files = FileListWidget("Documents (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.docx *.doc *.xlsx *.xls "
                                    "*.pptx *.txt *.md *.html *.xps *.epub);;All files (*)")
        self.files.add_folder = lambda folder=None, exts=INPUT_EXT, _f=self.files.add_folder: _f(folder, exts)
        rv.addWidget(self.files, 2)
        box = QGroupBox("Output")
        f = QFormLayout(box)
        self.out_folder = _PathEdit("folder", "")
        self.out_folder.edit.setPlaceholderText("Same folder as each file")
        self.out_pattern = QLineEdit("{name}_{tool}")
        self.out_pattern.setToolTip("{name} {tool} {date} {time} {n}")
        self.overwrite = QCheckBox("Overwrite existing files")
        self.merge = QCheckBox("Combine all results into one PDF")
        f.addRow(tr("Output folder"), self.out_folder)
        f.addRow("File name", self.out_pattern)
        f.addRow("", self.overwrite)
        f.addRow("", self.merge)
        rv.addWidget(box)
        rr = QHBoxLayout()
        self.run_btn = QPushButton(icon("next", "#FFFFFF"), "  " + tr("Run"))
        self.run_btn.setObjectName("primary")
        self.run_btn.setMinimumHeight(38)
        self.run_btn.clicked.connect(self.run)
        self.stop_btn = QPushButton(tr("Stop"))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        rr.addWidget(self.run_btn, 2)
        rr.addWidget(self.stop_btn, 1)
        rv.addLayout(rr)
        self.bar = QProgressBar()
        rv.addWidget(self.bar)
        rt = QTabWidget()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Status", "Output", "Notes"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._open_output)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        rt.addTab(self.table, tr("Report"))
        rt.addTab(self.logbox, "Log")
        rv.addWidget(rt, 2)
        self.save_report = QPushButton("Save report…")
        self.save_report.clicked.connect(self._save_report)
        self.save_report.setEnabled(False)
        rv.addWidget(self.save_report)
        split.addWidget(right)
        split.setSizes([260, 400, 560])
        for wdg in (self.out_pattern,):
            wdg.editingFinished.connect(self._store_output)
        self.overwrite.toggled.connect(self._store_output)
        self.merge.toggled.connect(self._store_output)
        self.out_folder.edit.editingFinished.connect(self._store_output)
        return w

    def _title(self, s):
        l = QLabel(s)
        l.setObjectName("panelTitle")
        return l

    # ---------------------------------------------------------------- tools storage
    def _load_tools(self):
        self.tool_list.clear()
        for t in batch.presets():
            self._add_tool_item(t)
        for fn in sorted(os.listdir(tools_dir())):
            if fn.endswith(".json"):
                try:
                    t = json.load(open(os.path.join(tools_dir(), fn), encoding="utf-8"))
                    t["_file"] = fn
                    self._add_tool_item(t)
                except Exception:
                    pass
        self.tool_list.setCurrentRow(0)
        self._refresh_monitor_tools()

    def _add_tool_item(self, t):
        it = QListWidgetItem(icon("compress" if t.get("preset") else "save"), t["name"])
        it.setData(Qt.UserRole, t)
        if not t.get("preset"):
            it.setForeground(QColor("#1D4ED8"))
        self.tool_list.addItem(it)
        return it

    def _filter_tools(self, q):
        q = q.lower()
        for i in range(self.tool_list.count()):
            it = self.tool_list.item(i)
            it.setHidden(bool(q) and q not in it.text().lower())

    def _save_tool(self):
        t = self.tool
        if not t or t.get("preset"):
            return
        fn = t.get("_file") or ("".join(c for c in t["name"] if c.isalnum() or c in " _-").strip() or "tool") + f"_{int(time.time())}.json"
        t["_file"] = fn
        data = {k: v for k, v in t.items() if not k.startswith("_")}
        json.dump(data, open(os.path.join(tools_dir(), fn), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        it = self.tool_list.currentItem()
        if it:
            it.setText(t["name"])
            it.setData(Qt.UserRole, t)
        self._refresh_monitor_tools()

    def _tool_selected(self, it, _prev=None):
        if not it:
            return
        self.tool = it.data(Qt.UserRole)
        self.tool_name.setText(self.tool["name"])
        self.tool_name.setReadOnly(bool(self.tool.get("preset")))
        o = self.tool.get("output", {})
        for wd in (self.out_pattern, self.overwrite, self.merge):
            wd.blockSignals(True)
        self.out_folder.edit.setText(o.get("folder", ""))
        self.out_pattern.setText(o.get("pattern", "{name}_out"))
        self.overwrite.setChecked(o.get("overwrite", False))
        self.merge.setChecked(o.get("merge", False))
        for wd in (self.out_pattern, self.overwrite, self.merge):
            wd.blockSignals(False)
        self._fill_seq()

    def _fill_seq(self):
        self.seq.clear()
        for k, step in enumerate(self.tool.get("actions", [])):
            it = QListWidgetItem(f"{k + 1}. {batch.describe(step)}")
            it.setData(Qt.UserRole, k)
            self.seq.addItem(it)
        if not self.tool.get("actions"):
            it = QListWidgetItem("(no actions — files are converted to PDF and saved)")
            it.setFlags(Qt.NoItemFlags)
            self.seq.addItem(it)

    def _editable(self):
        """Presets are read-only: editing one makes a custom copy first."""
        if self.tool and self.tool.get("preset"):
            t = batch.clone(self.tool)
            t["name"] = self.tool["name"] + " (custom)"
            self.tool = t
            it = self._add_tool_item(t)
            self.tool_list.blockSignals(True)
            self.tool_list.setCurrentItem(it)
            self.tool_list.blockSignals(False)
            self.tool_name.setText(t["name"])
            self.tool_name.setReadOnly(False)
            self._save_tool()
        return self.tool

    def _store_output(self, *_):
        if not self.tool:
            return
        o = dict(folder=self.out_folder.value(), pattern=self.out_pattern.text() or "{name}_out",
                 overwrite=self.overwrite.isChecked(), merge=self.merge.isChecked())
        if o != self.tool.get("output") and not self.tool.get("preset"):
            self.tool["output"] = o
            self._save_tool()

    def new_tool(self):
        name, ok = QInputDialog.getText(self, "New tool", "Name")
        if not ok or not name:
            return
        t = dict(name=name, actions=[], output=dict(folder="", pattern="{name}_out", overwrite=False, merge=False))
        it = self._add_tool_item(t)
        self.tool_list.setCurrentItem(it)
        self._save_tool()

    def clone_tool(self):
        if not self.tool:
            return
        t = batch.clone(self.tool)
        t.pop("_file", None)
        t["name"] = self.tool["name"] + " copy"
        it = self._add_tool_item(t)
        self.tool_list.setCurrentItem(it)
        self._save_tool()

    def delete_tool(self):
        if not self.tool or self.tool.get("preset"):
            QMessageBox.information(self, tr("Delete"), "Built-in tools cannot be deleted.")
            return
        if QMessageBox.question(self, tr("Delete"), f"Delete tool “{self.tool['name']}”?") != QMessageBox.Yes:
            return
        if self.tool.get("_file"):
            try:
                os.remove(os.path.join(tools_dir(), self.tool["_file"]))
            except OSError:
                pass
        self.tool_list.takeItem(self.tool_list.currentRow())

    def import_tool(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Import tool", "", "Waraq tool (*.json)")
        if fn:
            t = json.load(open(fn, encoding="utf-8"))
            t.pop("preset", None)
            t.pop("_file", None)
            it = self._add_tool_item(t)
            self.tool_list.setCurrentItem(it)
            self._save_tool()

    def export_tool(self):
        if not self.tool:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Export tool", self.tool["name"] + ".json", "Waraq tool (*.json)")
        if fn:
            data = {k: v for k, v in self.tool.items() if not k.startswith("_") and k != "preset"}
            json.dump(data, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def _rename(self):
        if self.tool and not self.tool.get("preset") and self.tool_name.text():
            self.tool["name"] = self.tool_name.text()
            self._save_tool()

    # ---------------------------------------------------------------- sequence editing
    def add_step(self, item, _col=0):
        aid = item.data(0, Qt.UserRole)
        if not aid:
            return
        t = self._editable()
        step = dict(id=aid, params=batch.default_params(aid))
        if batch.ACTIONS[aid]["params"]:
            v = self._ask_params(aid, step["params"])
            if v is None:
                return
            step["params"] = v
        t.setdefault("actions", []).append(step)
        self._save_tool()
        self._fill_seq()

    def _ask_params(self, aid, current):
        a = batch.ACTIONS[aid]
        fields = []
        for p in a["params"]:
            key, label, typ, default = p[:4]
            extra = p[4] if len(p) > 4 else None
            if typ == "text" and key == "pages":
                label += " (all, odd, 1-3,5)"
            fields.append((key, label, typ, current.get(key, default), extra))
        return ask(self, a["title"], fields)

    def edit_step(self, item):
        if not item or item.data(Qt.UserRole) is None:
            return
        k = item.data(Qt.UserRole)
        t = self._editable()
        step = t["actions"][k]
        if not batch.ACTIONS[step["id"]]["params"]:
            return
        v = self._ask_params(step["id"], step.get("params", {}))
        if v is not None:
            step["params"] = v
            self._save_tool()
            self._fill_seq()

    def move_step(self, d):
        r = self.seq.currentRow()
        t = self._editable()
        acts = t.get("actions", [])
        if 0 <= r < len(acts) and 0 <= r + d < len(acts):
            acts[r], acts[r + d] = acts[r + d], acts[r]
            self._save_tool()
            self._fill_seq()
            self.seq.setCurrentRow(r + d)

    def remove_step(self):
        r = self.seq.currentRow()
        t = self._editable()
        if 0 <= r < len(t.get("actions", [])):
            t["actions"].pop(r)
            self._save_tool()
            self._fill_seq()

    def _seq_moved(self):
        t = self._editable()
        order = [self.seq.item(i).data(Qt.UserRole) for i in range(self.seq.count())]
        if None in order:
            return
        t["actions"] = [t["actions"][k] for k in order]
        self._save_tool()
        self._fill_seq()

    # ---------------------------------------------------------------- run
    def run(self):
        files = self.files.files()
        if not files:
            QMessageBox.information(self, tr("Run"), "Add input files first.")
            return
        if not self.tool:
            return
        tool = batch.clone(self.tool)
        tool["output"] = dict(folder=self.out_folder.value(), pattern=self.out_pattern.text() or "{name}_out",
                              overwrite=self.overwrite.isChecked(), merge=self.merge.isChecked())
        self.table.setRowCount(0)
        self.logbox.clear()
        self.bar.setRange(0, len(files))
        self.bar.setValue(0)
        from PySide6.QtCore import QSettings
        author = QSettings("Waraq", "WaraqPDF").value("author", "")
        self.worker = Worker(tool, files, author)
        self.worker.log.connect(self.logbox.appendPlainText)
        self.worker.prog.connect(lambda i, n: self.bar.setValue(i))
        self.worker.done.connect(self._done)
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.cancel = True

    def _done(self, report):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.report = report
        self.save_report.setEnabled(True)
        self.table.setRowCount(len(report))
        for r, row in enumerate(report):
            self.table.setItem(r, 0, QTableWidgetItem(os.path.basename(row["file"])))
            st = QTableWidgetItem(row["status"])
            st.setForeground(QColor("#15803D" if row["status"] == "OK" else "#B91C1C"))
            self.table.setItem(r, 1, st)
            out = QTableWidgetItem(", ".join(os.path.basename(o) for o in row["outputs"][:3]) +
                                   (f" (+{len(row['outputs']) - 3})" if len(row["outputs"]) > 3 else ""))
            out.setData(Qt.UserRole, row["outputs"])
            self.table.setItem(r, 2, out)
            self.table.setItem(r, 3, QTableWidgetItem(row["message"]))
        ok = sum(1 for r in report if r["status"] == "OK")
        self.logbox.appendPlainText(f"\n{ok}/{len(report)} done.")
        self.bar.setValue(self.bar.maximum())

    def _open_output(self, row, col):
        it = self.table.item(row, 2)
        outs = it.data(Qt.UserRole) if it else None
        if outs:
            target = outs[0] if col == 2 else os.path.dirname(outs[0])
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _save_report(self):
        fn, _ = QFileDialog.getSaveFileName(self, tr("Report"), "report.html", "HTML (*.html)")
        if fn:
            open(fn, "w", encoding="utf-8").write(batch.report_html(self.tool, self.report))
            QDesktopServices.openUrl(QUrl.fromLocalFile(fn))

    # ---------------------------------------------------------------- folder monitor
    def _build_monitor(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(self._title(tr("Folder monitor")))
        expl = QLabel("Watches a folder and runs a tool on every new file that appears in it. "
                      "Processed originals are moved into a “processed” sub-folder.")
        expl.setWordWrap(True)
        expl.setObjectName("muted")
        v.addWidget(expl)
        f = QFormLayout()
        self.mon_folder = _PathEdit("folder", "")
        self.mon_out = _PathEdit("folder", "")
        self.mon_tool = QComboBox()
        self.mon_interval = QSpinBox()
        self.mon_interval.setRange(2, 3600)
        self.mon_interval.setValue(5)
        self.mon_interval.setSuffix(" s")
        f.addRow("Watch folder", self.mon_folder)
        f.addRow(tr("Output folder"), self.mon_out)
        f.addRow("Tool", self.mon_tool)
        f.addRow("Check every", self.mon_interval)
        v.addLayout(f)
        row = QHBoxLayout()
        self.mon_start = QPushButton(tr("Start"))
        self.mon_start.setObjectName("primary")
        self.mon_start.clicked.connect(self.monitor_toggle)
        row.addWidget(self.mon_start)
        row.addStretch()
        v.addLayout(row)
        self.mon_log = QPlainTextEdit()
        self.mon_log.setReadOnly(True)
        v.addWidget(self.mon_log)
        self.mon_timer = QTimer(self, timeout=self._monitor_tick)
        self._mon_sizes = {}
        return w

    def _refresh_monitor_tools(self):
        if not hasattr(self, "mon_tool"):
            return
        cur = self.mon_tool.currentText()
        self.mon_tool.clear()
        for i in range(self.tool_list.count()):
            t = self.tool_list.item(i).data(Qt.UserRole)
            self.mon_tool.addItem(t["name"], t)
        k = self.mon_tool.findText(cur)
        if k >= 0:
            self.mon_tool.setCurrentIndex(k)

    def monitor_toggle(self):
        if self.mon_timer.isActive():
            self.mon_timer.stop()
            self.mon_start.setText(tr("Start"))
            self.mon_log.appendPlainText(f"{time.strftime('%H:%M:%S')}  stopped")
            return
        folder = self.mon_folder.value()
        if not os.path.isdir(folder):
            QMessageBox.warning(self, tr("Folder monitor"), "Choose a folder to watch.")
            return
        self.mon_timer.start(self.mon_interval.value() * 1000)
        self.mon_start.setText(tr("Stop"))
        self.mon_log.appendPlainText(f"{time.strftime('%H:%M:%S')}  watching {folder} with “{self.mon_tool.currentText()}”")

    def _monitor_tick(self):
        folder = self.mon_folder.value()
        try:
            names = [n for n in os.listdir(folder) if os.path.splitext(n)[1].lower() in INPUT_EXT]
        except OSError:
            return
        ready = []
        for n in names:
            p = os.path.join(folder, n)
            try:
                s = os.path.getsize(p)
            except OSError:
                continue
            # only process once the size stops changing (file fully copied)
            if self._mon_sizes.get(p) == s:
                ready.append(p)
            self._mon_sizes[p] = s
        if not ready:
            return
        tool = batch.clone(self.mon_tool.currentData())
        out = self.mon_out.value() or os.path.join(folder, "output")
        tool["output"] = {**tool.get("output", {}), "folder": out}
        self.mon_timer.stop()
        try:
            rep = batch.run_tool(tool, ready, lambda m: None)
            done_dir = os.path.join(folder, "processed")
            os.makedirs(done_dir, exist_ok=True)
            for r in rep:
                if r["file"] in ready:
                    self.mon_log.appendPlainText(f"{time.strftime('%H:%M:%S')}  {'✔' if r['status'] == 'OK' else '✖'} "
                                                 f"{os.path.basename(r['file'])}  {r['message']}")
                    try:
                        shutil.move(r["file"], os.path.join(done_dir, os.path.basename(r["file"])))
                    except OSError:
                        pass
                    self._mon_sizes.pop(r["file"], None)
        finally:
            self.mon_timer.start(self.mon_interval.value() * 1000)
