using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace WaraqPdfLite
{
    /// <summary>Small single-line input box (password, page number...).</summary>
    public sealed class InputDialog : Form
    {
        private readonly TextBox box = new TextBox();

        public string Value { get { return box.Text; } }

        public InputDialog(string title, string prompt, string initial, bool password)
        {
            Text = title;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterParent;
            MinimizeBox = false;
            MaximizeBox = false;
            ShowInTaskbar = false;
            ClientSize = new Size(380, 120);
            Font = new Font("Segoe UI", 9f);

            Label label = new Label { Text = prompt, Left = 12, Top = 12, Width = 356, Height = 20 };
            box.SetBounds(12, 36, 356, 24);
            box.Text = initial ?? "";
            box.UseSystemPasswordChar = password;
            Button ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Left = 212, Top = 78, Width = 75 };
            Button cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Left = 293, Top = 78, Width = 75 };
            Controls.AddRange(new Control[] { label, box, ok, cancel });
            AcceptButton = ok;
            CancelButton = cancel;
        }

        public static string Ask(IWin32Window owner, string title, string prompt, string initial, bool password)
        {
            using (InputDialog d = new InputDialog(title, prompt, initial, password))
            {
                return d.ShowDialog(owner) == DialogResult.OK ? d.Value : null;
            }
        }
    }

    /// <summary>Text comment editor: text, font size, text colour and box colour.</summary>
    public sealed class TextCommentDialog : Form
    {
        private readonly TextBox textBox = new TextBox();
        private readonly NumericUpDown sizeBox = new NumericUpDown();
        private readonly Button textColorButton = new Button();
        private readonly Button fillColorButton = new Button();
        private readonly TextBox authorBox = new TextBox();

        public string CommentText { get { return textBox.Text; } }
        public double FontSizePt { get { return (double)sizeBox.Value; } }
        public Color TextColor { get { return textColorButton.BackColor; } }
        public Color FillColor { get { return fillColorButton.BackColor; } }
        public string Author { get { return authorBox.Text; } }

        public TextCommentDialog(string author)
        {
            Text = "Add Text Comment";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterParent;
            MinimizeBox = false;
            MaximizeBox = false;
            ShowInTaskbar = false;
            ClientSize = new Size(440, 300);
            Font = new Font("Segoe UI", 9f);

            Label l1 = new Label { Text = "Comment text:", Left = 12, Top = 10, Width = 200 };
            textBox.SetBounds(12, 30, 416, 130);
            textBox.Multiline = true;
            textBox.ScrollBars = ScrollBars.Vertical;
            textBox.AcceptsReturn = true;

            Label l2 = new Label { Text = "Font size:", Left = 12, Top = 174, Width = 70 };
            sizeBox.SetBounds(90, 170, 70, 24);
            sizeBox.Minimum = 6;
            sizeBox.Maximum = 72;
            sizeBox.Value = 11;

            Label l3 = new Label { Text = "Text colour:", Left = 180, Top = 174, Width = 80 };
            textColorButton.SetBounds(262, 170, 40, 24);
            textColorButton.BackColor = Color.FromArgb(17, 24, 39);
            textColorButton.FlatStyle = FlatStyle.Flat;
            textColorButton.Click += delegate { PickColor(textColorButton); };

            Label l4 = new Label { Text = "Box colour:", Left = 312, Top = 174, Width = 70 };
            fillColorButton.SetBounds(388, 170, 40, 24);
            fillColorButton.BackColor = Color.FromArgb(255, 249, 196);
            fillColorButton.FlatStyle = FlatStyle.Flat;
            fillColorButton.Click += delegate { PickColor(fillColorButton); };

            Label l5 = new Label { Text = "Author:", Left = 12, Top = 214, Width = 70 };
            authorBox.SetBounds(90, 210, 212, 24);
            authorBox.Text = author ?? Environment.UserName;

            Button ok = new Button { Text = "Add", DialogResult = DialogResult.OK, Left = 272, Top = 258, Width = 75 };
            Button cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Left = 353, Top = 258, Width = 75 };
            Controls.AddRange(new Control[] { l1, textBox, l2, sizeBox, l3, textColorButton, l4, fillColorButton, l5, authorBox, ok, cancel });
            CancelButton = cancel;
        }

        private void PickColor(Button target)
        {
            using (ColorDialog cd = new ColorDialog())
            {
                cd.Color = target.BackColor;
                cd.FullOpen = true;
                if (cd.ShowDialog(this) == DialogResult.OK) target.BackColor = cd.Color;
            }
        }
    }

    /// <summary>Split options: every N pages or explicit ranges, plus output folder.</summary>
    public sealed class SplitDialog : Form
    {
        private readonly RadioButton everyRadio = new RadioButton();
        private readonly RadioButton rangesRadio = new RadioButton();
        private readonly NumericUpDown everyBox = new NumericUpDown();
        private readonly TextBox rangesBox = new TextBox();
        private readonly TextBox folderBox = new TextBox();
        private readonly TextBox nameBox = new TextBox();

        public bool UseRanges { get { return rangesRadio.Checked; } }
        public int PagesPerFile { get { return (int)everyBox.Value; } }
        public string Ranges { get { return rangesBox.Text; } }
        public string OutputFolder { get { return folderBox.Text; } }
        public string BaseName { get { return nameBox.Text; } }

        public SplitDialog(int pageCount, string defaultFolder, string defaultName)
        {
            Text = "Split Document";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterParent;
            MinimizeBox = false;
            MaximizeBox = false;
            ShowInTaskbar = false;
            ClientSize = new Size(470, 250);
            Font = new Font("Segoe UI", 9f);

            Label info = new Label { Text = "The document has " + pageCount + " page(s).", Left = 12, Top = 10, Width = 440 };

            everyRadio.Text = "Every";
            everyRadio.SetBounds(12, 40, 60, 24);
            everyRadio.Checked = true;
            everyBox.SetBounds(76, 40, 60, 24);
            everyBox.Minimum = 1;
            everyBox.Maximum = Math.Max(1, pageCount);
            everyBox.Value = 1;
            Label pagesLabel = new Label { Text = "page(s) per file", Left = 142, Top = 44, Width = 140 };

            rangesRadio.Text = "Ranges:";
            rangesRadio.SetBounds(12, 74, 72, 24);
            rangesBox.SetBounds(90, 74, 362, 24);
            rangesBox.Text = "1-" + Math.Max(1, pageCount / 2) + "; " + (pageCount / 2 + 1) + "-" + pageCount;
            Label hint = new Label { Text = "Each part separated by ';' becomes one file, e.g. 1-3; 4-6; 7-", Left = 90, Top = 100, Width = 362, ForeColor = Color.DimGray };

            Label folderLabel = new Label { Text = "Output folder:", Left = 12, Top = 134, Width = 90 };
            folderBox.SetBounds(104, 130, 300, 24);
            folderBox.Text = defaultFolder;
            Button browse = new Button { Text = "...", Left = 410, Top = 129, Width = 42 };
            browse.Click += delegate
            {
                using (FolderBrowserDialog fb = new FolderBrowserDialog())
                {
                    fb.SelectedPath = folderBox.Text;
                    if (fb.ShowDialog(this) == DialogResult.OK) folderBox.Text = fb.SelectedPath;
                }
            };

            Label nameLabel = new Label { Text = "File name prefix:", Left = 12, Top = 168, Width = 100 };
            nameBox.SetBounds(116, 164, 336, 24);
            nameBox.Text = defaultName;

            Button ok = new Button { Text = "Split", Left = 296, Top = 210, Width = 75 };
            ok.Click += delegate
            {
                if (!Directory.Exists(folderBox.Text))
                {
                    MessageBox.Show(this, "Please choose an existing output folder.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                if (nameBox.Text.Trim().Length == 0)
                {
                    MessageBox.Show(this, "Please enter a file name prefix.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    return;
                }
                DialogResult = DialogResult.OK;
                Close();
            };
            Button cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Left = 377, Top = 210, Width = 75 };
            Controls.AddRange(new Control[] { info, everyRadio, everyBox, pagesLabel, rangesRadio, rangesBox, hint,
                                              folderLabel, folderBox, browse, nameLabel, nameBox, ok, cancel });
            CancelButton = cancel;
        }
    }

    /// <summary>Shows the error log collected during this session.</summary>
    public sealed class LogDialog : Form
    {
        public LogDialog()
        {
            Text = "Error Log";
            StartPosition = FormStartPosition.CenterParent;
            ClientSize = new Size(720, 380);
            Font = new Font("Segoe UI", 9f);
            ShowInTaskbar = false;

            TextBox box = new TextBox
            {
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Both,
                WordWrap = false,
                Dock = DockStyle.Fill,
                Font = new Font("Consolas", 9f),
                Text = ErrorLog.Entries.Count == 0 ? "No errors." : string.Join(Environment.NewLine, ErrorLog.Entries)
            };
            FlowLayoutPanel bar = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 40, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(6) };
            Button close = new Button { Text = "Close", DialogResult = DialogResult.OK, Width = 80 };
            Button clear = new Button { Text = "Clear", Width = 80 };
            clear.Click += delegate { ErrorLog.Clear(); box.Text = "No errors."; };
            Button openFile = new Button { Text = "Open log file", Width = 110 };
            openFile.Click += delegate
            {
                if (File.Exists(ErrorLog.LogFilePath)) System.Diagnostics.Process.Start("notepad.exe", "\"" + ErrorLog.LogFilePath + "\"");
            };
            bar.Controls.AddRange(new Control[] { close, clear, openFile });
            Controls.Add(box);
            Controls.Add(bar);
            AcceptButton = close;
        }
    }
}
