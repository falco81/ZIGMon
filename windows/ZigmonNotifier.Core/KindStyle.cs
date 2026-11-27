using System;
using System.Collections.Generic;
using System.Globalization;

namespace ZigmonNotifier.Core;

/// <summary>ZIGMon's dashboard palette (web/index.php :root), so the app looks like part of it.</summary>
public static class Palette
{
    public const string Bg = "#0D1117";
    public const string Panel = "#161B22";
    public const string Panel2 = "#1C222B";
    public const string Line = "#262C37";
    public const string Text = "#E6E9EF";
    public const string TextDim = "#8B94A3";
    public const string TextMuted = "#5B6472";
    public const string Ok = "#3FB950";
    public const string Warn = "#D29922";
    public const string Crit = "#F85149";
    public const string Info = "#58A6FF";
    public const string Batt = "#A371F7";
    public const string Load = "#F0883E";
    public const string Sleep = "#6E7681";
    public const string Water = "#39C5CF";
}

/// <summary>How each kind of sensor looks and speaks.</summary>
public sealed record KindStyle(string Kind, string Label, string Accent, string IconPath, string ActiveWord, string QuietWord)
{
    private static readonly Dictionary<string, KindStyle> Styles = new(StringComparer.Ordinal)
    {
        [SensorKinds.Motion] = new(SensorKinds.Motion, "Motion", Palette.Info, Icons.Motion, "Motion", "Quiet"),
        [SensorKinds.Contact] = new(SensorKinds.Contact, "Door / window", Palette.Batt, Icons.Door, "Open", "Closed"),
        [SensorKinds.Leak] = new(SensorKinds.Leak, "Water leak", Palette.Water, Icons.Drop, "Wet", "Dry"),
        [SensorKinds.Smoke] = new(SensorKinds.Smoke, "Smoke", Palette.Crit, Icons.Smoke, "Smoke", "Clear"),
        [SensorKinds.Gas] = new(SensorKinds.Gas, "Gas", Palette.Load, Icons.Flame, "Gas", "Clear"),
        [SensorKinds.Co] = new(SensorKinds.Co, "Carbon monoxide", Palette.Crit, Icons.Alert, "CO", "Clear"),
        [SensorKinds.Tamper] = new(SensorKinds.Tamper, "Tamper", Palette.Warn, Icons.Shield, "Tampered", "OK"),
        [SensorKinds.Vibration] = new(SensorKinds.Vibration, "Vibration", Palette.Load, Icons.Vibration, "Vibrating", "Still"),
        [SensorKinds.Button] = new(SensorKinds.Button, "Button", Palette.Ok, Icons.Hand, "Pressed", "Ready"),
        [SensorKinds.Other] = new(SensorKinds.Other, "Sensor", Palette.TextDim, Icons.Pulse, "Active", "Quiet"),
    };

    public static KindStyle For(string? kind) => Styles[SensorKinds.Normalize(kind)];

    public static IEnumerable<KindStyle> All => Styles.Values;

    /// <summary>The words for a state chip: "Open", "Closed", "Offline", "Unknown".</summary>
    public string StateWord(bool? active, bool online)
    {
        if (!online) return "Offline";
        if (Kind == SensorKinds.Button) return "Ready";
        return active switch { true => ActiveWord, false => QuietWord, null => "Unknown" };
    }

    /// <summary>The headline of an alert: the server's "what", tidied, else a word of our own.</summary>
    public string Headline(string? what, bool? active)
    {
        string w = SafeText.Clean(what, ProtocolParser.WhatMax);
        if (w.Length == 0) w = active == false ? QuietWord : ActiveWord;
        return char.ToUpper(w[0], CultureInfo.InvariantCulture) + w[1..];
    }
}

/// <summary>
/// Stroke icons on a 24x24 grid, drawn like the dashboard's (stroke 1.7, round caps and joins),
/// in path markup that WPF's Geometry.Parse and SVG both read: absolute commands,
/// numbers with leading zeros, separated by spaces.
/// </summary>
public static class Icons
{
    public const double StrokeWidth = 1.7;

    public static readonly string Motion = Circle(8.5, 5, 2)
        + " M 8.5 8 L 7.5 13 L 10 15.5 L 10.5 20 M 7.5 13 L 5.5 20 M 5 11 L 8.2 8.5 L 11 11"
        + " M 15 9 A 4 4 0 0 1 15 15 M 18 6.5 A 7.5 7.5 0 0 1 18 17.5";

    public static readonly string Door = "M 14 3 H 6 V 21 H 14 M 14 3 L 18 5 V 19 L 14 21 Z " + Circle(15.5, 12, 0.6);

    public static readonly string Drop =
        "M 12 3.5 C 15.5 7.7 18 11.1 18 14 A 6 6 0 0 1 6 14 C 6 11.1 8.5 7.7 12 3.5 Z M 9.5 14.5 A 2.5 2.5 0 0 0 12 17";

    public static readonly string Smoke =
        "M 7.5 20 C 5.5 17 9.5 15 7.5 12 C 5.5 9 9.5 7 7.5 4"
        + " M 12 20 C 10 17 14 15 12 12 C 10 9 14 7 12 4"
        + " M 16.5 20 C 14.5 17 18.5 15 16.5 12 C 14.5 9 18.5 7 16.5 4";

    public static readonly string Flame =
        "M 12 3 C 13 6.5 17 8.5 17 13.5 A 5 5 0 0 1 7 13.5 C 7 11 8.5 9.5 9.5 8.5 C 9.8 10.3 10.7 11.3 12 11.5 C 12 8.5 11 6 12 3 Z";

    public static readonly string Alert = "M 12 3.5 L 2.5 20 H 21.5 Z M 12 10 V 14.5 M 12 17.2 L 12.01 17.2";

    public static readonly string Shield =
        "M 12 3 L 20 6 V 12 C 20 17 16.5 20 12 21 C 7.5 20 4 17 4 12 V 6 Z M 12 8.5 V 12.5 M 12 15.8 L 12.01 15.8";

    public static readonly string Vibration = RoundRect(8.5, 4, 7, 16, 1.6)
        + " M 5 9 V 15 M 19 9 V 15 M 2.5 10.5 V 13.5 M 21.5 10.5 V 13.5";

    public static readonly string Hand =
        "M 9 11 V 5.5 A 1.5 1.5 0 0 1 12 5.5 V 11 M 12 11 V 4.5 A 1.5 1.5 0 0 1 15 4.5 V 11"
        + " M 15 11 V 6.5 A 1.5 1.5 0 0 1 18 6.5 V 13 C 18 17 15.5 20 12 20 C 8.5 20 6 17.5 6 14 V 11 A 1.5 1.5 0 0 1 9 11";

    public static readonly string Pulse = "M 3 12 H 7 L 10 5 L 14 19 L 17 12 H 21";

    /// <summary>ZIGMon Notifier's own mark: a sensor sending out its waves.</summary>
    public static readonly string Radar = Circle(7, 17, 1.4)
        + " M 7 11 A 6 6 0 0 1 13 17 M 7 6 A 11 11 0 0 1 18 17";

    /// <summary>An arrow coming round to a tick: "updated".</summary>
    public static readonly string Updated = "M 19.5 12 A 7.5 7.5 0 1 1 16.8 6.2 M 17.5 2.8 L 17 6.6 L 13.2 6.3 M 8.5 12.2 L 11 14.7 L 15.5 10";

    public static readonly string Bell = "M 6 16 V 11 A 6 6 0 0 1 18 11 V 16 L 20 18 H 4 Z M 10 20 A 2 2 0 0 0 14 20";

    public static string Circle(double cx, double cy, double r) =>
        "M " + N(cx - r) + " " + N(cy) + " A " + N(r) + " " + N(r) + " 0 1 0 " + N(cx + r) + " " + N(cy)
        + " A " + N(r) + " " + N(r) + " 0 1 0 " + N(cx - r) + " " + N(cy) + " Z";

    public static string RoundRect(double x, double y, double w, double h, double r) =>
        "M " + N(x + r) + " " + N(y) + " H " + N(x + w - r)
        + " A " + N(r) + " " + N(r) + " 0 0 1 " + N(x + w) + " " + N(y + r) + " V " + N(y + h - r)
        + " A " + N(r) + " " + N(r) + " 0 0 1 " + N(x + w - r) + " " + N(y + h) + " H " + N(x + r)
        + " A " + N(r) + " " + N(r) + " 0 0 1 " + N(x) + " " + N(y + h - r) + " V " + N(y + r)
        + " A " + N(r) + " " + N(r) + " 0 0 1 " + N(x + r) + " " + N(y) + " Z";

    private static string N(double v) => Math.Round(v, 3).ToString("0.###", CultureInfo.InvariantCulture);
}
