using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>The right-click menu of the tray icon: a small dark window at the cursor that closes when it loses focus.</summary>
public partial class TrayMenu : Window
{
    private readonly AppController _app;
    private Native.POINT _cursor;
    private bool _closing;

    internal TrayMenu(AppController app)
    {
        InitializeComponent();
        _app = app;
        Mark.Data = Ui.Geometry(Icons.Radar);
        VersionNote.Text = "v" + AppInfo.Version;

        SourceInitialized += (_, _) =>
        {
            Native.MakeToolWindow(this);
            Place();
        };
        Loaded += (_, _) =>
        {
            Place();
            var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
            Root.BeginAnimation(OpacityProperty, new DoubleAnimation(1, TimeSpan.FromMilliseconds(130)));
            Slide.BeginAnimation(System.Windows.Media.TranslateTransform.YProperty,
                new DoubleAnimation(0, TimeSpan.FromMilliseconds(180)) { EasingFunction = ease });
        };
        DpiChanged += (_, _) => Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(Place));
        SizeChanged += (_, _) => Place();
        Deactivated += (_, _) => SafeClose();
        PreviewKeyDown += OnKey;
        _app.StatusChanged += Refresh;
        Closed += (_, _) => _app.StatusChanged -= Refresh;
        Refresh();
    }

    internal void ShowAtCursor()
    {
        _cursor = Native.CursorPosition();
        Show();
        Activate();
        Native.SetForegroundWindow(new System.Windows.Interop.WindowInteropHelper(this).Handle);
    }

    /// <summary>The card's corner at the cursor, opening up and to the left, kept inside the cursor's monitor.</summary>
    private void Place()
    {
        double w = ActualWidth, h = ActualHeight;
        if (w <= 0 || h <= 0)
        {
            if (Content is not FrameworkElement c) return;
            c.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
            w = c.DesiredSize.Width;
            h = c.DesiredSize.Height;
        }
        var (work, scale) = Native.WorkAreaAt(_cursor);
        int wpx = (int)Math.Ceiling(w * scale), hpx = (int)Math.Ceiling(h * scale);
        int m = (int)Math.Round(Root.Margin.Left * scale); // the see-through edge round the card

        int x = _cursor.X - wpx + m;
        if (x < work.Left - m) x = _cursor.X - m;
        int y = _cursor.Y - hpx + m;
        if (y < work.Top - m) y = _cursor.Y - m;
        x = Math.Clamp(x, work.Left - m, Math.Max(work.Left - m, work.Right - wpx + m));
        y = Math.Clamp(y, work.Top - m, Math.Max(work.Top - m, work.Bottom - hpx + m));
        Native.MoveWindow(this, x, y);
    }

    private void Refresh()
    {
        var s = _app.Status;
        string house = _app.Settings.House ?? "";
        HouseText.Text = house.Length > 0 ? house : _app.Address?.Host ?? "Not connected yet";

        StatusDot.Fill = _app.Dot switch
        {
            Core.StatusDot.Green => Ui.Brush(Palette.Ok),
            Core.StatusDot.Red => Ui.Brush(Palette.Crit),
            Core.StatusDot.Amber => Ui.Brush(Palette.Warn),
            _ => Ui.Brush(Palette.TextDim),
        };
        StatusText.Text = _app.ShortStatus;
        bool problem = s.State is ConnectionState.Retrying or ConnectionState.NeedsAttention;
        ProblemText.Text = problem ? s.Message + (s.RetryIn is { } r ? " (again in " + (int)Math.Ceiling(r.TotalSeconds) + " s)" : "") : "";
        ProblemText.Visibility = problem ? Visibility.Visible : Visibility.Collapsed;

        int watched = _app.Settings.Watched.Count;
        SensorsNote.Text = _app.Sensors.Count > 0 ? watched + " of " + _app.Sensors.Count : watched > 0 ? watched + " watched" : "";
        SensorsRow.IsEnabled = _app.Settings.HasConnection;

        bool paused = _app.IsPaused;
        PauseNote.Text = paused ? _app.PauseText : "";
        PauseGlyph.Foreground = paused ? Ui.Brush(Palette.Warn) : Ui.Brush(Palette.TextDim);
        ResumeRow.Visibility = paused ? Visibility.Visible : Visibility.Collapsed;

        SoundToggle.IsChecked = _app.Settings.Sound;
        FrontToggle.IsChecked = _app.Settings.BringToFront;
        AutoCloseToggle.IsChecked = _app.Settings.AutoClose;
        StartToggle.IsChecked = Autostart.IsEnabled;
        OpenRow.IsEnabled = _app.Address is not null;
        RefreshUpdates();
    }

    private void RefreshUpdates()
    {
        var u = _app.Update;
        AutoUpdateToggle.IsChecked = _app.AutoUpdate;
        bool offer = u.State == UpdateState.Available && !_app.AutoUpdate;
        UpdateRowText.Text = offer ? "Install version " + u.Version : "Check for updates now";
        UpdateGlyph.Text = offer ? "\uE896" : "\uE777";
        UpdateGlyph.Foreground = offer ? Ui.Brush(Palette.Info) : Ui.Brush(Palette.TextDim);
        UpdateRow.IsEnabled = _app.CanCheckForUpdates;
        UpdateRow.ToolTip = _app.Settings.HasConnection ? null : "Connect to ZIGMon first - updates come from it.";

        UpdateStatusText.Text = u.State == UpdateState.Idle ? "Version " + AppInfo.Version : u.Text;
        UpdateDot.Fill = u.State switch
        {
            UpdateState.UpToDate or UpdateState.NotOffered => Ui.Brush(Palette.Ok),
            UpdateState.Available or UpdateState.Checking or UpdateState.Updating or UpdateState.Restarting => Ui.Brush(Palette.Info),
            UpdateState.Failed => Ui.Brush(Palette.Crit),
            _ => Ui.Brush(Palette.TextMuted),
        };
        UpdateStatusText.Foreground = u.State == UpdateState.Failed ? Ui.Brush(Palette.Text) : Ui.Brush(Palette.TextDim);
    }

    private void OnKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            SafeClose();
            e.Handled = true;
        }
        else if ((e.Key == Key.Down || e.Key == Key.Up) && Keyboard.FocusedElement is not System.Windows.Controls.Primitives.ButtonBase)
        {
            (SensorsRow.IsEnabled ? SensorsRow : ConnectionRow).Focus();
            e.Handled = true;
        }
    }

    private void SafeClose()
    {
        if (_closing) return;
        _closing = true;
        Dispatcher.BeginInvoke(new Action(Close));
    }

    /// <summary>Close the menu, then do the thing (so a window that opens gets the focus).</summary>
    private void Then(Action a)
    {
        SafeClose();
        Dispatcher.BeginInvoke(DispatcherPriority.Background, a);
    }

    private void OnSensors(object sender, RoutedEventArgs e) => Then(_app.ShowSensors);
    private void OnConnection(object sender, RoutedEventArgs e) => Then(_app.ShowConnection);
    private void OnTest(object sender, RoutedEventArgs e) => Then(_app.TestAlert);
    private void OnOpen(object sender, RoutedEventArgs e) => Then(_app.OpenDashboard);
    private void OnExit(object sender, RoutedEventArgs e) => Then(_app.RequestExit);

    private void OnPauseRow(object sender, RoutedEventArgs e)
    {
        bool open = PausePanel.Visibility != Visibility.Visible;
        PausePanel.Visibility = open ? Visibility.Visible : Visibility.Collapsed;
        ChevronTurn.BeginAnimation(System.Windows.Media.RotateTransform.AngleProperty,
            new DoubleAnimation(open ? 180 : 0, TimeSpan.FromMilliseconds(150)));
    }

    private void OnPause15(object sender, RoutedEventArgs e) => Then(() => _app.Pause(TimeSpan.FromMinutes(15)));
    private void OnPause60(object sender, RoutedEventArgs e) => Then(() => _app.Pause(TimeSpan.FromHours(1)));
    private void OnPauseForever(object sender, RoutedEventArgs e) => Then(() => _app.Pause(null));
    private void OnResume(object sender, RoutedEventArgs e) => Then(_app.Resume);

    private void OnSound(object sender, RoutedEventArgs e)
    {
        _app.Settings.Sound = SoundToggle.IsChecked == true;
        _app.Save();
        if (_app.Settings.Sound) Sounds.Chime();
    }

    private void OnFront(object sender, RoutedEventArgs e)
    {
        _app.Settings.BringToFront = FrontToggle.IsChecked == true;
        _app.Save();
    }

    private void OnAutoClose(object sender, RoutedEventArgs e)
    {
        _app.Settings.AutoClose = AutoCloseToggle.IsChecked == true;
        _app.Save();
    }

    private void OnAutoUpdate(object sender, RoutedEventArgs e) => _app.SetAutoUpdate(AutoUpdateToggle.IsChecked == true);

    /// <summary>Stays open: the status line below shows how the check goes.</summary>
    private void OnUpdateRow(object sender, RoutedEventArgs e)
    {
        if (_app.Update.State == UpdateState.Available && !_app.AutoUpdate) _app.InstallUpdateNow();
        else _app.CheckForUpdatesNow();
        RefreshUpdates();
    }

    private void OnStart(object sender, RoutedEventArgs e)
    {
        Autostart.Set(StartToggle.IsChecked == true);
        StartToggle.IsChecked = Autostart.IsEnabled; // what the registry really says
    }
}
