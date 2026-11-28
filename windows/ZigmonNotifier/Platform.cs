using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Media;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Media;
using Microsoft.Win32;
using ZigmonNotifier.Core;

namespace ZigmonNotifier;

/// <summary>DPAPI for the current Windows user, with this app's own entropy.</summary>
internal sealed class DpapiProtector : ISecretProtector
{
    private static readonly byte[] Entropy = SHA256.HashData(Encoding.UTF8.GetBytes("ZIGMon Notifier / notifier key / v1"));

    public byte[] Protect(byte[] plain) => ProtectedData.Protect(plain, Entropy, DataProtectionScope.CurrentUser);

    public byte[] Unprotect(byte[] protectedData) => ProtectedData.Unprotect(protectedData, Entropy, DataProtectionScope.CurrentUser);
}

/// <summary>"Start with Windows": one value under HKCU\Software\Microsoft\Windows\CurrentVersion\Run.</summary>
internal static class Autostart
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "ZIGMon Notifier";

    private static string? ExePath => Environment.ProcessPath;

    private static string Command => "\"" + ExePath + "\" --autostart";

    public static bool IsEnabled
    {
        get
        {
            try
            {
                using var k = Registry.CurrentUser.OpenSubKey(RunKey, false);
                return k?.GetValue(ValueName) is string v && string.Equals(v, Command, StringComparison.OrdinalIgnoreCase);
            }
            catch (Exception)
            {
                return false;
            }
        }
    }

    public static bool Set(bool enabled)
    {
        try
        {
            using var k = Registry.CurrentUser.CreateSubKey(RunKey, true);
            if (enabled && ExePath is not null) k.SetValue(ValueName, Command, RegistryValueKind.String);
            else k.DeleteValue(ValueName, false);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}

/// <summary>
/// Plays the alarm the user chose, at their volume, once or repeated for a while or until
/// the alert is dismissed. The sound is made in memory (or read from their .wav file).
/// </summary>
internal static class Sounds
{
    private static SoundPlayer? _player;
    private static string _playerKey = "";
    private static DateTime _last = DateTime.MinValue;
    private static System.Windows.Threading.DispatcherTimer? _stopTimer;

    /// <summary>Why the user's own file could not be played last time (shown in the settings), or "".</summary>
    public static string FileProblem { get; private set; } = "";

    /// <summary>Plays for an alert, as the settings say.</summary>
    public static void Alarm(NotifierSettings s, string? sensorId, bool force = false)
    {
        if (!force && (DateTime.UtcNow - _last).TotalMilliseconds < 1200) return; // several at once: one sound
        _last = DateTime.UtcNow;
        var (id, file) = s.SoundFor(sensorId);
        Play(id, file, s.Volume, s.SoundSeconds);
    }

    /// <summary>Plays these choices (the settings window's Test).</summary>
    public static void Play(string soundId, string? file, int volume, int seconds)
    {
        Stop();
        try
        {
            var p = PlayerFor(soundId, file, volume);
            if (p is null) return;
            if (seconds == AlertChoices.Once)
            {
                p.Play();
                return;
            }
            p.PlayLooping();
            var length = seconds == AlertChoices.UntilDismissed ? AlertChoices.LongestSound : TimeSpan.FromSeconds(seconds);
            _stopTimer = new System.Windows.Threading.DispatcherTimer { Interval = length };
            _stopTimer.Tick += (_, _) => Stop();
            _stopTimer.Start();
        }
        catch (Exception)
        {
            // no sound device: alerts still show
        }
    }

    public static void Stop()
    {
        _stopTimer?.Stop();
        _stopTimer = null;
        try
        {
            _player?.Stop();
        }
        catch (Exception)
        {
            // nothing playing
        }
    }

    private static SoundPlayer? PlayerFor(string soundId, string? file, int volume)
    {
        string key = soundId + "|" + file + "|" + volume;
        if (_player is not null && _playerKey == key) return _player;
        byte[]? wav = null;
        if (soundId == AlarmSounds.FileId && file is not null)
        {
            FileProblem = "";
            try
            {
                var info = new FileInfo(file);
                if (!info.Exists) FileProblem = "The sound file is gone.";
                else if (info.Length > WavAudio.MaxFileBytes) FileProblem = "The file is larger than 20 MB.";
                else
                {
                    wav = WavAudio.FromFile(File.ReadAllBytes(file), volume, out string why);
                    FileProblem = why;
                }
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
            {
                FileProblem = "The sound file cannot be read.";
            }
            // the user's file unusable: the alarm still sounds, with the default
        }
        wav ??= WavAudio.Builtin(soundId == AlarmSounds.FileId ? AlarmSounds.DefaultId : soundId, volume);
        _player?.Dispose();
        _player = new SoundPlayer(new MemoryStream(wav));
        _player.Load();
        _playerKey = key;
        return _player;
    }
}

/// <summary>Opens only the dashboard address, checked again right before.</summary>
internal static class Browser
{
    public static bool OpenDashboard(string? serverUrl)
    {
        if (!ServerAddress.TryParse(serverUrl, out var a, out _)) return false;
        var uri = a.DashboardUri;
        if (uri.Scheme != Uri.UriSchemeHttps && !(uri.Scheme == Uri.UriSchemeHttp && ServerAddress.IsLocalHost(uri.Host))) return false;
        try
        {
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}

/// <summary>The Windows-only end of the self-update: starting the new exe.</summary>
internal static class SelfUpdate
{
    /// <summary>The running exe's full path (the single-file app's own file), or null.</summary>
    public static string? ExePath
    {
        get
        {
            string? p = Environment.ProcessPath;
            return !string.IsNullOrEmpty(p) && Path.IsPathFullyQualified(p) && p.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ? p : null;
        }
    }

    /// <summary>Starts exactly that file (no shell, no search path) with these arguments.</summary>
    public static bool Start(string exe, IReadOnlyList<string> args)
    {
        var psi = new ProcessStartInfo(exe)
        {
            UseShellExecute = false,
            WorkingDirectory = Path.GetDirectoryName(exe) ?? "",
        };
        foreach (var a in args) psi.ArgumentList.Add(a);
        using var p = Process.Start(psi);
        return p is not null;
    }
}

/// <summary>Brushes and geometries made from the Core's strings, frozen and cached.</summary>
internal static class Ui
{
    private static readonly Dictionary<string, SolidColorBrush> BrushCache = new();
    private static readonly Dictionary<string, Geometry> GeometryCache = new();

    public static SolidColorBrush Brush(string hex, byte alpha = 255)
    {
        string k = hex + "/" + alpha;
        if (BrushCache.TryGetValue(k, out var b)) return b;
        Color c;
        try
        {
            c = (Color)ColorConverter.ConvertFromString(hex);
        }
        catch (FormatException)
        {
            c = Colors.Gray;
        }
        c.A = alpha;
        b = new SolidColorBrush(c);
        b.Freeze();
        BrushCache[k] = b;
        return b;
    }

    private static System.Windows.Media.ImageSource? _icon;
    private static bool _iconTried;

    /// <summary>The app icon on a window's title bar and taskbar button; a window without it is no reason to fail.</summary>
    public static void ApplyIcon(System.Windows.Window w)
    {
        if (!_iconTried)
        {
            _iconTried = true;
            try
            {
                var frame = System.Windows.Media.Imaging.BitmapFrame.Create(
                    new Uri("pack://application:,,,/Assets/app.ico", UriKind.Absolute));
                if (frame.CanFreeze) frame.Freeze();
                _icon = frame;
            }
            catch (Exception)
            {
                _icon = null;
            }
        }
        if (_icon is not null) w.Icon = _icon;
    }

    /// <summary>Puts plain text on the clipboard (which another program may hold for a moment: a few tries).</summary>
    public static bool CopyText(string text)
    {
        for (int i = 0; i < 4; i++)
        {
            try
            {
                System.Windows.Clipboard.SetDataObject(text ?? "", true);
                return true;
            }
            catch (System.Runtime.InteropServices.ExternalException)
            {
                System.Threading.Thread.Sleep(40);
            }
        }
        return false;
    }

    public static Geometry Geometry(string path)
    {
        if (GeometryCache.TryGetValue(path, out var g)) return g;
        try
        {
            g = System.Windows.Media.Geometry.Parse(path);
        }
        catch (Exception)
        {
            g = System.Windows.Media.Geometry.Empty;
        }
        if (g.CanFreeze) g.Freeze();
        GeometryCache[path] = g;
        return g;
    }
}
