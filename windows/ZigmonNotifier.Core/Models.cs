using System;
using System.Collections.Generic;

namespace ZigmonNotifier.Core;

/// <summary>What the key is, as ZIGMon tells it (hello.key).</summary>
public sealed record KeyInfo(string Name, int Devices, string Hint);

/// <summary>hello: who answers and where the event stream stands.</summary>
public sealed record HelloInfo(
    int Api, string Server, string Version, string House, KeyInfo Key, string Boot, long Seq);

/// <summary>One sensor the key may see.</summary>
public sealed record SensorInfo(
    string Id, string Name, string? Room, string Kind, bool? Active, DateTimeOffset? At,
    int? Battery, bool Online)
{
    public SensorInfo WithState(bool? active, DateTimeOffset? at) => this with { Active = active, At = at };
}

public sealed record SensorsSnapshot(string Boot, long Seq, IReadOnlyList<SensorInfo> Sensors);

/// <summary>A trigger event (an edge) of one sensor.</summary>
public sealed record TriggerEvent(
    long Seq, DateTimeOffset At, string Device, string Name, string? Room, string Kind,
    string Key, bool? Active, string What);

public sealed record WaitResult(string Boot, long Seq, bool Reset, IReadOnlyList<TriggerEvent> Events);

/// <summary>The sensor kinds protocol v1 knows; anything else is shown as "other".</summary>
public static class SensorKinds
{
    public const string Motion = "motion";
    public const string Contact = "contact";
    public const string Leak = "leak";
    public const string Smoke = "smoke";
    public const string Gas = "gas";
    public const string Co = "co";
    public const string Tamper = "tamper";
    public const string Vibration = "vibration";
    public const string Button = "button";
    public const string Other = "other";

    public static readonly IReadOnlyList<string> All =
        new[] { Motion, Contact, Leak, Smoke, Gas, Co, Tamper, Vibration, Button };

    public static string Normalize(string? kind)
    {
        string k = (kind ?? string.Empty).Trim().ToLowerInvariant();
        foreach (var known in All) if (known == k) return known;
        return Other;
    }
}
