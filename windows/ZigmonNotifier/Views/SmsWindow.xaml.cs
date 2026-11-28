using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>
/// (1.4.0) An SMS card in the alert stack: who wrote, when, the text (scrolling when long),
/// and Reply (inline, with the character and SMS-part counter), Copy, Dismiss. Further SMS
/// from the same person join this card. Shown on top without taking the keyboard, unless the
/// user asked for it (a Stream Deck key) or chose "Bring to front".
/// </summary>
public partial class SmsWindow : Window, IStackCard
{
    private readonly AppController _app;
    private readonly DispatcherTimer _clock;
    private readonly List<SmsMessage> _messages = new();
    private DateTimeOffset _shownAt = DateTimeOffset.UtcNow;
    private bool _shown;
    private bool _sending;
    private bool _sent;

    internal event Action? HeightSettled;

    public string ThreadKey { get; }
    public bool IsClosing { get; private set; }
    public bool IsReplying => ReplyPanel.Visibility == Visibility.Visible;
    internal double TargetScale { get; init; } = 1;
    public double ExpectedHeight => ActualHeight > 0 ? ActualHeight : 230;

    private SmsMessage Latest => _messages[^1];

    internal SmsWindow(AppController app, SmsMessage first)
    {
        InitializeComponent();
        Ui.ApplyIcon(this);
        _app = app;
        ThreadKey = first.ThreadKey;
        _messages.Add(first);
        Fill();

        _clock = new DispatcherTimer(DispatcherPriority.Background) { Interval = TimeSpan.FromSeconds(1) };
        _clock.Tick += (_, _) => Tick();
        SizeChanged += (_, args) => { if (args.HeightChanged) HeightSettled?.Invoke(); };
        PreviewKeyDown += (_, args) =>
        {
            if (args.Key != Key.Escape) return;
            if (IsReplying && !_sending) CloseReply();
            else Dismiss();
            args.Handled = true;
        };
        Closed += (_, _) => _clock.Stop();
        SourceInitialized += (_, _) => Native.MoveWindow(this, (int)Math.Round(Left * TargetScale), (int)Math.Round(Top * TargetScale));
        MouseEnter += (_, _) => _shownAt = DateTimeOffset.UtcNow;
    }

    /// <summary>Another SMS from the same person: it joins this card.</summary>
    internal void Add(SmsMessage m)
    {
        if (m.Id.Length > 0 && _messages.Any(x => x.Id == m.Id)) { _shownAt = DateTimeOffset.UtcNow; return; }
        _messages.Add(m);
        _messages.Sort((a, b) => a.At.CompareTo(b.At));
        if (_messages.Count > 20) _messages.RemoveAt(0);
        _shownAt = DateTimeOffset.UtcNow;
        if (_sent) ShowFeedback(null, false); // a new message after a reply: the card is about it now
        _sent = false;
        Fill();
    }

    private void Fill()
    {
        var m = Latest;
        string accent = Avatars.Accent(ThreadKey);
        Stripe.Background = Ui.Brush(accent);
        Avatar.Fill = Ui.Brush(accent, 0x26);
        Avatar.Stroke = Ui.Brush(accent, 0x66);
        Pulse.Stroke = Ui.Brush(accent);
        Headline.Foreground = Ui.Brush(accent);
        string initials = Avatars.Initials(m.Contact?.Name);
        Initials.Text = initials;
        Initials.Foreground = Ui.Brush(accent);
        PersonGlyph.Foreground = Ui.Brush(accent);
        PersonGlyph.Visibility = initials.Length == 0 ? Visibility.Visible : Visibility.Collapsed;

        // all plain text, cleaned by the core; never markup
        WhoText.Text = m.Who;
        NumberText.Text = m.Contact is not null ? m.Number : "Not in your contacts";
        NumberText.Visibility = m.Number.Length > 0 || m.Contact is null ? Visibility.Visible : Visibility.Collapsed;
        Body.Text = m.Text.Length > 0 ? m.Text : "(an empty message)";
        Body.Foreground = m.Text.Length > 0 ? Ui.Brush(Palette.Text) : Ui.Brush(Palette.TextMuted);

        Earlier.Children.Clear();
        foreach (var e in _messages.Take(_messages.Count - 1))
        {
            Earlier.Children.Add(new TextBlock
            {
                Text = Clock(e.At), FontSize = 11, Foreground = Ui.Brush(Palette.TextMuted), Margin = new Thickness(0, 0, 0, 2),
            });
            Earlier.Children.Add(new TextBlock
            {
                Text = e.Text, FontSize = 13.5, TextWrapping = TextWrapping.Wrap, Foreground = Ui.Brush(Palette.TextDim),
                Margin = new Thickness(0, 0, 6, 10), LineHeight = 19,
            });
        }
        if (_messages.Count > 1)
            Earlier.Children.Add(new TextBlock { Text = Clock(m.At), FontSize = 11, Foreground = Ui.Brush(Palette.TextMuted), Margin = new Thickness(0, 0, 0, 2) });
        CountText.Text = "×" + _messages.Count.ToString(CultureInfo.InvariantCulture);
        CountBadge.Visibility = _messages.Count > 1 ? Visibility.Visible : Visibility.Collapsed;
        CountBadge.ToolTip = _messages.Count + " messages from " + m.Who;
        Title = "SMS from " + m.Who;
        ReplyBox.Tag = "Reply to " + m.Who + "…";
        Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() => Scroller.ScrollToEnd()));

        bool canReply = _app.Sms.CanSend && m.Number.Length > 0;
        ReplyButton.Visibility = canReply ? Visibility.Visible : Visibility.Collapsed;
        if (!canReply && IsReplying) CloseReply();
        ThreadButton.Visibility = _app.Sms.Read ? Visibility.Visible : Visibility.Collapsed;
        Tick();
    }

    private static string Clock(DateTimeOffset at)
    {
        var local = at.ToLocalTime();
        return local.Date == DateTimeOffset.Now.Date ? local.ToString("t", CultureInfo.CurrentCulture) : local.ToString("g", CultureInfo.CurrentCulture);
    }

    private void Tick()
    {
        var now = DateTimeOffset.UtcNow;
        When.Text = "· " + TimeText.Ago(Latest.At, now);
        When.ToolTip = Latest.At.ToLocalTime().ToString("F", CultureInfo.CurrentCulture);
        // the alerts' "close by itself" - but never while it is being answered or read
        int after = _app.Settings.AutoCloseSeconds;
        if (after > 0 && !IsReplying && !_sending && !IsMouseOver && !IsKeyboardFocusWithin
            && now - _shownAt > TimeSpan.FromSeconds(Math.Max(after, 30)))
            Dismiss();
    }

    // ---- showing, moving, leaving (as the alert cards) -------------------------------------

    internal void Appear(double left, double top, bool takeFocus, bool asked)
    {
        Left = left + 56;
        Top = top;
        ShowActivated = takeFocus;
        Show();
        Left = left + 56;
        Top = top;
        _shown = true;
        _clock.Start();
        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        BeginAnimation(LeftProperty, new DoubleAnimation(left, TimeSpan.FromMilliseconds(320)) { EasingFunction = ease });
        Root.BeginAnimation(OpacityProperty, new DoubleAnimation(1, TimeSpan.FromMilliseconds(220)));
        Attention(takeFocus, asked);
    }

    public void MoveTo(double left, double top)
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

    internal void Attention(bool takeFocus, bool asked)
    {
        if (!asked) Native.Flash(this);
        var grow = new DoubleAnimation(1, 1.4, TimeSpan.FromMilliseconds(900)) { EasingFunction = new QuadraticEase { EasingMode = EasingMode.EaseOut }, RepeatBehavior = new RepeatBehavior(2) };
        var fade = new DoubleAnimation(0.9, 0, TimeSpan.FromMilliseconds(900)) { RepeatBehavior = new RepeatBehavior(2) };
        PulseScale.BeginAnimation(ScaleTransform.ScaleXProperty, grow);
        PulseScale.BeginAnimation(ScaleTransform.ScaleYProperty, grow);
        Pulse.BeginAnimation(OpacityProperty, fade);
        if (takeFocus) TakeFocus(IsReplying ? ReplyBox : ReplyButton.Visibility == Visibility.Visible ? ReplyButton : DismissButton);
    }

    private void TakeFocus(IInputElement target)
    {
        Activate();
        Native.ForceForeground(this);
        Topmost = true;
        Dispatcher.BeginInvoke(DispatcherPriority.Input, new Action(() => Keyboard.Focus(target)));
    }

    public void Dismiss()
    {
        if (IsClosing) return;
        IsClosing = true;
        _clock.Stop();
        var fade = new DoubleAnimation(0, TimeSpan.FromMilliseconds(170));
        fade.Completed += (_, _) => Close();
        BeginAnimation(LeftProperty, new DoubleAnimation(Left + 40, TimeSpan.FromMilliseconds(170)));
        Root.BeginAnimation(OpacityProperty, fade);
    }

    // ---- buttons -------------------------------------------------------------------------

    private void OnDismiss(object sender, RoutedEventArgs e) => Dismiss();

    private void OnOpenThread(object sender, RoutedEventArgs e)
    {
        _app.ShowMessages(ThreadKey, IsReplying ? ReplyBox.Text : null);
        Dismiss();
    }

    private void OnCopy(object sender, RoutedEventArgs e)
    {
        string text = string.Join("\n\n", _messages.Select(m => m.Text));
        if (!Ui.CopyText(text)) return;
        CopyGlyph.Text = ""; // a tick for a moment
        CopyButton.ToolTip = "Copied";
        var t = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.6) };
        t.Tick += (_, _) => { t.Stop(); CopyGlyph.Text = ""; CopyButton.ToolTip = "Copy the text"; };
        t.Start();
    }

    private void OnReply(object sender, RoutedEventArgs e)
    {
        ShowFeedback(null, false);
        ReplyPanel.Visibility = Visibility.Visible;
        ReadButtons.Visibility = Visibility.Collapsed;
        ReplyButtons.Visibility = Visibility.Visible;
        UpdateCounter();
        TakeFocus(ReplyBox);
    }

    private void OnCancelReply(object sender, RoutedEventArgs e) => CloseReply();

    private void CloseReply()
    {
        ReplyPanel.Visibility = Visibility.Collapsed;
        ReplyButtons.Visibility = Visibility.Collapsed;
        ReadButtons.Visibility = Visibility.Visible;
        _shownAt = DateTimeOffset.UtcNow;
    }

    private void OnReplyChanged(object sender, TextChangedEventArgs e) => UpdateCounter();

    private void UpdateCounter()
    {
        var c = SmsCounter.Count(ReplyBox.Text);
        Counter.Text = c.Text;
        bool many = c.Parts >= SmsCounter.ManyParts;
        Counter.Foreground = many ? Ui.Brush(Palette.Warn) : Ui.Brush(Palette.TextDim);
        CounterChip.BorderBrush = many ? Ui.Brush(Palette.Warn, 0x59) : Ui.Brush(Palette.Line);
        SendButton.IsEnabled = !_sending && ReplyBox.Text.Trim().Length > 0;
    }

    private void OnReplyKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && (Keyboard.Modifiers & ModifierKeys.Control) != 0)
        {
            e.Handled = true;
            if (SendButton.IsEnabled) OnSend(sender, e);
        }
    }

    private async void OnSend(object sender, RoutedEventArgs e)
    {
        if (_sending) return;
        string text = ReplyBox.Text;
        if (text.Trim().Length == 0) return;
        var m = Latest;
        string? replyTo = _messages.LastOrDefault(x => x.Incoming)?.Id;
        _sending = true;
        ReplyBox.IsReadOnly = true;
        SendButton.IsEnabled = false;
        CancelButton.IsEnabled = false;
        SendText.Text = "Sending…";
        ShowFeedback(null, false);
        SmsSendResult r;
        try
        {
            r = await _app.SendSmsAsync(new[] { m.Number }, text, replyTo);
        }
        finally
        {
            _sending = false;
            ReplyBox.IsReadOnly = false;
            CancelButton.IsEnabled = true;
            SendText.Text = "Send";
        }
        if (r.Ok)
        {
            _sent = true;
            ReplyBox.Clear();
            CloseReply();
            ShowFeedback("Sent to " + m.Who + (r.Message.Length > 0 && r.Message != "Sent." ? " · " + r.Message : ""), true);
            ReplyButton.Visibility = Visibility.Collapsed;
            DismissButton.Content = "Close";
            // done: the card goes by itself a moment later, unless the mouse is on it
            var t = new DispatcherTimer { Interval = TimeSpan.FromSeconds(4) };
            t.Tick += (_, _) => { if (!IsMouseOver && _sent) { t.Stop(); Dismiss(); } };
            t.Start();
        }
        else
        {
            ShowFeedback(r.Message, false, error: true);
            UpdateCounter();
            Keyboard.Focus(ReplyBox);
        }
    }

    private void ShowFeedback(string? text, bool ok, bool error = false)
    {
        if (text is null)
        {
            Feedback.Visibility = Visibility.Collapsed;
            return;
        }
        string accent = ok ? Palette.Ok : error ? Palette.Crit : Palette.Info;
        Feedback.Background = Ui.Brush(accent, 0x1F);
        Feedback.BorderBrush = Ui.Brush(accent, 0x59);
        FeedbackGlyph.Text = ok ? "" : "";
        FeedbackGlyph.Foreground = Ui.Brush(accent);
        FeedbackText.Text = text;
        FeedbackText.Foreground = Ui.Brush(Palette.Text);
        Feedback.Visibility = Visibility.Visible;
    }
}
