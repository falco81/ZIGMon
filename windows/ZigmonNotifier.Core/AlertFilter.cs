using System;

namespace ZigmonNotifier.Core;

public enum AlertDecision
{
    Alert,
    NotWatched,
    Paused,
    Muted,
    /// <summary>It went back to quiet and this sensor does not alert on that.</summary>
    ClearingNotWanted,
    /// <summary>The state is unknown (active null) for a sensor that is not a button.</summary>
    NoState,
}

/// <summary>Decides whether an event becomes an alert.</summary>
public static class AlertFilter
{
    public static AlertDecision Decide(NotifierSettings settings, TriggerEvent e, DateTimeOffset now)
    {
        // a test sent from the dashboard on purpose: always shown, whatever is watched, paused or muted
        if (e.Kind == SensorKinds.Test) return AlertDecision.Alert;
        var watched = settings.FindWatched(e.Device);
        if (watched is null) return AlertDecision.NotWatched;
        if (settings.IsPaused(now)) return AlertDecision.Paused;
        if (settings.IsMuted(e.Device, now)) return AlertDecision.Muted;
        if (e.Kind == SensorKinds.Button) return AlertDecision.Alert; // every press is a press
        return e.Active switch
        {
            true => AlertDecision.Alert,
            false => watched.AlsoWhenClears ? AlertDecision.Alert : AlertDecision.ClearingNotWanted,
            null => AlertDecision.NoState,
        };
    }

    public static bool ShouldAlert(NotifierSettings settings, TriggerEvent e, DateTimeOffset now) =>
        Decide(settings, e, now) == AlertDecision.Alert;
}
