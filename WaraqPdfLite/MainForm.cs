using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Printing;
using System.Globalization;
using System.IO;
using System.Windows.Forms;
using PdfiumViewer;
using PdfiumDoc = PdfiumViewer.PdfDocument;

namespace WaraqPdfLite
{
    /// <summary>
    /// Main window. All UI is built in code (no designer file needed).
    /// The open PDF is copied to a private working file; every edit is applied to that file with PDFsharp,
    /// then the viewer (PDFium) reloads it. Save / Save As copy the working file to the chosen location.
    /// </summary>
    public sealed class MainForm : Form
    {
        private const string AppName = "Waraq PDF Lite";
        private const int PageMargin = 16;
        private const int MaxUndo = 20;

        // ---- document state
        private string originalPath;          // file on disk (null for a new, unsaved document)
        private string workPath;              // private working copy
        private PdfiumDoc pdf;                // renderer
        private MemoryStream pdfStream;       // keeps the renderer's data alive
        private List<PageGeometry> geometry = new List<PageGeometry>();
        private int currentPage;
        private double zoom = 1.0;
        private bool fitWidth = true;
        private bool dirty;
        private bool commentMode;
        private readonly List<byte[]> undoStack = new List<byte[]>();
        private string commentAuthor = Environment.UserName;

        // ---- controls
        private MenuStrip menu;
        private TabControl ribbon;
        private SplitContainer split;
        private ListView thumbList;
        private ImageList thumbImages;
        private FocusPanel viewerPanel;
        private PictureBox pageBox;
        private StatusStrip status;
        private ToolStripStatusLabel statusMessage;
        private ToolStripStatusLabel statusFile;
        private ToolStripStatusLabel statusPage;
        private ToolStripStatusLabel statusZoom;
        private ToolStripDropDownButton statusLog;
        private ToolStripTextBox pageBoxText;
        private ToolStripLabel pageCountLabel;
        private ToolStripComboBox zoomCombo;
        private ToolStripButton commentButton;
        private readonly List<ToolStripItem> docOnlyItems = new List<ToolStripItem>();
        private readonly List<ToolStripMenuItem> docOnlyMenus = new List<ToolStripMenuItem>();
        private Timer thumbTimer;
        private int nextThumb;

        public MainForm(string startFile)
        {
            Text = AppName;
            Icon = IconFactory.AppIcon();
            Font = new Font("Segoe UI", 9f);
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1280, 860);
            MinimumSize = new Size(800, 560);
            KeyPreview = true;
            AllowDrop = true;

            BuildMenu();
            BuildRibbon();
            BuildBody();
            BuildStatusBar();

            Controls.Add(split);
            Controls.Add(ribbon);
            Controls.Add(menu);
            Controls.Add(status);
            MainMenuStrip = menu;

            thumbTimer = new Timer { Interval = 15 };
            thumbTimer.Tick += ThumbTimerTick;

            DragEnter += OnDragEnter;
            DragDrop += OnDragDrop;
            FormClosing += OnFormClosing;
            ErrorLog.Changed += delegate { UpdateLogButton(); };

            UpdateUi();
            if (!string.IsNullOrEmpty(startFile) && File.Exists(startFile))
                Shown += delegate { OpenFile(startFile); };
        }

        // =================================================================== UI construction
        private ToolStripMenuItem MenuItem(string text, string icon, Keys keys, EventHandler click, bool needsDoc)
        {
            ToolStripMenuItem item = new ToolStripMenuItem(text);
            if (icon != null) item.Image = IconFactory.Get(icon, 16);
            if (keys != Keys.None) item.ShortcutKeys = keys;
            item.Click += click;
            if (needsDoc) docOnlyMenus.Add(item);
            return item;
        }

        private void BuildMenu()
        {
            menu = new MenuStrip { Dock = DockStyle.Top };
            ToolStripMenuItem file = new ToolStripMenuItem("&File");
            file.DropDownItems.Add(MenuItem("&Open...", "open", Keys.Control | Keys.O, delegate { CmdOpen(); }, false));
            file.DropDownItems.Add(MenuItem("&Save", "save", Keys.Control | Keys.S, delegate { CmdSave(); }, true));
            file.DropDownItems.Add(MenuItem("Save &As...", "saveas", Keys.Control | Keys.Shift | Keys.S, delegate { CmdSaveAs(); }, true));
            file.DropDownItems.Add(new ToolStripSeparator());
            file.DropDownItems.Add(MenuItem("&Print...", "print", Keys.Control | Keys.P, delegate { CmdPrint(); }, true));
            file.DropDownItems.Add(new ToolStripSeparator());
            file.DropDownItems.Add(MenuItem("&Close Document", "close", Keys.Control | Keys.W, delegate { CmdClose(); }, true));
            file.DropDownItems.Add(MenuItem("E&xit", null, Keys.Alt | Keys.F4, delegate { Close(); }, false));

            ToolStripMenuItem edit = new ToolStripMenuItem("&Edit");
            edit.DropDownItems.Add(MenuItem("&Undo", "undo", Keys.Control | Keys.Z, delegate { CmdUndo(); }, true));

            ToolStripMenuItem help = new ToolStripMenuItem("&Help");
            help.DropDownItems.Add(MenuItem("Error &Log...", "log", Keys.None, delegate { ShowLog(); }, false));
            help.DropDownItems.Add(MenuItem("&About", null, Keys.None, delegate
            {
                MessageBox.Show(this, AppName + "\r\nPDF viewer and editor.\r\nRendering: PDFium (PdfiumViewer)\r\nEditing: PDFsharp",
                                "About", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }, false));

            menu.Items.AddRange(new ToolStripItem[] { file, edit, help });
        }

        private ToolStripButton BigButton(string text, string icon, EventHandler click, bool needsDoc)
        {
            ToolStripButton b = new ToolStripButton(text)
            {
                Image = IconFactory.Get(icon, 32),
                ImageScaling = ToolStripItemImageScaling.None,
                TextImageRelation = TextImageRelation.ImageAboveText,
                DisplayStyle = ToolStripItemDisplayStyle.ImageAndText,
                AutoSize = false,
                Width = 72,
                Height = 62,
                Padding = new Padding(2)
            };
            b.Click += click;
            if (needsDoc) docOnlyItems.Add(b);
            return b;
        }

        private ToolStripLabel GroupLabel(string text)
        {
            return new ToolStripLabel(text) { ForeColor = Color.DimGray, Font = new Font("Segoe UI", 8f), Margin = new Padding(4, 0, 2, 0) };
        }

        private ToolStrip NewStrip()
        {
            ToolStrip strip = new ToolStrip
            {
                Dock = DockStyle.Fill,
                GripStyle = ToolStripGripStyle.Hidden,
                ImageScalingSize = new Size(32, 32),
                BackColor = Color.FromArgb(245, 246, 248),
                RenderMode = ToolStripRenderMode.Professional,
                Padding = new Padding(4, 2, 4, 2),
                CanOverflow = true
            };
            return strip;
        }

        private void BuildRibbon()
        {
            ribbon = new TabControl { Dock = DockStyle.Top, Height = 104, Padding = new Point(14, 4) };

            // ---------------- Home
            ToolStrip home = NewStrip();
            home.Items.Add(BigButton("Open", "open", delegate { CmdOpen(); }, false));
            home.Items.Add(BigButton("Save", "save", delegate { CmdSave(); }, true));
            home.Items.Add(BigButton("Save As", "saveas", delegate { CmdSaveAs(); }, true));
            home.Items.Add(BigButton("Print", "print", delegate { CmdPrint(); }, true));
            home.Items.Add(new ToolStripSeparator());

            home.Items.Add(BigButton("Zoom Out", "zoomout", delegate { CmdZoom(1 / 1.2); }, true));
            zoomCombo = new ToolStripComboBox { AutoSize = false, Width = 90 };
            zoomCombo.Items.AddRange(new object[] { "25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%", "Fit Width" });
            zoomCombo.KeyDown += delegate (object s, KeyEventArgs e) { if (e.KeyCode == Keys.Enter) { ApplyZoomText(); e.SuppressKeyPress = true; } };
            zoomCombo.SelectedIndexChanged += delegate { ApplyZoomText(); };
            docOnlyItems.Add(zoomCombo);
            home.Items.Add(zoomCombo);
            home.Items.Add(BigButton("Zoom In", "zoomin", delegate { CmdZoom(1.2); }, true));
            home.Items.Add(BigButton("Fit Width", "fitwidth", delegate { CmdFitWidth(); }, true));
            home.Items.Add(new ToolStripSeparator());

            home.Items.Add(BigButton("First", "first", delegate { GoToPage(0); }, true));
            home.Items.Add(BigButton("Previous", "prev", delegate { GoToPage(currentPage - 1); }, true));
            home.Items.Add(GroupLabel("Page"));
            pageBoxText = new ToolStripTextBox { AutoSize = false, Width = 44, TextBoxTextAlign = HorizontalAlignment.Center };
            pageBoxText.KeyDown += delegate (object s, KeyEventArgs e)
            {
                if (e.KeyCode != Keys.Enter) return;
                int n;
                if (int.TryParse(pageBoxText.Text, NumberStyles.Integer, CultureInfo.InvariantCulture, out n)) GoToPage(n - 1);
                e.SuppressKeyPress = true;
            };
            docOnlyItems.Add(pageBoxText);
            home.Items.Add(pageBoxText);
            pageCountLabel = GroupLabel("of 0");
            home.Items.Add(pageCountLabel);
            home.Items.Add(BigButton("Next", "next", delegate { GoToPage(currentPage + 1); }, true));
            home.Items.Add(BigButton("Last", "last", delegate { GoToPage(PageCount - 1); }, true));
            home.Items.Add(new ToolStripSeparator());

            home.Items.Add(BigButton("Rotate Page", "rotate", delegate { CmdRotate(false); }, true));
            home.Items.Add(BigButton("Undo", "undo", delegate { CmdUndo(); }, true));

            // ---------------- Organize
            ToolStrip organize = NewStrip();
            organize.Items.Add(BigButton("Merge PDFs", "merge", delegate { CmdMerge(); }, false));
            organize.Items.Add(BigButton("Split PDF", "split", delegate { CmdSplit(); }, true));
            organize.Items.Add(new ToolStripSeparator());
            organize.Items.Add(BigButton("Rotate Page", "rotate", delegate { CmdRotate(false); }, true));
            organize.Items.Add(BigButton("Rotate All", "rotateall", delegate { CmdRotate(true); }, true));

            // ---------------- Comment
            ToolStrip comment = NewStrip();
            commentButton = BigButton("Text Comment", "comment", delegate { ToggleCommentMode(); }, true);
            commentButton.CheckOnClick = false;
            comment.Items.Add(commentButton);
            comment.Items.Add(GroupLabel("Click the button, then click on the page where the comment should appear."));

            AddRibbonTab("Home", home);
            AddRibbonTab("Organize", organize);
            AddRibbonTab("Comment", comment);
        }

        private void AddRibbonTab(string title, ToolStrip strip)
        {
            TabPage page = new TabPage(title) { BackColor = strip.BackColor, Padding = new Padding(0) };
            page.Controls.Add(strip);
            ribbon.TabPages.Add(page);
        }

        private void BuildBody()
        {
            split = new SplitContainer
            {
                Dock = DockStyle.Fill,
                FixedPanel = FixedPanel.Panel1,
                SplitterWidth = 4,
                BackColor = Color.FromArgb(210, 214, 220)
            };

            thumbImages = new ImageList { ImageSize = new Size(96, 128), ColorDepth = ColorDepth.Depth24Bit };
            thumbList = new ListView
            {
                Dock = DockStyle.Fill,
                View = View.LargeIcon,
                LargeImageList = thumbImages,
                MultiSelect = false,
                HideSelection = false,
                BorderStyle = BorderStyle.None,
                BackColor = Color.FromArgb(248, 250, 252)
            };
            thumbList.SelectedIndexChanged += delegate
            {
                if (thumbList.SelectedIndices.Count == 1 && thumbList.SelectedIndices[0] != currentPage)
                    GoToPage(thumbList.SelectedIndices[0]);
            };
            Label thumbHeader = new Label
            {
                Text = "  Pages",
                Dock = DockStyle.Top,
                Height = 24,
                TextAlign = ContentAlignment.MiddleLeft,
                Font = new Font("Segoe UI", 9f, FontStyle.Bold),
                BackColor = Color.FromArgb(230, 232, 236)
            };
            split.Panel1.Controls.Add(thumbList);
            split.Panel1.Controls.Add(thumbHeader);

            viewerPanel = new FocusPanel
            {
                Dock = DockStyle.Fill,
                AutoScroll = true,
                BackColor = Color.FromArgb(155, 155, 155)
            };
            pageBox = new PictureBox
            {
                SizeMode = PictureBoxSizeMode.AutoSize,
                BackColor = Color.White,
                Location = new Point(PageMargin, PageMargin)
            };
            pageBox.MouseClick += OnPageClick;
            pageBox.MouseDown += delegate { viewerPanel.Focus(); };
            viewerPanel.Controls.Add(pageBox);
            viewerPanel.Resize += delegate
            {
                if (fitWidth && pdf != null) RenderCurrentPage(false);
                else CenterPage();
            };
            viewerPanel.MouseWheel += OnViewerWheel;
            viewerPanel.Click += delegate { viewerPanel.Focus(); };
            viewerPanel.AllowDrop = true;
            viewerPanel.DragEnter += OnDragEnter;
            viewerPanel.DragDrop += OnDragDrop;
            split.Panel2.Controls.Add(viewerPanel);
            HandleCreated += delegate
            {
                split.SplitterDistance = 150;
                split.Panel1MinSize = 100;
            };
        }

        private void BuildStatusBar()
        {
            status = new StatusStrip { Dock = DockStyle.Bottom, SizingGrip = true };
            statusMessage = new ToolStripStatusLabel("Ready") { Spring = true, TextAlign = ContentAlignment.MiddleLeft };
            statusFile = new ToolStripStatusLabel("No file") { BorderSides = ToolStripStatusLabelBorderSides.Left, TextAlign = ContentAlignment.MiddleLeft };
            statusPage = new ToolStripStatusLabel("Page 0 of 0") { BorderSides = ToolStripStatusLabelBorderSides.Left };
            statusZoom = new ToolStripStatusLabel("100%") { BorderSides = ToolStripStatusLabelBorderSides.Left };
            statusLog = new ToolStripDropDownButton("Errors: 0") { Image = IconFactory.Get("log", 16), ShowDropDownArrow = false };
            statusLog.Click += delegate { ShowLog(); };
            status.Items.AddRange(new ToolStripItem[] { statusMessage, statusFile, statusPage, statusZoom, statusLog });
        }

        // =================================================================== helpers
        private int PageCount { get { return pdf == null ? 0 : pdf.PageCount; } }

        private void SetStatus(string text)
        {
            statusMessage.ForeColor = SystemColors.ControlText;
            statusMessage.Text = text;
        }

        private void ReportError(string action, Exception ex)
        {
            ErrorLog.Write(action, ex);
            statusMessage.ForeColor = Color.Firebrick;
            statusMessage.Text = action + " failed: " + ex.Message;
            MessageBox.Show(this, action + " failed:\r\n\r\n" + ex.Message, AppName, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }

        private void RunSafe(string action, Action body)
        {
            Cursor previous = Cursor.Current;
            try
            {
                Cursor.Current = Cursors.WaitCursor;
                body();
            }
            catch (Exception ex)
            {
                ReportError(action, ex);
                // If the failure happened after the viewer released the document, show the (unchanged) file again.
                if (pdf == null && workPath != null && File.Exists(workPath))
                {
                    try { ReloadWorkingFile(true); }
                    catch (Exception reloadError) { ErrorLog.Write("Reloading document", reloadError); }
                }
            }
            finally
            {
                Cursor.Current = previous;
            }
        }

        private void UpdateLogButton()
        {
            statusLog.Text = "Errors: " + ErrorLog.Entries.Count;
            statusLog.ForeColor = ErrorLog.Entries.Count > 0 ? Color.Firebrick : SystemColors.ControlText;
        }

        private void ShowLog()
        {
            using (LogDialog d = new LogDialog()) d.ShowDialog(this);
            UpdateLogButton();
        }

        private void UpdateUi()
        {
            bool has = pdf != null;
            foreach (ToolStripItem item in docOnlyItems) item.Enabled = has;
            foreach (ToolStripMenuItem item in docOnlyMenus) item.Enabled = has;
            string name = originalPath != null ? Path.GetFileName(originalPath) : (has ? "Untitled.pdf" : null);
            Text = name == null ? AppName : name + (dirty ? " *" : "") + " - " + AppName;
            statusFile.Text = originalPath ?? (has ? "(not saved yet)" : "No file");
            statusPage.Text = has ? "Page " + (currentPage + 1) + " of " + PageCount : "Page 0 of 0";
            statusZoom.Text = Math.Round(zoom * 100) + "%";
            pageBoxText.Text = has ? (currentPage + 1).ToString(CultureInfo.InvariantCulture) : "";
            pageCountLabel.Text = "of " + PageCount;
            zoomCombo.Text = fitWidth ? "Fit Width" : Math.Round(zoom * 100) + "%";
            commentButton.Checked = commentMode;
            pageBox.Cursor = commentMode ? Cursors.Cross : Cursors.Default;
            UpdateLogButton();
        }

        private string NewWorkPath()
        {
            string dir = Path.Combine(Path.GetTempPath(), "WaraqPdfLite");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, Guid.NewGuid().ToString("N") + ".pdf");
        }

        private void DisposeRenderer()
        {
            thumbTimer.Stop();
            if (pageBox.Image != null)
            {
                Image old = pageBox.Image;
                pageBox.Image = null;
                old.Dispose();
            }
            if (pdf != null) { pdf.Dispose(); pdf = null; }
            if (pdfStream != null) { pdfStream.Dispose(); pdfStream = null; }
        }

        private void DeleteWorkFile()
        {
            if (workPath == null) return;
            try { if (File.Exists(workPath)) File.Delete(workPath); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            workPath = null;
        }

        /// <summary>(Re)loads the renderer from the working file.</summary>
        private void ReloadWorkingFile(bool rebuildThumbs)
        {
            DisposeRenderer();
            byte[] data = File.ReadAllBytes(workPath);
            pdfStream = new MemoryStream(data);
            pdf = PdfiumDoc.Load(pdfStream);
            try
            {
                geometry = PdfOps.ReadGeometry(workPath);
            }
            catch (Exception ex)
            {
                // Viewing still works; editing commands will report their own errors.
                ErrorLog.Write("Reading page geometry", ex);
                geometry = new List<PageGeometry>();
                for (int i = 0; i < pdf.PageCount; i++)
                    geometry.Add(new PageGeometry { Width = pdf.PageSizes[i].Width, Height = pdf.PageSizes[i].Height, Rotation = 0 });
            }
            if (currentPage >= pdf.PageCount) currentPage = pdf.PageCount - 1;
            if (currentPage < 0) currentPage = 0;
            RenderCurrentPage(false);
            if (rebuildThumbs) StartThumbnails();
            else RefreshThumbnail(currentPage);
            UpdateUi();
        }

        private void PushUndo()
        {
            undoStack.Add(File.ReadAllBytes(workPath));
            if (undoStack.Count > MaxUndo) undoStack.RemoveAt(0);
        }

        private void MarkChanged(string message, bool rebuildThumbs)
        {
            dirty = true;
            ReloadWorkingFile(rebuildThumbs);
            SetStatus(message);
        }

        // =================================================================== rendering
        private void RenderCurrentPage(bool scrollToTop)
        {
            if (pdf == null || PageCount == 0) return;
            SizeF size = pdf.PageSizes[currentPage];   // displayed size in points (rotation applied by PDFium)
            if (fitWidth)
            {
                int available = viewerPanel.ClientSize.Width - PageMargin * 2 - SystemInformation.VerticalScrollBarWidth;
                zoom = Math.Max(0.1, Math.Min(8.0, available / (size.Width * 96.0 / 72.0)));
            }
            double scale = zoom * 96.0 / 72.0;
            int width = Math.Max(1, (int)(size.Width * scale));
            int height = Math.Max(1, (int)(size.Height * scale));
            float dpi = (float)(96.0 * zoom);
            Image img = pdf.Render(currentPage, width, height, dpi, dpi, PdfRenderFlags.Annotations);

            Image old = pageBox.Image;
            pageBox.Image = img;
            if (old != null) old.Dispose();
            if (scrollToTop) viewerPanel.AutoScrollPosition = new Point(0, 0);
            CenterPage();
            UpdateUi();
        }

        private void CenterPage()
        {
            if (pageBox.Image == null) return;
            Point scroll = viewerPanel.AutoScrollPosition;
            int x = Math.Max(PageMargin, (viewerPanel.ClientSize.Width - pageBox.Width) / 2);
            pageBox.Location = new Point(x + scroll.X, PageMargin + scroll.Y);
            viewerPanel.AutoScrollMinSize = new Size(pageBox.Width + PageMargin * 2, pageBox.Height + PageMargin * 2);
        }

        private void GoToPage(int index)
        {
            if (pdf == null) return;
            if (index < 0) index = 0;
            if (index > PageCount - 1) index = PageCount - 1;
            if (index == currentPage && pageBox.Image != null) { UpdateUi(); return; }
            currentPage = index;
            RenderCurrentPage(true);
            if (index < thumbList.Items.Count)
            {
                thumbList.SelectedIndices.Clear();
                thumbList.Items[index].Selected = true;
                thumbList.EnsureVisible(index);
            }
        }

        // =================================================================== thumbnails
        private void StartThumbnails()
        {
            thumbTimer.Stop();
            thumbList.BeginUpdate();
            thumbList.Items.Clear();
            thumbImages.Images.Clear();
            using (Bitmap blank = new Bitmap(96, 128))
            {
                using (Graphics g = Graphics.FromImage(blank)) g.Clear(Color.White);
                for (int i = 0; i < PageCount; i++)
                {
                    thumbImages.Images.Add((Image)blank.Clone());
                    thumbList.Items.Add(new ListViewItem((i + 1).ToString(CultureInfo.InvariantCulture), i));
                }
            }
            thumbList.EndUpdate();
            if (currentPage < thumbList.Items.Count) thumbList.Items[currentPage].Selected = true;
            nextThumb = 0;
            thumbTimer.Start();
        }

        private void ThumbTimerTick(object sender, EventArgs e)
        {
            if (pdf == null) { thumbTimer.Stop(); return; }
            for (int k = 0; k < 4 && nextThumb < PageCount; k++, nextThumb++)
                RefreshThumbnail(nextThumb);
            if (nextThumb >= PageCount) thumbTimer.Stop();
        }

        private void RefreshThumbnail(int index)
        {
            if (pdf == null || index < 0 || index >= PageCount || index >= thumbImages.Images.Count) return;
            try
            {
                SizeF size = pdf.PageSizes[index];
                double s = Math.Min(92.0 / size.Width, 124.0 / size.Height);
                int w = Math.Max(1, (int)(size.Width * s));
                int h = Math.Max(1, (int)(size.Height * s));
                using (Image page = pdf.Render(index, w, h, 72, 72, PdfRenderFlags.Annotations))
                {
                    Bitmap canvas = new Bitmap(96, 128);
                    using (Graphics g = Graphics.FromImage(canvas))
                    {
                        g.Clear(Color.FromArgb(248, 250, 252));
                        int x = (96 - w) / 2;
                        int y = (128 - h) / 2;
                        g.DrawImage(page, x, y, w, h);
                        g.DrawRectangle(Pens.Silver, x, y, w - 1, h - 1);
                    }
                    thumbImages.Images[index] = canvas;
                }
                thumbList.Invalidate();
            }
            catch (Exception ex)
            {
                ErrorLog.Write("Rendering thumbnail " + (index + 1), ex);
            }
        }

        // =================================================================== commands: file
        private bool ConfirmDiscard()
        {
            if (pdf == null || !dirty) return true;
            DialogResult r = MessageBox.Show(this, "Save changes to " + (originalPath != null ? Path.GetFileName(originalPath) : "the document") + "?",
                                             AppName, MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question);
            if (r == DialogResult.Cancel) return false;
            if (r == DialogResult.Yes) return CmdSave();
            return true;
        }

        private void CmdOpen()
        {
            if (!ConfirmDiscard()) return;
            using (OpenFileDialog dlg = new OpenFileDialog())
            {
                dlg.Filter = "PDF files (*.pdf)|*.pdf|All files (*.*)|*.*";
                dlg.Title = "Open PDF";
                if (dlg.ShowDialog(this) != DialogResult.OK) return;
                OpenFile(dlg.FileName);
            }
        }

        private void OpenFile(string path)
        {
            RunSafe("Opening " + Path.GetFileName(path), delegate
            {
                string password = null;
                if (PdfOps.NeedsPassword(path))
                {
                    password = InputDialog.Ask(this, "Password required", Path.GetFileName(path) + " is protected. Enter its password:", "", true);
                    if (password == null) return;
                }
                string newWork = NewWorkPath();
                PdfOps.CreateWorkingCopy(path, newWork, password);

                DisposeRenderer();
                DeleteWorkFile();
                workPath = newWork;
                originalPath = Path.GetFullPath(path);
                currentPage = 0;
                fitWidth = true;
                dirty = false;
                commentMode = false;
                undoStack.Clear();
                ReloadWorkingFile(true);
                SetStatus("Opened " + originalPath + " (" + PageCount + " pages)" +
                          (password != null ? " — saved copies will not be password protected" : ""));
            });
        }

        private bool CmdSave()
        {
            if (pdf == null) return false;
            if (originalPath == null) return CmdSaveAs();
            bool ok = false;
            RunSafe("Saving", delegate
            {
                File.Copy(workPath, originalPath, true);
                dirty = false;
                ok = true;
                SetStatus("Saved " + originalPath);
                UpdateUi();
            });
            return ok;
        }

        private bool CmdSaveAs()
        {
            if (pdf == null) return false;
            using (SaveFileDialog dlg = new SaveFileDialog())
            {
                dlg.Filter = "PDF files (*.pdf)|*.pdf";
                dlg.Title = "Save PDF As";
                dlg.FileName = originalPath != null ? Path.GetFileName(originalPath) : "Untitled.pdf";
                if (originalPath != null) dlg.InitialDirectory = Path.GetDirectoryName(originalPath);
                if (dlg.ShowDialog(this) != DialogResult.OK) return false;
                bool ok = false;
                RunSafe("Saving", delegate
                {
                    File.Copy(workPath, dlg.FileName, true);
                    originalPath = Path.GetFullPath(dlg.FileName);
                    dirty = false;
                    ok = true;
                    SetStatus("Saved " + originalPath);
                    UpdateUi();
                });
                return ok;
            }
        }

        private void CmdPrint()
        {
            if (pdf == null) return;
            RunSafe("Printing", delegate
            {
                using (PrintDocument doc = pdf.CreatePrintDocument())
                using (PrintDialog dlg = new PrintDialog())
                {
                    doc.DocumentName = originalPath != null ? Path.GetFileName(originalPath) : "Untitled.pdf";
                    dlg.Document = doc;
                    dlg.AllowSomePages = true;
                    dlg.PrinterSettings.FromPage = 1;
                    dlg.PrinterSettings.ToPage = PageCount;
                    dlg.PrinterSettings.MinimumPage = 1;
                    dlg.PrinterSettings.MaximumPage = PageCount;
                    dlg.UseEXDialog = true;
                    if (dlg.ShowDialog(this) == DialogResult.OK)
                    {
                        doc.Print();
                        SetStatus("Sent to printer");
                    }
                }
            });
        }

        private void CmdClose()
        {
            if (!ConfirmDiscard()) return;
            DisposeRenderer();
            DeleteWorkFile();
            originalPath = null;
            geometry.Clear();
            undoStack.Clear();
            dirty = false;
            commentMode = false;
            thumbList.Items.Clear();
            thumbImages.Images.Clear();
            viewerPanel.AutoScrollMinSize = Size.Empty;
            SetStatus("Ready");
            UpdateUi();
        }

        private void CmdUndo()
        {
            if (pdf == null) return;
            if (undoStack.Count == 0) { SetStatus("Nothing to undo"); return; }
            RunSafe("Undo", delegate
            {
                byte[] previous = undoStack[undoStack.Count - 1];
                undoStack.RemoveAt(undoStack.Count - 1);
                DisposeRenderer();
                File.WriteAllBytes(workPath, previous);
                MarkChanged("Undone", true);
            });
        }

        // =================================================================== commands: view
        private void CmdZoom(double factor)
        {
            if (pdf == null) return;
            fitWidth = false;
            zoom = Math.Max(0.1, Math.Min(8.0, zoom * factor));
            RenderCurrentPage(false);
        }

        private void CmdFitWidth()
        {
            if (pdf == null) return;
            fitWidth = true;
            RenderCurrentPage(false);
        }

        private void ApplyZoomText()
        {
            if (pdf == null) return;
            string t = zoomCombo.Text.Trim();
            if (t.StartsWith("Fit", StringComparison.OrdinalIgnoreCase)) { CmdFitWidth(); return; }
            double percent;
            if (double.TryParse(t.TrimEnd('%').Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out percent) && percent >= 10 && percent <= 800)
            {
                fitWidth = false;
                zoom = percent / 100.0;
                RenderCurrentPage(false);
            }
        }

        private void OnViewerWheel(object sender, MouseEventArgs e)
        {
            if (pdf == null) return;
            if ((ModifierKeys & Keys.Control) == Keys.Control)
            {
                CmdZoom(e.Delta > 0 ? 1.15 : 1 / 1.15);
                return;
            }
            VScrollProperties v = viewerPanel.VerticalScroll;
            bool atBottom = !v.Visible || v.Value >= v.Maximum - v.LargeChange;
            bool atTop = !v.Visible || v.Value <= v.Minimum;
            if (e.Delta < 0 && atBottom && currentPage < PageCount - 1)
                GoToPage(currentPage + 1);
            else if (e.Delta > 0 && atTop && currentPage > 0)
            {
                GoToPage(currentPage - 1);
                viewerPanel.AutoScrollPosition = new Point(0, viewerPanel.VerticalScroll.Maximum);
                CenterPage();
            }
        }

        protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
        {
            if (pdf != null && !(ActiveControl is TextBoxBase) && !pageBoxText.Focused && !zoomCombo.Focused)
            {
                switch (keyData)
                {
                    case Keys.PageDown: GoToPage(currentPage + 1); return true;
                    case Keys.PageUp: GoToPage(currentPage - 1); return true;
                    case Keys.Control | Keys.Home: GoToPage(0); return true;
                    case Keys.Control | Keys.End: GoToPage(PageCount - 1); return true;
                    case Keys.Control | Keys.Oemplus:
                    case Keys.Control | Keys.Add: CmdZoom(1.2); return true;
                    case Keys.Control | Keys.OemMinus:
                    case Keys.Control | Keys.Subtract: CmdZoom(1 / 1.2); return true;
                    case Keys.Control | Keys.D0: CmdFitWidth(); return true;
                    case Keys.Control | Keys.R: CmdRotate(false); return true;
                    case Keys.Escape:
                        if (commentMode) { ToggleCommentMode(); return true; }
                        break;
                }
            }
            return base.ProcessCmdKey(ref msg, keyData);
        }

        // =================================================================== commands: organize
        private void CmdRotate(bool allPages)
        {
            if (pdf == null) return;
            RunSafe("Rotating", delegate
            {
                PushUndo();
                List<int> pages = new List<int>();
                if (allPages) for (int i = 0; i < PageCount; i++) pages.Add(i);
                else pages.Add(currentPage);
                DisposeRenderer();
                PdfOps.RotatePages(workPath, pages, 90);
                MarkChanged(allPages ? "All pages rotated 90° clockwise" : "Page " + (currentPage + 1) + " rotated 90° clockwise", allPages);
            });
        }

        private void CmdMerge()
        {
            using (OpenFileDialog dlg = new OpenFileDialog())
            {
                dlg.Filter = "PDF files (*.pdf)|*.pdf";
                dlg.Multiselect = true;
                if (pdf != null)
                {
                    dlg.Title = "Choose PDF file(s) to append to the current document";
                    if (dlg.ShowDialog(this) != DialogResult.OK) return;
                    RunSafe("Merging", delegate
                    {
                        PushUndo();
                        List<string> inputs = new List<string> { workPath };
                        inputs.AddRange(dlg.FileNames);
                        int before = PageCount;
                        DisposeRenderer();
                        int total = PdfOps.MergeFiles(inputs, workPath);
                        MarkChanged("Merged " + dlg.FileNames.Length + " file(s): " + (total - before) + " page(s) added", true);
                    });
                }
                else
                {
                    dlg.Title = "Choose two or more PDF files to merge (in the order to combine)";
                    if (dlg.ShowDialog(this) != DialogResult.OK) return;
                    if (dlg.FileNames.Length < 2)
                    {
                        MessageBox.Show(this, "Select at least two PDF files (hold Ctrl to select several).", AppName,
                                        MessageBoxButtons.OK, MessageBoxIcon.Information);
                        return;
                    }
                    RunSafe("Merging", delegate
                    {
                        string newWork = NewWorkPath();
                        List<string> files = new List<string>(dlg.FileNames);
                        files.Sort(StringComparer.OrdinalIgnoreCase);
                        int total = PdfOps.MergeFiles(files, newWork);
                        DisposeRenderer();
                        DeleteWorkFile();
                        workPath = newWork;
                        originalPath = null;
                        currentPage = 0;
                        fitWidth = true;
                        undoStack.Clear();
                        dirty = true;
                        ReloadWorkingFile(true);
                        SetStatus("Merged " + files.Count + " files into a new document (" + total + " pages). Use Save As to store it.");
                    });
                }
            }
        }

        private void CmdSplit()
        {
            if (pdf == null) return;
            string folder = originalPath != null ? Path.GetDirectoryName(originalPath) : Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            string baseName = originalPath != null ? Path.GetFileNameWithoutExtension(originalPath) : "Untitled";
            using (SplitDialog dlg = new SplitDialog(PageCount, folder, baseName))
            {
                if (dlg.ShowDialog(this) != DialogResult.OK) return;
                RunSafe("Splitting", delegate
                {
                    List<List<int>> groups = dlg.UseRanges
                        ? PdfOps.GroupsFromRanges(dlg.Ranges, PageCount)
                        : PdfOps.GroupsEveryN(PageCount, dlg.PagesPerFile);
                    if (groups.Count == 0) throw new InvalidOperationException("No valid page ranges were given.");
                    List<string> files = PdfOps.Split(workPath, dlg.OutputFolder, dlg.BaseName.Trim(), groups);
                    SetStatus("Split into " + files.Count + " file(s) in " + dlg.OutputFolder);
                    if (MessageBox.Show(this, files.Count + " file(s) created in:\r\n" + dlg.OutputFolder + "\r\n\r\nOpen the folder?",
                                        AppName, MessageBoxButtons.YesNo, MessageBoxIcon.Information) == DialogResult.Yes)
                        System.Diagnostics.Process.Start("explorer.exe", "\"" + dlg.OutputFolder + "\"");
                });
            }
        }

        // =================================================================== commands: comment
        private void ToggleCommentMode()
        {
            if (pdf == null) return;
            commentMode = !commentMode;
            SetStatus(commentMode ? "Click on the page where the text comment should be placed (Esc to cancel)" : "Ready");
            UpdateUi();
        }

        private void OnPageClick(object sender, MouseEventArgs e)
        {
            viewerPanel.Focus();
            if (!commentMode || e.Button != MouseButtons.Left || pdf == null) return;
            double scale = zoom * 96.0 / 72.0;
            double x = e.X / scale;
            double y = e.Y / scale;
            using (TextCommentDialog dlg = new TextCommentDialog(commentAuthor))
            {
                if (dlg.ShowDialog(this) != DialogResult.OK || dlg.CommentText.Trim().Length == 0) return;
                commentAuthor = dlg.Author;
                RunSafe("Adding text comment", delegate
                {
                    PushUndo();
                    DisposeRenderer();
                    PdfOps.AddTextComment(workPath, currentPage, x, y, dlg.CommentText, dlg.FontSizePt,
                                          dlg.TextColor, dlg.FillColor, dlg.Author);
                    commentMode = false;
                    MarkChanged("Text comment added on page " + (currentPage + 1), false);
                });
            }
        }

        // =================================================================== drag & drop, closing
        private void OnDragEnter(object sender, DragEventArgs e)
        {
            if (e.Data.GetDataPresent(DataFormats.FileDrop)) e.Effect = DragDropEffects.Copy;
        }

        private void OnDragDrop(object sender, DragEventArgs e)
        {
            string[] files = e.Data.GetData(DataFormats.FileDrop) as string[];
            if (files == null || files.Length == 0) return;
            if (!ConfirmDiscard()) return;
            OpenFile(files[0]);
        }

        private void OnFormClosing(object sender, FormClosingEventArgs e)
        {
            if (!ConfirmDiscard())
            {
                e.Cancel = true;
                return;
            }
            DisposeRenderer();
            DeleteWorkFile();
        }
    }

    /// <summary>A scrollable panel that can take keyboard focus (so the mouse wheel reaches it).</summary>
    public sealed class FocusPanel : Panel
    {
        public FocusPanel()
        {
            SetStyle(ControlStyles.Selectable, true);
            TabStop = true;
            DoubleBuffered = true;
        }

        protected override void OnMouseEnter(EventArgs e)
        {
            base.OnMouseEnter(e);
            if (!Focused && FindForm() != null && FindForm().ContainsFocus && !(FindForm().ActiveControl is TextBoxBase)) Focus();
        }

        protected override Point ScrollToControl(Control activeControl)
        {
            // Keep the current scroll position when the page picture gets focus.
            return DisplayRectangle.Location;
        }
    }
}
