using System;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>One alert card. Shown on top without taking the keyboard (unless the user asked for that).</summary>
public partial class AlertWindow : Window
{
    private readonly AppController _app;
    private readonly bool _test;
    private readonly DispatcherTimer _clock;
    private TriggerEvent _event;
    private DateTimeOffset _shownAt;
    private int _count = 1;
    private bool _shown;

    internal event Action? HeightSettled;

    public string Device => _event.Device;
    public bool IsClosing { get; private set; }

    /// <summary>The scale of the monitor the card goes to (its pixels per unit).</summary>
    internal double TargetScale { get; init; } = 1;

    /// <summary>The height to stack by: the real one once laid out.</summary>
    public double ExpectedHeight => ActualHeight > 0 ? ActualHeight : 156;

    internal AlertWindow(AppController app, TriggerEvent e, bool test)
    {
        InitializeComponent();
        Ui.ApplyIcon(this);
        _app = app;
        _test = test;
        _event = e;
        _shownAt = DateTimeOffset.UtcNow;
        Fill();

        _clock = new DispatcherTimer(DispatcherPriority.Background) { Interval = TimeSpan.FromSeconds(1) };
        _clock.Tick += (_, _) => Tick();
        SizeChanged += (_, args) => { if (args.HeightChanged) HeightSettled?.Invoke(); };
        KeyDown += (_, args) =>
        {
            if (args.Key == Key.Escape) { Sounds.Stop(); Dismiss(); args.Handled = true; }
        };
        Closed += (_, _) => _clock.Stop();
        // put the window on its monitor in pixels before it shows, so it takes that monitor's scale
        SourceInitialized += (_, _) => Native.MoveWindow(this, (int)Math.Round(Left * TargetScale), (int)Math.Round(Top * TargetScale));
        MouseEnter += (_, _) => _shownAt = DateTimeOffset.UtcNow; // reading it: the auto-close waits
    }

    internal void Update(TriggerEvent e)
    {
        _event = e;
        _count++;
        _shownAt = DateTimeOffset.UtcNow;
        Fill();
    }

    private void Fill()
    {
        var style = KindStyle.For(_event.Kind);
        // a sensor going quiet again is good news: green; else the kind's own colour
        bool clearing = _event.Kind != SensorKinds.Button && _event.Active == false;
        string accent = clearing ? Palette.Ok : style.Accent;

        Stripe.Background = Ui.Brush(accent);
        Tile.Background = Ui.Brush(accent, 0x1F);
        Tile.BorderBrush = Ui.Brush(accent, 0x59);
        Pulse.BorderBrush = Ui.Brush(accent);
        KindIcon.Stroke = Ui.Brush(accent);
        KindIcon.Data = Ui.Geometry(style.IconPath);
        Headline.Foreground = Ui.Brush(accent);

        // everything below is plain text from the server, cleaned by the core; never markup
        Headline.Text = _test ? "Test alert" : style.Headline(_event.What, _event.Active);
        KindLabel.Text = "· " + style.Label;
        SensorName.Text = _event.Name;
        CountText.Text = "×" + _count.ToString(System.Globalization.CultureInfo.InvariantCulture);
        CountBadge.Visibility = _count > 1 ? Visibility.Visible : Visibility.Collapsed;
        Title = "ZIGMon: " + _event.Name + " – " + Headline.Text;
        MuteButton.IsEnabled = !_test;
        OpenButton.IsEnabled = _app.Address is not null;
        Tick();
    }

    private void Tick()
    {
        var now = DateTimeOffset.UtcNow;
        string when = TimeText.Ago(_event.At, now);
        if (_test && _event.Kind == SensorKinds.Test)
            Meta.Text = (string.IsNullOrEmpty(_event.What) ? "Sent from ZIGMon" : _event.What) + " · " + when;
        else if (_test) Meta.Text = "This is how alerts will look · " + when;
        else Meta.Text = string.IsNullOrEmpty(_event.Room) ? when : _event.Room + " · " + when;

        int after = _app.Settings.AutoCloseSeconds;
        if (after > 0 && !IsMouseOver && now - _shownAt > TimeSpan.FromSeconds(after)) Dismiss();
    }

    // ---- showing, moving, leaving --------------------------------------------------------

    internal void Appear(double left, double top, bool takeFocus)
    {
        Left = left + 56;
        Top = top;
        ShowActivated = takeFocus;
        Show();
        Left = left + 56; // again, in the units of the monitor it is now on
        Top = top;
        _shown = true;
        _clock.Start();

        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        BeginAnimation(LeftProperty, new DoubleAnimation(left, TimeSpan.FromMilliseconds(320)) { EasingFunction = ease });
        Root.BeginAnimation(OpacityProperty, new DoubleAnimation(1, TimeSpan.FromMilliseconds(220)));
        Attention(takeFocus);
    }

    internal void MoveTo(double left, double top)
    {
        if (!_shown)
        {
            Left = left;
            Top = top;
            return;
        }
        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        if (Math.Abs(Top - top) > 0.5)
            BeginAnimation(TopProperty, new DoubleAnimation(top, TimeSpan.FromMilliseconds(260)) { EasingFunction = ease });
    }

    /// <summary>Flash the taskbar button, pulse the ring, and take the focus when that is wanted.</summary>
    internal void Attention(bool takeFocus)
    {
        Native.Flash(this);
        var grow = new DoubleAnimation(1, 1.35, TimeSpan.FromMilliseconds(900)) { EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut } };
        var fade = new DoubleAnimation(0.9, 0, TimeSpan.FromMilliseconds(900));
        grow.RepeatBehavior = new RepeatBehavior(2);
        fade.RepeatBehavior = new RepeatBehavior(2);
        PulseScale.BeginAnimation(ScaleTransform.ScaleXProperty, grow);
        PulseScale.BeginAnimation(ScaleTransform.ScaleYProperty, grow);
        Pulse.BeginAnimation(OpacityProperty, fade);
        if (takeFocus)
        {
            Activate();
            Topmost = true;
        }
    }

    internal void Dismiss()
    {
        if (IsClosing) return;
        IsClosing = true;
        _clock.Stop();
        var fade = new DoubleAnimation(0, TimeSpan.FromMilliseconds(170));
        fade.Completed += (_, _) => Close();
        BeginAnimation(LeftProperty, new DoubleAnimation(Left + 40, TimeSpan.FromMilliseconds(170)));
        Root.BeginAnimation(OpacityProperty, fade);
    }

    private void OnDismiss(object sender, RoutedEventArgs e)
    {
        Sounds.Stop();
        Dismiss();
    }

    private void OnMute(object sender, RoutedEventArgs e)
    {
        Sounds.Stop();
        if (!_test) _app.Mute(_event.Device, TimeSpan.FromHours(1));
        Dismiss();
    }

    private void OnOpen(object sender, RoutedEventArgs e)
    {
        Sounds.Stop();
        _app.OpenDashboard();
        Dismiss();
    }
}
