using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using ZigmonNotifier.Core;
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
            var w = new AlertWindow(_app, e, test);
            w.Closed += (_, _) =>
            {
                _open.Remove(w);
                Layout();
            };
            w.HeightSettled += Layout;
            _open.Add(w);
            var work = SystemParameters.WorkArea;
            w.Appear(work.Right - w.Width, work.Bottom - w.ExpectedHeight, _app.Settings.BringToFront);
            Layout();
        }
        if (_app.Settings.Sound) Sounds.Chime();
    }

    /// <summary>Puts every card in its place, newest lowest.</summary>
    public void Layout()
    {
        var work = SystemParameters.WorkArea;
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
