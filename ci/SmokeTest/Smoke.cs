using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using PdfSharp.Drawing;
using PdfSharp.Pdf;
using WaraqPdfLite;

internal static class Smoke
{
    private static int failures;

    private static void Check(bool ok, string what)
    {
        Console.WriteLine((ok ? "PASS  " : "FAIL  ") + what);
        if (!ok) failures++;
    }

    private static Bitmap Render(string path, int page)
    {
        PageGeometry g = PdfOps.ReadGeometry(path)[page];
        using (var stream = new MemoryStream(File.ReadAllBytes(path)))
        using (var doc = PdfiumViewer.PdfDocument.Load(stream))
        {
            Console.WriteLine("  pdfium PageSizes[" + page + "] = " + doc.PageSizes[page] + "  display = " + g.DisplayWidth + "x" + g.DisplayHeight);
            return (Bitmap)doc.Render(page, (int)g.DisplayWidth, (int)g.DisplayHeight, 72, 72, PdfiumViewer.PdfRenderFlags.Annotations);
        }
    }

    private static bool TextUpright(Bitmap bmp)
    {
        // The box text starts near the box's top-left; a dark pixel should exist in the first text line band.
        for (int y = 124; y < 140; y++)
            for (int x = 104; x < 160; x++)
            {
                Color c = bmp.GetPixel(x, y);
                if (c.R < 90 && c.G < 90 && c.B < 90) return true;
            }
        return false;
    }

    private static bool IsBoxColour(Color c)
    {
        return c.R > 240 && c.G > 235 && c.B > 170 && c.B < 220;   // ~ (255, 249, 196)
    }

    private static int Main()
    {
        string dir = Path.Combine(Path.GetTempPath(), "waraq_smoke");
        Directory.CreateDirectory(dir);
        string src = Path.Combine(dir, "source.pdf");
        using (var doc = new PdfDocument())
        {
            for (int i = 0; i < 4; i++)
            {
                PdfPage p = doc.AddPage();
                using (XGraphics g = XGraphics.FromPdfPage(p))
                    g.DrawString("Page " + (i + 1), new XFont("Arial", 30), XBrushes.Black, new XPoint(60, 100));
            }
            doc.Save(src);
        }
        string work = Path.Combine(dir, "work.pdf");
        File.Copy(src, work, true);

        // rotation
        PdfOps.RotatePages(work, new[] { 1 }, 90);
        PdfOps.RotatePages(work, new[] { 2 }, 180);
        PdfOps.RotatePages(work, new[] { 3 }, 270);
        List<PageGeometry> geo = PdfOps.ReadGeometry(work);
        Check(geo[0].Rotation == 0 && geo[1].Rotation == 90 && geo[2].Rotation == 180 && geo[3].Rotation == 270, "rotation values stored");

        // comments on every rotation, all at displayed (100, 120)
        for (int i = 0; i < 4; i++)
            PdfOps.AddTextComment(work, i, 100, 120, "Hello comment " + i, 12, Color.Black, Color.FromArgb(255, 249, 196), "CI");
        for (int i = 0; i < 4; i++)
        {
            using (Bitmap bmp = Render(work, i))
            {
                Color inside = bmp.GetPixel(103, 123);
                Color far = bmp.GetPixel(bmp.Width - 5, bmp.Height - 5);
                Console.WriteLine("  page " + (i + 1) + " rot " + geo[i].Rotation + " size " + bmp.Width + "x" + bmp.Height + " pixel@103,123=" + inside + " far=" + far);
                Check(IsBoxColour(inside), "comment box drawn at the clicked spot (page rotated " + geo[i].Rotation + ")");
                Check(bmp.Width == (int)geo[i].DisplayWidth, "rendered with displayed size (page rotated " + geo[i].Rotation + ")");
                Check(TextUpright(bmp), "comment text starts at box's top-left as displayed (page rotated " + geo[i].Rotation + ")");
                bmp.Save(Path.Combine(dir, "page" + (i + 1) + ".png"));
            }
        }
        using (PdfDocument check = PdfSharp.Pdf.IO.PdfReader.Open(work, PdfSharp.Pdf.IO.PdfDocumentOpenMode.Import))
            Check(check.Pages[0].Annotations.Count == 1, "sticky-note annotation added");

        // merge
        string merged = Path.Combine(dir, "merged.pdf");
        int n = PdfOps.MergeFiles(new List<string> { work, src }, merged);
        Check(n == 8, "merge produced 8 pages (got " + n + ")");
        int appended = PdfOps.MergeFiles(new List<string> { work, src }, work);
        Check(appended == 8 && PdfOps.ReadGeometry(work).Count == 8, "append into working file in place");

        // split
        string outDir = Path.Combine(dir, "split");
        Directory.CreateDirectory(outDir);
        List<string> parts = PdfOps.Split(merged, outDir, "doc", PdfOps.GroupsEveryN(8, 3));
        Check(parts.Count == 3, "split every 3 pages -> 3 files (got " + parts.Count + ")");
        List<string> parts2 = PdfOps.Split(merged, outDir, "rng", PdfOps.GroupsFromRanges("1-2; 5-; 3", 8));
        Check(parts2.Count == 3 && PdfOps.ReadGeometry(parts2[1]).Count == 4, "split by ranges");

        // ranges parser
        List<int> r = PdfOps.ParseRanges("1-3, 5, 7-", 8);
        Check(string.Join(",", r) == "0,1,2,4,6,7", "range parser: " + string.Join(",", r));

        Console.WriteLine(failures == 0 ? "ALL TESTS PASSED" : failures + " TEST(S) FAILED");
        return failures == 0 ? 0 : 1;
    }
}
