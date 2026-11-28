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
    /// <summary>This sensor's own sound (an <see cref="AlarmSounds"/> id or "file"); null = the default one.</summary>
    public string? SoundId { get; set; }
    /// <summary>This sensor's own .wav file, when SoundId is "file".</summary>
    public string? SoundFile { get; set; }
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
    /// <summary>Old (1.1.0) "close alerts after a minute"; read once and turned into <see cref="AutoCloseSeconds"/>.</summary>
    public bool? AutoClose { get; set; }
    /// <summary>Alerts close by themselves after this many seconds; 0 = they stay until dismissed.</summary>
    public int AutoCloseSeconds { get; set; }
    /// <summary>Which built-in sound (<see cref="AlarmSounds"/>), or "file" for <see cref="SoundFile"/>.</summary>
    public string SoundId { get; set; } = AlarmSounds.DefaultId;
    /// <summary>The user's own .wav file (full path), used when SoundId is "file".</summary>
    public string? SoundFile { get; set; }
    /// <summary>How long the sound plays: seconds, 0 once, -1 until the alert is dismissed.</summary>
    public int SoundSeconds { get; set; } = AlertChoices.Once;
    /// <summary>Alarm volume 0..100 (of the Windows volume).</summary>
    public int Volume { get; set; } = 80;
    /// <summary>Where alerts appear: "primary", "cursor", or a monitor's device name (\\.\DISPLAY2).</summary>
    public string? Monitor { get; set; }
    /// <summary>Install signed updates from the connected ZIGMon by themselves (off: show them, install on a click).</summary>
    public bool AutoUpdate { get; set; } = true;

    // ---- SMS (1.4.0): this computer's own switches; ZIGMon's permissions still decide what is possible

    /// <summary>A card pops up when an SMS comes in (off: it is only listed in Messages).</summary>
    public bool SmsPopups { get; set; } = true;
    /// <summary>A Stream Deck key may make this app show the latest SMS or open a new message.</summary>
    public bool DeckPopups { get; set; } = true;
    /// <summary>A short sound when an SMS comes in (once, at the alert volume; not the alarm).</summary>
    public bool SmsSound { get; set; } = true;
    /// <summary>The sound an SMS makes (an <see cref="AlarmSounds"/> id; not a file).</summary>
    public string SmsSoundId { get; set; } = AlarmSounds.DefaultId;

    /// <summary>Whether an incoming SMS should pop up now (switched on, and alerts not paused).</summary>
    public bool ShowsSmsPopup(DateTimeOffset now) => SmsPopups && !IsPaused(now);

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
            .Select(w => CleanWatched(w))
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

        if (AutoClose == true && AutoCloseSeconds == 0) AutoCloseSeconds = 60; // 1.1.0's "after a minute"
        AutoClose = null;
        AutoCloseSeconds = AlertChoices.Snap(AutoCloseSeconds, AlertChoices.CloseAfter, 0);
        SoundSeconds = AlertChoices.Snap(SoundSeconds, AlertChoices.SoundLengths, AlertChoices.Once);
        Volume = Math.Clamp(Volume, 0, 100);
        SoundFile = CleanSoundFile(SoundFile);
        if (SoundId == AlarmSounds.FileId) { if (SoundFile is null) SoundId = AlarmSounds.DefaultId; }
        else if (!AlarmSounds.IsKnown(SoundId)) SoundId = AlarmSounds.DefaultId;
        Monitor = Monitor is AlertChoices.MonitorPrimary or AlertChoices.MonitorCursor ? Monitor : CleanMonitor(Monitor);
        if (!AlarmSounds.IsKnown(SmsSoundId)) SmsSoundId = AlarmSounds.DefaultId;
    }

    private static WatchedSensor CleanWatched(WatchedSensor w)
    {
        string? file = CleanSoundFile(w.SoundFile);
        string? sound = w.SoundId == AlarmSounds.FileId ? (file is null ? null : AlarmSounds.FileId)
            : AlarmSounds.IsKnown(w.SoundId) ? w.SoundId : null;
        return new WatchedSensor
        {
            Id = SafeText.Identifier(w.Id), Name = SafeText.Clean(w.Name, ProtocolParser.NameMax),
            AlsoWhenClears = w.AlsoWhenClears, SoundId = sound, SoundFile = sound == AlarmSounds.FileId ? file : null,
        };
    }

    /// <summary>The sound for an alert of this sensor: its own when it has one, else the default (id, file).</summary>
    public (string Id, string? File) SoundFor(string? sensorId)
    {
        var w = sensorId is null ? null : FindWatched(sensorId);
        if (w?.SoundId is { } own) return (own, own == AlarmSounds.FileId ? w.SoundFile : null);
        return (SoundId, SoundId == AlarmSounds.FileId ? SoundFile : null);
    }

    /// <summary>A full local path to a .wav file, or null.</summary>
    public static string? CleanSoundFile(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || path.Length > 1024) return null;
        if (path.Any(char.IsControl)) return null;
        try
        {
            if (!System.IO.Path.IsPathFullyQualified(path)) return null;
        }
        catch (ArgumentException)
        {
            return null;
        }
        return path.EndsWith(".wav", StringComparison.OrdinalIgnoreCase) ? path : null;
    }

    /// <summary>A monitor's device name as Windows gives it (\\.\DISPLAY1), or null (= the primary one).</summary>
    public static string? CleanMonitor(string? name)
    {
        if (string.IsNullOrEmpty(name) || name.Length > 64) return null;
        return name.All(c => c is >= ' ' and <= '~') ? name : null;
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
