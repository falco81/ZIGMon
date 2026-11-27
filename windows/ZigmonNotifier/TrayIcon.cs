using System;
using System.Collections.Generic;
using System.IO;
using System.Windows.Forms;
using ZigmonNotifier.Core;
using DrawingIcon = System.Drawing.Icon;

namespace ZigmonNotifier;

/// <summary>The icon next to the clock, drawn at run time at the size Windows asks for, with a status dot.</summary>
internal sealed class TrayIcon : IDisposable
{
    private readonly NotifyIcon _icon;
    private readonly Dictionary<StatusDot, DrawingIcon> _cache = new();
    private StatusDot? _shown;

    public event Action? MenuRequested;
    public event Action? DoubleClicked;

    public TrayIcon()
    {
        _icon = new NotifyIcon { Text = AppInfoText("ZIGMon Notifier"), Icon = Make(StatusDot.Grey), Visible = true };
        _shown = StatusDot.Grey;
        _icon.MouseUp += (_, e) =>
        {
            if (e.Button == MouseButtons.Right) MenuRequested?.Invoke();
        };
        _icon.MouseDoubleClick += (_, e) =>
        {
            if (e.Button == MouseButtons.Left) DoubleClicked?.Invoke();
        };
    }

    public void SetState(StatusDot dot, string tooltip)
    {
        if (_shown != dot)
        {
            _icon.Icon = Make(dot);
            _shown = dot;
        }
        _icon.Text = AppInfoText(tooltip);
    }

    private static string AppInfoText(string s)
    {
        return s.Length <= 120 ? s : s[..119] + "…";
    }

    private DrawingIcon Make(StatusDot dot)
    {
        if (_cache.TryGetValue(dot, out var icon)) return icon;
        int size = Math.Clamp(SystemInformation.SmallIconSize.Width, 16, 64);
        var frames = new List<(int, byte[])> { (size, IconPainter.Render(size, dot)) };
        if (size != 32) frames.Add((32, IconPainter.Render(32, dot)));
        byte[] ico = ImageFiles.Ico(frames);
        using var ms = new MemoryStream(ico);
        icon = new DrawingIcon(ms, size, size);
        _cache[dot] = icon;
        return icon;
    }

    public void Dispose()
    {
        _icon.Visible = false;
        _icon.Dispose();
        foreach (var i in _cache.Values) i.Dispose();
        _cache.Clear();
    }
}
