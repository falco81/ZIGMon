using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace ZigmonNotifier.Core;

/// <summary>
/// What the key may do with SMS (hello.sms, ZIGMon 5.59.4). An older ZIGMon sends no
/// "sms" at all: then <see cref="None"/>, and every SMS feature of the app stays hidden.
/// </summary>
public sealed record SmsPermissions(bool Read, bool Send, bool Contacts, bool Ready)
{
    public static readonly SmsPermissions None = new(false, false, false, false);

    /// <summary>Whether anything SMS is offered at all.</summary>
    public bool Any => Read || Send;

    /// <summary>"Write an SMS…" is offered: the key may send and the gateway is set up.</summary>
    public bool CanSend => Send && Ready;
}

/// <summary>A contact as an SMS names it: its id and name (or null when the number is nobody's).</summary>
public sealed record SmsContactRef(string Id, string Name);

/// <summary>One SMS from ZIGMon's own log, in or out.</summary>
public sealed record SmsMessage(
    string Id, bool Incoming, string Number, SmsContactRef? Contact, string Text, DateTimeOffset At, bool? Ok)
{
    /// <summary>The name to show: the contact's, else the number.</summary>
    public string Who => Contact is { Name.Length: > 0 } c ? c.Name : Number.Length > 0 ? Number : "Unknown number";

    /// <summary>What groups it into a conversation: the contact, else the number.</summary>
    public string ThreadKey => Contact is { Id.Length: > 0 } c ? "contact:" + c.Id : "number:" + SmsNumbers.Key(Number);
}

/// <summary>A person the Stream Deck asked to write to (already expanded by ZIGMon to a number).</summary>
public sealed record DeckRecipient(string Id, string Name, string Number);

/// <summary>A Stream Deck key asking this app to show the latest SMS or to open a new message.</summary>
public sealed record DeckAsk(string What, string Install, string Computer, IReadOnlyList<DeckRecipient> To)
{
    public const string Last = "last";
    public const string Compose = "compose";
}

public sealed record ContactNumber(string Label, string Number);

/// <summary>One row of ZIGMon's contacts (read-only here).</summary>
public sealed record Contact(string Id, string Name, IReadOnlyList<ContactNumber> Numbers, string Group, string Note, bool Favourite);

public sealed record ContactBook(IReadOnlyList<Contact> Contacts, IReadOnlyList<string> Groups)
{
    public static readonly ContactBook Empty = new(Array.Empty<Contact>(), Array.Empty<string>());

    public Contact? Find(string id) => Contacts.FirstOrDefault(c => c.Id == id);

    /// <summary>The contact one of whose numbers this is, or null.</summary>
    public Contact? ByNumber(string number)
    {
        string k = SmsNumbers.Key(number);
        if (k.Length == 0) return null;
        return Contacts.FirstOrDefault(c => c.Numbers.Any(n => SmsNumbers.Key(n.Number) == k));
    }
}

/// <summary>What ZIGMon said about a send.</summary>
public sealed record SmsSendResult(bool Ok, int Sent, int Failed, string Message);

/// <summary>Phone numbers: cleaned, checked, compared.</summary>
public static class SmsNumbers
{
    public const int MaxLength = 24;

    /// <summary>Digits and a leading +, else empty: "+420 777 123 456" → "+420777123456".</summary>
    public static string Clean(string? s)
    {
        if (string.IsNullOrEmpty(s) || s.Length > 64) return string.Empty;
        var sb = new StringBuilder(s.Length);
        foreach (char c in s.Trim())
        {
            if (c is >= '0' and <= '9') sb.Append(c);
            else if (c == '+' && sb.Length == 0) sb.Append(c);
            else if (c is ' ' or '-' or '.' or '(' or ')' or '/' or ' ') continue;
            else return string.Empty;
        }
        string r = sb.ToString();
        int digits = r.Count(char.IsAsciiDigit);
        return digits is >= 3 and <= 20 && r.Length <= MaxLength ? r : string.Empty;
    }

    public static bool IsNumber(string? s) => Clean(s).Length > 0;

    /// <summary>The same phone written two ways compares equal: "+420…" and "00420…".</summary>
    public static string Key(string? s)
    {
        string c = Clean(s);
        if (c.StartsWith("00", StringComparison.Ordinal)) c = "+" + c[2..];
        return c;
    }

    /// <summary>"…456": a number shown where it need not be read in full.</summary>
    public static string Masked(string? s)
    {
        string c = Clean(s);
        return c.Length <= 3 ? c : "…" + c[^3..];
    }
}

/// <summary>How long a text is in SMS terms: GSM-7 160 / 153 a part, UCS-2 70 / 67.</summary>
public sealed record SmsCount(int Characters, int Units, int Parts, bool Unicode, int PerPart, int Left)
{
    /// <summary>"42 / 160 · 1 SMS", "170 / 306 · 2 SMS", "Unicode: 12 / 70 · 1 SMS".</summary>
    public string Text
    {
        get
        {
            string parts = Parts.ToString(CultureInfo.InvariantCulture) + " SMS";
            string n = Units.ToString(CultureInfo.InvariantCulture) + " / " + (PerPart * Math.Max(1, Parts)).ToString(CultureInfo.InvariantCulture);
            return (Unicode ? "Unicode · " : "") + n + " · " + parts;
        }
    }
}

public static class SmsCounter
{
    public const int GsmSingle = 160, GsmPart = 153, UcsSingle = 70, UcsPart = 67;
    /// <summary>The app refuses longer texts before ZIGMon has to (10 parts of GSM-7).</summary>
    public const int MaxText = 1530;
    public const int ManyParts = 6;

    private const string Extension = "{}[]~\\|^";

    /// <summary>
    /// Counted the way ZIGMon counts it (zigmon.py sms_parts), so the numbers here and the
    /// server's limits agree: any character past ASCII makes the whole text UCS-2 (UTF-16
    /// units, an emoji is two); otherwise GSM-7 septets, where {}[]~\|^ take an escape and are two.
    /// </summary>
    public static SmsCount Count(string? text)
    {
        string t = text ?? string.Empty;
        bool wide = t.Any(c => c > 127);
        int units = wide ? t.Length : t.Length + t.Count(c => Extension.IndexOf(c) >= 0);
        int one = wide ? UcsSingle : GsmSingle, more = wide ? UcsPart : GsmPart;
        int parts = units == 0 ? 0 : units <= one ? 1 : (units + more - 1) / more;
        int per = parts <= 1 ? one : more;
        int left = parts == 0 ? one : per * parts - units;
        int chars = new StringInfo(t).LengthInTextElements;
        return new SmsCount(chars, units, parts, wide, per, left);
    }
}

/// <summary>Who a message goes to, as a chip: a contact, a group, or a typed number.</summary>
public enum RecipientKind { Contact, Group, Number }

/// <summary>
/// One recipient chip. <see cref="Wire"/> is what goes in the send's "to": "contact:&lt;id&gt;",
/// "group:&lt;name&gt;" or a number (ZIGMon expands and de-duplicates).
/// </summary>
public sealed record Recipient(RecipientKind Kind, string Wire, string Title, string Detail, bool Favourite = false)
{
    public static Recipient ForNumber(string number, string? name = null)
    {
        string n = SmsNumbers.Clean(number);
        return new Recipient(RecipientKind.Number, n, string.IsNullOrEmpty(name) ? n : name, string.IsNullOrEmpty(name) ? "Number" : n);
    }

    public static Recipient ForContact(Contact c) =>
        c.Numbers.Count == 1
            ? new Recipient(RecipientKind.Contact, "contact:" + c.Id, c.Name, c.Numbers[0].Number, c.Favourite)
            : new Recipient(RecipientKind.Contact, "contact:" + c.Id, c.Name, c.Numbers.Count + " numbers", c.Favourite);

    public static Recipient ForContactNumber(Contact c, ContactNumber n) =>
        new(RecipientKind.Number, n.Number, c.Name, (n.Label.Length > 0 ? n.Label + " · " : "") + n.Number, c.Favourite);

    public static Recipient ForGroup(string group, int members) =>
        new(RecipientKind.Group, "group:" + group, group,
            "Group · " + members.ToString(CultureInfo.InvariantCulture) + (members == 1 ? " contact" : " contacts"));
}

/// <summary>Turns what is typed in the To box into chips, and offers contacts while typing.</summary>
public static class Recipients
{
    public const int MaxRecipients = 20;
    public const int GroupMax = 40;

    private static readonly CompareInfo Compare = CultureInfo.InvariantCulture.CompareInfo;
    private const CompareOptions Loose = CompareOptions.IgnoreCase | CompareOptions.IgnoreNonSpace;

    /// <summary>Whether a "to" entry is one ZIGMon takes: a number, contact:&lt;id&gt; or group:&lt;name&gt;.</summary>
    public static bool IsWire(string? s)
    {
        if (string.IsNullOrEmpty(s)) return false;
        if (s.StartsWith("contact:", StringComparison.Ordinal)) return ContactIds.IsValid(s["contact:".Length..]);
        if (s.StartsWith("group:", StringComparison.Ordinal))
        {
            string g = s["group:".Length..];
            return g.Length is > 0 and <= GroupMax && SafeText.Clean(g, GroupMax) == g;
        }
        return SmsNumbers.Clean(s) == s;
    }

    /// <summary>
    /// One typed entry: a number, a contact's exact name (a contact with one number) or a
    /// group's name; "contact:…" / "group:…" as such. Null when it is none of these.
    /// </summary>
    public static Recipient? Resolve(string? typed, ContactBook book)
    {
        string t = SafeText.Clean(typed, 100).Trim(',', ';', ' ');
        if (t.Length == 0) return null;
        if (t.StartsWith("contact:", StringComparison.Ordinal))
            return book.Find(t["contact:".Length..]) is { } byId ? Recipient.ForContact(byId) : null;
        if (t.StartsWith("group:", StringComparison.Ordinal))
        {
            string g = t["group:".Length..];
            var known = book.Groups.FirstOrDefault(x => string.Equals(x, g, StringComparison.OrdinalIgnoreCase));
            return known is null ? null : Recipient.ForGroup(known, book.Contacts.Count(c => c.Group == known));
        }
        string n = SmsNumbers.Clean(t);
        if (n.Length > 0)
        {
            var owner = book.ByNumber(n);
            return Recipient.ForNumber(n, owner?.Name);
        }
        var c = book.Contacts.FirstOrDefault(x => Compare.Compare(x.Name, t, Loose) == 0);
        if (c is not null) return Recipient.ForContact(c);
        var group = book.Groups.FirstOrDefault(x => Compare.Compare(x, t, Loose) == 0);
        if (group is not null) return Recipient.ForGroup(group, book.Contacts.Count(x => x.Group == group));
        return null;
    }

    /// <summary>
    /// A pasted or typed list ("+420 777 123 456, Jana Nováková; Family"): the chips it makes,
    /// and the pieces that were not understood. Separators are , ; and new lines.
    /// </summary>
    public static (IReadOnlyList<Recipient> Chips, IReadOnlyList<string> NotUnderstood) Parse(string? text, ContactBook book)
    {
        var chips = new List<Recipient>();
        var bad = new List<string>();
        foreach (string piece in (text ?? "").Split(new[] { ',', ';', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries))
        {
            string p = piece.Trim();
            if (p.Length == 0) continue;
            var r = Resolve(p, book);
            if (r is null) bad.Add(SafeText.Clean(p, 40));
            else if (chips.All(x => x.Wire != r.Wire)) chips.Add(r);
        }
        return (chips, bad);
    }

    /// <summary>The "to" list for a send: each chip's wire form, duplicates dropped, at most 20.</summary>
    public static IReadOnlyList<string> ToWire(IEnumerable<Recipient> chips) =>
        chips.Select(c => c.Wire).Where(IsWire).Distinct(StringComparer.Ordinal).Take(MaxRecipients).ToList();

    /// <summary>
    /// Suggestions while typing: contacts by name (accents and case ignored), by any of their
    /// numbers' digits, by group; groups by name; favourites first. A contact with several
    /// numbers is offered once per number.
    /// </summary>
    public static IReadOnlyList<Recipient> Suggest(string? query, ContactBook book, int max = 8)
    {
        string q = SafeText.Clean(query, 60);
        var found = new List<(int Rank, Recipient R)>();
        if (q.Length == 0)
        {
            foreach (var c in book.Contacts.Where(c => c.Favourite).Take(max))
                found.Add((0, Recipient.ForContact(c)));
            return found.Select(f => f.R).ToList();
        }
        string digits = new string(q.Where(char.IsAsciiDigit).ToArray());
        bool numeric = digits.Length >= 2 && q.All(ch => char.IsAsciiDigit(ch) || ch is '+' or ' ' or '-');
        foreach (var c in book.Contacts)
        {
            int rank;
            if (Compare.IsPrefix(c.Name, q, Loose)) rank = 0;
            else if (c.Name.Split(' ').Any(w => Compare.IsPrefix(w, q, Loose))) rank = 1;
            else if (Compare.IndexOf(c.Name, q, Loose) >= 0) rank = 2;
            else if (numeric && c.Numbers.Any(n => n.Number.Contains(digits, StringComparison.Ordinal))) rank = 3;
            else if (c.Group.Length > 0 && Compare.IsPrefix(c.Group, q, Loose)) rank = 4;
            else continue;
            if (!c.Favourite) rank += 10;
            if (c.Numbers.Count > 1)
                foreach (var n in c.Numbers) found.Add((rank, Recipient.ForContactNumber(c, n)));
            else found.Add((rank, Recipient.ForContact(c)));
        }
        foreach (var g in book.Groups)
            if (Compare.IsPrefix(g, q, Loose) || Compare.IndexOf(g, q, Loose) >= 0)
                found.Add((5, Recipient.ForGroup(g, book.Contacts.Count(x => x.Group == g))));
        var list = found.OrderBy(f => f.Rank).ThenBy(f => f.R.Title, StringComparer.CurrentCultureIgnoreCase)
            .Select(f => f.R).Take(max).ToList();
        string n2 = SmsNumbers.Clean(q);
        if (n2.Length > 0 && list.All(r => SmsNumbers.Key(r.Wire) != SmsNumbers.Key(n2)))
            list.Insert(0, Recipient.ForNumber(n2, book.ByNumber(n2)?.Name));
        return list.Take(max).ToList();
    }
}

public static class ContactIds
{
    /// <summary>"c_" and 6-12 lowercase hex, as ZIGMon makes them.</summary>
    public static bool IsValid(string? id)
    {
        if (id is null || id.Length is < 8 or > 14 || !id.StartsWith("c_", StringComparison.Ordinal)) return false;
        for (int i = 2; i < id.Length; i++)
            if (id[i] is not ((>= '0' and <= '9') or (>= 'a' and <= 'f'))) return false;
        return true;
    }
}

/// <summary>One conversation of the Messages window: everything with one contact or one number.</summary>
public sealed record SmsConversation(string Key, string Title, string Number, string? ContactId, IReadOnlyList<SmsMessage> Messages)
{
    public SmsMessage Last => Messages[^1];
}

public static class SmsThreads
{
    /// <summary>Groups by contact (else number), each oldest first; the conversations newest first.</summary>
    public static IReadOnlyList<SmsConversation> Group(IEnumerable<SmsMessage> messages)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var unique = messages.Where(m => m.Id.Length == 0 || seen.Add(m.Id)).ToList();
        return unique
            .GroupBy(m => m.ThreadKey, StringComparer.Ordinal)
            .Select(g =>
            {
                var list = g.OrderBy(m => m.At).ToList();
                var named = list.LastOrDefault(m => m.Contact is not null);
                string number = list.LastOrDefault(m => m.Number.Length > 0)?.Number ?? "";
                string title = named?.Contact?.Name is { Length: > 0 } n ? n : number.Length > 0 ? number : "Unknown number";
                return new SmsConversation(g.Key, title, number, named?.Contact?.Id, list);
            })
            .OrderByDescending(c => c.Last.At)
            .ToList();
    }
}

/// <summary>A round avatar's letters and colour, the same for the same person every time.</summary>
public static class Avatars
{
    private static readonly string[] Accents = { Palette.Info, Palette.Batt, Palette.Water, Palette.Rule, Palette.Load, Palette.Ok, Palette.Warn };

    /// <summary>"Jana Nováková" → "JN", "jana" → "J", a number or nothing → "" (the app shows a person glyph).</summary>
    public static string Initials(string? name)
    {
        string n = SafeText.Clean(name, 80);
        if (n.Length == 0 || SmsNumbers.IsNumber(n)) return "";
        var words = n.Split(' ', StringSplitOptions.RemoveEmptyEntries)
            .Where(w => char.IsLetterOrDigit(w, 0)).ToList();
        if (words.Count == 0) return "";
        string first = new StringInfo(words[0]).SubstringByTextElements(0, 1);
        string last = words.Count > 1 ? new StringInfo(words[^1]).SubstringByTextElements(0, 1) : "";
        return (first + last).ToUpper(CultureInfo.CurrentCulture);
    }

    public static string Accent(string? key)
    {
        uint h = 2166136261;
        foreach (char c in key ?? "") h = (h ^ c) * 16777619;
        return Accents[h % (uint)Accents.Length];
    }
}
