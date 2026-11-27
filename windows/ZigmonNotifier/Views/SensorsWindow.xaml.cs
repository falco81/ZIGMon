using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Windows;
using System.Windows.Data;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Views;

/// <summary>Choose the sensors that alert; their state is live while the window is open.</summary>
public partial class SensorsWindow : Window
{
    private readonly AppController _app;
    private readonly ObservableCollection<SensorRow> _rows = new();
    private readonly Dictionary<string, SensorRow> _byId = new(StringComparer.Ordinal);
    private readonly ICollectionView _view;
    private string _filter = "";

    internal SensorsWindow(AppController app)
    {
        InitializeComponent();
        Ui.ApplyIcon(this);
        _app = app;
        _view = CollectionViewSource.GetDefaultView(_rows);
        _view.Filter = o => _filter.Length == 0 || o is SensorRow r && _filter.Split(' ', StringSplitOptions.RemoveEmptyEntries).All(r.Search.Contains);
        List.ItemsSource = _view;

        SourceInitialized += (_, _) => Native.DarkTitleBar(this);
        _app.SensorsChanged += Rebuild;
        _app.StatusChanged += UpdateTexts;
        Closed += (_, _) =>
        {
            _app.SensorsChanged -= Rebuild;
            _app.StatusChanged -= UpdateTexts;
        };
        Rebuild();
        Loaded += (_, _) => SearchBox.Focus();
    }

    private void Rebuild()
    {
        var wanted = new List<SensorRow>();
        foreach (var s in _app.Sensors)
        {
            var row = Row(s.Id);
            row.Fill(s, s.Name);
            wanted.Add(row);
        }
        // watched sensors the key no longer offers: shown, so they can be switched off
        if (_app.Sensors.Count > 0)
        {
            foreach (var w in _app.Settings.Watched.Where(w => _app.Sensors.All(s => s.Id != w.Id)).ToList())
            {
                var row = Row(w.Id);
                row.Fill(null, w.Name);
                wanted.Add(row);
            }
        }

        // update the list in place, so scrolling and focus stay where they are
        for (int i = 0; i < wanted.Count; i++)
        {
            if (i < _rows.Count && ReferenceEquals(_rows[i], wanted[i])) continue;
            int at = _rows.IndexOf(wanted[i]);
            if (at >= 0) _rows.Move(at, i);
            else _rows.Insert(i, wanted[i]);
        }
        while (_rows.Count > wanted.Count)
        {
            _byId.Remove(_rows[^1].Id);
            _rows.RemoveAt(_rows.Count - 1);
        }
        UpdateTexts();
    }

    private SensorRow Row(string id)
    {
        if (!_byId.TryGetValue(id, out var row))
        {
            row = new SensorRow(_app, id);
            _byId[id] = row;
        }
        return row;
    }

    private void UpdateTexts()
    {
        int watched = _app.Settings.Watched.Count;
        int total = _app.Sensors.Count;
        Summary.Text = total > 0
            ? "Alerts come from the sensors you switch on. " + watched + " of " + total + " watched."
            : "Alerts come from the sensors you switch on.";

        var st = _app.Status;
        FootDot.Fill = _app.Dot switch
        {
            StatusDot.Green => Ui.Brush(Palette.Ok),
            StatusDot.Red => Ui.Brush(Palette.Crit),
            StatusDot.Amber => Ui.Brush(Palette.Warn),
            _ => Ui.Brush(Palette.TextDim),
        };
        string house = string.IsNullOrEmpty(_app.Settings.House) ? "" : _app.Settings.House + " · ";
        Footer.Text = house + _app.ShortStatus;
        Footer.ToolTip = st.Message;

        bool configured = _app.Settings.HasConnection;
        bool any = _rows.Count > 0;
        bool shown = any && !_view.IsEmpty;
        Empty.Visibility = shown ? Visibility.Collapsed : Visibility.Visible;
        AllButton.IsEnabled = NoneButton.IsEnabled = shown;
        EmptyButton.Visibility = Visibility.Collapsed;
        if (!configured)
        {
            EmptyGlyph.Text = "";
            EmptyTitle.Text = "Not connected yet";
            EmptyBody.Text = "Connect to your ZIGMon first; its sensors then show up here.";
            EmptyButton.Visibility = Visibility.Visible;
        }
        else if (!any)
        {
            bool trouble = st.State is ConnectionState.NeedsAttention or ConnectionState.Retrying;
            EmptyGlyph.Text = trouble ? "" : "";
            EmptyTitle.Text = trouble ? "ZIGMon cannot be reached" : st.State == ConnectionState.Connected ? "No sensors for this key" : "Waiting for ZIGMon…";
            EmptyBody.Text = trouble ? st.Message
                : st.State == ConnectionState.Connected
                    ? "This key may not see any sensor that can trigger. An administrator can change that in ZIGMon."
                    : "The sensors show up as soon as ZIGMon answers.";
            EmptyButton.Visibility = trouble ? Visibility.Visible : Visibility.Collapsed;
            EmptyButton.Content = "Check the connection";
        }
        else
        {
            EmptyGlyph.Text = "";
            EmptyTitle.Text = "Nothing matches";
            EmptyBody.Text = "No sensor has “" + SearchBox.Text.Trim() + "” in its name, room or kind.";
        }
    }

    private void OnSearch(object sender, RoutedEventArgs e)
    {
        _filter = SafeText.Clean(SearchBox.Text, 80).ToLowerInvariant();
        _view.Refresh();
        UpdateTexts();
    }

    private IEnumerable<SensorRow> Shown() => _view.Cast<SensorRow>().ToList();

    private void OnAll(object sender, RoutedEventArgs e)
    {
        foreach (var r in Shown().Where(r => !r.IsMissing)) r.IsWatched = true;
    }

    private void OnNone(object sender, RoutedEventArgs e)
    {
        foreach (var r in Shown()) r.IsWatched = false;
        Rebuild(); // forgotten sensors leave the list
    }

    private void OnPlaySound(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: SensorRow r }) r.PlaySound();
    }

    private void OnSetUp(object sender, RoutedEventArgs e) => _app.ShowConnection();

    private void OnDone(object sender, RoutedEventArgs e) => Close();
}
