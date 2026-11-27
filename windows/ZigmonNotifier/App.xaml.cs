using System;
using System.Diagnostics;
using System.Linq;
using System.Threading;
using System.Windows;
using System.Windows.Threading;

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

        // one copy per Windows session: a second start just asks the first to show itself
        _mutex = new Mutex(true, MutexName, out bool first);
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
