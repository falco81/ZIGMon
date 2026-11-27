using System;
using System.Globalization;
using System.Text;

namespace ZigmonNotifier.Core;

/// <summary>
/// Everything the server says is cleaned here before it is shown: control and
/// formatting characters (bidi overrides, zero-width tricks) are dropped,
/// whitespace collapsed, and the length capped by whole characters. The result
/// is only ever put in a TextBlock's Text - never parsed as markup.
/// </summary>
public static class SafeText
{
    public static string Clean(string? value, int maxLength)
    {
        if (string.IsNullOrEmpty(value) || maxLength <= 0) return string.Empty;
        // a hostile server could send megabytes in one name; look at a bounded prefix only
        string s = value.Length > maxLength * 4 + 16 ? value.Substring(0, maxLength * 4 + 16) : value;

        var sb = new StringBuilder(Math.Min(s.Length, maxLength + 8));
        bool lastSpace = true; // drops leading whitespace
        for (int i = 0; i < s.Length; i++)
        {
            char c = s[i];
            if (char.IsHighSurrogate(c))
            {
                if (i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]))
                {
                    var cat = CharUnicodeInfo.GetUnicodeCategory(s, i);
                    if (cat != UnicodeCategory.Format && cat != UnicodeCategory.PrivateUse)
                    {
                        sb.Append(c).Append(s[i + 1]);
                        lastSpace = false;
                    }
                    i++;
                }
                continue; // lone surrogate: dropped
            }
            if (char.IsLowSurrogate(c)) continue;

            var category = char.GetUnicodeCategory(c);
            if (char.IsWhiteSpace(c) || category == UnicodeCategory.Control)
            {
                if (!lastSpace) { sb.Append(' '); lastSpace = true; }
                continue;
            }
            if (category == UnicodeCategory.Format || category == UnicodeCategory.PrivateUse
                || category == UnicodeCategory.LineSeparator || category == UnicodeCategory.ParagraphSeparator
                || c == '�' || c == '￾' || c == '￿')
                continue;
            sb.Append(c);
            lastSpace = false;
        }
        string cleaned = sb.ToString().Trim();
        return Truncate(cleaned, maxLength);
    }

    /// <summary>Cuts to at most <paramref name="maxLength"/> UTF-16 units without splitting a character.</summary>
    public static string Truncate(string s, int maxLength)
    {
        if (s.Length <= maxLength) return s;
        var info = new StringInfo(s);
        var sb = new StringBuilder();
        for (int i = 0; i < info.LengthInTextElements; i++)
        {
            string el = info.SubstringByTextElements(i, 1);
            if (sb.Length + el.Length > maxLength - 1) break;
            sb.Append(el);
        }
        return sb.ToString().TrimEnd() + "…";
    }

    /// <summary>An identifier: printable ASCII without spaces, else empty.</summary>
    public static string Identifier(string? value, int maxLength = 80)
    {
        if (string.IsNullOrEmpty(value)) return string.Empty;
        string s = value.Trim();
        if (s.Length == 0 || s.Length > maxLength) return string.Empty;
        foreach (char c in s)
            if (c <= ' ' || c > '~') return string.Empty;
        return s;
    }
}
