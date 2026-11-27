using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Threading;
using ZigmonNotifier.Core;
using ZigmonNotifier.Views;

namespace ZigmonNotifier;

/// <summary>
/// The app's one owner of state: settings, the long-poll service, the tray icon,
/// the alerts and the windows. Everything here runs on the UI thread; the
/// service's events are passed over with the dispatcher.
/// </summary>
internal sealed class AppController : IDisposable
{
    private readonly Dispatcher _ui;
    private readonly SettingsStore _store;
    private readonly ISecretProtector _protector = new DpapiProtector();
    private readonly TrayIcon _tray;
    private readonly DispatcherTimer _tick;
    private CancellationTokenSource? _cts;
    private NotifierService? _service;
    private ConnectionWindow? _connectionWindow;
    private SensorsWindow? _sensorsWindow;
    private TrayMenu? _menu;
    private bool _disposed;

    public NotifierSettings Settings { get; }
    public AlertManager Alerts { get; }
    public ConnectionStatus Status { get; private set; } = ConnectionStatus.NotConfigured;
    public IReadOnlyList<SensorInfo> Sensors { get; private set; } = Array.Empty<SensorInfo>();

    public event Action? StatusChanged;
    public event Action? SensorsChanged;
    public event Action? ExitRequested;

    public AppController(Dispatcher ui)
    {
        _ui = ui;
        _store = new SettingsStore(SettingsStore.DefaultPath());
        Settings = _store.Load(DateTimeOffset.UtcNow);
        Alerts = new AlertManager(this);
        _tray = new TrayIcon();
        _tray.MenuRequested += ShowMenu;
        _tray.DoubleClicked += ShowMain;
        _tick = new DispatcherTimer(DispatcherPriority.Background, ui) { Interval = TimeSpan.FromSeconds(20) };
        _tick.Tick += (_, _) => Housekeeping();
        _tick.Start();
        UpdateTray();
    }

    public static void Log(string line) => Debug.WriteLine("[ZIGMon Notifier] " + line); // never given the key

    public ServerAddress? Address => ServerAddress.TryParse(Settings.ServerUrl, out var a, out _) ? a : null;

    // ---- the connection ------------------------------------------------------------------

    public void Start()
    {
        Stop();
        Sensors = Array.Empty<SensorInfo>();
        SensorsChanged?.Invoke();
        if (!Settings.HasConnection || Address is not { } address)
        {
            SetStatus(ConnectionStatus.NotConfigured);
            return;
        }
        var key = KeyVault.TryLoad(Settings, _protector);
        if (key is null)
        {
            SetStatus(new ConnectionStatus(ConnectionState.NeedsAttention,
                "The saved key cannot be read on this Windows account. Enter it again in Connection."));
            return;
        }

        var client = ZigmonClient.Create(address, key, Settings.GetPin());
        var service = new NotifierService(client, Log);
        service.StatusChanged += s => _ui.BeginInvoke(() => { if (ReferenceEquals(service, _service)) SetStatus(s); });
        service.SensorsChanged += list => _ui.BeginInvoke(() =>
        {
            if (!ReferenceEquals(service, _service)) return;
            Sensors = list;
            RememberNames(list);
            SensorsChanged?.Invoke();
        });
        service.EventsArrived += list => _ui.BeginInvoke(() => { if (ReferenceEquals(service, _service)) OnEvents(list); });

        var cts = new CancellationTokenSource();
        _cts = cts;
        _service = service;
        SetStatus(new ConnectionStatus(ConnectionState.Connecting, "Connecting…"));
        Task.Run(() => service.RunAsync(cts.Token)).ContinueWith(_ =>
        {
            client.Dispose();
            cts.Dispose();
        }, TaskScheduler.Default);
    }

    public void Stop()
    {
        var cts = _cts;
        _cts = null;
        _service = null;
        try { cts?.Cancel(); } catch (ObjectDisposedException) { }
    }

    private void SetStatus(ConnectionStatus s)
    {
        Status = s;
        if (s.Hello is { } h && h.House.Length > 0 && h.House != Settings.House)
        {
            Settings.House = h.House;
            Save();
        }
        UpdateTray();
        StatusChanged?.Invoke();
    }

    private void RememberNames(IReadOnlyList<SensorInfo> list)
    {
        bool changed = false;
        foreach (var w in Settings.Watched)
        {
            var s = list.FirstOrDefault(x => x.Id == w.Id);
            if (s is not null && s.Name != w.Name) { w.Name = s.Name; changed = true; }
        }
        if (changed) Save();
    }

    private void OnEvents(IReadOnlyList<TriggerEvent> events)
    {
        var now = DateTimeOffset.UtcNow;
        foreach (var e in events)
        {
            var d = AlertFilter.Decide(Settings, e, now);
            if (d == AlertDecision.Alert) Alerts.Show(e, test: false);
        }
    }

    // ---- settings ------------------------------------------------------------------------

    public void Save()
    {
        try
        {
            _store.Save(Settings);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Log("settings not saved: " + ex.GetType().Name);
        }
    }

    public bool IsWatched(string id) => Settings.FindWatched(id) is not null;

    public void SetWatched(SensorInfo s, bool watched)
    {
        var w = Settings.FindWatched(s.Id);
        if (watched && w is null) Settings.Watched.Add(new WatchedSensor { Id = s.Id, Name = s.Name });
        else if (!watched && w is not null) Settings.Watched.Remove(w);
        Save();
        UpdateTray();
        StatusChanged?.Invoke();
    }

    public void SetAlsoWhenClears(string id, bool on)
    {
        var w = Settings.FindWatched(id);
        if (w is null || w.AlsoWhenClears == on) return;
        w.AlsoWhenClears = on;
        Save();
    }

    public void ForgetWatched(string id)
    {
        var w = Settings.FindWatched(id);
        if (w is null) return;
        Settings.Watched.Remove(w);
        Save();
        UpdateTray();
        StatusChanged?.Invoke();
    }

    public void Mute(string id, TimeSpan howLong)
    {
        Settings.Mutes[id] = DateTimeOffset.UtcNow + howLong;
        Save();
    }

    public void Pause(TimeSpan? howLong)
    {
        if (howLong is null)
        {
            Settings.PausedUntilResumed = true;
            Settings.PausedUntil = null;
        }
        else
        {
            Settings.PausedUntilResumed = false;
            Settings.PausedUntil = DateTimeOffset.UtcNow + howLong.Value;
        }
        Save();
        UpdateTray();
        StatusChanged?.Invoke();
    }

    public void Resume()
    {
        Settings.PausedUntilResumed = false;
        Settings.PausedUntil = null;
        Save();
        UpdateTray();
        StatusChanged?.Invoke();
    }

    public bool IsPaused => Settings.IsPaused(DateTimeOffset.UtcNow);

    public string PauseText => TimeText.Until(Settings.PausedUntil, Settings.PausedUntilResumed);

    /// <summary>Called by the Connection window once a test went well.</summary>
    public void ApplyConnection(ServerAddress address, NotifierKey? newKey, CertificatePin? pin, string house)
    {
        Settings.ServerUrl = address.Base;
        if (newKey is not null) KeyVault.Store(Settings, newKey, _protector);
        Settings.SetPin(pin);
        Settings.House = SafeText.Clean(house, ProtocolParser.NameMax);
        Save();
        Start();
    }

    public void RemoveConnection()
    {
        Stop();
        Settings.ServerUrl = null;
        KeyVault.Forget(Settings);
        Settings.SetPin(null);
        Settings.House = null;
        Save();
        Start();
    }

    public NotifierKey? SavedKey() => KeyVault.TryLoad(Settings, _protector);

    private void Housekeeping()
    {
        bool wasPaused = Settings.PausedUntil is not null;
        int mutes = Settings.Mutes.Count;
        Settings.Sanitize(DateTimeOffset.UtcNow);
        if (wasPaused && Settings.PausedUntil is null || mutes != Settings.Mutes.Count)
        {
            Save();
            UpdateTray();
            StatusChanged?.Invoke();
        }
    }

    // ---- the tray ------------------------------------------------------------------------

    public StatusDot Dot
    {
        get
        {
            switch (Status.State)
            {
                case ConnectionState.Retrying:
                case ConnectionState.NeedsAttention:
                    return StatusDot.Red;
                case ConnectionState.Connected:
                    return IsPaused ? StatusDot.Amber : StatusDot.Green;
                default:
                    return IsPaused ? StatusDot.Amber : StatusDot.Grey;
            }
        }
    }

    public string ShortStatus
    {
        get
        {
            if (Status.State == ConnectionState.Connected)
            {
                if (IsPaused) return "Alerts paused " + PauseText;
                int n = Settings.Watched.Count;
                return n == 0 ? "Connected · no sensors watched yet" : "Connected · watching " + n;
            }
            return Status.State switch
            {
                ConnectionState.NotConfigured => "Not set up yet",
                ConnectionState.Connecting => "Connecting…",
                ConnectionState.Retrying => Status.Error == ZigmonErrorKind.RateLimited
                    ? "Too many tries – waiting"
                    : "Cannot reach ZIGMon – trying again",
                ConnectionState.NeedsAttention => Status.Error switch
                {
                    ZigmonErrorKind.Unauthorized => "Key not accepted",
                    ZigmonErrorKind.Certificate => "Certificate not trusted",
                    _ => "Needs your attention",
                },
                _ => "Stopped",
            };
        }
    }

    private void UpdateTray()
    {
        string house = string.IsNullOrEmpty(Settings.House) ? "" : " – " + Settings.House;
        _tray.SetState(Dot, "ZIGMon Notifier" + house + "\n" + ShortStatus);
    }

    // ---- windows -------------------------------------------------------------------------

    public void ShowMenu()
    {
        if (_menu is not null) { _menu.Close(); return; }
        var menu = new TrayMenu(this);
        menu.Closed += (_, _) => { if (ReferenceEquals(_menu, menu)) _menu = null; };
        _menu = menu;
        menu.ShowAtCursor();
    }

    /// <summary>What a double-click (or a second start of the app) opens.</summary>
    public void ShowMain()
    {
        if (!Settings.HasConnection) ShowConnection();
        else ShowSensors();
    }

    public void ShowSensors()
    {
        if (_sensorsWindow is null)
        {
            _sensorsWindow = new SensorsWindow(this);
            _sensorsWindow.Closed += (_, _) => _sensorsWindow = null;
            _sensorsWindow.Show();
        }
        Bring(_sensorsWindow);
    }

    public void ShowConnection()
    {
        if (_connectionWindow is null)
        {
            _connectionWindow = new ConnectionWindow(this);
            _connectionWindow.Closed += (_, _) => _connectionWindow = null;
            _connectionWindow.Show();
        }
        Bring(_connectionWindow);
    }

    private static void Bring(System.Windows.Window w)
    {
        if (w.WindowState == System.Windows.WindowState.Minimized) w.WindowState = System.Windows.WindowState.Normal;
        w.Activate();
        w.Topmost = true;  // the classic nudge past the foreground lock
        w.Topmost = false;
        w.Focus();
    }

    public void OpenDashboard() => Browser.OpenDashboard(Settings.ServerUrl);

    public void TestAlert()
    {
        var first = Settings.Watched.FirstOrDefault();
        var s = first is null ? null : Sensors.FirstOrDefault(x => x.Id == first.Id);
        string name = s?.Name ?? (first?.Name is { Length: > 0 } fn ? fn : "Hallway motion sensor");
        var e = new TriggerEvent(0, DateTimeOffset.UtcNow, "test-alert", name,
            s?.Room ?? "Test", s?.Kind ?? SensorKinds.Motion, "test", true, "test alert");
        Alerts.Show(e, test: true);
    }

    public void RequestExit() => ExitRequested?.Invoke();

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Stop();
        _tick.Stop();
        Alerts.CloseAll();
        _menu?.Close();
        _connectionWindow?.Close();
        _sensorsWindow?.Close();
        _tray.Dispose();
    }
}
