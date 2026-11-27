using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace ZigmonNotifier.Core;

public enum UpdateState
{
    /// <summary>Not checked yet.</summary>
    Idle,
    Checking,
    UpToDate,
    /// <summary>The server is too old to offer the app (404/400 to /update).</summary>
    NotOffered,
    /// <summary>A verified update waits for a click (automatic updates are off).</summary>
    Available,
    Updating,
    /// <summary>The new version is running; this one must exit.</summary>
    Restarting,
    Failed,
}

public sealed record UpdateStatus(UpdateState State, string Text, string? Version = null)
{
    public bool IsBusy => State is UpdateState.Checking or UpdateState.Updating or UpdateState.Restarting;
}

/// <summary>
/// The app's self-update, without anything Windows-only in it: asks the source
/// for an offer, verifies it (signature, then manifest), downloads, checks the
/// bytes and hands them to the installer. One check at a time; never downgrades;
/// never runs anything that failed a check.
/// </summary>
public sealed class UpdateManager
{
    public static readonly TimeSpan Period = TimeSpan.FromHours(6);

    private readonly Version _running;
    private readonly IReadOnlyList<ReleaseKey> _keys;
    private readonly UpdateInstaller _installer;
    private readonly string? _exePath;
    private readonly string _stagingDir;
    private readonly Func<string, IReadOnlyList<string>, bool> _start;
    private readonly Action<string> _log;
    private readonly object _gate = new();
    private UpdateStatus _status;

    public event Action<UpdateStatus>? StatusChanged;

    public UpdateManager(Version running, IReadOnlyList<ReleaseKey> keys, UpdateInstaller installer,
        string? exePath, string stagingDir, Func<string, IReadOnlyList<string>, bool> start, Action<string>? log = null)
    {
        _running = running ?? throw new ArgumentNullException(nameof(running));
        _keys = keys ?? throw new ArgumentNullException(nameof(keys));
        _installer = installer ?? throw new ArgumentNullException(nameof(installer));
        _exePath = exePath;
        _stagingDir = stagingDir ?? throw new ArgumentNullException(nameof(stagingDir));
        _start = start ?? throw new ArgumentNullException(nameof(start));
        _log = log ?? (_ => { });
        _status = new UpdateStatus(UpdateState.Idle, "Version " + RunningText);
    }

    public string RunningText => AppVersions.Format(_running);

    public UpdateStatus Status { get { lock (_gate) return _status; } }

    /// <summary>
    /// Whether a hello should lead to a look at /update by itself: only when the
    /// server says (hello.app.version) it has a newer app. A server that does not
    /// say anything about the app (older ZIGMon) is asked only from the menu.
    /// </summary>
    public bool HelloOffersNewer(HelloInfo hello) =>
        hello is { AdvertisesApp: true } && AppVersions.IsNewer(hello.AppVersion, _running);

    /// <param name="install">True: install a verified update straight away. False: only report it (Available).</param>
    public async Task<UpdateStatus> CheckAsync(IUpdateSource source, bool install, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(source);
        lock (_gate)
        {
            if (_status.IsBusy) return _status;
            _status = new UpdateStatus(UpdateState.Checking, "Checking for updates…");
        }
        Raise(Status);

        UpdateStatus result;
        try
        {
            result = await RunAsync(source, install, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            result = new UpdateStatus(UpdateState.Idle, "Version " + RunningText);
        }
        catch (Exception ex)
        {
            // anything unforeseen is a failed update, never a crash of the app
            result = Failed("something unexpected went wrong (" + ex.GetType().Name + ")");
        }
        lock (_gate) _status = result;
        _log("update: " + result.State + " " + result.Text);
        Raise(result);
        return result;
    }

    private async Task<UpdateStatus> RunAsync(IUpdateSource source, bool install, CancellationToken ct)
    {
        UpdateOffer offer;
        try
        {
            offer = await source.UpdateAsync(ct).ConfigureAwait(false);
        }
        catch (ZigmonException z) when (z.Status is 404 or 400)
        {
            // a ZIGMon from before 5.58 does not know /update: that is "no updates", not an error
            return new UpdateStatus(UpdateState.NotOffered, "Up to date – " + RunningText + " (this ZIGMon offers no updates)");
        }
        catch (ZigmonException z)
        {
            return Failed("could not ask ZIGMon – " + z.Message);
        }

        if (!offer.Available || !AppVersions.IsNewer(offer.Version, _running))
            return UpToDate();

        VerifiedUpdate update;
        try
        {
            update = UpdateVerifier.Verify(offer, _keys, _running);
        }
        catch (UpdateException u)
        {
            return Failed(u.Message);
        }
        _log("update " + update.VersionText + " verified with " + update.KeyName);

        if (!install)
            return new UpdateStatus(UpdateState.Available, "Version " + update.VersionText + " is available", update.VersionText);
        if (_exePath is null)
            return Failed("the app's own file cannot be found");

        SetStatus(new UpdateStatus(UpdateState.Updating, "Updating to " + update.VersionText + "…", update.VersionText));
        byte[] exe;
        try
        {
            exe = await source.DownloadAsync(update.Manifest.Size, ct).ConfigureAwait(false);
        }
        catch (ZigmonException z)
        {
            return Failed("the download failed – " + z.Message);
        }

        var r = _installer.Install(exe, update, _exePath, _stagingDir, RunningText, _start);
        return r.Outcome switch
        {
            InstallOutcome.Started => new UpdateStatus(UpdateState.Restarting, "Restarting as " + update.VersionText + "…", update.VersionText),
            _ => Failed(r.Message),
        };
    }

    private UpdateStatus UpToDate() => new(UpdateState.UpToDate, "Up to date – " + RunningText);

    private static UpdateStatus Failed(string why) => new(UpdateState.Failed, "Update failed: " + why);

    private void SetStatus(UpdateStatus s)
    {
        lock (_gate) _status = s;
        Raise(s);
    }

    private void Raise(UpdateStatus s)
    {
        try { StatusChanged?.Invoke(s); }
        catch (Exception ex) { _log("an update listener failed: " + ex.GetType().Name); }
    }
}
