using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using PdfSharp;
using PdfSharp.Drawing;
using PdfSharp.Drawing.Layout;
using PdfSharp.Pdf;
using PdfSharp.Pdf.Annotations;
using PdfSharp.Pdf.IO;
using SharpDoc = PdfSharp.Pdf.PdfDocument;

namespace WaraqPdfLite
{
    /// <summary>Unrotated page geometry (PDF points) and the page's /Rotate value.</summary>
    public sealed class PageGeometry
    {
        public double Width;
        public double Height;
        public int Rotation;

        public double DisplayWidth { get { return Rotation % 180 == 0 ? Width : Height; } }
        public double DisplayHeight { get { return Rotation % 180 == 0 ? Height : Width; } }
    }

    /// <summary>All document-changing operations. Every method works on files so the viewer can reload safely.</summary>
    public static class PdfOps
    {
        // ------------------------------------------------------------------ helpers
        public static int NormalizeRotation(int rotation)
        {
            int r = rotation % 360;
            if (r < 0) r += 360;
            return r;
        }

        /// <summary>Save a PDFsharp document to a temp file first, then replace the target (safe overwrite).</summary>
        public static void SaveReplace(SharpDoc doc, string path)
        {
            string tmp = path + ".saving.tmp";
            if (File.Exists(tmp)) File.Delete(tmp);
            doc.Save(tmp);
            File.Copy(tmp, path, true);
            File.Delete(tmp);
        }

        public static List<PageGeometry> ReadGeometry(string path)
        {
            List<PageGeometry> list = new List<PageGeometry>();
            using (SharpDoc doc = PdfReader.Open(path, PdfDocumentOpenMode.Import))
            {
                foreach (PdfPage page in doc.Pages)
                {
                    PageGeometry g = new PageGeometry();
                    g.Width = page.MediaBox.Width;
                    g.Height = page.MediaBox.Height;
                    g.Rotation = NormalizeRotation(page.Rotate);
                    list.Add(g);
                }
            }
            return list;
        }

        /// <summary>
        /// Opens a PDF with PDFsharp. If it is password protected, decrypts it with the given password and saves an
        /// unprotected working copy. Returns true when a working copy was written.
        /// </summary>
        public static void CreateWorkingCopy(string source, string workPath, string password)
        {
            if (string.IsNullOrEmpty(password))
            {
                File.Copy(source, workPath, true);
                return;
            }
            using (SharpDoc doc = PdfReader.Open(source, password, PdfDocumentOpenMode.Modify))
            {
                doc.SecuritySettings.DocumentSecurityLevel = PdfSharp.Pdf.Security.PdfDocumentSecurityLevel.None;
                doc.Save(workPath);
            }
        }

        public static bool NeedsPassword(string path)
        {
            try
            {
                using (SharpDoc doc = PdfReader.Open(path, PdfDocumentOpenMode.Modify))
                {
                    return false;
                }
            }
            catch (PdfReaderException ex)
            {
                string m = ex.Message.ToLowerInvariant();
                return m.Contains("password");
            }
        }

        /// <summary>Parses "1-3, 5, 8-" style page ranges (1-based) into 0-based indices.</summary>
        public static List<int> ParseRanges(string spec, int pageCount)
        {
            List<int> result = new List<int>();
            if (string.IsNullOrWhiteSpace(spec) || spec.Trim().Equals("all", StringComparison.OrdinalIgnoreCase))
            {
                for (int i = 0; i < pageCount; i++) result.Add(i);
                return result;
            }
            string[] parts = spec.Split(new[] { ',', ';', ' ' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (string raw in parts)
            {
                string part = raw.Trim();
                int dash = part.IndexOf('-');
                if (dash >= 0)
                {
                    string a = part.Substring(0, dash).Trim();
                    string b = part.Substring(dash + 1).Trim();
                    int from = a.Length == 0 ? 1 : int.Parse(a, CultureInfo.InvariantCulture);
                    int to = b.Length == 0 ? pageCount : int.Parse(b, CultureInfo.InvariantCulture);
                    if (from > to) { int t = from; from = to; to = t; }
                    for (int p = from; p <= to; p++)
                        if (p >= 1 && p <= pageCount && !result.Contains(p - 1)) result.Add(p - 1);
                }
                else
                {
                    int p = int.Parse(part, CultureInfo.InvariantCulture);
                    if (p >= 1 && p <= pageCount && !result.Contains(p - 1)) result.Add(p - 1);
                }
            }
            return result;
        }

        // ------------------------------------------------------------------ rotate
        public static void RotatePages(string path, IEnumerable<int> pageIndices, int degreesClockwise)
        {
            using (SharpDoc doc = PdfReader.Open(path, PdfDocumentOpenMode.Modify))
            {
                foreach (int i in pageIndices)
                {
                    PdfPage page = doc.Pages[i];
                    page.Rotate = NormalizeRotation(page.Rotate + degreesClockwise);
                }
                SaveReplace(doc, path);
            }
        }

        // ------------------------------------------------------------------ merge / split
        public static int MergeFiles(IList<string> inputs, string output)
        {
            int pages = 0;
            using (SharpDoc result = new SharpDoc())
            {
                foreach (string file in inputs)
                {
                    using (SharpDoc input = PdfReader.Open(file, PdfDocumentOpenMode.Import))
                    {
                        foreach (PdfPage page in input.Pages)
                        {
                            result.AddPage(page);
                            pages++;
                        }
                    }
                }
                string tmp = output + ".merging.tmp";
                if (File.Exists(tmp)) File.Delete(tmp);
                result.Save(tmp);
                File.Copy(tmp, output, true);
                File.Delete(tmp);
            }
            return pages;
        }

        /// <summary>Writes one file per group of pages. Returns the list of created files.</summary>
        public static List<string> Split(string path, string folder, string baseName, List<List<int>> groups)
        {
            List<string> created = new List<string>();
            using (SharpDoc input = PdfReader.Open(path, PdfDocumentOpenMode.Import))
            {
                for (int g = 0; g < groups.Count; g++)
                {
                    if (groups[g].Count == 0) continue;
                    using (SharpDoc part = new SharpDoc())
                    {
                        foreach (int i in groups[g])
                            part.AddPage(input.Pages[i]);
                        string name = string.Format(CultureInfo.InvariantCulture, "{0}_part{1:000}.pdf", baseName, g + 1);
                        string full = Path.Combine(folder, name);
                        part.Save(full);
                        created.Add(full);
                    }
                }
            }
            return created;
        }

        public static List<List<int>> GroupsEveryN(int pageCount, int n)
        {
            List<List<int>> groups = new List<List<int>>();
            if (n < 1) n = 1;
            for (int start = 0; start < pageCount; start += n)
            {
                List<int> g = new List<int>();
                for (int i = start; i < Math.Min(pageCount, start + n); i++) g.Add(i);
                groups.Add(g);
            }
            return groups;
        }

        public static List<List<int>> GroupsFromRanges(string spec, int pageCount)
        {
            // "1-3; 4-6; 7-" -> each segment separated by ';' or '|' is one output file
            List<List<int>> groups = new List<List<int>>();
            string[] segments = spec.Split(new[] { ';', '|' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (string seg in segments)
            {
                List<int> g = ParseRanges(seg, pageCount);
                if (g.Count > 0) groups.Add(g);
            }
            return groups;
        }

        // ------------------------------------------------------------------ text comment
        /// <summary>Maps a point measured on the page as displayed (top-left origin, points) to the unrotated page
        /// (top-left origin, points).</summary>
        public static void DisplayToUnrotated(int rotation, double width, double height, double x, double y,
                                              out double u, out double v)
        {
            switch (NormalizeRotation(rotation))
            {
                case 90:
                    u = y; v = height - x; break;
                case 180:
                    u = width - x; v = height - y; break;
                case 270:
                    u = width - y; v = x; break;
                default:
                    u = x; v = y; break;
            }
        }

        /// <summary>
        /// Adds a visible text box (drawn into the page content, readable in every viewer) and a matching
        /// sticky-note annotation that holds the same text as a real PDF comment.
        /// x, y are in points on the page as it is displayed (rotation applied), top-left origin.
        /// </summary>
        public static void AddTextComment(string path, int pageIndex, double x, double y, string text, double fontSize,
                                          System.Drawing.Color textColor, System.Drawing.Color fillColor, string author)
        {
            if (string.IsNullOrEmpty(text)) return;
            using (SharpDoc doc = PdfReader.Open(path, PdfDocumentOpenMode.Modify))
            {
                PdfPage page = doc.Pages[pageIndex];
                int rot = NormalizeRotation(page.Rotate);
                double w = page.MediaBox.Width;
                double h = page.MediaBox.Height;

                double u, v;
                DisplayToUnrotated(rot, w, h, x, y, out u, out v);

                XFont font = new XFont("Arial", fontSize, XFontStyle.Regular, new XPdfFontOptions(PdfFontEncoding.Unicode));
                const double pad = 5.0;
                const double maxTextWidth = 320.0;
                double boxW;
                double boxH;

                // Draw in the unrotated coordinate system; temporarily neutralise rotation so PDFsharp does not
                // apply its own landscape transform, then rotate our drawing so it reads upright on screen.
                PageOrientation orientation = page.Orientation;
                page.Rotate = 0;
                page.Orientation = PageOrientation.Portrait;
                using (XGraphics gfx = XGraphics.FromPdfPage(page, XGraphicsPdfPageOptions.Append))
                {
                    string[] lines = text.Replace("\r\n", "\n").Split('\n');
                    double lineHeight = gfx.MeasureString("Xg", font).Height;
                    double widest = 0;
                    int visualLines = 0;
                    foreach (string line in lines)
                    {
                        double lw = gfx.MeasureString(line.Length == 0 ? " " : line, font).Width;
                        widest = Math.Max(widest, Math.Min(lw, maxTextWidth));
                        visualLines += Math.Max(1, (int)Math.Ceiling(lw / maxTextWidth));
                    }
                    boxW = widest + pad * 2 + 2;
                    boxH = visualLines * lineHeight + pad * 2;

                    gfx.RotateAtTransform(-rot, new XPoint(u, v));
                    XRect box = new XRect(u, v, boxW, boxH);
                    XColor fill = XColor.FromArgb(fillColor.A, fillColor.R, fillColor.G, fillColor.B);
                    XColor ink = XColor.FromArgb(textColor.A, textColor.R, textColor.G, textColor.B);
                    gfx.DrawRectangle(new XPen(ink, 0.8), new XSolidBrush(fill), box);
                    XTextFormatter tf = new XTextFormatter(gfx);
                    tf.DrawString(text, font, new XSolidBrush(ink),
                                  new XRect(u + pad, v + pad, boxW - pad * 2, boxH - pad * 2), XStringFormats.TopLeft);
                }
                page.Rotate = rot;
                page.Orientation = orientation;

                // Sticky-note comment at the box's top-right corner (as displayed).
                double cu, cv;
                DisplayToUnrotated(rot, w, h, x + boxW, y, out cu, out cv);
                PdfTextAnnotation note = new PdfTextAnnotation();
                note.Title = string.IsNullOrEmpty(author) ? Environment.UserName : author;
                note.Subject = "Comment";
                note.Contents = text;
                note.Icon = PdfTextAnnotationIcon.Comment;
                note.Color = XColor.FromArgb(255, 230, 180, 30);
                note.Rectangle = new PdfRectangle(new XRect(cu, h - cv - 18, 18, 18));
                page.Annotations.Add(note);

                SaveReplace(doc, path);
            }
        }
    }
}
