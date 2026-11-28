using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>The sound (which, how long, how loud) and the alert window (when it closes, which monitor). Saved at once.</summary>
public partial class AlertSettingsWindow : Window
{
    private readonly AppController _app;
    private readonly Dictionary<string, RadioButton> _soundRows = new();
    private bool _filling;
    private bool _testing;

    internal AlertSettingsWindow(AppController app)
    {
        InitializeComponent();
        Ui.ApplyIcon(this);
        _app = app;
        SourceInitialized += (_, _) => Native.DarkTitleBar(this);
        Closed += (_, _) =>
        {
            if (_testing) Sounds.Stop();
            _app.StatusChanged -= FillSms;
        };
        _app.StatusChanged += FillSms;
        Build();
        Fill();
    }

    private NotifierSettings S => _app.Settings;

    // ---- building the choices ------------------------------------------------------------

    private void Build()
    {
        foreach (var a in AlarmSounds.All)
        {
            var row = new RadioButton { GroupName = "sound", Style = (Style)FindResource("ChoiceRow"), Tag = a.Id };
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var words = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            words.Children.Add(new TextBlock { Text = a.Name, FontWeight = FontWeights.SemiBold });
            words.Children.Add(new TextBlock { Text = a.Note, Style = (Style)FindResource("Hint") });
            grid.Children.Add(words);
            var play = new Button { Style = (Style)FindResource("IconButton"), ToolTip = "Play " + a.Name, Tag = a.Id };
            play.Content = new TextBlock { Style = (Style)FindResource("Glyph"), FontSize = 12, Text = "" };
            play.Click += (_, e) =>
            {
                Sounds.Play(a.Id, null, S.Volume, AlertChoices.Once);
                e.Handled = true;
            };
            Grid.SetColumn(play, 1);
            grid.Children.Add(play);
            row.Content = grid;
            row.Click += (_, _) => Choose(a.Id);
            _soundRows[a.Id] = row;
            SoundList.Children.Add(row);
        }

        foreach (int s in AlertChoices.SoundLengths)
        {
            var pill = new RadioButton { GroupName = "length", Style = (Style)FindResource("Choice"), Content = AlertChoices.SoundLengthText(s), Tag = s };
            pill.Click += (_, _) => { S.SoundSeconds = s; _app.Save(); };
            LengthChoices.Children.Add(pill);
        }
        foreach (int s in AlertChoices.CloseAfter)
        {
            var pill = new RadioButton { GroupName = "close", Style = (Style)FindResource("Choice"), Content = AlertChoices.CloseAfterText(s), Tag = s };
            pill.Click += (_, _) => { S.AutoCloseSeconds = s; _app.Save(); };
            CloseChoices.Children.Add(pill);
        }
        BuildMonitors();

        // (1.4.0) the SMS sound: the gentle ones only, once
        foreach (var id in new[] { "chime", "doorbell", "bell", "beeps" })
        {
            var a = AlarmSounds.Find(id);
            var pill = new RadioButton { GroupName = "smssound", Style = (Style)FindResource("Choice"), Content = a.Name, Tag = a.Id, ToolTip = a.Note };
            pill.Click += (_, _) =>
            {
                S.SmsSoundId = a.Id;
                _app.Save();
                Sounds.Play(a.Id, null, S.Volume, AlertChoices.Once);
            };
            SmsSoundChoices.Children.Add(pill);
        }
    }

    private void BuildMonitors()
    {
        _filling = true;
        var monitors = MonitorChoice.Ordered(Native.Monitors());
        var items = new List<ComboBoxItem>
        {
            new() { Content = "The primary monitor", Tag = AlertChoices.MonitorPrimary },
            new() { Content = "The monitor with the mouse pointer", Tag = AlertChoices.MonitorCursor },
        };
        foreach (var m in monitors) items.Add(new ComboBoxItem { Content = MonitorChoice.Describe(m, monitors), Tag = m.Device });
        // a monitor chosen earlier that is not connected now stays chosen (alerts use the primary meanwhile)
        if (S.Monitor is { } dev && dev is not (AlertChoices.MonitorPrimary or AlertChoices.MonitorCursor)
            && monitors.All(m => !string.Equals(m.Device, dev, StringComparison.OrdinalIgnoreCase)))
            items.Add(new ComboBoxItem { Content = dev + " (not connected now)", Tag = dev });
        MonitorBox.ItemsSource = items;
        string want = S.Monitor ?? AlertChoices.MonitorPrimary;
        MonitorBox.SelectedItem = items.FirstOrDefault(i => string.Equals((string)i.Tag, want, StringComparison.OrdinalIgnoreCase)) ?? items[0];
        MonitorNote.Text = monitors.Count > 1
            ? monitors.Count + " monitors connected. When the chosen one is unplugged, alerts show on the primary one."
            : "One monitor connected. With more, choose here which one alerts show on.";
        _filling = false;
    }

    // ---- showing what is set -------------------------------------------------------------

    private void Fill()
    {
        _filling = true;
        SoundOn.IsChecked = S.Sound;
        SoundPanel.IsEnabled = S.Sound;
        SoundPanel.Opacity = S.Sound ? 1 : 0.5;
        foreach (var (id, row) in _soundRows) row.IsChecked = S.SoundId == id;
        FileChoice.IsChecked = S.SoundId == AlarmSounds.FileId;
        FileName.Text = S.SoundFile is { } f ? System.IO.Path.GetFileName(f) : "A .wav file on this computer (up to 20 MB)";
        FileName.ToolTip = S.SoundFile;
        FilePlay.IsEnabled = S.SoundFile is not null;
        foreach (RadioButton p in LengthChoices.Children) p.IsChecked = (int)p.Tag == S.SoundSeconds;
        foreach (RadioButton p in CloseChoices.Children) p.IsChecked = (int)p.Tag == S.AutoCloseSeconds;
        VolumeSlider.Value = S.Volume;
        VolumeText.Text = S.Volume + " %";
        FrontOn.IsChecked = S.BringToFront;
        ShowFileProblem();
        _filling = false;
        FillSms();
    }

    /// <summary>(1.4.0) The SMS switches, and what ZIGMon allows this computer.</summary>
    private void FillSms()
    {
        SmsPopupsOn.IsChecked = S.SmsPopups;
        SmsSoundOn.IsChecked = S.SmsSound;
        DeckOn.IsChecked = S.DeckPopups;
        SmsSoundChoices.IsEnabled = S.SmsSound;
        SmsSoundChoices.Opacity = S.SmsSound ? 1 : 0.5;
        foreach (RadioButton p in SmsSoundChoices.Children) p.IsChecked = (string)p.Tag == S.SmsSoundId;

        var sms = _app.Sms;
        var can = new System.Collections.Generic.List<string>();
        if (sms.Read) can.Add("read incoming and sent SMS");
        if (sms.Send) can.Add(sms.Ready ? "send" : "send (once ZIGMon's SMS gateway is set up)");
        if (sms.Contacts) can.Add("see the contacts");
        bool connected = _app.Status.State == ConnectionState.Connected;
        SmsAllowedText.Text = !connected
            ? "Connect to ZIGMon to see what this computer may do with SMS. These switches are kept on this computer either way."
            : can.Count == 0
                ? "ZIGMon does not share SMS with this computer. An administrator can allow it: Settings → Messages → Desktop app → this key → SMS (ZIGMon 5.59.4 or newer)."
                : "ZIGMon lets this computer " + string.Join(", ", can) + ". The switches below decide what it does with that.";
        string accent = connected && can.Count > 0 ? Palette.Ok : Palette.TextDim;
        SmsAllowedGlyph.Text = connected && can.Count > 0 ? "\uE73E" : "\uE946";
        SmsAllowedGlyph.Foreground = Ui.Brush(accent);
        SmsAllowed.BorderBrush = connected && can.Count > 0 ? Ui.Brush(Palette.Ok, 0x59) : Ui.Brush(Palette.Line);
    }

    private void OnSmsPopups(object sender, RoutedEventArgs e)
    {
        S.SmsPopups = SmsPopupsOn.IsChecked == true;
        _app.Save();
    }

    private void OnSmsSound(object sender, RoutedEventArgs e)
    {
        S.SmsSound = SmsSoundOn.IsChecked == true;
        _app.Save();
        FillSms();
        if (S.SmsSound) Sounds.Play(S.SmsSoundId, null, S.Volume, AlertChoices.Once);
    }

    private void OnDeck(object sender, RoutedEventArgs e)
    {
        S.DeckPopups = DeckOn.IsChecked == true;
        _app.Save();
    }

    private void ShowFileProblem()
    {
        string p = S.SoundId == AlarmSounds.FileId ? Sounds.FileProblem : "";
        FileProblem.Text = p.Length > 0 ? p + " The default sound plays instead." : "";
        FileProblem.Visibility = p.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    // ---- changes ---------------------------------------------------------------------------

    private void Choose(string id)
    {
        S.SoundId = id;
        _app.Save();
        Fill();
        Sounds.Play(id, null, S.Volume, AlertChoices.Once);
    }

    private void OnSoundOn(object sender, RoutedEventArgs e)
    {
        S.Sound = SoundOn.IsChecked == true;
        _app.Save();
        if (!S.Sound) Sounds.Stop();
        Fill();
    }

    private void OnFileChoice(object sender, RoutedEventArgs e)
    {
        if (S.SoundFile is null)
        {
            OnChooseFile(sender, e);
            return;
        }
        S.SoundId = AlarmSounds.FileId;
        _app.Save();
        Fill();
    }

    private void OnChooseFile(object sender, RoutedEventArgs e)
    {
        e.Handled = true;
        string? file = _app.PickSoundFile();
        if (file is not null)
        {
            S.SoundFile = file;
            S.SoundId = AlarmSounds.FileId;
            _app.Save();
            Sounds.Play(AlarmSounds.FileId, file, S.Volume, AlertChoices.Once);
        }
        Fill();
    }

    private void OnPlayFile(object sender, RoutedEventArgs e)
    {
        e.Handled = true;
        if (S.SoundFile is null) return;
        Sounds.Play(AlarmSounds.FileId, S.SoundFile, S.Volume, AlertChoices.Once);
        ShowFileProblem();
    }

    private void OnVolume(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (_filling) return;
        S.Volume = (int)Math.Round(VolumeSlider.Value);
        VolumeText.Text = S.Volume + " %";
    }

    /// <summary>Let go of the slider: saved, and heard at the new volume.</summary>
    private void OnVolumeDone(object sender, RoutedEventArgs e)
    {
        _app.Save();
        var (id, file) = S.SoundFor(null);
        Sounds.Play(id, file, S.Volume, AlertChoices.Once);
    }

    /// <summary>Plays the default sound for as long as set; a second click stops it.</summary>
    private void OnTestSound(object sender, RoutedEventArgs e)
    {
        if (_testing)
        {
            Sounds.Stop();
            _testing = false;
            TestSoundText.Text = "Test";
            return;
        }
        var (id, file) = S.SoundFor(null);
        Sounds.Play(id, file, S.Volume, S.SoundSeconds);
        ShowFileProblem();
        if (S.SoundSeconds != AlertChoices.Once)
        {
            _testing = true;
            TestSoundText.Text = "Stop";
        }
    }

    private void OnMonitor(object sender, SelectionChangedEventArgs e)
    {
        if (_filling || MonitorBox.SelectedItem is not ComboBoxItem { Tag: string tag }) return;
        S.Monitor = tag == AlertChoices.MonitorPrimary ? null : tag;
        _app.Save();
    }

    private void OnShowMe(object sender, RoutedEventArgs e) => _app.TestAlert();

    private void OnFront(object sender, RoutedEventArgs e)
    {
        S.BringToFront = FrontOn.IsChecked == true;
        _app.Save();
    }

    private void OnTestAlert(object sender, RoutedEventArgs e) => _app.TestAlert();

    private void OnDone(object sender, RoutedEventArgs e) => Close();
}
