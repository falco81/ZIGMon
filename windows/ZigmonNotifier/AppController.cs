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
    private readonly DispatcherTimer _updateTimer;
    private readonly UpdateManager _updates;
    private CancellationTokenSource? _cts;
    private NotifierService? _service;
    private ZigmonClient? _client;
    private HelloInfo? _lastHello;
    private DateTimeOffset _lastAutoCheck = DateTimeOffset.MinValue;
    private ConnectionWindow? _connectionWindow;
    private SensorsWindow? _sensorsWindow;
    private AlertSettingsWindow? _alertSettingsWindow;
    private MessagesWindow? _messagesWindow;
    private SmsPermissions _sms = SmsPermissions.None;
    /// <summary>Thread key → SMS that came in there since it was last looked at.</summary>
    private readonly Dictionary<string, int> _unread = new(StringComparer.Ordinal);
    private TrayMenu? _menu;
    private bool _disposed;

    public NotifierSettings Settings { get; }
    public AlertManager Alerts { get; }
    public ConnectionStatus Status { get; private set; } = ConnectionStatus.NotConfigured;
    public IReadOnlyList<SensorInfo> Sensors { get; private set; } = Array.Empty<SensorInfo>();
    public UpdateStatus Update => _updates.Status;

    public event Action? StatusChanged;
    public event Action? SensorsChanged;
    public event Action? ExitRequested;
    /// <summary>(1.4.0) The SMS list, the contacts, the unread ones or the SMS permissions changed.</summary>
    public event Action? SmsChanged;

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

        _updates = new UpdateManager(AppVersions.Running, ReleaseKeys.Embedded, new UpdateInstaller(RealFileSystem.Instance),
            SelfUpdate.ExePath, UpdateInstaller.DefaultStagingDir(), SelfUpdate.Start, Log);
        _updates.StatusChanged += _ => _ui.BeginInvoke(() => StatusChanged?.Invoke());
        _updateTimer = new DispatcherTimer(DispatcherPriority.Background, ui) { Interval = UpdateManager.Period };
        _updateTimer.Tick += (_, _) => PeriodicUpdateLook();
        _updateTimer.Start();
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
        _client = client;
        _lastHello = null;
        SetStatus(new ConnectionStatus(ConnectionState.Connecting, "Connecting…"));
        Task.Run(() => service.RunAsync(cts.Token)).ContinueWith(_ =>
        {
            client.Dispose();
            cts.Dispose();
        }, TaskScheduler.Default);
    }

    public void Stop()
    {
        SmsMessages = Array.Empty<SmsMessage>();
        Contacts = ContactBook.Empty;
        _unread.Clear();
        _sms = SmsPermissions.None;
        var cts = _cts;
        _cts = null;
        _service = null;
        _client = null;
        try { cts?.Cancel(); } catch (ObjectDisposedException) { }
    }

    private void SetStatus(ConnectionStatus s)
    {
        Status = s;
        if (s.State == ConnectionState.Connected && s.Hello is { } hello && !ReferenceEquals(hello, _lastHello))
        {
            _lastHello = hello;
            OnHello(hello);
            SetSmsPermissions(hello.Sms, fresh: true);
        }
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
            if (e.Kind == SensorKinds.Sms)
            {
                if (e.Sms is { } m) OnSms(m);
                continue;
            }
            if (e.Kind == SensorKinds.Deck)
            {
                if (e.Deck is { } ask) OnDeck(ask);
                continue;
            }
            var d = AlertFilter.Decide(Settings, e, now);
            if (d == AlertDecision.Alert) Alerts.Show(e, test: e.Kind == SensorKinds.Test);
        }
    }

    // ---- SMS (1.4.0) -----------------------------------------------------------------------

    /// <summary>What this key may do with SMS, as the last hello said (nothing from an older ZIGMon).</summary>
    public SmsPermissions Sms => _sms;
    public IReadOnlyList<SmsMessage> SmsMessages { get; private set; } = Array.Empty<SmsMessage>();
    public ContactBook Contacts { get; private set; } = ContactBook.Empty;
    /// <summary>Why the SMS list could not be read last time, or null.</summary>
    public string? SmsProblem { get; private set; }
    public DateTimeOffset? SmsReadAt { get; private set; }
    /// <summary>SMS that came in since they were last looked at.</summary>
    public int UnreadSms => _unread.Values.Sum();

    public bool IsUnread(string threadKey) => _unread.ContainsKey(threadKey);

    public void MarkRead(string threadKey)
    {
        if (!_unread.Remove(threadKey)) return;
        SmsChanged?.Invoke();
        StatusChanged?.Invoke();
    }

    private void SetSmsPermissions(SmsPermissions p, bool fresh)
    {
        bool changed = p != _sms;
        _sms = p;
        if (!p.Read) SmsMessages = Array.Empty<SmsMessage>();
        if (!p.Contacts) Contacts = ContactBook.Empty;
        if (changed)
        {
            SmsChanged?.Invoke();
            StatusChanged?.Invoke();
        }
        if (fresh || changed)
        {
            _ = RefreshSmsAsync();
            _ = RefreshContactsAsync();
        }
    }

    /// <summary>Reads the latest SMS again (when the key may read them). Never logs what they say.</summary>
    public async Task RefreshSmsAsync()
    {
        var client = _client;
        if (client is null || !_sms.Read) return;
        try
        {
            var list = await client.GetSmsAsync(100, CancellationToken.None);
            if (!ReferenceEquals(client, _client)) return;
            // what was just sent and is not in ZIGMon's log yet stays shown for a while
            var now = DateTimeOffset.UtcNow;
            var pending = SmsMessages.Where(m => m.Id.StartsWith("local-", StringComparison.Ordinal) && now - m.At < TimeSpan.FromMinutes(2)
                && !list.Any(x => !x.Incoming && x.Text == m.Text && SmsNumbers.Key(x.Number) == SmsNumbers.Key(m.Number))).ToList();
            SmsMessages = pending.Concat(list).OrderByDescending(m => m.At).ToList();
            SmsProblem = null;
            SmsReadAt = DateTimeOffset.UtcNow;
        }
        catch (ZigmonException ex)
        {
            SmsProblem = "Messages could not be read: " + ex.Message;
            Log("sms list: " + ex.Kind);
        }
        catch (Exception ex)
        {
            SmsProblem = "Messages could not be read just now.";
            Log("sms list: " + ex.GetType().Name);
        }
        SmsChanged?.Invoke();
    }

    public async Task RefreshContactsAsync()
    {
        var client = _client;
        if (client is null || !_sms.Contacts) return;
        try
        {
            var book = await client.GetContactsAsync(CancellationToken.None);
            if (!ReferenceEquals(client, _client)) return;
            Contacts = book;
        }
        catch (Exception ex)
        {
            Log("contacts: " + (ex is ZigmonException z ? z.Kind.ToString() : ex.GetType().Name));
        }
        SmsChanged?.Invoke();
    }

    /// <summary>
    /// Sends through ZIGMon. ZIGMon's refusals (its limits, the gateway) come back as a result
    /// that is not Ok with ZIGMon's words, for the window to show. Logged: only that it was tried.
    /// </summary>
    public async Task<SmsSendResult> SendSmsAsync(IReadOnlyList<string> to, string text, string? replyTo)
    {
        var client = _client;
        if (client is null || Status.State != ConnectionState.Connected)
            return new SmsSendResult(false, 0, 0, "Not connected to ZIGMon just now – it was not sent.");
        if (!_sms.CanSend)
            return new SmsSendResult(false, 0, 0, _sms.Send ? "ZIGMon's SMS gateway is not set up." : "This computer may not send SMS.");
        SmsSendResult r;
        try
        {
            r = await client.SendSmsAsync(to, text, replyTo, CancellationToken.None);
        }
        catch (ZigmonException ex)
        {
            Log("sms send: " + ex.Kind);
            return new SmsSendResult(false, 0, 0, ex.Message);
        }
        catch (Exception ex)
        {
            Log("sms send: " + ex.GetType().Name);
            return new SmsSendResult(false, 0, 0, "Something went wrong; it may not have been sent.");
        }
        Log("sms send: " + (r.Ok ? "accepted" : "refused"));
        if (r.Ok)
        {
            // shown at once as "Sending…"; ZIGMon's own log replaces it on the next read
            string clean = SafeText.CleanMultiline(text, ProtocolParser.SmsTextMax);
            var local = new List<SmsMessage>();
            foreach (var w in to)
            {
                string number = SmsNumbers.Clean(w);
                Contact? c = null;
                if (w.StartsWith("contact:", StringComparison.Ordinal) && Contacts.Find(w["contact:".Length..]) is { } found)
                {
                    c = found;
                    number = found.Numbers[0].Number;
                }
                else if (number.Length > 0) c = Contacts.ByNumber(number);
                if (number.Length == 0) continue; // a group: ZIGMon's log has it soon enough
                local.Add(new SmsMessage("local-" + Guid.NewGuid().ToString("N"), false, number,
                    c is null ? null : new SmsContactRef(c.Id, c.Name), clean, DateTimeOffset.UtcNow, null));
            }
            SmsMessages = local.Concat(SmsMessages).ToList();
            SmsChanged?.Invoke();
            _ = RefreshSoon();
        }
        return r;
    }

    private async Task RefreshSoon()
    {
        await Task.Delay(TimeSpan.FromSeconds(2));
        await RefreshSmsAsync();
    }

    private void OnSms(SmsMessage m)
    {
        if (m.Id.Length > 0 && SmsMessages.Any(x => x.Id == m.Id)) return;
        SmsMessages = new[] { m }.Concat(SmsMessages).Take(500).ToList();
        bool looking = _messagesWindow is { IsActive: true } w && w.CurrentKey == m.ThreadKey;
        if (m.Incoming && !looking)
        {
            _unread[m.ThreadKey] = _unread.GetValueOrDefault(m.ThreadKey) + 1;
        }
        SmsChanged?.Invoke();
        StatusChanged?.Invoke();
        if (m.Incoming && Settings.ShowsSmsPopup(DateTimeOffset.UtcNow)) Alerts.ShowSms(m, asked: false);
    }

    /// <summary>A Stream Deck key asked (it was pressed on purpose: shown even while alerts are paused).</summary>
    private async void OnDeck(DeckAsk ask)
    {
        if (!Settings.DeckPopups)
        {
            Log("stream deck ask ignored (switched off)");
            return;
        }
        if (ask.What == DeckAsk.Compose)
        {
            // pressed again while Messages is up: the key closes it, nothing is sent
            if (DeckAsk.OnComposePress(_messagesWindow is { IsVisible: true }) == ComposePress.Close)
            {
                _messagesWindow!.Close();
                return;
            }
            if (!_sms.CanSend)
            {
                ShowMessages();
                return;
            }
            var to = ask.To.Select(r => Recipient.ForNumber(r.Number, r.Name.Length > 0 ? r.Name : Contacts.ByNumber(r.Number)?.Name)).ToList();
            ShowCompose(to);
            return;
        }
        // "last": the latest SMS that came in, even when it was seen already
        if (!SmsMessages.Any(m => m.Incoming)) await RefreshSmsAsync();
        var latest = SmsMessages.Where(m => m.Incoming).OrderByDescending(m => m.At).FirstOrDefault();
        if (latest is null)
        {
            ShowMessages();
            return;
        }
        // pressed again while its card is up: the key closes it (an answer being typed only comes forward)
        var card = Alerts.SmsCard(latest.ThreadKey);
        switch (DeckAsk.OnLastPress(card is not null, card is { IsReplying: true } c && c.ReplyText.Trim().Length > 0))
        {
            case LastPress.Close:
                card!.Dismiss();
                return;
            case LastPress.Focus:
                card!.Attention(true, true);
                return;
        }
        MarkRead(latest.ThreadKey);
        Alerts.ShowSms(latest, asked: true);
    }

    /// <summary>Messages, on a conversation (by its key) or on a new message; brought to the front.</summary>
    public void ShowMessages(string? threadKey = null, string? draft = null)
    {
        var w = MessagesWin();
        if (threadKey is not null) w.OpenThread(threadKey, draft);
        BringForward(w);
        if (threadKey is not null) w.FocusText();
    }

    /// <summary>A new message to these people, the cursor in the text: the Stream Deck's "compose", or "Write an SMS…".</summary>
    public void ShowCompose(IReadOnlyList<Recipient> to)
    {
        var w = MessagesWin();
        w.ShowNew(to);
        BringForward(w);
        if (to.Count > 0) w.FocusText();
    }

    private MessagesWindow MessagesWin()
    {
        if (_messagesWindow is null)
        {
            var w = new MessagesWindow(this);
            w.Closed += (_, _) => { if (ReferenceEquals(_messagesWindow, w)) _messagesWindow = null; };
            _messagesWindow = w;
            w.Show();
            _ = RefreshSmsAsync();
            _ = RefreshContactsAsync();
        }
        return _messagesWindow;
    }

    /// <summary>To the front with the keyboard, past Windows' foreground lock (a Stream Deck press is not our input).</summary>
    private static void BringForward(System.Windows.Window w)
    {
        if (w.WindowState == System.Windows.WindowState.Minimized) w.WindowState = System.Windows.WindowState.Normal;
        if (!w.IsVisible) w.Show();
        w.Activate();
        if (!Native.ForceForeground(w))
        {
            w.Topmost = true;  // at least on top, and the taskbar button flashes
            w.Topmost = false;
            Native.Flash(w);
        }
        w.Focus();
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

    /// <summary>A sensor's own sound (null = the default one).</summary>
    public void SetSound(string id, string? soundId, string? file)
    {
        var w = Settings.FindWatched(id);
        if (w is null) return;
        w.SoundId = soundId;
        w.SoundFile = soundId == AlarmSounds.FileId ? NotifierSettings.CleanSoundFile(file) : null;
        if (w.SoundId == AlarmSounds.FileId && w.SoundFile is null) w.SoundId = null;
        Save();
    }

    /// <summary>Asks for a .wav file; null when cancelled or not usable (the user is told why).</summary>
    public string? PickSoundFile()
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Choose a sound (WAV)",
            Filter = "WAV sound (*.wav)|*.wav",
            CheckFileExists = true,
            Multiselect = false,
        };
        if (dlg.ShowDialog() != true) return null;
        string path = dlg.FileName;
        string? clean = NotifierSettings.CleanSoundFile(path);
        string why = clean is null ? "Choose a .wav file." : "";
        if (clean is not null)
        {
            try
            {
                var info = new FileInfo(clean);
                if (info.Length > WavAudio.MaxFileBytes) why = "The file is larger than 20 MB.";
                else if (WavAudio.FromFile(File.ReadAllBytes(clean), 50, out string reason) is null) why = reason;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                why = "The file cannot be read.";
            }
        }
        if (why.Length > 0)
        {
            System.Windows.MessageBox.Show(why, "ZIGMon Notifier", System.Windows.MessageBoxButton.OK, System.Windows.MessageBoxImage.Warning);
            return null;
        }
        return clean;
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

    // ---- updates -------------------------------------------------------------------------

    public bool AutoUpdate => Settings.AutoUpdate;

    /// <summary>Whether "Check for updates now" can do anything (it needs the connection's client).</summary>
    public bool CanCheckForUpdates => _client is not null && !_updates.Status.IsBusy;

    public void SetAutoUpdate(bool on)
    {
        if (Settings.AutoUpdate == on) return;
        Settings.AutoUpdate = on;
        Save();
        // switched on with an update already waiting: take it now
        if (on && _updates.Status.State == UpdateState.Available) _ = RunUpdateAsync(install: true);
        StatusChanged?.Invoke();
    }

    /// <summary>From the menu: asks the server even when its hello said nothing about the app (an older ZIGMon answers "no updates").</summary>
    public void CheckForUpdatesNow() => _ = RunUpdateAsync(install: Settings.AutoUpdate);

    /// <summary>From the menu, with automatic updates off: install the update it showed.</summary>
    public void InstallUpdateNow() => _ = RunUpdateAsync(install: true);

    /// <summary>After a hello: only when the server says it has a newer app (older servers say nothing and are not asked).</summary>
    private void OnHello(HelloInfo hello)
    {
        if (!_updates.HelloOffersNewer(hello)) return;
        if (DateTimeOffset.UtcNow - _lastAutoCheck < TimeSpan.FromMinutes(30)) return; // a flapping connection is not a reason to ask again
        _ = RunUpdateAsync(install: Settings.AutoUpdate);
    }

    /// <summary>Every 6 hours: a fresh hello says whether there is something newer; then as after any hello.</summary>
    private async void PeriodicUpdateLook()
    {
        var client = _client;
        if (client is null || Status.State != ConnectionState.Connected || _updates.Status.IsBusy) return;
        try
        {
            var hello = await client.HelloAsync(CancellationToken.None);
            if (!ReferenceEquals(client, _client)) return;
            _lastAutoCheck = DateTimeOffset.MinValue;
            OnHello(hello);
            SetSmsPermissions(hello.Sms, fresh: false);
        }
        catch (Exception ex)
        {
            Log("update look: " + ex.GetType().Name); // the long poll reports connection trouble on its own
        }
    }

    private async System.Threading.Tasks.Task RunUpdateAsync(bool install)
    {
        var client = _client;
        if (client is null || _updates.Status.IsBusy) return;
        _lastAutoCheck = DateTimeOffset.UtcNow;
        UpdateStatus result;
        try
        {
            result = await _updates.CheckAsync(client, install, CancellationToken.None);
        }
        catch (Exception ex)
        {
            Log("update: " + ex.GetType().Name);
            return;
        }
        StatusChanged?.Invoke();
        // the new version is running and waits for this one to let go of the single-instance lock
        if (result.State == UpdateState.Restarting) RequestExit();
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

    public void ShowAlertSettings()
    {
        if (_alertSettingsWindow is null)
        {
            _alertSettingsWindow = new AlertSettingsWindow(this);
            _alertSettingsWindow.Closed += (_, _) => _alertSettingsWindow = null;
            _alertSettingsWindow.Show();
        }
        Bring(_alertSettingsWindow);
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
        _updateTimer.Stop();
        Alerts.CloseAll();
        _menu?.Close();
        _connectionWindow?.Close();
        _sensorsWindow?.Close();
        _alertSettingsWindow?.Close();
        _messagesWindow?.Close();
        _tray.Dispose();
    }
}
