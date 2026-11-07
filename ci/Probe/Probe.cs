using System;
using System.Drawing;
using System.IO;
using PdfSharp.Drawing;
using PdfSharp.Pdf;
using PdfSharp.Pdf.IO;

internal static class Probe
{
    private static void Main()
    {
        string dir = Path.Combine(Path.GetTempPath(), "probe");
        Directory.CreateDirectory(dir);
        foreach (int rot in new[] { 0, 90, 180, 270 })
        {
            string f = Path.Combine(dir, "r" + rot + ".pdf");
            using (var d = new PdfDocument()) { d.AddPage(); d.Save(f); }
            using (var d = PdfReader.Open(f, PdfDocumentOpenMode.Modify)) { d.Pages[0].Rotate = rot; d.Save(f); }
            using (var d = PdfReader.Open(f, PdfDocumentOpenMode.Modify))
            {
                PdfPage p = d.Pages[0];
                using (XGraphics g = XGraphics.FromPdfPage(p, XGraphicsPdfPageOptions.Append))
                {
                    Console.WriteLine("rot " + rot + " gfx PageSize=" + g.PageSize.Width + "x" + g.PageSize.Height);
                    g.DrawRectangle(XBrushes.Red, new XRect(100, 120, 60, 20));
                    g.DrawRectangle(XBrushes.Blue, new XRect(100, 120, 6, 6));
                }
                d.Save(f);
            }
            using (var d = PdfReader.Open(f, PdfDocumentOpenMode.Import))
                Console.WriteLine("  raw MediaBox=" + d.Pages[0].Elements["/MediaBox"] + " Rotate=" + d.Pages[0].Elements["/Rotate"]);
            using (var s = new MemoryStream(File.ReadAllBytes(f)))
            using (var pd = PdfiumViewer.PdfDocument.Load(s))
            {
                SizeF sz = pd.PageSizes[0];
                using (var bmp = (Bitmap)pd.Render(0, (int)sz.Width, (int)sz.Height, 72, 72, PdfiumViewer.PdfRenderFlags.Annotations))
                {
                    int rx0 = 9999, ry0 = 9999, rx1 = -1, ry1 = -1, bx0 = 9999, by0 = 9999, bx1 = -1, by1 = -1;
                    for (int y = 0; y < bmp.Height; y++)
                        for (int x = 0; x < bmp.Width; x++)
                        {
                            Color c = bmp.GetPixel(x, y);
                            if (c.R > 200 && c.G < 60 && c.B < 60) { rx0 = Math.Min(rx0, x); ry0 = Math.Min(ry0, y); rx1 = Math.Max(rx1, x); ry1 = Math.Max(ry1, y); }
                            if (c.B > 200 && c.R < 60 && c.G < 60) { bx0 = Math.Min(bx0, x); by0 = Math.Min(by0, y); bx1 = Math.Max(bx1, x); by1 = Math.Max(by1, y); }
                        }
                    Console.WriteLine("  display " + bmp.Width + "x" + bmp.Height + " red=(" + rx0 + "," + ry0 + ")-(" + rx1 + "," + ry1 + ") blue=(" + bx0 + "," + by0 + ")-(" + bx1 + "," + by1 + ")");
                }
            }
        }
    }
}
