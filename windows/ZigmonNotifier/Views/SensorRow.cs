using System;
using System.Collections.Generic;
using System.Linq;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Windows;
using System.Windows.Media;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>A sound in a drop-down: an id (null = the default sound) and its name.</summary>
public sealed record SoundOption(string? Id, string Name)
{
    public override string ToString() => Name;
}

/// <summary>One line of the Watched sensors list. All text is cleaned plain text from the core.</summary>
public sealed class SensorRow : INotifyPropertyChanged
{
    private readonly AppController _app;
    private SensorInfo? _sensor;
    private bool _watched;
    private bool _alsoWhenClears;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Id { get; }
    public string Name { get; private set; } = "";
    public string Subtitle { get; private set; } = "";
    public string Search { get; private set; } = "";
    public Geometry Icon { get; private set; } = Geometry.Empty;
    public Brush Accent { get; private set; } = Brushes.Gray;
    public Brush AccentSoft { get; private set; } = Brushes.Transparent;
    public Brush AccentEdge { get; private set; } = Brushes.Transparent;
    public string StateText { get; private set; } = "";
    public Brush StateFg { get; private set; } = Brushes.Gray;
    public Brush StateBg { get; private set; } = Brushes.Transparent;
    public Brush StateEdge { get; private set; } = Brushes.Transparent;
    public string StateTip { get; private set; } = "";
    public bool IsMissing => _sensor is null;
    public Visibility MissingVisibility => IsMissing ? Visibility.Visible : Visibility.Collapsed;
    public Visibility ClearsVisibility => _watched && _sensor is not null && _sensor.Kind != SensorKinds.Button
        ? Visibility.Visible : Visibility.Collapsed;
    public string ClearsText { get; private set; } = "";

    /// <summary>The sound choices: the default, every built-in one, and the user's own file.</summary>
    public List<SoundOption> SoundOptions { get; private set; } = new();
    private SoundOption? _sound;
    public Visibility WatchedVisibility => _watched && _sensor is not null ? Visibility.Visible : Visibility.Collapsed;

    public SoundOption? SelectedSound
    {
        get => _sound;
        set
        {
            if (value is null || ReferenceEquals(value, _sound)) return;
            if (value.Id == AlarmSounds.FileId)
            {
                string? file = _app.PickSoundFile();
                if (file is null)
                {
                    Raise(); // cancelled: the drop-down goes back to what it was
                    return;
                }
                _app.SetSound(Id, AlarmSounds.FileId, file);
            }
            else _app.SetSound(Id, value.Id, null);
            BuildSounds();
            Raise(nameof(SoundOptions));
            Raise();
        }
    }

    /// <summary>Plays this sensor's sound once, at the set volume.</summary>
    public void PlaySound()
    {
        var (id, file) = _app.Settings.SoundFor(Id);
        Sounds.Play(id, file, _app.Settings.Volume, AlertChoices.Once);
    }

    private void BuildSounds()
    {
        var w = _app.Settings.FindWatched(Id);
        var list = new List<SoundOption>
        {
            new(null, "Default sound (" + DefaultName() + ")"),
        };
        list.AddRange(AlarmSounds.All.Select(a => new SoundOption(a.Id, a.Name)));
        string fileName = w?.SoundId == AlarmSounds.FileId && w.SoundFile is { } f ? System.IO.Path.GetFileName(f) : "";
        list.Add(new SoundOption(AlarmSounds.FileId, fileName.Length > 0 ? "Own file: " + fileName : "Own WAV file…"));
        SoundOptions = list;
        _sound = list.FirstOrDefault(o => o.Id == w?.SoundId) ?? list[0];
    }

    private string DefaultName()
    {
        var st = _app.Settings;
        if (st.SoundId == AlarmSounds.FileId && st.SoundFile is { } f) return System.IO.Path.GetFileName(f);
        return AlarmSounds.Find(st.SoundId).Name;
    }

    internal SensorRow(AppController app, string id)
    {
        _app = app;
        Id = id;
    }

    public bool IsWatched
    {
        get => _watched;
        set
        {
            if (_watched == value) return;
            _watched = value;
            if (_sensor is not null) _app.SetWatched(_sensor, value);
            else if (!value) _app.ForgetWatched(Id);
            BuildSounds();
            Raise(string.Empty);
        }
    }

    public bool AlsoWhenClears
    {
        get => _alsoWhenClears;
        set
        {
            if (_alsoWhenClears == value) return;
            _alsoWhenClears = value;
            _app.SetAlsoWhenClears(Id, value);
            Raise();
        }
    }

    /// <summary>From what ZIGMon said (or, for a sensor the key no longer offers, from the settings).</summary>
    internal void Fill(SensorInfo? s, string fallbackName)
    {
        _sensor = s;
        var style = KindStyle.For(s?.Kind);
        Name = s?.Name ?? (fallbackName.Length > 0 ? fallbackName : Id);
        Icon = Ui.Geometry(style.IconPath);
        string accent = s is null ? Palette.TextMuted : style.Accent;
        Accent = Ui.Brush(accent);
        AccentSoft = Ui.Brush(accent, 0x1F);
        AccentEdge = Ui.Brush(accent, 0x4D);

        if (s is null)
        {
            Subtitle = "No longer offered by this key";
            SetState("Gone", Palette.TextMuted);
            StateTip = "ZIGMon no longer lists this sensor for this key. Switch it off to forget it.";
            ClearsText = "";
        }
        else
        {
            string sub = s.Kind == SensorKinds.Rule && s.RuleText is { } rt
                ? rt + (s.ValueText is { } vt ? " · now " + vt : "")
                : style.Label;
            if (s.Kind == SensorKinds.Rule && s.DeviceName is { } dn && dn != s.Name) sub = dn + " · " + sub;
            if (!string.IsNullOrEmpty(s.Room)) sub = s.Room + " · " + sub;
            if (s.Battery is { } b) sub += " · battery " + b.ToString(System.Globalization.CultureInfo.CurrentCulture) + " %";
            Subtitle = sub;
            string word = style.StateWord(s.Active, s.Online);
            string colour = !s.Online ? Palette.TextMuted
                : s.Kind == SensorKinds.Button ? Palette.TextDim
                : s.Active == true ? style.Accent
                : s.Active == false ? Palette.Ok
                : Palette.TextMuted;
            SetState(word, colour);
            StateTip = s.At is { } at ? "Changed " + TimeText.Ago(at, DateTimeOffset.UtcNow) : "No change seen yet";
            ClearsText = s.Kind == SensorKinds.Rule
                ? "Also when it is no longer met"
                : "Also when it clears (" + style.QuietWord.ToLowerInvariant() + " again)";
        }
        Search = (Name + " " + Subtitle + " " + style.Kind).ToLowerInvariant();

        var w = _app.Settings.FindWatched(Id);
        _watched = w is not null;
        _alsoWhenClears = w?.AlsoWhenClears ?? false;
        BuildSounds();
        Raise(string.Empty); // everything
    }

    private void SetState(string word, string colour)
    {
        StateText = word;
        StateFg = Ui.Brush(colour);
        StateBg = Ui.Brush(colour, 0x1C);
        StateEdge = Ui.Brush(colour, 0x47);
    }

    private void Raise([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
