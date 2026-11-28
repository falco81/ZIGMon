using System;
using System.Collections.Generic;
using System.Linq;
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
            Boot(root), Seq(root)) { AdvertisesApp = advertises, AppVersion = appVersion, Sms = SmsPerms(root) };
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
                    Bool(s, "online") ?? true)
                {
                    RuleText = NullIfEmpty(RuleText(s)),
                    ValueText = NullIfEmpty(Str(s, "value_text", WhatMax)),
                    DeviceName = NullIfEmpty(Str(s, "device_name", NameMax)),
                });
            }
        }
        return new SensorsSnapshot(Boot(root), Seq(root), list);
    }

    /// <summary>A condition's words: sensors[].rule.text (5.58), plain text only.</summary>
    private static string RuleText(JsonElement s) =>
        s.TryGetProperty("rule", out var r) && r.ValueKind == JsonValueKind.Object ? Str(r, "text", WhatMax) : string.Empty;

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
                string rawKind = Str(e, "kind", 20).ToLowerInvariant();
                if (rawKind == SensorKinds.Sms || rawKind == SensorKinds.Deck)
                {
                    // not a sensor: an SMS, or a Stream Deck's ask - kept only when its payload is whole
                    var special = Special(e, seq, device, rawKind);
                    if (special is not null) list.Add(special);
                    continue;
                }
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

    // ---- SMS, contacts and the Stream Deck (5.59.4) ------------------------------------

    public const int MaxSms = 200;
    public const int SmsTextMax = 4000;
    public const int MaxContacts = 2000;
    public const int MaxGroups = 500;
    public const int MaxNumbersPerContact = 5;
    public const int MaxDeckTo = 20;

    /// <summary>hello.sms; absent (an older ZIGMon) or not an object: nothing allowed.</summary>
    private static SmsPermissions SmsPerms(JsonElement root)
    {
        if (!root.TryGetProperty("sms", out var o) || o.ValueKind != JsonValueKind.Object) return SmsPermissions.None;
        return new SmsPermissions(Bool(o, "read") == true, Bool(o, "send") == true, Bool(o, "contacts") == true, Bool(o, "ready") == true);
    }

    private static TriggerEvent? Special(JsonElement e, long seq, string device, string kind)
    {
        var at = Time(e, "at") ?? DateTimeOffset.UtcNow;
        string key = SafeText.Identifier(Str(e, "key", 40, clean: false), 40);
        string what = SafeText.Identifier(Str(e, "what", 20, clean: false), 20);
        if (kind == SensorKinds.Sms)
        {
            if (!e.TryGetProperty("sms", out var o) || o.ValueKind != JsonValueKind.Object) return null;
            var m = SmsObject(o, incomingByDefault: true);
            if (m is null) return null;
            return new TriggerEvent(seq, at, device, m.Who, null, SensorKinds.Sms, key, true, "sms") { Sms = m };
        }
        if (key != "sms" || what is not (DeckAsk.Last or DeckAsk.Compose)) return null;
        string install = "", computer = "";
        var to = new List<DeckRecipient>();
        if (e.TryGetProperty("deck", out var d) && d.ValueKind == JsonValueKind.Object)
        {
            install = SafeText.Identifier(Str(d, "install", 80, clean: false), 80);
            computer = Str(d, "computer", NameMax);
            if (d.TryGetProperty("to", out var arr) && arr.ValueKind == JsonValueKind.Array)
            {
                foreach (var r in arr.EnumerateArray())
                {
                    if (to.Count >= MaxDeckTo) break;
                    if (r.ValueKind != JsonValueKind.Object) continue;
                    string number = SmsNumbers.Clean(Str(r, "number", 64, clean: false));
                    if (number.Length == 0 || to.Any(x => SmsNumbers.Key(x.Number) == SmsNumbers.Key(number))) continue;
                    string id = Str(r, "id", 20, clean: false);
                    to.Add(new DeckRecipient(ContactIds.IsValid(id) ? id : "", Str(r, "name", NameMax), number));
                }
            }
        }
        return new TriggerEvent(seq, at, device, "Stream Deck", null, SensorKinds.Deck, key, true, what)
        {
            Deck = new DeckAsk(what, install, computer, to),
        };
    }

    /// <summary>One SMS object (an event's "sms", or a row of the list); null when it has neither a number nor text.</summary>
    private static SmsMessage? SmsObject(JsonElement o, bool incomingByDefault)
    {
        string id = SafeText.Identifier(Str(o, "id", 64, clean: false), 64);
        string dir = Str(o, "dir", 8, clean: false);
        bool incoming = dir switch { "in" => true, "out" => false, _ => incomingByDefault };
        string number = SmsNumbers.Clean(Str(o, "number", 64, clean: false));
        if (number.Length == 0) number = SmsNumbers.Clean(Str(o, "from", 64, clean: false));
        SmsContactRef? contact = null;
        if (o.TryGetProperty("contact", out var c) && c.ValueKind == JsonValueKind.Object)
        {
            string cid = Str(c, "id", 20, clean: false);
            string cname = Str(c, "name", NameMax);
            if (cname.Length > 0) contact = new SmsContactRef(ContactIds.IsValid(cid) ? cid : "", cname);
        }
        string text = o.TryGetProperty("text", out var t) && t.ValueKind == JsonValueKind.String
            ? SafeText.CleanMultiline(t.GetString(), SmsTextMax) : "";
        if (number.Length == 0 && text.Length == 0) return null;
        return new SmsMessage(id, incoming, number, contact, text, Time(o, "at") ?? DateTimeOffset.UtcNow, Bool(o, "ok"));
    }

    /// <summary>GET /api/notifier/sms: {"messages":[...]}, returned newest first.</summary>
    public static IReadOnlyList<SmsMessage> SmsList(JsonElement root)
    {
        var list = new List<SmsMessage>();
        if (root.TryGetProperty("messages", out var arr) && arr.ValueKind == JsonValueKind.Array)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var m in arr.EnumerateArray())
            {
                if (list.Count >= MaxSms) break;
                if (m.ValueKind != JsonValueKind.Object) continue;
                var s = SmsObject(m, incomingByDefault: true);
                if (s is null || s.Id.Length > 0 && !seen.Add(s.Id)) continue;
                list.Add(s);
            }
        }
        return list.OrderByDescending(m => m.At).ToList();
    }

    /// <summary>GET /api/notifier/contacts: {"contacts":[...],"groups":[...]}, every field checked.</summary>
    public static ContactBook Contacts(JsonElement root)
    {
        var list = new List<Contact>();
        var groups = new List<string>();
        if (root.TryGetProperty("contacts", out var arr) && arr.ValueKind == JsonValueKind.Array)
        {
            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var c in arr.EnumerateArray())
            {
                if (list.Count >= MaxContacts) break;
                if (c.ValueKind != JsonValueKind.Object) continue;
                string id = Str(c, "id", 20, clean: false);
                string name = Str(c, "name", NameMax);
                if (!ContactIds.IsValid(id) || name.Length == 0 || !ids.Add(id)) continue;
                var numbers = new List<ContactNumber>();
                if (c.TryGetProperty("numbers", out var ns) && ns.ValueKind == JsonValueKind.Array)
                {
                    foreach (var n in ns.EnumerateArray())
                    {
                        if (numbers.Count >= MaxNumbersPerContact) break;
                        if (n.ValueKind != JsonValueKind.Object) continue;
                        string number = SmsNumbers.Clean(Str(n, "number", 64, clean: false));
                        if (number.Length == 0 || numbers.Any(x => x.Number == number)) continue;
                        numbers.Add(new ContactNumber(Str(n, "label", 20), number));
                    }
                }
                if (numbers.Count == 0) continue; // nothing to write to
                list.Add(new Contact(id, name, numbers, Str(c, "group", Recipients.GroupMax), Str(c, "note", 200), Bool(c, "favourite") == true));
            }
        }
        if (root.TryGetProperty("groups", out var gs) && gs.ValueKind == JsonValueKind.Array)
        {
            foreach (var g in gs.EnumerateArray())
            {
                if (groups.Count >= MaxGroups) break;
                if (g.ValueKind != JsonValueKind.String) continue;
                string name = SafeText.Clean(g.GetString(), Recipients.GroupMax);
                if (name.Length > 0 && !groups.Contains(name, StringComparer.OrdinalIgnoreCase)) groups.Add(name);
            }
        }
        // a group a contact names but the list left out is still a group
        foreach (var c in list)
            if (c.Group.Length > 0 && groups.Count < MaxGroups && !groups.Contains(c.Group, StringComparer.OrdinalIgnoreCase)) groups.Add(c.Group);
        list.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.CurrentCultureIgnoreCase));
        return new ContactBook(list, groups);
    }

    /// <summary>POST /api/notifier/sms/send's answer: ok, the numbers sent and failed, ZIGMon's words.</summary>
    public static SmsSendResult SendResult(JsonElement root)
    {
        bool ok = IsOk(root);
        int sent = Count(root, "sent"), failed = Count(root, "failed");
        string words = ok ? Str(root, "message", 200) : Str(root, "error", 200);
        if (words.Length == 0) words = ok ? Str(root, "error", 200) : Str(root, "message", 200);
        if (words.Length == 0) words = ok ? "Sent." : "ZIGMon did not send it, without saying why.";
        return new SmsSendResult(ok, sent, failed, words);
    }

    private static int Count(JsonElement o, string name)
    {
        if (!o.TryGetProperty(name, out var v)) return 0;
        if (v.ValueKind == JsonValueKind.Array) return Math.Min(v.GetArrayLength(), 10000);
        return Math.Clamp(Int(o, name) ?? 0, 0, 10000);
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
