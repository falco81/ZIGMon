using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace ZigmonNotifier.Core;

public enum ConnectionState
{
    /// <summary>No address or key yet.</summary>
    NotConfigured,
    Connecting,
    Connected,
    /// <summary>Something failed; trying again by itself after <see cref="ConnectionStatus.RetryIn"/>.</summary>
    Retrying,
    /// <summary>Stopped until the user does something (wrong key, certificate changed, redirect).</summary>
    NeedsAttention,
    Stopped,
}

public sealed record ConnectionStatus(
    ConnectionState State, string Message, HelloInfo? Hello = null, TimeSpan? RetryIn = null, ZigmonErrorKind? Error = null)
{
    public static readonly ConnectionStatus NotConfigured =
        new(ConnectionState.NotConfigured, "Not set up yet - right-click the icon and choose Connection.");
}

/// <summary>
/// The long-poll loop: hello → sensors → wait, wait, wait... A reset (or a new
/// boot id) re-reads the sensors and goes on from their seq; failures back off
/// 1 s, 2 s, 4 s ... 60 s; a 429 waits at least a minute; a wrong key, a
/// rejected certificate or a redirect stop the loop until the user acts.
/// Events are raised on the loop's thread.
/// </summary>
public sealed class NotifierService
{
    public static readonly TimeSpan MaxBackoff = TimeSpan.FromSeconds(60);

    private readonly INotifierApi _api;
    private readonly Action<string> _log;
    private readonly Func<TimeSpan, CancellationToken, Task> _delay;
    private readonly object _gate = new();
    private Dictionary<string, SensorInfo> _sensors = new(StringComparer.Ordinal);
    private List<string> _order = new();
    private ConnectionStatus _status = new(ConnectionState.Connecting, "Connecting…");

    public event Action<ConnectionStatus>? StatusChanged;
    public event Action<IReadOnlyList<SensorInfo>>? SensorsChanged;
    public event Action<IReadOnlyList<TriggerEvent>>? EventsArrived;

    public NotifierService(INotifierApi api, Action<string>? log = null, Func<TimeSpan, CancellationToken, Task>? delay = null)
    {
        _api = api ?? throw new ArgumentNullException(nameof(api));
        _log = log ?? (_ => { });
        _delay = delay ?? ((t, ct) => Task.Delay(t, ct));
    }

    public ConnectionStatus Status { get { lock (_gate) return _status; } }

    /// <summary>The sensors as last read, with states kept up to date by the events.</summary>
    public IReadOnlyList<SensorInfo> Sensors
    {
        get { lock (_gate) return _order.Select(id => _sensors[id]).ToList(); }
    }

    /// <summary>1, 2, 4, 8, 16, 32, 60, 60 ... seconds for the 1st, 2nd ... failure in a row.</summary>
    public static TimeSpan Backoff(int failuresInARow)
    {
        if (failuresInARow <= 1) return TimeSpan.FromSeconds(1);
        if (failuresInARow > 7) return MaxBackoff;
        double s = Math.Pow(2, failuresInARow - 1);
        return TimeSpan.FromSeconds(Math.Min(s, MaxBackoff.TotalSeconds));
    }

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        HelloInfo? hello = null;
        string boot = "";
        long seq = 0;
        int failures = 0;
        SetStatus(new ConnectionStatus(ConnectionState.Connecting, "Connecting…"));

        while (true)
        {
            try
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (hello is null)
                {
                    var h = await _api.HelloAsync(cancellationToken).ConfigureAwait(false);
                    var snap = await _api.SensorsAsync(cancellationToken).ConfigureAwait(false);
                    PublishSensors(snap.Sensors);
                    boot = h.Boot;
                    seq = h.Seq;
                    if (snap.Boot != h.Boot) { boot = snap.Boot; seq = snap.Seq; } // restarted in between
                    hello = h;
                    failures = 0;
                    _log("connected to " + (h.House.Length > 0 ? h.House : "ZIGMon") + " " + h.Version);
                    SetStatus(Connected(h));
                }

                var w = await _api.WaitAsync(seq, boot, cancellationToken).ConfigureAwait(false);
                if (failures > 0 || Status.State != ConnectionState.Connected)
                {
                    failures = 0;
                    SetStatus(Connected(hello));
                }

                if (w.Reset || w.Boot != boot)
                {
                    _log("event stream reset; reading the sensors again");
                    var snap = await _api.SensorsAsync(cancellationToken).ConfigureAwait(false);
                    PublishSensors(snap.Sensors);
                    boot = snap.Boot;
                    seq = snap.Seq;
                    continue;
                }

                long from = seq;
                var fresh = w.Events.Where(e => e.Seq > from).OrderBy(e => e.Seq).ToList();
                if (fresh.Count > 0)
                {
                    ApplyEvents(fresh);
                    seq = Math.Max(seq, fresh[^1].Seq);
                    Raise(() => EventsArrived?.Invoke(fresh));
                }
                seq = Math.Max(seq, w.Seq);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                SetStatus(new ConnectionStatus(ConnectionState.Stopped, "Stopped.", hello));
                return;
            }
            catch (Exception ex)
            {
                var z = ex as ZigmonException
                    ?? new ZigmonException(ZigmonErrorKind.Protocol, "Something unexpected went wrong (" + ex.GetType().Name + ").");
                if (z.Kind is ZigmonErrorKind.Unauthorized or ZigmonErrorKind.Certificate or ZigmonErrorKind.Redirect)
                {
                    _log("stopped: " + z.Kind);
                    SetStatus(new ConnectionStatus(ConnectionState.NeedsAttention, z.Message, hello, null, z.Kind));
                    return;
                }
                failures++;
                TimeSpan wait = Backoff(failures);
                if (z.Kind == ZigmonErrorKind.RateLimited)
                    wait = z.RetryAfter is { } ra && ra > MaxBackoff ? ra : MaxBackoff;
                _log("failed (" + z.Kind + "), trying again in " + (int)wait.TotalSeconds + " s: " + z.Message);
                SetStatus(new ConnectionStatus(ConnectionState.Retrying, z.Message, hello, wait, z.Kind));
                try
                {
                    await _delay(wait, cancellationToken).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    SetStatus(new ConnectionStatus(ConnectionState.Stopped, "Stopped.", hello));
                    return;
                }
            }
        }
    }

    private static ConnectionStatus Connected(HelloInfo h) =>
        new(ConnectionState.Connected, "Connected" + (h.House.Length > 0 ? " to " + h.House : ""), h);

    private void PublishSensors(IReadOnlyList<SensorInfo> sensors)
    {
        lock (_gate)
        {
            _sensors = sensors.ToDictionary(s => s.Id, StringComparer.Ordinal);
            _order = sensors.Select(s => s.Id).ToList();
        }
        var copy = Sensors;
        Raise(() => SensorsChanged?.Invoke(copy));
    }

    private void ApplyEvents(IReadOnlyList<TriggerEvent> events)
    {
        bool changed = false;
        lock (_gate)
        {
            foreach (var e in events)
            {
                if (!_sensors.TryGetValue(e.Device, out var s)) continue;
                bool? active = e.Kind == SensorKinds.Button ? s.Active : e.Active;
                _sensors[e.Device] = s with { Active = active, At = e.At, Online = true };
                changed = true;
            }
        }
        if (changed)
        {
            var copy = Sensors;
            Raise(() => SensorsChanged?.Invoke(copy));
        }
    }

    private void SetStatus(ConnectionStatus status)
    {
        lock (_gate) _status = status;
        Raise(() => StatusChanged?.Invoke(status));
    }

    private void Raise(Action a)
    {
        try { a(); }
        catch (Exception ex) { _log("a listener failed: " + ex.GetType().Name); }
    }
}
