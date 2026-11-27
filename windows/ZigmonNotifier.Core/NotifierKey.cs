using System;
using System.Diagnostics.CodeAnalysis;

namespace ZigmonNotifier.Core;

/// <summary>
/// A notifier key ("zmn_" + 40 url-safe characters). The value can only be read
/// inside this library (to put it in the X-Zigmon-Notifier header or to encrypt
/// it); ToString and the debugger show only the last two characters.
/// </summary>
[System.Diagnostics.DebuggerDisplay("{ToString(),nq}")]
public sealed class NotifierKey
{
    public const string Prefix = "zmn_";
    private readonly string _value;

    private NotifierKey(string value) => _value = value;

    /// <summary>The last two characters - what ZIGMon also shows as the key's hint.</summary>
    public string Hint => _value[^2..];

    /// <summary>Only for the request header and DPAPI. Never log, show or put it in a message.</summary>
    internal string Reveal() => _value;

    public static bool TryParse(string? input, [NotNullWhen(true)] out NotifierKey? key, [NotNullWhen(false)] out string? error)
    {
        key = null;
        string s = (input ?? string.Empty).Trim();
        if (s.Length == 0) { error = "Paste the key ZIGMon showed when the key was made."; return false; }
        if (!s.StartsWith(Prefix, StringComparison.Ordinal))
        {
            error = "A desktop-app key starts with \"zmn_\". Make one in ZIGMon: Settings → Messages → Desktop app.";
            return false;
        }
        // the relay keeps [A-Za-z0-9_-]{0,80}; ZIGMon itself makes 44 characters
        if (s.Length < Prefix.Length + 20 || s.Length > 80)
        {
            error = "That key is not the right length - copy it again, all of it.";
            return false;
        }
        foreach (char c in s)
        {
            if (!(c is >= 'a' and <= 'z' or >= 'A' and <= 'Z' or >= '0' and <= '9' or '_' or '-'))
            {
                error = "The key has a character a key cannot have - copy it again.";
                return false;
            }
        }
        key = new NotifierKey(s);
        error = null;
        return true;
    }

    /// <summary>Replaces any copy of the key in <paramref name="text"/> (an echo from a server, say).</summary>
    public string Scrub(string? text)
    {
        if (string.IsNullOrEmpty(text)) return string.Empty;
        string t = text.Replace(_value, "zmn_…" + Hint, StringComparison.Ordinal);
        // and the secret part alone, in case the prefix was cut off
        string body = _value[Prefix.Length..];
        if (body.Length >= 8) t = t.Replace(body, "…" + Hint, StringComparison.Ordinal);
        return t;
    }

    public bool SameAs(NotifierKey? other) =>
        other is not null && System.Security.Cryptography.CryptographicOperations.FixedTimeEquals(
            System.Text.Encoding.ASCII.GetBytes(_value), System.Text.Encoding.ASCII.GetBytes(other._value));

    public override string ToString() => "notifier key …" + Hint;
    public override bool Equals(object? obj) => obj is NotifierKey k && SameAs(k);
    public override int GetHashCode() => Hint.GetHashCode(StringComparison.Ordinal);
}
