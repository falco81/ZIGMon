using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using ZigmonNotifier.Core;
using Rect = System.Windows.Rect;
using ZigmonNotifier.Views;

namespace ZigmonNotifier;

/// <summary>
/// Keeps up to four alert cards stacked in the bottom-right corner above the
/// taskbar, newest at the bottom. A sensor that fires again while its card is
/// up updates that card (with a count) instead of adding another.
/// </summary>
internal sealed class AlertManager
{
    public const int MaxOpen = 4;
    /// <summary>The cards' transparent edge (room for the shadow) minus the visible gap.</summary>
    private const double Overlap = 14;

    private readonly AppController _app;
    private readonly List<AlertWindow> _open = new();
    /// <summary>The monitor the cards are on while any is open (its work area in pixels, its scale).</summary>
    private (PixelRect Work, double Scale)? _target;

    public AlertManager(AppController app) => _app = app;

    public void Show(TriggerEvent e, bool test)
    {
        var existing = test ? null : _open.FirstOrDefault(w => w.Device == e.Device && !w.IsClosing);
        if (existing is not null)
        {
            existing.Update(e);
            _open.Remove(existing);
            _open.Add(existing);
            Layout();
            existing.Attention(_app.Settings.BringToFront);
        }
        else
        {
            var live = _open.Where(w => !w.IsClosing).ToList();
            while (live.Count >= MaxOpen)
            {
                live[0].Dismiss();
                live.RemoveAt(0);
            }
            if (!_open.Any(x => !x.IsClosing)) _target = null; // a new stack: ask again which monitor
            var (work, scale) = Target();
            var w = new AlertWindow(_app, e, test) { TargetScale = scale };
            w.Closed += (_, _) =>
            {
                _open.Remove(w);
                if (!_open.Any(x => !x.IsClosing)) Sounds.Stop(); // the last one gone: so is the alarm
                Layout();
            };
            w.HeightSettled += Layout;
            _open.Add(w);
            w.Appear(work.Right - w.Width, work.Bottom - w.ExpectedHeight, _app.Settings.BringToFront);
            Layout();
        }
        if (_app.Settings.Sound) Sounds.Alarm(_app.Settings, test ? null : e.Device);
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
            if (w.IsClosing) continue;
            double h = w.ExpectedHeight;
            double top = bottom - h;
            w.MoveTo(work.Right - w.Width, Math.Max(work.Top, top));
            bottom = top + Overlap;
        }
    }

    public void CloseAll()
    {
        foreach (var w in _open.ToList()) w.Close();
        _open.Clear();
    }
}
