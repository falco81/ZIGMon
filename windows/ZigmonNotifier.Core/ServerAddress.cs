using System;
using System.Diagnostics.CodeAnalysis;

namespace ZigmonNotifier.Core;

/// <summary>
/// The dashboard address the user typed, checked and normalised:
/// https only (plain http only to this very computer), no user:password@,
/// no query or fragment, a trailing "/index.php" or "/" dropped.
/// </summary>
public sealed class ServerAddress : IEquatable<ServerAddress>
{
    /// <summary>e.g. "https://mqtt.example.net" or "https://host:8443/zigmon" - never ends with '/'.</summary>
    public string Base { get; }
    public string Host { get; }
    public int Port { get; }
    public bool IsHttps { get; }

    private ServerAddress(string @base, string host, int port, bool https)
    {
        Base = @base;
        Host = host;
        Port = port;
        IsHttps = https;
    }

    /// <summary>The dashboard page to open in the browser.</summary>
    public Uri DashboardUri => new Uri(Base + "/", UriKind.Absolute);

    /// <summary>{base}/index.php?api=notifier&amp;do=...</summary>
    public Uri Endpoint(string what, string? extraQuery = null)
    {
        if (what is not ("hello" or "sensors" or "wait")) throw new ArgumentOutOfRangeException(nameof(what));
        string q = "api=notifier&do=" + what + (string.IsNullOrEmpty(extraQuery) ? "" : "&" + extraQuery);
        return new Uri(Base + "/index.php?" + q, UriKind.Absolute);
    }

    /// <summary>host:port, the thing a certificate pin belongs to.</summary>
    public string PinScope => Host + ":" + Port.ToString(System.Globalization.CultureInfo.InvariantCulture);

    public static bool IsLocalHost(string host)
    {
        string h = host.Trim().ToLowerInvariant();
        return h is "localhost" or "127.0.0.1" or "::1" or "[::1]";
    }

    public static ServerAddress Parse(string input)
    {
        if (!TryParse(input, out var a, out var error)) throw new FormatException(error);
        return a;
    }

    public static bool TryParse(string? input, [NotNullWhen(true)] out ServerAddress? address, [NotNullWhen(false)] out string? error)
    {
        address = null;
        string s = (input ?? string.Empty).Trim();
        if (s.Length == 0) { error = "Enter the address of your ZIGMon dashboard."; return false; }
        if (s.Length > 300) { error = "That address is too long."; return false; }
        foreach (char c in s)
        {
            if (c <= ' ' || c == '\\' || c > '~' && !char.IsLetterOrDigit(c))
            {
                error = "The address has a character an address cannot have (a space or a backslash?).";
                return false;
            }
        }
        if (!s.Contains("://", StringComparison.Ordinal)) s = "https://" + s;

        if (!Uri.TryCreate(s, UriKind.Absolute, out var uri))
        {
            error = "That does not look like a web address (for example https://zigmon.example.net).";
            return false;
        }
        bool https = uri.Scheme == Uri.UriSchemeHttps;
        if (!https && uri.Scheme != Uri.UriSchemeHttp)
        {
            error = "Only https:// addresses can be used.";
            return false;
        }
        if (!string.IsNullOrEmpty(uri.UserInfo))
        {
            error = "Leave the name and password out of the address - the key does the signing in.";
            return false;
        }
        if (!string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment) || s.Contains('?') || s.Contains('#'))
        {
            error = "Use the dashboard address only, without a ?... or #... part.";
            return false;
        }
        string host = uri.Host.ToLowerInvariant();
        if (host.Length == 0)
        {
            error = "The address has no server name.";
            return false;
        }
        if (!https && !IsLocalHost(host))
        {
            error = "Plain http:// would send the key unprotected - use https:// (http is only allowed for localhost).";
            return false;
        }

        string path = uri.AbsolutePath;
        while (true)
        {
            if (path.EndsWith("/index.php", StringComparison.OrdinalIgnoreCase)) path = path[..^"/index.php".Length];
            else if (path.EndsWith('/')) path = path[..^1];
            else break;
        }
        if (path.Contains("//", StringComparison.Ordinal) || path.Contains("/../", StringComparison.Ordinal) || path.EndsWith("/..", StringComparison.Ordinal))
        {
            error = "The path in that address looks wrong.";
            return false;
        }

        string authority = uri.GetComponents(UriComponents.SchemeAndServer, UriFormat.UriEscaped).ToLowerInvariant();
        address = new ServerAddress(authority + path, host, uri.Port, https);
        error = null;
        return true;
    }

    public bool Equals(ServerAddress? other) => other is not null && string.Equals(Base, other.Base, StringComparison.Ordinal);
    public override bool Equals(object? obj) => Equals(obj as ServerAddress);
    public override int GetHashCode() => StringComparer.Ordinal.GetHashCode(Base);
    public override string ToString() => Base;
}
