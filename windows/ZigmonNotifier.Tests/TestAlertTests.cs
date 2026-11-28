using System;
using System.Text;
using ZigmonNotifier.Core;
using Xunit;

namespace ZigmonNotifier.Tests;

/// <summary>1.3.0: a test alert sent from ZIGMon's dashboard (Settings - Desktop app - Test alert).</summary>
public class TestAlertTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 28, 12, 0, 0, TimeSpan.Zero);

    private static TriggerEvent FromServer()
    {
        // what ZIGMon 5.59.2 sends: kind "test", a device id no sensor has
        string json = "{\"ok\":true,\"boot\":\"a1b2c3\",\"seq\":7,\"reset\":false,\"events\":[{\"seq\":7,\"at\":1795000000.5,"
            + "\"device\":\"zigmon-test\",\"name\":\"Test alert\",\"room\":null,\"kind\":\"test\",\"key\":\"test\","
            + "\"active\":true,\"what\":\"sent from the dashboard by owner\"}]}";
        using var doc = ProtocolParser.ParseDocument(Encoding.UTF8.GetBytes(json));
        var w = ProtocolParser.Wait(doc.RootElement);
        return Assert.Single(w.Events);
    }

    [Fact]
    public void TheKindIsKnown()
    {
        var e = FromServer();
        Assert.Equal(SensorKinds.Test, e.Kind);
        Assert.Equal("Test from ZIGMon", KindStyle.For(e.Kind).Label);
    }

    [Fact]
    public void ItAlertsThoughNothingWatchesIt()
    {
        var s = new NotifierSettings();
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, FromServer(), Now));
    }

    [Fact]
    public void ItAlertsWhilePausedOrMuted()
    {
        var s = new NotifierSettings { PausedUntilResumed = true };
        s.Mutes["zigmon-test"] = Now.AddHours(1);
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, FromServer(), Now));
    }

    [Fact]
    public void AnUnknownKindStillDoesNot()
    {
        var s = new NotifierSettings();
        var e = FromServer() with { Kind = SensorKinds.Normalize("teSt-ish") };
        Assert.Equal(AlertDecision.NotWatched, AlertFilter.Decide(s, e, Now));
    }
}
