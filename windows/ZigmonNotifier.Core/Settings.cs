using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ZigmonNotifier.Core;

/// <summary>Encrypts small secrets for this Windows user (DPAPI on Windows; a fake in tests).</summary>
public interface ISecretProtector
{
    byte[] Protect(byte[] plain);
    /// <summary>Throws when the data cannot be decrypted (another user, another machine, tampered).</summary>
    byte[] Unprotect(byte[] protectedData);
}

public sealed class WatchedSensor
{
    public string Id { get; set; } = "";
    /// <summary>The name last seen, so a sensor the key no longer offers can still be named.</summary>
    public string Name { get; set; } = "";
    public bool AlsoWhenClears { get; set; }
}

public sealed class PinSetting
{
    public string Scope { get; set; } = "";
    public string Sha256 { get; set; } = "";
    public string Subject { get; set; } = "";
    public DateTimeOffset PinnedAt { get; set; }
}

/// <summary>Everything the app keeps, in %APPDATA%\ZIGMon Notifier\settings.json.</summary>
public sealed class NotifierSettings
{
    public int Format { get; set; } = 1;
    public string? ServerUrl { get; set; }
    /// <summary>The key, encrypted with DPAPI (CurrentUser + app entropy), base64. Never the key itself.</summary>
    public string? ProtectedKey { get; set; }
    /// <summary>The key's last two characters, to show "saved key …xQ".</summary>
    public string? KeyHint { get; set; }
    public PinSetting? Pin { get; set; }
    public string? House { get; set; }
    public List<WatchedSensor> Watched { get; set; } = new();
    /// <summary>sensor id → muted until.</summary>
    public Dictionary<string, DateTimeOffset> Mutes { get; set; } = new(StringComparer.Ordinal);
    public DateTimeOffset? PausedUntil { get; set; }
    public bool PausedUntilResumed { get; set; }
    public bool Sound { get; set; } = true;
    /// <summary>Alerts take the keyboard focus (off: they show on top without taking it).</summary>
    public bool BringToFront { get; set; }
    /// <summary>Alerts close by themselves after a minute.</summary>
    public bool AutoClose { get; set; }
    /// <summary>Install signed updates from the connected ZIGMon by themselves (off: show them, install on a click).</summary>
    public bool AutoUpdate { get; set; } = true;

    [JsonIgnore] public bool HasConnection => !string.IsNullOrEmpty(ServerUrl) && !string.IsNullOrEmpty(ProtectedKey);

    public CertificatePin? GetPin()
    {
        if (Pin is null) return null;
        string? sha = CertificatePolicy.NormalizePin(Pin.Sha256);
        if (sha is null || string.IsNullOrWhiteSpace(Pin.Scope)) return null;
        return new CertificatePin(Pin.Scope, sha, Pin.Subject, Pin.PinnedAt);
    }

    public void SetPin(CertificatePin? pin) => Pin = pin is null ? null : new PinSetting
    {
        Scope = pin.Scope, Sha256 = pin.Sha256, Subject = SafeText.Clean(pin.Subject, 300), PinnedAt = pin.PinnedAt,
    };

    public WatchedSensor? FindWatched(string id) => Watched.FirstOrDefault(w => w.Id == id);

    public bool IsPaused(DateTimeOffset now) => PausedUntilResumed || PausedUntil is { } u && u > now;

    public bool IsMuted(string id, DateTimeOffset now) => Mutes.TryGetValue(id, out var until) && until > now;

    /// <summary>Puts whatever came from disk in order: no duplicates, no rubbish, nothing expired.</summary>
    public void Sanitize(DateTimeOffset now)
    {
        if (ServerUrl is not null) ServerUrl = ServerAddress.TryParse(ServerUrl, out var a, out _) ? a.Base : null;
        if (ProtectedKey is not null && ProtectedKey.Length > 4096) ProtectedKey = null;
        KeyHint = SafeText.Identifier(KeyHint, 4);
        House = SafeText.Clean(House, ProtocolParser.NameMax);
        if (Pin is not null && GetPin() is null) Pin = null;
        if (Pin is not null) Pin.Sha256 = CertificatePolicy.NormalizePin(Pin.Sha256)!;

        var seen = new HashSet<string>(StringComparer.Ordinal);
        Watched = (Watched ?? new()).Where(w => w is not null)
            .Select(w => new WatchedSensor { Id = SafeText.Identifier(w.Id), Name = SafeText.Clean(w.Name, ProtocolParser.NameMax), AlsoWhenClears = w.AlsoWhenClears })
            .Where(w => w.Id.Length > 0 && seen.Add(w.Id))
            .Take(ProtocolParser.MaxSensors)
            .ToList();

        var mutes = new Dictionary<string, DateTimeOffset>(StringComparer.Ordinal);
        foreach (var (id, until) in Mutes ?? new())
        {
            string clean = SafeText.Identifier(id);
            if (clean.Length > 0 && until > now) mutes[clean] = until;
        }
        Mutes = mutes;
        if (PausedUntil is { } p && p <= now) PausedUntil = null;
    }
}

[JsonSourceGenerationOptions(WriteIndented = true, PropertyNamingPolicy = JsonKnownNamingPolicy.CamelCase,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull)]
[JsonSerializable(typeof(NotifierSettings))]
internal sealed partial class SettingsJsonContext : JsonSerializerContext
{
}

/// <summary>Loads and saves settings.json (atomically: a new file is written, then moved over the old).</summary>
public sealed class SettingsStore
{
    private const int MaxFileBytes = 4 * 1024 * 1024;
    public string Path { get; }

    public SettingsStore(string path) => Path = path;

    public static string DefaultPath() => System.IO.Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), AppInfo.Name, "settings.json");

    public NotifierSettings Load(DateTimeOffset now)
    {
        NotifierSettings? s = null;
        try
        {
            var info = new FileInfo(Path);
            if (info.Exists && info.Length <= MaxFileBytes)
            {
                byte[] bytes = File.ReadAllBytes(Path);
                s = JsonSerializer.Deserialize(bytes, SettingsJsonContext.Default.NotifierSettings);
            }
        }
        catch (Exception e) when (e is JsonException or IOException or UnauthorizedAccessException or NotSupportedException)
        {
            try { File.Copy(Path, Path + ".unreadable", overwrite: true); } catch (Exception) { /* nothing more to do */ }
            s = null;
        }
        s ??= new NotifierSettings();
        s.Sanitize(now);
        return s;
    }

    public void Save(NotifierSettings settings)
    {
        string dir = System.IO.Path.GetDirectoryName(Path)!;
        Directory.CreateDirectory(dir);
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(settings, SettingsJsonContext.Default.NotifierSettings);
        string temp = Path + ".new";
        using (var fs = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None, 4096, FileOptions.WriteThrough))
        {
            fs.Write(bytes);
            fs.Flush(true);
        }
        File.Move(temp, Path, overwrite: true);
    }
}

/// <summary>Puts the key in the settings encrypted, and takes it out again.</summary>
public static class KeyVault
{
    public static void Store(NotifierSettings settings, NotifierKey key, ISecretProtector protector)
    {
        byte[] plain = Encoding.ASCII.GetBytes(key.Reveal());
        try
        {
            settings.ProtectedKey = Convert.ToBase64String(protector.Protect(plain));
            settings.KeyHint = key.Hint;
        }
        finally
        {
            Array.Clear(plain);
        }
    }

    public static void Forget(NotifierSettings settings)
    {
        settings.ProtectedKey = null;
        settings.KeyHint = null;
    }

    public static NotifierKey? TryLoad(NotifierSettings settings, ISecretProtector protector)
    {
        if (string.IsNullOrEmpty(settings.ProtectedKey)) return null;
        byte[]? plain = null;
        try
        {
            plain = protector.Unprotect(Convert.FromBase64String(settings.ProtectedKey));
            return NotifierKey.TryParse(Encoding.ASCII.GetString(plain), out var key, out _) ? key : null;
        }
        catch (Exception)
        {
            return null; // another user's or another machine's blob, or damaged
        }
        finally
        {
            if (plain is not null) Array.Clear(plain);
        }
    }
}
