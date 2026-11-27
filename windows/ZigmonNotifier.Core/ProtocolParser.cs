using System;
using System.Collections.Generic;
using System.Text.Json;

namespace ZigmonNotifier.Core;

/// <summary>
/// Reads the server's JSON by hand, field by field: wrong types are treated as
/// missing, every string is cleaned and capped, lists are bounded. Nothing the
/// server sends is trusted to be well-formed.
/// </summary>
public static class ProtocolParser
{
    public const int MaxSensors = 2000;
    public const int MaxEvents = 200;
    public const int NameMax = 80;
    public const int RoomMax = 60;
    public const int WhatMax = 60;

    private static readonly JsonDocumentOptions DocOptions = new() { MaxDepth = 16, AllowTrailingCommas = false };

    public static JsonDocument ParseDocument(ReadOnlyMemory<byte> body)
    {
        try
        {
            var doc = JsonDocument.Parse(body, DocOptions);
            if (doc.RootElement.ValueKind != JsonValueKind.Object)
            {
                doc.Dispose();
                throw new ZigmonException(ZigmonErrorKind.Protocol, "The server answered, but not with what ZIGMon sends.");
            }
            return doc;
        }
        catch (JsonException)
        {
            throw new ZigmonException(ZigmonErrorKind.Protocol,
                "The address answered, but not as ZIGMon does. Is it your dashboard's address, and is ZIGMon new enough to have the desktop app?");
        }
    }

    /// <summary>The "error" words of a failed answer, cleaned; null when absent.</summary>
    public static string? ErrorText(JsonElement root)
    {
        string? e = Str(root, "error", 200);
        return string.IsNullOrEmpty(e) ? null : e;
    }

    public static bool IsOk(JsonElement root) =>
        root.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.True;

    public static HelloInfo Hello(JsonElement root)
    {
        int api = Int(root, "api") ?? 0;
        string server = Str(root, "server", 40);
        if (!string.Equals(server, "zigmon", StringComparison.OrdinalIgnoreCase))
            throw new ZigmonException(ZigmonErrorKind.Protocol, "The address answered, but it is not ZIGMon.");
        if (api != AppInfo.ProtocolVersion)
            throw new ZigmonException(ZigmonErrorKind.Protocol,
                api > AppInfo.ProtocolVersion
                    ? "This ZIGMon is newer than this app understands - get the newer ZIGMon Notifier."
                    : "This ZIGMon does not speak the desktop-app protocol yet - update ZIGMon.");
        KeyInfo key = new("", 0, "");
        if (root.TryGetProperty("key", out var k) && k.ValueKind == JsonValueKind.Object)
            key = new KeyInfo(Str(k, "name", 60), Math.Clamp(Int(k, "devices") ?? 0, 0, 100000), SafeText.Identifier(Str(k, "hint", 4), 4));
        bool advertises = root.TryGetProperty("app", out var app);
        string? appVersion = null;
        if (advertises && app.ValueKind == JsonValueKind.Object
            && AppVersions.TryParse(Str(app, "version", 24, clean: false), out var v))
            appVersion = AppVersions.Format(v);
        return new HelloInfo(api, "zigmon", Str(root, "version", 24), Str(root, "house", NameMax), key,
            Boot(root), Seq(root)) { AdvertisesApp = advertises, AppVersion = appVersion };
    }

    /// <summary>
    /// /update: either {"available":false}, or the advertised version, size and
    /// sha256 with the signed manifest and its signature (both base64). Nothing
    /// here is trusted yet - <see cref="UpdateVerifier"/> decides.
    /// </summary>
    public static UpdateOffer Update(JsonElement root)
    {
        if (!root.TryGetProperty("available", out var av) || av.ValueKind != JsonValueKind.True)
            return UpdateOffer.None;
        string version = Str(root, "version", 24, clean: false);
        long size = Long(root, "size") ?? -1;
        string sha = Str(root, "sha256", 64, clean: false);
        byte[]? manifest = Base64(root, "manifest", UpdateVerifier.MaxManifestBytes);
        byte[]? sig = Base64(root, "sig", 128);
        if (version.Length == 0 || size < 0 || sha.Length == 0 || manifest is null || sig is null)
            throw new ZigmonException(ZigmonErrorKind.Protocol, "ZIGMon's answer about the app update is incomplete.");
        return new UpdateOffer(true, version, size, sha, manifest, sig);
    }

    private static byte[]? Base64(JsonElement o, string name, int maxBytes)
    {
        if (!o.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.String) return null;
        string s = v.GetString() ?? "";
        if (s.Length == 0 || s.Length > (maxBytes + 2) / 3 * 4) return null;
        try
        {
            return Convert.FromBase64String(s);
        }
        catch (FormatException)
        {
            return null;
        }
    }

    public static SensorsSnapshot Sensors(JsonElement root)
    {
        var list = new List<SensorInfo>();
        if (root.TryGetProperty("sensors", out var arr) && arr.ValueKind == JsonValueKind.Array)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var s in arr.EnumerateArray())
            {
                if (list.Count >= MaxSensors) break;
                if (s.ValueKind != JsonValueKind.Object) continue;
                string id = SafeText.Identifier(Str(s, "id", 200, clean: false));
                if (id.Length == 0 || !seen.Add(id)) continue;
                string name = Str(s, "name", NameMax);
                int? batt = Int(s, "battery");
                list.Add(new SensorInfo(
                    id,
                    name.Length > 0 ? name : id,
                    NullIfEmpty(Str(s, "room", RoomMax)),
                    SensorKinds.Normalize(Str(s, "kind", 20)),
                    Bool(s, "active"),
                    Time(s, "at"),
                    batt is >= 0 and <= 100 ? batt : null,
                    Bool(s, "online") ?? true));
            }
        }
        return new SensorsSnapshot(Boot(root), Seq(root), list);
    }

    public static WaitResult Wait(JsonElement root)
    {
        var list = new List<TriggerEvent>();
        if (root.TryGetProperty("events", out var arr) && arr.ValueKind == JsonValueKind.Array)
        {
            foreach (var e in arr.EnumerateArray())
            {
                if (list.Count >= MaxEvents) break;
                if (e.ValueKind != JsonValueKind.Object) continue;
                long seq = Long(e, "seq") ?? -1;
                string device = SafeText.Identifier(Str(e, "device", 200, clean: false));
                if (seq < 0 || device.Length == 0) continue;
                string name = Str(e, "name", NameMax);
                list.Add(new TriggerEvent(
                    seq,
                    Time(e, "at") ?? DateTimeOffset.UtcNow,
                    device,
                    name.Length > 0 ? name : device,
                    NullIfEmpty(Str(e, "room", RoomMax)),
                    SensorKinds.Normalize(Str(e, "kind", 20)),
                    SafeText.Identifier(Str(e, "key", 40, clean: false), 40),
                    Bool(e, "active"),
                    Str(e, "what", WhatMax)));
            }
        }
        list.Sort((a, b) => a.Seq.CompareTo(b.Seq));
        bool reset = root.TryGetProperty("reset", out var r) && r.ValueKind == JsonValueKind.True;
        return new WaitResult(Boot(root), Seq(root), reset, list);
    }

    // ---- small readers -------------------------------------------------------------

    private static string Boot(JsonElement root)
    {
        string b = SafeText.Identifier(Str(root, "boot", 64, clean: false), 64);
        if (b.Length == 0) throw new ZigmonException(ZigmonErrorKind.Protocol, "ZIGMon's answer had no boot id.");
        return b;
    }

    private static long Seq(JsonElement root)
    {
        long? s = Long(root, "seq");
        if (s is null || s < 0) throw new ZigmonException(ZigmonErrorKind.Protocol, "ZIGMon's answer had no event number.");
        return s.Value;
    }

    private static string? NullIfEmpty(string s) => s.Length == 0 ? null : s;

    internal static string Str(JsonElement o, string name, int max, bool clean = true)
    {
        if (!o.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.String) return string.Empty;
        string s = v.GetString() ?? string.Empty;
        return clean ? SafeText.Clean(s, max) : (s.Length > max ? string.Empty : s);
    }

    private static bool? Bool(JsonElement o, string name)
    {
        if (!o.TryGetProperty(name, out var v)) return null;
        return v.ValueKind switch { JsonValueKind.True => true, JsonValueKind.False => false, _ => null };
    }

    private static long? Long(JsonElement o, string name)
    {
        if (!o.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.Number) return null;
        if (v.TryGetInt64(out long l)) return l;
        if (v.TryGetDouble(out double d) && double.IsFinite(d) && d >= 0 && d < 9e15 && Math.Floor(d) == d) return (long)d;
        return null;
    }

    private static int? Int(JsonElement o, string name)
    {
        long? l = Long(o, name);
        if (l is null) return null;
        if (l > int.MaxValue) return int.MaxValue;
        if (l < int.MinValue) return int.MinValue;
        return (int)l.Value;
    }

    private static DateTimeOffset? Time(JsonElement o, string name)
    {
        if (!o.TryGetProperty(name, out var v) || v.ValueKind != JsonValueKind.Number) return null;
        if (!v.TryGetDouble(out double d) || !double.IsFinite(d)) return null;
        // 2001 .. 2200: anything outside is nonsense
        if (d < 978307200 || d > 7258118400) return null;
        return DateTimeOffset.FromUnixTimeMilliseconds((long)Math.Round(d * 1000));
    }
}
