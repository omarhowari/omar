using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;

namespace WaraqPdfLite
{
    /// <summary>Draws the application's own toolbar icons at runtime (no image resources needed).</summary>
    public static class IconFactory
    {
        private static readonly Dictionary<string, Bitmap> cache = new Dictionary<string, Bitmap>();

        public static Bitmap Get(string name, int size)
        {
            string key = name + "_" + size;
            Bitmap bmp;
            if (cache.TryGetValue(key, out bmp)) return bmp;
            bmp = new Bitmap(size, size);
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                float s = size / 32f;
                g.ScaleTransform(s, s);
                Draw(g, name);
            }
            cache[key] = bmp;
            return bmp;
        }

        private static Pen P(Color c, float w)
        {
            Pen p = new Pen(c, w);
            p.StartCap = LineCap.Round;
            p.EndCap = LineCap.Round;
            p.LineJoin = LineJoin.Round;
            return p;
        }

        private static void Page(Graphics g, Color fill, Color border)
        {
            PointF[] pts = { new PointF(8, 3), new PointF(20, 3), new PointF(26, 9), new PointF(26, 29), new PointF(8, 29) };
            using (Brush b = new SolidBrush(fill)) g.FillPolygon(b, pts);
            using (Pen p = P(border, 1.6f))
            {
                g.DrawPolygon(p, pts);
                g.DrawLines(p, new[] { new PointF(20, 3), new PointF(20, 9), new PointF(26, 9) });
            }
        }

        private static void Arrow(Graphics g, Color c, PointF a, PointF b)
        {
            using (Pen p = P(c, 2.6f))
            {
                p.CustomEndCap = new AdjustableArrowCap(3.2f, 3.2f, true);
                g.DrawLine(p, a, b);
            }
        }

        private static void Draw(Graphics g, string name)
        {
            Color blue = Color.FromArgb(43, 108, 176);
            Color green = Color.FromArgb(47, 133, 90);
            Color red = Color.FromArgb(197, 48, 48);
            Color dark = Color.FromArgb(55, 65, 81);
            Color yellow = Color.FromArgb(246, 195, 67);
            Color paper = Color.White;

            switch (name)
            {
                case "open":
                    using (Brush b = new SolidBrush(yellow))
                        g.FillPolygon(b, new[] { new PointF(3, 9), new PointF(12, 9), new PointF(15, 12), new PointF(29, 12), new PointF(29, 27), new PointF(3, 27) });
                    using (Pen p = P(Color.FromArgb(183, 121, 31), 1.6f))
                        g.DrawPolygon(p, new[] { new PointF(3, 9), new PointF(12, 9), new PointF(15, 12), new PointF(29, 12), new PointF(29, 27), new PointF(3, 27) });
                    break;
                case "save":
                case "saveas":
                    using (Brush b = new SolidBrush(Color.FromArgb(144, 205, 244))) g.FillRectangle(b, 4, 4, 24, 24);
                    using (Pen p = P(blue, 1.8f)) g.DrawRectangle(p, 4, 4, 24, 24);
                    using (Brush b = new SolidBrush(paper)) g.FillRectangle(b, 9, 4, 14, 9);
                    using (Brush b = new SolidBrush(blue)) g.FillRectangle(b, 9, 18, 14, 10);
                    if (name == "saveas")
                        using (Pen p = P(red, 2.4f)) g.DrawLine(p, 18, 30, 30, 18);
                    break;
                case "print":
                    using (Brush b = new SolidBrush(Color.FromArgb(203, 213, 224))) g.FillRectangle(b, 3, 12, 26, 11);
                    using (Pen p = P(dark, 1.6f)) g.DrawRectangle(p, 3, 12, 26, 11);
                    using (Brush b = new SolidBrush(paper)) { g.FillRectangle(b, 9, 4, 14, 8); g.FillRectangle(b, 9, 19, 14, 10); }
                    using (Pen p = P(dark, 1.4f)) { g.DrawRectangle(p, 9, 4, 14, 8); g.DrawRectangle(p, 9, 19, 14, 10); }
                    break;
                case "zoomin":
                case "zoomout":
                    using (Pen p = P(blue, 2.4f))
                    {
                        g.DrawEllipse(p, 4, 4, 17, 17);
                        g.DrawLine(p, 18, 18, 28, 28);
                        g.DrawLine(p, 8.5f, 12.5f, 16.5f, 12.5f);
                        if (name == "zoomin") g.DrawLine(p, 12.5f, 8.5f, 12.5f, 16.5f);
                    }
                    break;
                case "fitwidth":
                    Page(g, paper, dark);
                    Arrow(g, blue, new PointF(16, 18), new PointF(4, 18));
                    Arrow(g, blue, new PointF(16, 18), new PointF(29, 18));
                    break;
                case "rotate":
                    using (Pen p = P(green, 2.6f))
                    {
                        g.DrawArc(p, 5, 5, 22, 22, 200, 270);
                        p.CustomEndCap = new AdjustableArrowCap(3.4f, 3.4f, true);
                        g.DrawArc(p, 5, 5, 22, 22, 110, 70);
                    }
                    break;
                case "rotateall":
                    Page(g, paper, dark);
                    using (Pen p = P(green, 2.2f))
                    {
                        p.CustomEndCap = new AdjustableArrowCap(3f, 3f, true);
                        g.DrawArc(p, 9, 11, 14, 14, 180, 250);
                    }
                    break;
                case "merge":
                    Page(g, Color.FromArgb(233, 216, 253), Color.FromArgb(107, 70, 193));
                    using (Pen p = P(Color.FromArgb(107, 70, 193), 2.2f))
                    {
                        g.DrawLine(p, 12, 13, 17, 18);
                        g.DrawLine(p, 22, 13, 17, 18);
                        g.DrawLine(p, 17, 18, 17, 25);
                    }
                    break;
                case "split":
                    Page(g, Color.FromArgb(233, 216, 253), Color.FromArgb(107, 70, 193));
                    using (Pen p = P(Color.FromArgb(107, 70, 193), 2.2f))
                    {
                        p.DashStyle = DashStyle.Dash;
                        g.DrawLine(p, 6, 17, 28, 17);
                    }
                    break;
                case "comment":
                    using (Brush b = new SolidBrush(Color.FromArgb(250, 240, 137)))
                        g.FillPolygon(b, new[] { new PointF(3, 5), new PointF(29, 5), new PointF(29, 21), new PointF(14, 21), new PointF(7, 28), new PointF(8, 21), new PointF(3, 21) });
                    using (Pen p = P(Color.FromArgb(183, 121, 31), 1.6f))
                    {
                        g.DrawPolygon(p, new[] { new PointF(3, 5), new PointF(29, 5), new PointF(29, 21), new PointF(14, 21), new PointF(7, 28), new PointF(8, 21), new PointF(3, 21) });
                        g.DrawLine(p, 8, 11, 24, 11);
                        g.DrawLine(p, 8, 15, 20, 15);
                    }
                    break;
                case "first":
                case "prev":
                case "next":
                case "last":
                    using (Brush b = new SolidBrush(blue))
                    {
                        bool left = name == "first" || name == "prev";
                        PointF[] tri = left
                            ? new[] { new PointF(22, 7), new PointF(10, 16), new PointF(22, 25) }
                            : new[] { new PointF(10, 7), new PointF(22, 16), new PointF(10, 25) };
                        g.FillPolygon(b, tri);
                        if (name == "first") g.FillRectangle(b, 6, 7, 3, 18);
                        if (name == "last") g.FillRectangle(b, 23, 7, 3, 18);
                    }
                    break;
                case "undo":
                    using (Pen p = P(blue, 2.6f))
                    {
                        p.CustomEndCap = new AdjustableArrowCap(3.2f, 3.2f, true);
                        g.DrawArc(p, 7, 8, 18, 16, 20, -200);
                    }
                    break;
                case "close":
                    using (Pen p = P(red, 2.8f))
                    {
                        g.DrawLine(p, 9, 9, 23, 23);
                        g.DrawLine(p, 23, 9, 9, 23);
                    }
                    break;
                case "log":
                    Page(g, paper, dark);
                    using (Pen p = P(red, 2.2f))
                    {
                        g.DrawLine(p, 17, 12, 17, 20);
                        g.DrawLine(p, 17, 24, 17, 24.5f);
                    }
                    break;
                default:
                    Page(g, paper, dark);
                    break;
            }
        }

        /// <summary>Simple application icon: a page with the letter W.</summary>
        public static Icon AppIcon()
        {
            using (Bitmap bmp = new Bitmap(32, 32))
            {
                using (Graphics g = Graphics.FromImage(bmp))
                {
                    g.SmoothingMode = SmoothingMode.AntiAlias;
                    g.Clear(Color.Transparent);
                    using (Brush b = new SolidBrush(Color.FromArgb(29, 78, 216)))
                        g.FillRectangle(b, 3, 3, 26, 26);
                    using (Font f = new Font("Segoe UI", 15f, FontStyle.Bold, GraphicsUnit.Pixel))
                    using (Brush w = new SolidBrush(Color.White))
                    {
                        StringFormat sf = new StringFormat();
                        sf.Alignment = StringAlignment.Center;
                        sf.LineAlignment = StringAlignment.Center;
                        g.DrawString("W", f, w, new RectangleF(3, 3, 26, 26), sf);
                    }
                }
                return Icon.FromHandle(bmp.GetHicon());
            }
        }
    }
}
