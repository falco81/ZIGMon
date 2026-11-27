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

/// <summary>The chime, made once in memory and played without waiting.</summary>
internal static class Sounds
{
    private static SoundPlayer? _player;
    private static DateTime _last = DateTime.MinValue;

    public static void Chime()
    {
        try
        {
            if ((DateTime.UtcNow - _last).TotalMilliseconds < 1200) return; // several at once: one chime
            _last = DateTime.UtcNow;
            if (_player is null)
            {
                _player = new SoundPlayer(new MemoryStream(Core.Chime.CreateWav()));
                _player.Load();
            }
            _player.Play();
        }
        catch (Exception)
        {
            // no sound device: alerts still show
        }
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
