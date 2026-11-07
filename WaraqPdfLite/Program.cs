using System;
using System.Threading;
using System.Windows.Forms;

namespace WaraqPdfLite
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
            Application.ThreadException += OnThreadException;
            AppDomain.CurrentDomain.UnhandledException += OnUnhandledException;

            string startFile = args != null && args.Length > 0 ? args[0] : null;
            Application.Run(new MainForm(startFile));
        }

        private static void OnThreadException(object sender, ThreadExceptionEventArgs e)
        {
            ErrorLog.Write("Unhandled UI exception", e.Exception);
            MessageBox.Show("An unexpected error occurred:\r\n\r\n" + e.Exception.Message +
                            "\r\n\r\nDetails were written to:\r\n" + ErrorLog.LogFilePath,
                            "Waraq PDF Lite", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }

        private static void OnUnhandledException(object sender, UnhandledExceptionEventArgs e)
        {
            Exception ex = e.ExceptionObject as Exception;
            ErrorLog.Write("Fatal exception", ex);
        }
    }
}
