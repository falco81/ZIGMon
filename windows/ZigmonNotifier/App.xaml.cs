using System;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Windows;
using System.Windows.Threading;
using ZigmonNotifier.Core;
using ZigmonNotifier.Views;

namespace ZigmonNotifier;

public partial class App : Application
{
    private const string MutexName = @"Local\ZIGMonNotifier.SingleInstance.v1";
    private const string ShowEventName = @"Local\ZIGMonNotifier.Show.v1";

    private Mutex? _mutex;
    private EventWaitHandle? _showEvent;
    private RegisteredWaitHandle? _showWait;
    private AppController? _controller;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // started by the old version after it put this one in place: it is exiting now
        string? updatedFrom = ArgAfter(e.Args, "--updated");

        // one copy per Windows session: a second start just asks the first to show itself
        _mutex = new Mutex(true, MutexName, out bool first);
        if (!first && updatedFrom is not null)
        {
            try
            {
                first = _mutex.WaitOne(TimeSpan.FromSeconds(15));
            }
            catch (AbandonedMutexException)
            {
                first = true; // the old one went without letting go: ours now all the same
            }
        }
        if (!first)
        {
            try
            {
                using var ev = EventWaitHandle.OpenExisting(ShowEventName);
                ev.Set();
            }
            catch (Exception)
            {
                // the first copy is still starting; nothing more to do
            }
            _mutex.Dispose();
            _mutex = null;
            Shutdown(0);
            return;
        }

        DispatcherUnhandledException += OnUnhandled;
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
            Debug.WriteLine("[ZIGMon Notifier] fatal: " + (args.ExceptionObject as Exception)?.GetType().Name);

        bool autostart = e.Args.Any(a => string.Equals(a, "--autostart", StringComparison.OrdinalIgnoreCase));
        _controller = new AppController(Dispatcher);
        _controller.ExitRequested += ExitApp;
        _controller.Start();

        _showEvent = new EventWaitHandle(false, EventResetMode.AutoReset, ShowEventName);
        _showWait = ThreadPool.RegisterWaitForSingleObject(_showEvent,
            (_, _) => Dispatcher.BeginInvoke(() => _controller?.ShowMain()), null, Timeout.Infinite, false);

        if (!_controller.Settings.HasConnection && !autostart)
            _controller.ShowConnection();

        CleanUpAfterUpdate(updatedFrom);
    }

    private static string? ArgAfter(string[] args, string name)
    {
        int i = Array.FindIndex(args, a => string.Equals(a, name, StringComparison.OrdinalIgnoreCase));
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : i >= 0 ? "" : null;
    }

    /// <summary>
    /// The old exe (ZigmonNotifier.exe.old) goes - a few tries, as the old process
    /// may take a moment to end after letting go of the lock - and, after an
    /// update, a card says so.
    /// </summary>
    private void CleanUpAfterUpdate(string? updatedFrom)
    {
        string? exe = SelfUpdate.ExePath;
        if (exe is not null)
        {
            var installer = new UpdateInstaller(RealFileSystem.Instance);
            ThreadPool.QueueUserWorkItem(_ =>
            {
                for (int i = 0; i < 40; i++)
                {
                    if (installer.CleanUp(exe)) return;
                    Thread.Sleep(500);
                }
                Debug.WriteLine("[ZIGMon Notifier] the old exe could not be removed");
            });
        }

        if (updatedFrom is null) return;
        string? from = AppVersions.TryParse(updatedFrom, out var v) ? AppVersions.Format(v) : null;
        if (from is not null && v >= AppVersions.Running) return; // not an update to this version
        Dispatcher.InvokeAsync(() => NoticeWindow.ShowUpdated(AppInfo.Version, from), DispatcherPriority.ApplicationIdle);
    }

    private void OnUnhandled(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        // keep running: a notifier that vanishes is worse than one small glitch
        Debug.WriteLine("[ZIGMon Notifier] unhandled: " + e.Exception.GetType().Name);
        e.Handled = true;
    }

    private void ExitApp()
    {
        _controller?.Dispose();
        _controller = null;
        Shutdown(0);
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _showWait?.Unregister(null);
        _showEvent?.Dispose();
        _controller?.Dispose();
        if (_mutex is not null)
        {
            try { _mutex.ReleaseMutex(); } catch (ApplicationException) { }
            _mutex.Dispose();
        }
        base.OnExit(e);
    }
}
