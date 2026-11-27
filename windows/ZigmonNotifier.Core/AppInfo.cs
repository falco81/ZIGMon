namespace ZigmonNotifier.Core;

/// <summary>Fixed facts about the app; nothing here is secret.</summary>
public static class AppInfo
{
    public const string Name = "ZIGMon Notifier";
    public const string Version = "1.2.0";
    public const string UserAgent = "ZigmonNotifier/" + Version + " (Windows)";

    /// <summary>The header that carries the notifier key - and the only place the key ever travels.</summary>
    public const string KeyHeader = "X-Zigmon-Notifier";

    /// <summary>Protocol version this build speaks (hello's "api").</summary>
    public const int ProtocolVersion = 1;
}
