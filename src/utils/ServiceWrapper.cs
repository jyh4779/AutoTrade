
using System;
using System.Diagnostics;
using System.ServiceProcess;
using System.IO;
using System.Threading;

namespace TradingServiceWrapper
{
    public class TradingService : ServiceBase
    {
        private Process _childProcess;
        private const string LogPath = @"D:\ML\data\service_wrapper.log";

        public TradingService()
        {
            this.ServiceName = "AI_AutoTrade_Bot";
            this.CanStop = true;
            this.CanPauseAndContinue = false;
            this.AutoLog = true;
        }

        protected override void OnStart(string[] args)
        {
            Log("Service starting...");
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = @"D:\ML\venv2\Scripts\python.exe",
                    Arguments = @"D:\ML\src\main_scheduler.py",
                    WorkingDirectory = @"D:\ML",
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };

                _childProcess = new Process { StartInfo = psi };
                _childProcess.Start();
                Log("Python daemon started. PID: " + _childProcess.Id.ToString());
            }
            catch (Exception ex)
            {
                Log("Error during startup: " + ex.Message);
                this.Stop();
            }
        }

        protected override void OnStop()
        {
            Log("Service stopping...");
            if (_childProcess != null && !_childProcess.HasExited)
            {
                try
                {
                    _childProcess.Kill();
                    Log("Child process killed.");
                }
                catch (Exception ex)
                {
                    Log("Error killing child process: " + ex.Message);
                }
            }
            Log("Service stopped.");
        }

        private void Log(string message)
        {
            try
            {
                string logDir = Path.GetDirectoryName(LogPath);
                if (!Directory.Exists(logDir)) Directory.CreateDirectory(logDir);
                File.AppendAllText(LogPath, "[" + DateTime.Now.ToString() + "] " + message + Environment.NewLine);
            }
            catch { }
        }

        public static void Main()
        {
            ServiceBase.Run(new TradingService());
        }
    }
}
