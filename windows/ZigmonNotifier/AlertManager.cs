using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using ZigmonNotifier.Core;
using Rect = System.Windows.Rect;
using ZigmonNotifier.Views;

namespace ZigmonNotifier;

/// <summary>A card in the stack: a sensor alert or (1.4.0) an SMS.</summary>
internal interface IStackCard
{
    bool IsClosing { get; }
    double ExpectedHeight { get; }
    void MoveTo(double left, double top);
    void Dismiss();
}

/// <summary>
/// Keeps up to four cards stacked in the bottom-right corner above the taskbar of the
/// chosen monitor, newest at the bottom: sensor alerts and SMS alike. A sensor that fires
/// again while its card is up updates that card (with a count) instead of adding another;
/// an SMS from someone whose card is up joins that card.
/// </summary>
internal sealed class AlertManager
{
    public const int MaxOpen = 4;
    /// <summary>The cards' transparent edge (room for the shadow) minus the visible gap.</summary>
    private const double Overlap = 14;

    private readonly AppController _app;
    private readonly List<Window> _open = new();
    /// <summary>The monitor the cards are on while any is open (its work area in pixels, its scale).</summary>
    private (PixelRect Work, double Scale)? _target;

    public AlertManager(AppController app) => _app = app;

    private static IStackCard Card(Window w) => (IStackCard)w;

    private IEnumerable<Window> Live => _open.Where(w => !Card(w).IsClosing);

    public void Show(TriggerEvent e, bool test)
    {
        var existing = test ? null : Live.OfType<AlertWindow>().FirstOrDefault(w => w.Device == e.Device);
        if (existing is not null)
        {
            existing.Update(e);
            ToNewest(existing);
            existing.Attention(_app.Settings.BringToFront);
        }
        else
        {
            var (work, scale) = MakeRoom();
            var w = new AlertWindow(_app, e, test) { TargetScale = scale };
            Add(w, () => w.HeightSettled += Layout);
            w.Appear(work.Right - w.Width, work.Bottom - w.ExpectedHeight, _app.Settings.BringToFront);
            Layout();
        }
        if (_app.Settings.Sound) Sounds.Alarm(_app.Settings, test ? null : e.Device);
    }

    /// <summary>
    /// An SMS card (1.4.0). <paramref name="asked"/>: the user asked for it (a Stream Deck key, a
    /// click) - then it comes to the front with the keyboard and makes no sound.
    /// </summary>
    public SmsWindow ShowSms(SmsMessage m, bool asked)
    {
        var existing = Live.OfType<SmsWindow>().FirstOrDefault(w => w.ThreadKey == m.ThreadKey);
        bool focus = asked || _app.Settings.BringToFront;
        if (existing is not null)
        {
            existing.Add(m);
            ToNewest(existing);
            existing.Attention(focus, asked);
        }
        else
        {
            var (work, scale) = MakeRoom();
            var w = new SmsWindow(_app, m) { TargetScale = scale };
            Add(w, () => w.HeightSettled += Layout);
            w.Appear(work.Right - w.Width, work.Bottom - w.ExpectedHeight, focus, asked);
            Layout();
            existing = w;
        }
        if (!asked && _app.Settings.SmsSound) Sounds.Play(_app.Settings.SmsSoundId, null, _app.Settings.Volume, AlertChoices.Once);
        return existing;
    }

    private void ToNewest(Window w)
    {
        _open.Remove(w);
        _open.Add(w);
        Layout();
    }

    /// <summary>The oldest cards go when four are up; a new stack asks again which monitor.</summary>
    private (Rect Work, double Scale) MakeRoom()
    {
        var live = Live.ToList();
        while (live.Count >= MaxOpen)
        {
            // an SMS being answered stays: the oldest other card goes first
            var drop = live.FirstOrDefault(x => x is not SmsWindow { IsReplying: true }) ?? live[0];
            Card(drop).Dismiss();
            live.Remove(drop);
        }
        if (!Live.Any()) _target = null;
        return Target();
    }

    private void Add(Window w, Action hook)
    {
        w.Closed += (_, _) =>
        {
            _open.Remove(w);
            if (!_open.OfType<AlertWindow>().Any(x => !x.IsClosing)) Sounds.Stop(); // the last alert gone: so is the alarm
            Layout();
        };
        hook();
        _open.Add(w);
    }

    /// <summary>The chosen monitor's work area in this app's units (pixels / that monitor's scale).</summary>
    private (Rect Work, double Scale) Target()
    {
        if (_target is null)
        {
            var c = Native.CursorPosition();
            var m = MonitorChoice.Pick(Native.Monitors(), _app.Settings.Monitor, c.X, c.Y);
            if (m is not null) _target = (m.Work, m.Scale);
        }
        if (_target is not { } t)
            return (SystemParameters.WorkArea, 1);
        double k = t.Scale > 0 ? t.Scale : 1;
        return (new Rect(t.Work.Left / k, t.Work.Top / k, t.Work.Width / k, t.Work.Height / k), k);
    }

    /// <summary>Puts every card in its place, newest lowest.</summary>
    public void Layout()
    {
        var (work, _) = Target();
        double bottom = work.Bottom;
        for (int i = _open.Count - 1; i >= 0; i--)
        {
            var w = _open[i];
            var c = Card(w);
            if (c.IsClosing) continue;
            double h = c.ExpectedHeight;
            double top = bottom - h;
            c.MoveTo(work.Right - w.Width, Math.Max(work.Top, top));
            bottom = top + Overlap;
        }
    }

    public void CloseAll()
    {
        foreach (var w in _open.ToList()) w.Close();
        _open.Clear();
    }
}
