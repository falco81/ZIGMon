using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>One conversation in the list (plain values, made again on every refresh).</summary>
public sealed class ConversationRow
{
    public string Key { get; init; } = "";
    public string Title { get; init; } = "";
    public string Preview { get; init; } = "";
    public string When { get; init; } = "";
    public string Initials { get; init; } = "";
    public Brush Accent { get; init; } = Brushes.Gray;
    public Brush AccentSoft { get; init; } = Brushes.Transparent;
    public Brush AccentEdge { get; init; } = Brushes.Transparent;
    public Brush WhenBrush { get; init; } = Brushes.Gray;
    public Visibility GlyphVisibility { get; init; }
    public Visibility UnreadVisibility { get; init; }
    public string Search { get; init; } = "";
}

/// <summary>One suggestion under the To box.</summary>
public sealed class SuggestionRow
{
    public Recipient Recipient { get; init; } = Recipient.ForNumber("000");
    public string Title => Recipient.Title;
    public string Detail => Recipient.Detail;
    public string Glyph { get; init; } = "";
    public Brush Accent { get; init; } = Brushes.Gray;
    public Brush AccentSoft { get; init; } = Brushes.Transparent;
    public Visibility FavouriteVisibility => Recipient.Favourite ? Visibility.Visible : Visibility.Collapsed;
}

/// <summary>
/// (1.4.0) Messages: the conversations on the left (from ZIGMon's SMS log, by contact or number,
/// newest first), the chosen one as bubbles on the right, and the box to write in. "New" writes
/// to anyone: chips with an autocomplete over the contacts, their groups and numbers, the
/// favourites as quick chips, and any typed number.
/// </summary>
public partial class MessagesWindow : Window
{
    private readonly AppController _app;
    private readonly List<Recipient> _chips = new();
    private IReadOnlyList<SmsConversation> _threads = Array.Empty<SmsConversation>();
    private string? _currentKey;
    private bool _composing = true;
    private bool _filling;
    private bool _sending;
    private string _filter = "";

    internal MessagesWindow(AppController app)
    {
        InitializeComponent();
        Ui.ApplyIcon(this);
        _app = app;
        SourceInitialized += (_, _) => Native.DarkTitleBar(this);
        _app.SmsChanged += Refresh;
        _app.StatusChanged += ApplyPermissions;
        Closed += (_, _) =>
        {
            _app.SmsChanged -= Refresh;
            _app.StatusChanged -= ApplyPermissions;
        };
        Activated += (_, _) => { if (!_composing && _currentKey is not null) _app.MarkRead(_currentKey); };
        PreviewKeyDown += OnWindowKey;
        ApplyPermissions();
        Refresh();
        ShowNew(Array.Empty<Recipient>());
    }

    private SmsPermissions Sms => _app.Sms;
    private ContactBook Book => _app.Contacts;

    // ---- what may be done ----------------------------------------------------------------

    private void ApplyPermissions()
    {
        var p = Sms;
        HouseText.Text = string.IsNullOrEmpty(_app.Settings.House) ? "SMS through ZIGMon" : "SMS through ZIGMon · " + _app.Settings.House;
        NewButton.Visibility = p.CanSend ? Visibility.Visible : Visibility.Collapsed;
        bool canWrite = p.CanSend;
        ComposeArea.Visibility = canWrite ? Visibility.Visible : Visibility.Collapsed;
        ComposeOff.Visibility = canWrite ? Visibility.Collapsed : Visibility.Visible;
        ComposeOffText.Text = !p.Any
            ? "This ZIGMon does not offer SMS to the desktop app (it needs ZIGMon 5.59.4 or newer, and an administrator to allow it)."
            : !p.Send
                ? "Sending is not allowed for this computer. An administrator can allow it in ZIGMon: Settings → Messages → Desktop app → this key → SMS."
                : "ZIGMon's SMS gateway is not set up yet, so nothing can be sent just now.";
        FavRow.Visibility = p.Contacts && Book.Contacts.Any(c => c.Favourite) ? Visibility.Visible : Visibility.Collapsed;
        ToBox.Tag = p.Contacts ? "Name, group or number" : "Phone number";
        UpdateFooter();
        UpdateSendState();
    }

    // ---- the list ------------------------------------------------------------------------

    private void Refresh()
    {
        _threads = Sms.Read ? SmsThreads.Group(_app.SmsMessages) : Array.Empty<SmsConversation>();
        var now = DateTimeOffset.Now;
        var rows = new List<ConversationRow>();
        foreach (var t in _threads)
        {
            string accent = Avatars.Accent(t.Key);
            string initials = Avatars.Initials(t.ContactId is null ? null : t.Title);
            bool unread = _app.IsUnread(t.Key);
            var last = t.Last;
            rows.Add(new ConversationRow
            {
                Key = t.Key,
                Title = t.Title,
                Preview = (last.Incoming ? "" : "You: ") + OneLine(last.Text),
                When = ShortWhen(last.At, now),
                Initials = initials,
                GlyphVisibility = initials.Length == 0 ? Visibility.Visible : Visibility.Collapsed,
                Accent = Ui.Brush(accent),
                AccentSoft = Ui.Brush(accent, 0x26),
                AccentEdge = Ui.Brush(accent, 0x59),
                WhenBrush = unread ? Ui.Brush(Palette.Info) : Ui.Brush(Palette.TextMuted),
                UnreadVisibility = unread ? Visibility.Visible : Visibility.Collapsed,
                Search = (t.Title + " " + t.Number + " " + SmsNumbers.Key(t.Number) + " " + string.Join(" ", t.Messages.Select(m => m.Text))).ToLowerInvariant(),
            });
        }
        _filling = true;
        var shown = _filter.Length == 0 ? rows : rows.Where(r => _filter.Split(' ', StringSplitOptions.RemoveEmptyEntries).All(r.Search.Contains)).ToList();
        List.ItemsSource = shown;
        List.SelectedItem = _composing ? null : shown.FirstOrDefault(r => r.Key == _currentKey);
        _filling = false;

        bool none = shown.Count == 0;
        ListEmpty.Visibility = none ? Visibility.Visible : Visibility.Collapsed;
        if (!Sms.Read)
        {
            ListEmptyGlyph.Text = "";
            ListEmptyTitle.Text = "Reading is off";
            ListEmptyBody.Text = Sms.Any
                ? "This computer may send, but not read, SMS. An administrator can allow reading in ZIGMon."
                : "This ZIGMon does not share SMS with the desktop app.";
        }
        else if (_filter.Length > 0)
        {
            ListEmptyGlyph.Text = "";
            ListEmptyTitle.Text = "Nothing found";
            ListEmptyBody.Text = "No conversation has “" + SafeText.Clean(_filter, 40) + "”.";
        }
        else
        {
            ListEmptyGlyph.Text = "";
            ListEmptyTitle.Text = "No messages yet";
            ListEmptyBody.Text = _app.SmsProblem ?? "SMS that come in and go out through ZIGMon show here.";
        }

        if (!_composing && _currentKey is not null) ShowThreadBody();
        FavRow.Visibility = Sms.Contacts && Book.Contacts.Any(c => c.Favourite) ? Visibility.Visible : Visibility.Collapsed;
        BuildFavourites();
        UpdateFooter();
    }

    private void UpdateFooter()
    {
        if (_app.SmsProblem is { } p)
        {
            FootDot.Fill = Ui.Brush(Palette.Crit);
            Footer.Text = p;
            Footer.ToolTip = p;
            return;
        }
        bool connected = _app.Status.State == ConnectionState.Connected;
        FootDot.Fill = connected ? Ui.Brush(Palette.Ok) : Ui.Brush(Palette.TextDim);
        int n = _threads.Count;
        string when = _app.SmsReadAt is { } at ? " · " + at.ToLocalTime().ToString("t", CultureInfo.CurrentCulture) : "";
        Footer.Text = !connected ? _app.ShortStatus : Sms.Read ? n + (n == 1 ? " conversation" : " conversations") + when : "Connected";
        Footer.ToolTip = null;
    }

    private static string OneLine(string s) => s.Replace('\n', ' ');

    private static string ShortWhen(DateTimeOffset at, DateTimeOffset now)
    {
        var local = at.ToLocalTime();
        if (local.Date == now.Date) return local.ToString("t", CultureInfo.CurrentCulture);
        if (local.Date == now.Date.AddDays(-1)) return "Yesterday";
        if (now - local < TimeSpan.FromDays(6)) return local.ToString("ddd", CultureInfo.CurrentCulture);
        return local.ToString("d", CultureInfo.CurrentCulture);
    }

    private void OnSearch(object sender, TextChangedEventArgs e)
    {
        _filter = SafeText.Clean(SearchBox.Text, 60).ToLowerInvariant();
        Refresh();
    }

    private void OnPick(object sender, SelectionChangedEventArgs e)
    {
        if (_filling || List.SelectedItem is not ConversationRow row) return;
        OpenThread(row.Key, null);
    }

    private async void OnRefresh(object sender, RoutedEventArgs e)
    {
        RefreshButton.IsEnabled = false;
        try
        {
            await _app.RefreshSmsAsync();
            await _app.RefreshContactsAsync();
        }
        finally
        {
            RefreshButton.IsEnabled = true;
        }
    }

    private void OnWindowKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.N && (Keyboard.Modifiers & ModifierKeys.Control) != 0 && Sms.CanSend)
        {
            ShowNew(Array.Empty<Recipient>());
            e.Handled = true;
        }
        else if (e.Key == Key.F5)
        {
            OnRefresh(sender, e);
            e.Handled = true;
        }
        else if (e.Key == Key.Escape && Suggest.IsOpen)
        {
            Suggest.IsOpen = false;
            e.Handled = true;
        }
    }

    // ---- a conversation ------------------------------------------------------------------

    /// <summary>Shows one conversation (by its thread key), with a draft in the box if given.</summary>
    internal void OpenThread(string key, string? draft)
    {
        if (_threads.All(t => t.Key != key))
        {
            // not in the list (yet): a new message to that number, so nothing is lost
            var number = key.StartsWith("number:", StringComparison.Ordinal) ? key["number:".Length..] : "";
            ShowNew(number.Length > 0 ? new[] { Recipient.ForNumber(number, Book.ByNumber(number)?.Name) } : Array.Empty<Recipient>());
            if (draft is not null) MessageText.Text = draft;
            return;
        }
        _composing = false;
        _currentKey = key;
        ToPanel.Visibility = Visibility.Collapsed;
        Suggest.IsOpen = false;
        if (draft is not null) MessageText.Text = draft;
        _filling = true;
        List.SelectedItem = (List.ItemsSource as IEnumerable<ConversationRow>)?.FirstOrDefault(r => r.Key == key);
        if (List.SelectedItem is not null) List.ScrollIntoView(List.SelectedItem);
        _filling = false;
        ShowFeedback(null, false);
        ShowThreadBody();
        _app.MarkRead(key);
        UpdateSendState();
        FocusText();
    }

    /// <summary>The conversation shown, or null while writing a new message.</summary>
    internal string? CurrentKey => _composing ? null : _currentKey;

    private SmsConversation? Current => _composing ? null : _threads.FirstOrDefault(t => t.Key == _currentKey);

    private void ShowThreadBody()
    {
        var t = Current;
        if (t is null) return;
        string accent = Avatars.Accent(t.Key);
        string initials = Avatars.Initials(t.ContactId is null ? null : t.Title);
        HeadAvatar.Fill = Ui.Brush(accent, 0x26);
        HeadAvatar.Stroke = Ui.Brush(accent, 0x59);
        HeadInitials.Text = initials;
        HeadInitials.Foreground = Ui.Brush(accent);
        HeadGlyph.Text = "";
        HeadGlyph.Foreground = Ui.Brush(accent);
        HeadGlyph.Visibility = initials.Length == 0 ? Visibility.Visible : Visibility.Collapsed;
        HeadTitle.Text = t.Title;
        var contact = t.ContactId is { } id ? Book.Find(id) : Book.ByNumber(t.Number);
        HeadSub.Text = t.Number + (contact?.Group is { Length: > 0 } g ? " · " + g : "") + " · " + t.Messages.Count + (t.Messages.Count == 1 ? " message" : " messages");
        CopyNumberButton.Visibility = t.Number.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        ToNewButton.Visibility = Sms.CanSend && t.Number.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        MessageText.Tag = "Write to " + t.Title + "…";
        ThreadEmpty.Visibility = Visibility.Collapsed;
        BuildBubbles(t);
    }

    private void BuildBubbles(SmsConversation t)
    {
        Bubbles.Children.Clear();
        DateTime? day = null;
        SmsMessage? prev = null;
        foreach (var m in t.Messages)
        {
            var local = m.At.ToLocalTime();
            if (day != local.Date)
            {
                day = local.Date;
                Bubbles.Children.Add(DaySeparator(local));
                prev = null;
            }
            bool sameSide = prev is not null && prev.Incoming == m.Incoming && m.At - prev.At < TimeSpan.FromMinutes(5);
            Bubbles.Children.Add(Bubble(m, sameSide));
            prev = m;
        }
        Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() => ThreadScroll.ScrollToEnd()));
    }

    private static UIElement DaySeparator(DateTimeOffset local)
    {
        var today = DateTimeOffset.Now.Date;
        string text = local.Date == today ? "Today" : local.Date == today.AddDays(-1) ? "Yesterday" : local.ToString("D", CultureInfo.CurrentCulture);
        return new Border
        {
            HorizontalAlignment = HorizontalAlignment.Center,
            Margin = new Thickness(0, 14, 0, 8),
            Padding = new Thickness(10, 2, 10, 3),
            CornerRadius = new CornerRadius(9),
            Background = Ui.Brush(Palette.Panel2),
            BorderBrush = Ui.Brush(Palette.Line),
            BorderThickness = new Thickness(1),
            Child = new TextBlock { Text = text, FontSize = 11.5, Foreground = Ui.Brush(Palette.TextDim) },
        };
    }

    private UIElement Bubble(SmsMessage m, bool sameSide)
    {
        bool failed = !m.Incoming && m.Ok == false;
        string accent = failed ? Palette.Crit : Palette.Info;
        var text = new TextBox
        {
            Style = (Style)FindResource("BareField"),
            Text = m.Text, // plain text from the core, cleaned
            IsReadOnly = true,
            IsTabStop = false,
            TextWrapping = TextWrapping.Wrap,
            AcceptsReturn = true,
            FontSize = 14,
            Padding = new Thickness(0),
            Foreground = Ui.Brush(Palette.Text),
            Cursor = Cursors.IBeam,
        };
        var bubble = new Border
        {
            MaxWidth = 520,
            HorizontalAlignment = m.Incoming ? HorizontalAlignment.Left : HorizontalAlignment.Right,
            Padding = new Thickness(13, 8, 13, 9),
            Margin = new Thickness(m.Incoming ? 0 : 80, sameSide ? 2 : 8, m.Incoming ? 80 : 0, 0),
            CornerRadius = m.Incoming ? new CornerRadius(sameSide ? 14 : 4, 14, 14, 14) : new CornerRadius(14, sameSide ? 14 : 4, 14, 14),
            Background = m.Incoming ? Ui.Brush(Palette.Panel2) : Ui.Brush(accent, 0x2E),
            BorderBrush = m.Incoming ? Ui.Brush(Palette.Line) : Ui.Brush(accent, 0x66),
            BorderThickness = new Thickness(1),
            Child = text,
        };
        string time = m.At.ToLocalTime().ToString("t", CultureInfo.CurrentCulture);
        string state = m.Incoming ? "" : m.Ok switch { true => " · Sent", false => " · Not sent", null => m.Id.StartsWith("local-", StringComparison.Ordinal) ? " · Sending…" : "" };
        var meta = new TextBlock
        {
            Text = time + state,
            FontSize = 11,
            Foreground = failed ? Ui.Brush(Palette.Crit) : Ui.Brush(Palette.TextMuted),
            HorizontalAlignment = bubble.HorizontalAlignment,
            Margin = new Thickness(4, 3, 4, 0),
            ToolTip = m.At.ToLocalTime().ToString("F", CultureInfo.CurrentCulture),
        };
        var stack = new StackPanel();
        stack.Children.Add(bubble);
        stack.Children.Add(meta);
        return stack;
    }

    private void OnCopyNumber(object sender, RoutedEventArgs e)
    {
        if (Current is { Number.Length: > 0 } t && Ui.CopyText(t.Number)) ShowFeedback("Number copied.", true);
    }

    /// <summary>A new message starting with this conversation's person, to add others.</summary>
    private void OnForward(object sender, RoutedEventArgs e)
    {
        if (Current is not { } t) return;
        string draft = MessageText.Text;
        ShowNew(new[] { Recipient.ForNumber(t.Number, t.ContactId is null ? null : t.Title) });
        MessageText.Text = draft;
        Keyboard.Focus(ToBox);
    }

    // ---- a new message -------------------------------------------------------------------

    private void OnNew(object sender, RoutedEventArgs e) => ShowNew(Array.Empty<Recipient>());

    /// <summary>A new message, to these people (the Stream Deck's, or none); the cursor goes to the text when they are given.</summary>
    internal void ShowNew(IReadOnlyList<Recipient> to)
    {
        _composing = true;
        _currentKey = null;
        _chips.Clear();
        foreach (var r in to) if (Recipients.IsWire(r.Wire) && _chips.All(c => c.Wire != r.Wire)) _chips.Add(r);
        ToBox.Text = "";
        ToProblem.Visibility = Visibility.Collapsed;
        ToPanel.Visibility = Visibility.Visible;
        _filling = true;
        List.SelectedItem = null;
        _filling = false;
        HeadAvatar.Fill = Ui.Brush(Palette.Info, 0x1F);
        HeadAvatar.Stroke = Ui.Brush(Palette.Info, 0x59);
        HeadInitials.Text = "";
        HeadGlyph.Text = "";
        HeadGlyph.Foreground = Ui.Brush(Palette.Info);
        HeadGlyph.Visibility = Visibility.Visible;
        HeadTitle.Text = "New message";
        HeadSub.Text = Sms.Contacts ? "To people from your contacts, a whole group, or any number" : "To any phone number";
        CopyNumberButton.Visibility = Visibility.Collapsed;
        ToNewButton.Visibility = Visibility.Collapsed;
        MessageText.Tag = "Write a message…";
        Bubbles.Children.Clear();
        ThreadEmpty.Visibility = Visibility.Visible;
        ThreadEmptyTitle.Text = _chips.Count > 0 ? "Ready to write" : "Write to anyone in your contacts";
        ThreadEmptyBody.Text = "ZIGMon sends it from its own SMS gateway, with its own daily limits, and keeps it in its SMS log.";
        ShowFeedback(null, false);
        BuildChips();
        BuildFavourites();
        UpdateSendState();
        if (_chips.Count > 0) FocusText();
        else Dispatcher.BeginInvoke(DispatcherPriority.Input, new Action(() => Keyboard.Focus(ToBox)));
    }

    internal void FocusText()
    {
        Dispatcher.BeginInvoke(DispatcherPriority.Input, new Action(() =>
        {
            MessageText.Focus();
            Keyboard.Focus(MessageText);
            MessageText.CaretIndex = MessageText.Text.Length;
        }));
    }

    private void BuildChips()
    {
        while (Chips.Children.Count > 1) Chips.Children.RemoveAt(0);
        int i = 0;
        foreach (var r in _chips) Chips.Children.Insert(i++, Chip(r));
        ToCount.Text = _composing && _chips.Count > 0
            ? "To " + _chips.Count + (_chips.Count == 1 ? " recipient" : " recipients")
              + (_chips.Any(c => c.Kind == RecipientKind.Group) ? " · ZIGMon writes to each member of a group" : "")
            : "";
    }

    private UIElement Chip(Recipient r)
    {
        string accent = r.Kind switch { RecipientKind.Group => Palette.Rule, RecipientKind.Contact => Palette.Info, _ => Palette.TextDim };
        if (r.Kind == RecipientKind.Number && r.Title != r.Wire) accent = Palette.Info; // a contact's own number
        var row = new StackPanel { Orientation = Orientation.Horizontal };
        row.Children.Add(new TextBlock
        {
            Style = (Style)FindResource("Glyph"), FontSize = 11, Foreground = Ui.Brush(accent), Margin = new Thickness(0, 0, 6, 0),
            Text = r.Kind switch { RecipientKind.Group => "", RecipientKind.Contact => "", _ => r.Title != r.Wire ? "" : "" },
        });
        row.Children.Add(new TextBlock { Text = r.Title, FontSize = 13, Foreground = Ui.Brush(Palette.Text), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 220, TextTrimming = TextTrimming.CharacterEllipsis });
        var remove = new Button
        {
            Style = (Style)FindResource("IconButton"), Width = 20, Height = 20, Margin = new Thickness(4, 0, 0, 0),
            Content = "", FontSize = 8.5, ToolTip = "Remove", Tag = r, IsTabStop = false,
        };
        remove.Click += (_, _) =>
        {
            _chips.RemoveAll(c => c.Wire == r.Wire);
            BuildChips();
            UpdateSendState();
            Keyboard.Focus(ToBox);
        };
        row.Children.Add(remove);
        return new Border
        {
            CornerRadius = new CornerRadius(13),
            Padding = new Thickness(9, 3, 3, 3),
            Margin = new Thickness(0, 2, 6, 2),
            Background = Ui.Brush(accent, 0x1F),
            BorderBrush = Ui.Brush(accent, 0x59),
            BorderThickness = new Thickness(1),
            Child = row,
            ToolTip = r.Detail,
            Cursor = Cursors.Arrow,
        };
    }

    private void BuildFavourites()
    {
        Favourites.Children.Clear();
        if (!Sms.Contacts) return;
        foreach (var c in Book.Contacts.Where(c => c.Favourite).Take(8))
        {
            var r = Recipient.ForContact(c);
            string accent = Avatars.Accent("contact:" + c.Id);
            var b = new Button
            {
                Style = (Style)FindResource("GhostButton"),
                Padding = new Thickness(5, 3, 10, 3),
                Margin = new Thickness(0, 0, 6, 0),
                FontSize = 12.5,
                FontWeight = FontWeights.Normal,
                ToolTip = "Add " + c.Name + " (" + r.Detail + ")",
            };
            var content = new StackPanel { Orientation = Orientation.Horizontal };
            var dot = new Grid { Width = 20, Height = 20 };
            dot.Children.Add(new System.Windows.Shapes.Ellipse { Fill = Ui.Brush(accent, 0x33) });
            dot.Children.Add(new TextBlock
            {
                Text = Avatars.Initials(c.Name), FontSize = 9, FontWeight = FontWeights.SemiBold, Foreground = Ui.Brush(accent),
                HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
            });
            content.Children.Add(dot);
            content.Children.Add(new TextBlock { Text = c.Name, Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center });
            b.Content = content;
            b.Click += (_, _) => AddChip(r);
            Favourites.Children.Add(b);
        }
    }

    private void AddChip(Recipient r, bool focus = true)
    {
        if (!Recipients.IsWire(r.Wire)) return;
        if (_chips.Count >= Recipients.MaxRecipients)
        {
            ShowToProblem("At most " + Recipients.MaxRecipients + " recipients at once.");
            return;
        }
        if (_chips.All(c => c.Wire != r.Wire)) _chips.Add(r);
        ToBox.Text = "";
        Suggest.IsOpen = false;
        ToProblem.Visibility = Visibility.Collapsed;
        BuildChips();
        UpdateSendState();
        if (focus) Keyboard.Focus(ToBox);
    }

    private void ShowToProblem(string text)
    {
        ToProblem.Text = text;
        ToProblem.Visibility = Visibility.Visible;
    }

    private void OnToFrameClick(object sender, MouseButtonEventArgs e) => Keyboard.Focus(ToBox);

    private void OnToChanged(object sender, TextChangedEventArgs e)
    {
        string t = ToBox.Text;
        ToProblem.Visibility = Visibility.Collapsed;
        if (t.Length > 0 && (t.EndsWith(',') || t.EndsWith(';')))
        {
            CommitTyped(t.TrimEnd(',', ';'));
            return;
        }
        var found = Recipients.Suggest(t, Sms.Contacts ? Book : ContactBook.Empty, 8)
            .Where(r => _chips.All(c => c.Wire != r.Wire)).ToList();
        if (t.Trim().Length == 0 || found.Count == 0)
        {
            Suggest.IsOpen = false;
            return;
        }
        SuggestList.ItemsSource = found.Select(r =>
        {
            string accent = r.Kind == RecipientKind.Group ? Palette.Rule : r.Kind == RecipientKind.Number && r.Title == r.Wire ? Palette.TextDim : Avatars.Accent(r.Wire);
            return new SuggestionRow
            {
                Recipient = r,
                Glyph = r.Kind switch { RecipientKind.Group => "", RecipientKind.Contact => "", _ => r.Title != r.Wire ? "" : "" },
                Accent = Ui.Brush(accent),
                AccentSoft = Ui.Brush(accent, 0x26),
            };
        }).ToList();
        SuggestList.SelectedIndex = 0;
        Suggest.IsOpen = true;
    }

    private void OnToKey(object sender, KeyEventArgs e)
    {
        switch (e.Key)
        {
            case Key.Down when Suggest.IsOpen:
                SuggestList.SelectedIndex = Math.Min(SuggestList.Items.Count - 1, SuggestList.SelectedIndex + 1);
                SuggestList.ScrollIntoView(SuggestList.SelectedItem);
                e.Handled = true;
                break;
            case Key.Up when Suggest.IsOpen:
                SuggestList.SelectedIndex = Math.Max(0, SuggestList.SelectedIndex - 1);
                SuggestList.ScrollIntoView(SuggestList.SelectedItem);
                e.Handled = true;
                break;
            case Key.Enter:
            case Key.Tab when ToBox.Text.Trim().Length > 0:
                if (Suggest.IsOpen && SuggestList.SelectedItem is SuggestionRow s) AddChip(s.Recipient);
                else if (ToBox.Text.Trim().Length > 0) CommitTyped(ToBox.Text);
                else if (e.Key == Key.Enter && _chips.Count > 0) FocusText();
                e.Handled = true;
                break;
            case Key.Back when ToBox.Text.Length == 0 && _chips.Count > 0:
                _chips.RemoveAt(_chips.Count - 1);
                BuildChips();
                UpdateSendState();
                e.Handled = true;
                break;
        }
    }

    private void OnToLostFocus(object sender, KeyboardFocusChangedEventArgs e)
    {
        // a typed number becomes a chip when the cursor moves on; anything else is said to be unknown
        if (ToBox.Text.Trim().Length > 0) CommitTyped(ToBox.Text, quiet: true);
    }

    private void CommitTyped(string typed, bool quiet = false)
    {
        var (chips, bad) = Recipients.Parse(typed, Sms.Contacts ? Book : ContactBook.Empty);
        foreach (var c in chips) AddChip(c, focus: !quiet);
        if (bad.Count > 0)
        {
            ToBox.Text = typed.Trim();
            ToBox.CaretIndex = ToBox.Text.Length;
            ShowToProblem("Not a contact, group or phone number: " + string.Join(", ", bad) + (quiet ? "" : ". Pick from the list, or type the number."));
        }
        if (!quiet) Keyboard.Focus(ToBox);
    }

    private void OnSuggestClick(object sender, MouseButtonEventArgs e)
    {
        if (ItemsControl.ContainerFromElement(SuggestList, e.OriginalSource as DependencyObject) is ListBoxItem { DataContext: SuggestionRow s })
        {
            e.Handled = true; // the To box keeps the keyboard
            AddChip(s.Recipient);
        }
    }

    // ---- writing and sending -------------------------------------------------------------

    private void OnTextChanged(object sender, TextChangedEventArgs e) => UpdateSendState();

    private void UpdateSendState()
    {
        var c = SmsCounter.Count(MessageText.Text);
        Counter.Text = c.Text;
        bool many = c.Parts >= SmsCounter.ManyParts;
        Counter.Foreground = many ? Ui.Brush(Palette.Warn) : Ui.Brush(Palette.TextDim);
        CounterChip.BorderBrush = many ? Ui.Brush(Palette.Warn, 0x59) : Ui.Brush(Palette.Line);
        CounterChip.ToolTip = many
            ? "A long message: the network sends it as " + c.Parts + " SMS, and ZIGMon counts each against its limits."
            : "Characters, and how many SMS the network sends it as: 160 a part (153 when split); with accents or emoji 70 (67)";
        bool to = _composing ? _chips.Count > 0 : Current is { Number.Length: > 0 };
        SendButton.IsEnabled = !_sending && Sms.CanSend && to && MessageText.Text.Trim().Length > 0;
        if (!_composing) ToCount.Text = "";
    }

    private void OnTextKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && (Keyboard.Modifiers & ModifierKeys.Control) != 0)
        {
            e.Handled = true;
            if (SendButton.IsEnabled) OnSend(sender, e);
            else if (_composing && _chips.Count == 0) ShowFeedback("Add someone to send it to first.", false, error: true);
        }
    }

    private async void OnSend(object sender, RoutedEventArgs e)
    {
        if (_sending) return;
        if (_composing && ToBox.Text.Trim().Length > 0) CommitTyped(ToBox.Text, quiet: true);
        var thread = Current;
        IReadOnlyList<string> to = _composing ? Recipients.ToWire(_chips) : thread is { Number.Length: > 0 } t ? new[] { t.Number } : Array.Empty<string>();
        string text = MessageText.Text;
        if (to.Count == 0 || text.Trim().Length == 0) return;
        string? replyTo = thread?.Messages.LastOrDefault(m => m.Incoming)?.Id;
        string names = _composing
            ? (_chips.Count == 1 ? _chips[0].Title : _chips[0].Title + " and " + (_chips.Count - 1) + (_chips.Count == 2 ? " other" : " others"))
            : thread!.Title;
        var sentChips = _chips.ToList();

        _sending = true;
        SendButton.IsEnabled = false;
        SendText.Text = "Sending…";
        MessageText.IsReadOnly = true;
        ShowFeedback("Sending to " + names + "…", false);
        SmsSendResult r;
        try
        {
            r = await _app.SendSmsAsync(to, text, replyTo);
        }
        finally
        {
            _sending = false;
            SendText.Text = "Send";
            MessageText.IsReadOnly = false;
        }
        if (r.Ok)
        {
            MessageText.Clear();
            string detail = r.Failed > 0 ? " · " + r.Message : r.Sent > 1 ? " · " + r.Sent + " SMS sent" : "";
            if (_composing && sentChips.Count == 1 && sentChips[0].Kind != RecipientKind.Group)
            {
                // one person: go on in their conversation
                var c0 = sentChips[0];
                var keys = new List<string> { c0.Kind == RecipientKind.Contact ? c0.Wire : "number:" + SmsNumbers.Key(c0.Wire) };
                if (c0.Kind == RecipientKind.Number && Book.ByNumber(c0.Wire) is { } owner) keys.Add("contact:" + owner.Id);
                Refresh();
                var key = keys.FirstOrDefault(k => _threads.Any(x => x.Key == k));
                if (key is not null) OpenThread(key, null);
            }
            ShowFeedback("Sent to " + names + detail, r.Failed == 0, error: false, warn: r.Failed > 0);
        }
        else
        {
            ShowFeedback("Not sent: " + r.Message, false, error: true);
        }
        UpdateSendState();
        FocusText();
    }

    private void ShowFeedback(string? text, bool ok, bool error = false, bool warn = false)
    {
        if (text is null)
        {
            Feedback.Visibility = Visibility.Collapsed;
            return;
        }
        string accent = ok ? Palette.Ok : error ? Palette.Crit : warn ? Palette.Warn : Palette.Info;
        Feedback.Background = Ui.Brush(accent, 0x1F);
        Feedback.BorderBrush = Ui.Brush(accent, 0x59);
        FeedbackGlyph.Text = ok ? "" : error ? "" : warn ? "" : "";
        FeedbackGlyph.Foreground = Ui.Brush(accent);
        FeedbackText.Text = text;
        FeedbackText.Foreground = Ui.Brush(Palette.Text);
        Feedback.Visibility = Visibility.Visible;
    }
}
