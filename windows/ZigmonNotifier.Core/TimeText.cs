using System;
using System.Globalization;

namespace ZigmonNotifier.Core;

public static class TimeText
{
    /// <summary>"just now", "12 s ago", "5 min ago", "2 h ago", then the clock time or date.</summary>
    public static string Ago(DateTimeOffset at, DateTimeOffset now, CultureInfo? culture = null)
    {
        culture ??= CultureInfo.CurrentCulture;
        var d = now - at;
        if (d < TimeSpan.FromSeconds(10)) return "just now"; // also a clock a little ahead
        if (d < TimeSpan.FromMinutes(1)) return ((int)d.TotalSeconds).ToString(CultureInfo.InvariantCulture) + " s ago";
        if (d < TimeSpan.FromHours(1)) return ((int)d.TotalMinutes).ToString(CultureInfo.InvariantCulture) + " min ago";
        if (d < TimeSpan.FromHours(6)) return ((int)d.TotalHours).ToString(CultureInfo.InvariantCulture) + " h ago";
        var local = at.ToLocalTime();
        if (local.Date == now.ToLocalTime().Date) return local.ToString("t", culture);
        return local.ToString("g", culture);
    }

    /// <summary>"until 14:30" / "until resumed".</summary>
    public static string Until(DateTimeOffset? until, bool forever, CultureInfo? culture = null)
    {
        culture ??= CultureInfo.CurrentCulture;
        if (forever) return "until you resume";
        if (until is null) return "";
        var local = until.Value.ToLocalTime();
        return "until " + (local.Date == DateTimeOffset.Now.Date ? local.ToString("t", culture) : local.ToString("g", culture));
    }
}
