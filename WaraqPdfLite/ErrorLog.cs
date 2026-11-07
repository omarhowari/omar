using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace WaraqPdfLite
{
    /// <summary>Keeps an in-memory list of errors for the status bar and appends them to a log file.</summary>
    public static class ErrorLog
    {
        private static readonly List<string> entries = new List<string>();

        public static event EventHandler Changed;

        public static string LogFilePath
        {
            get
            {
                string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WaraqPdfLite");
                Directory.CreateDirectory(dir);
                return Path.Combine(dir, "errors.log");
            }
        }

        public static IList<string> Entries { get { return entries.AsReadOnly(); } }

        public static void Write(string context, Exception ex)
        {
            string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + context +
                          (ex == null ? "" : ": " + ex.GetType().Name + " - " + ex.Message);
            entries.Add(line);
            try
            {
                StringBuilder sb = new StringBuilder();
                sb.AppendLine(line);
                if (ex != null) sb.AppendLine(ex.ToString());
                File.AppendAllText(LogFilePath, sb.ToString(), Encoding.UTF8);
            }
            catch (IOException)
            {
                // The log file is optional; the in-memory list still shows the error.
            }
            EventHandler handler = Changed;
            if (handler != null) handler(null, EventArgs.Empty);
        }

        public static void Clear()
        {
            entries.Clear();
            EventHandler handler = Changed;
            if (handler != null) handler(null, EventArgs.Empty);
        }
    }
}
