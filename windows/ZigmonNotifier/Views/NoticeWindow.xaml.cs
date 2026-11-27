using System;
using System.Windows;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>
/// A small card in the bottom-right corner about the app itself - "Updated to
/// 1.1.0". Shown on top without taking the keyboard; goes by itself after a few
/// seconds (not while the mouse is on it).
/// </summary>
public partial class NoticeWindow : Window
{
    private static readonly TimeSpan Stay = TimeSpan.FromSeconds(9);
    private readonly DispatcherTimer _timer;
    private bool _closing;

    internal NoticeWindow(string headline, string main, string meta, string icon)
    {
        InitializeComponent();
        Ui.ApplyIcon(this);
        Headline.Text = headline;
        MainText.Text = main;
        Meta.Text = meta;
        Meta.Visibility = string.IsNullOrEmpty(meta) ? Visibility.Collapsed : Visibility.Visible;
        Glyph.Data = Ui.Geometry(icon);
        Title = "ZIGMon Notifier: " + headline + " – " + main;

        _timer = new DispatcherTimer(DispatcherPriority.Background) { Interval = Stay };
        _timer.Tick += (_, _) =>
        {
            if (IsMouseOver) return; // being read: stay
            Leave();
        };
        Closed += (_, _) => _timer.Stop();
        KeyDown += (_, e) => { if (e.Key == System.Windows.Input.Key.Escape) Leave(); };
    }

    /// <summary>Slides in at the bottom-right of the work area, over the alerts' corner.</summary>
    internal static void ShowUpdated(string version, string? from)
    {
        var w = new NoticeWindow("Updated", "ZIGMon Notifier " + version,
            (from is null ? "" : "Was " + from + " · ") + "signed by ZIGMon, installed from your server", Icons.Updated);
        w.Appear();
    }

    private void Appear()
    {
        // measure first, so the card's bottom sits on the work area's bottom
        Left = -32000;
        Top = -32000;
        Show();
        UpdateLayout();
        var work = SystemParameters.WorkArea;
        double left = work.Right - ActualWidth;
        Top = work.Bottom - ActualHeight;
        Left = left + 56;
        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        BeginAnimation(LeftProperty, new DoubleAnimation(left, TimeSpan.FromMilliseconds(320)) { EasingFunction = ease });
        Root.BeginAnimation(OpacityProperty, new DoubleAnimation(1, TimeSpan.FromMilliseconds(220)));
        _timer.Start();
    }

    private void Leave()
    {
        if (_closing) return;
        _closing = true;
        _timer.Stop();
        var fade = new DoubleAnimation(0, TimeSpan.FromMilliseconds(170));
        fade.Completed += (_, _) => Close();
        BeginAnimation(LeftProperty, new DoubleAnimation(Left + 40, TimeSpan.FromMilliseconds(170)));
        Root.BeginAnimation(OpacityProperty, fade);
    }

    private void OnClose(object sender, RoutedEventArgs e) => Leave();
}
