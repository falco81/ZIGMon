using System;
using System.Collections.Generic;
using System.Linq;

namespace ZigmonNotifier.Core;

/// <summary>A rectangle in screen pixels.</summary>
public readonly record struct PixelRect(int Left, int Top, int Right, int Bottom)
{
    public int Width => Right - Left;
    public int Height => Bottom - Top;
    public bool Contains(int x, int y) => x >= Left && x < Right && y >= Top && y < Bottom;
}

/// <summary>One monitor as Windows describes it.</summary>
public sealed record MonitorInfo(string Device, PixelRect Bounds, PixelRect Work, bool Primary, double Scale);

/// <summary>Which monitor alerts go to, and how each monitor is named in the settings.</summary>
public static class MonitorChoice
{
    /// <summary>
    /// The monitor for this setting: "cursor" → the one under the mouse; a device name → that
    /// monitor while it is connected; anything else (or a monitor that is gone) → the primary one.
    /// </summary>
    public static MonitorInfo? Pick(IReadOnlyList<MonitorInfo> monitors, string? setting, int cursorX, int cursorY)
    {
        if (monitors.Count == 0) return null;
        var primary = monitors.FirstOrDefault(m => m.Primary) ?? monitors[0];
        if (setting == AlertChoices.MonitorCursor)
            return monitors.FirstOrDefault(m => m.Bounds.Contains(cursorX, cursorY)) ?? primary;
        if (string.IsNullOrEmpty(setting) || setting == AlertChoices.MonitorPrimary) return primary;
        return monitors.FirstOrDefault(m => string.Equals(m.Device, setting, StringComparison.OrdinalIgnoreCase)) ?? primary;
    }

    /// <summary>The monitors in reading order (left to right, then top to bottom), as the list shows them.</summary>
    public static IReadOnlyList<MonitorInfo> Ordered(IEnumerable<MonitorInfo> monitors) =>
        monitors.OrderBy(m => m.Bounds.Left).ThenBy(m => m.Bounds.Top).ToList();

    /// <summary>"Display 2 · 2560 × 1440 · left · primary".</summary>
    public static string Describe(MonitorInfo m, IReadOnlyList<MonitorInfo> all)
    {
        string number = DeviceNumber(m.Device) is { } n ? "Display " + n : SafeText.Clean(m.Device, 40);
        var parts = new List<string> { number, m.Bounds.Width + " × " + m.Bounds.Height };
        if (all.Count > 1)
        {
            var ordered = Ordered(all);
            int i = ordered.ToList().FindIndex(x => x.Device == m.Device);
            if (ordered.Count == 2) parts.Add(i == 0 ? "left" : "right");
            else if (i == 0) parts.Add("leftmost");
            else if (i == ordered.Count - 1) parts.Add("rightmost");
        }
        if (m.Primary) parts.Add("primary");
        return string.Join(" · ", parts);
    }

    private static string? DeviceNumber(string device)
    {
        int i = device.LastIndexOf("DISPLAY", StringComparison.OrdinalIgnoreCase);
        if (i < 0) return null;
        string digits = new(device.Skip(i + 7).TakeWhile(char.IsAsciiDigit).ToArray());
        return digits.Length is > 0 and <= 3 ? digits : null;
    }

}
