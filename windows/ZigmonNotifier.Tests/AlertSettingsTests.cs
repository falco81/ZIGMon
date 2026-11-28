using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml.Linq;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Tests;

/// <summary>1.2.0: the alert settings (sounds, length, volume, closing, monitor), per-sensor sounds, conditions.</summary>
public class AlertSettingsTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 27, 12, 0, 0, TimeSpan.Zero);
    private static string Wav() => OperatingSystem.IsWindows() ? @"C:\Sounds\alarm.wav" : "/home/me/alarm.wav";

    [Fact]
    public void DefaultsAreTheOldBehaviour()
    {
        var s = new NotifierSettings();
        s.Sanitize(Now);
        Assert.Equal(AlarmSounds.DefaultId, s.SoundId);
        Assert.Equal(AlertChoices.Once, s.SoundSeconds);
        Assert.Equal(80, s.Volume);
        Assert.Equal(0, s.AutoCloseSeconds);
        Assert.Null(s.Monitor);
    }

    [Fact]
    public void Version110AutoCloseBecomesAMinute()
    {
        var path = Path.Combine(Path.GetTempPath(), "zn-" + Guid.NewGuid().ToString("N"), "settings.json");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        try
        {
            File.WriteAllText(path, "{\"format\":1,\"autoClose\":true,\"sound\":true}");
            var s = new SettingsStore(path).Load(Now);
            Assert.Equal(60, s.AutoCloseSeconds);
            Assert.Null(s.AutoClose);
            File.WriteAllText(path, "{\"format\":1,\"autoClose\":false}");
            Assert.Equal(0, new SettingsStore(path).Load(Now).AutoCloseSeconds);
        }
        finally
        {
            Directory.Delete(Path.GetDirectoryName(path)!, true);
        }
    }

    [Fact]
    public void EverythingIsRemembered()
    {
        var dir = Path.Combine(Path.GetTempPath(), "zn-" + Guid.NewGuid().ToString("N"));
        var store = new SettingsStore(Path.Combine(dir, "settings.json"));
        try
        {
            var s = new NotifierSettings
            {
                SoundId = "siren", SoundSeconds = 30, Volume = 35, AutoCloseSeconds = 300, Monitor = @"\\.\DISPLAY2",
                BringToFront = true, Sound = false,
            };
            s.Watched.Add(new WatchedSensor { Id = "0xa1", Name = "Door", SoundId = "klaxon" });
            s.Watched.Add(new WatchedSensor { Id = "rule:0123456789", Name = "Too hot", SoundId = AlarmSounds.FileId, SoundFile = Wav(), AlsoWhenClears = true });
            store.Save(s);
            var back = store.Load(Now);
            Assert.Equal("siren", back.SoundId);
            Assert.Equal(30, back.SoundSeconds);
            Assert.Equal(35, back.Volume);
            Assert.Equal(300, back.AutoCloseSeconds);
            Assert.Equal(@"\\.\DISPLAY2", back.Monitor);
            Assert.True(back.BringToFront);
            Assert.False(back.Sound);
            Assert.Equal("klaxon", back.FindWatched("0xa1")!.SoundId);
            var rule = back.FindWatched("rule:0123456789")!;
            Assert.Equal(AlarmSounds.FileId, rule.SoundId);
            Assert.Equal(Wav(), rule.SoundFile);
            Assert.True(rule.AlsoWhenClears);
        }
        finally
        {
            if (Directory.Exists(dir)) Directory.Delete(dir, true);
        }
    }

    [Theory]
    [InlineData(-3, 0, 0)]
    [InlineData(7, 15, 0)]     // between choices: the next one up
    [InlineData(301, -1, 0)]   // longer than the longest timed one: the longest timed one (300)
    [InlineData(-1, -1, 0)]
    public void SoundLengthsSnapToTheChoices(int given, int expectedIfUntil, int _)
    {
        var s = new NotifierSettings { SoundSeconds = given };
        s.Sanitize(Now);
        int expected = given switch { -3 => 0, 7 => 15, 301 => 300, _ => expectedIfUntil };
        Assert.Equal(expected, s.SoundSeconds);
        Assert.Contains(s.SoundSeconds, AlertChoices.SoundLengths);
    }

    [Theory]
    [InlineData(-5, 0)]
    [InlineData(45, 60)]
    [InlineData(99999, 900)]
    [InlineData(10, 10)]
    public void CloseAfterSnapsToTheChoices(int given, int expected)
    {
        var s = new NotifierSettings { AutoCloseSeconds = given };
        s.Sanitize(Now);
        Assert.Equal(expected, s.AutoCloseSeconds);
    }

    [Fact]
    public void RubbishFromDiskIsPutRight()
    {
        var s = new NotifierSettings { Volume = 400, SoundId = "nope", SoundFile = "relative.wav", Monitor = "bad\u0001name" };
        s.Watched.Add(new WatchedSensor { Id = "a", SoundId = "nope" });
        s.Watched.Add(new WatchedSensor { Id = "b", SoundId = AlarmSounds.FileId, SoundFile = "x.mp3" });
        s.Sanitize(Now);
        Assert.Equal(100, s.Volume);
        Assert.Equal(AlarmSounds.DefaultId, s.SoundId);
        Assert.Null(s.SoundFile);
        Assert.Null(s.Monitor);
        Assert.Null(s.FindWatched("a")!.SoundId);
        Assert.Null(s.FindWatched("b")!.SoundId);
        Assert.Null(s.FindWatched("b")!.SoundFile);

        var f = new NotifierSettings { SoundId = AlarmSounds.FileId, SoundFile = null, Volume = -2 };
        f.Sanitize(Now);
        Assert.Equal(AlarmSounds.DefaultId, f.SoundId); // a file sound with no file: the default
        Assert.Equal(0, f.Volume);
        Assert.Null(NotifierSettings.CleanSoundFile(Wav() + "\n"));
        Assert.Equal(Wav(), NotifierSettings.CleanSoundFile(Wav()));
    }

    [Fact]
    public void EachSensorMayHaveItsOwnSound()
    {
        var s = new NotifierSettings { SoundId = "bell" };
        s.Watched.Add(new WatchedSensor { Id = "door", SoundId = "doorbell" });
        s.Watched.Add(new WatchedSensor { Id = "pir" });
        s.Watched.Add(new WatchedSensor { Id = "hot", SoundId = AlarmSounds.FileId, SoundFile = Wav() });
        Assert.Equal(("doorbell", (string?)null), s.SoundFor("door"));
        Assert.Equal(("bell", (string?)null), s.SoundFor("pir"));
        Assert.Equal(("bell", (string?)null), s.SoundFor(null));
        Assert.Equal(("bell", (string?)null), s.SoundFor("unknown"));
        Assert.Equal((AlarmSounds.FileId, (string?)Wav()), s.SoundFor("hot"));
        s.SoundId = AlarmSounds.FileId;
        s.SoundFile = Wav();
        Assert.Equal((AlarmSounds.FileId, (string?)Wav()), s.SoundFor("pir"));
    }

    // ---- the sounds ----------------------------------------------------------------------

    [Fact]
    public void ThereAreSeveralDifferentSounds()
    {
        Assert.True(AlarmSounds.All.Count >= 8);
        Assert.Equal(AlarmSounds.All.Count, AlarmSounds.All.Select(a => a.Id).Distinct().Count());
        Assert.DoesNotContain(AlarmSounds.All, a => a.Id == AlarmSounds.FileId);
        var hashes = AlarmSounds.All.Select(a => Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(WavAudio.Builtin(a.Id, 80)))).ToList();
        Assert.Equal(hashes.Count, hashes.Distinct().Count());
    }

    [Theory]
    [MemberData(nameof(SoundIds))]
    public void EverySoundIsAProperRound(string id)
    {
        var b = AlarmSounds.Render(id);
        double seconds = b.Length / (double)AlarmSounds.SampleRate;
        Assert.InRange(seconds, 0.8, 3);
        Assert.InRange(b.Max(Math.Abs), 0.99, 1.0001);
        Assert.True(Math.Abs(b[^1]) < 0.01, "ends at silence, so repeating does not click");
        Assert.DoesNotContain(b, double.IsNaN);
    }

    public static TheoryData<string> SoundIds()
    {
        var d = new TheoryData<string>();
        foreach (var a in AlarmSounds.All) d.Add(a.Id);
        return d;
    }

    [Fact]
    public void VolumeIsApplied()
    {
        int p0 = WavAudio.Peak(WavAudio.Builtin("beeps", 0));
        int p50 = WavAudio.Peak(WavAudio.Builtin("beeps", 50));
        int p100 = WavAudio.Peak(WavAudio.Builtin("beeps", 100));
        Assert.Equal(0, p0);
        Assert.InRange(p100, 28000, 32767);
        Assert.InRange(p50, p100 / 5, p100 / 3); // squared: half the slider is a quarter of the level
        Assert.Equal(WavAudio.Builtin("chime", 70), WavAudio.Builtin("chime", 70));
    }

    // ---- the user's own wav file ---------------------------------------------------------

    private static byte[] MakeWav(int format, int channels, int rate, int bits, byte[] data, bool withData = true)
    {
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(Encoding.ASCII.GetBytes("RIFF")); w.Write(0);
        w.Write(Encoding.ASCII.GetBytes("WAVE"));
        w.Write(Encoding.ASCII.GetBytes("LIST")); w.Write(4); w.Write(Encoding.ASCII.GetBytes("INFO")); // a chunk to skip
        w.Write(Encoding.ASCII.GetBytes("fmt ")); w.Write(16);
        w.Write((ushort)format); w.Write((ushort)channels); w.Write(rate); w.Write(rate * channels * bits / 8);
        w.Write((ushort)(channels * bits / 8)); w.Write((ushort)bits);
        if (withData)
        {
            w.Write(Encoding.ASCII.GetBytes("data")); w.Write(data.Length); w.Write(data);
        }
        w.Flush();
        return ms.ToArray();
    }

    private static byte[] Pcm16(params short[] v) => v.SelectMany(BitConverter.GetBytes).ToArray();

    [Fact]
    public void OwnFile16BitIsRewrittenAtTheVolume()
    {
        var src = MakeWav(1, 1, 22050, 16, Pcm16(32767, -32768, 16384, 0));
        var full = WavAudio.FromFile(src, 100, out string why);
        Assert.NotNull(full);
        Assert.Equal("", why);
        Assert.Equal(22050, BitConverter.ToInt32(full!, 24));
        Assert.Equal(32767, WavAudio.Peak(full));
        var half = WavAudio.FromFile(src, 50, out _)!;
        Assert.InRange(WavAudio.Peak(half), 8100, 8300);
        Assert.Equal(0, WavAudio.Peak(WavAudio.FromFile(src, 0, out _)!));
    }

    [Fact]
    public void OwnFileOtherPcmShapesAreRead()
    {
        var eight = WavAudio.FromFile(MakeWav(1, 2, 8000, 8, new byte[] { 255, 0, 128, 128 }), 100, out _);
        Assert.NotNull(eight);
        Assert.Equal(2, BitConverter.ToUInt16(eight!, 22));
        Assert.InRange(WavAudio.Peak(eight), 32000, 32767);

        var fl = WavAudio.FromFile(MakeWav(3, 1, 48000, 32, BitConverter.GetBytes(0.5f).Concat(BitConverter.GetBytes(-0.25f)).ToArray()), 100, out _);
        Assert.InRange(WavAudio.Peak(fl!), 16300, 16400);

        var b24 = WavAudio.FromFile(MakeWav(1, 1, 44100, 24, new byte[] { 0, 0, 0x40, 0, 0, 0xC0 }), 100, out _);
        Assert.InRange(WavAudio.Peak(b24!), 16300, 32767);
    }

    [Fact]
    public void BadFilesAreRefusedWithAReason()
    {
        Assert.Null(WavAudio.FromFile(Encoding.ASCII.GetBytes("ID3 this is an mp3 file, really, it is long enough"), 80, out string a));
        Assert.Contains("not a WAV", a);
        Assert.Null(WavAudio.FromFile(MakeWav(2, 1, 44100, 4, new byte[] { 1, 2, 3, 4 }), 80, out string b)); // ADPCM
        Assert.Contains("uncompressed", b);
        Assert.Null(WavAudio.FromFile(MakeWav(1, 1, 44100, 16, Array.Empty<byte>(), withData: false), 80, out string c));
        Assert.Contains("no sound", c);
        Assert.Null(WavAudio.FromFile(MakeWav(1, 1, 1_000_000, 16, Pcm16(1, 2)), 80, out string d));
        Assert.Contains("not supported", d);
        Assert.Null(WavAudio.FromFile(new byte[10], 80, out _));
        Assert.Null(WavAudio.FromFile(new byte[WavAudio.MaxFileBytes + 1], 80, out string e));
        Assert.Contains("20 MB", e);

        // a data chunk that says it is longer than the file: what is there is played
        var cut = MakeWav(1, 1, 44100, 16, Pcm16(1000, 2000, 3000, 4000));
        Array.Resize(ref cut, cut.Length - 3);
        Assert.NotNull(WavAudio.FromFile(cut, 100, out _));

        // random bytes after a RIFF header never throw
        var rnd = new Random(7);
        for (int i = 0; i < 300; i++)
        {
            var junk = new byte[rnd.Next(12, 200)];
            rnd.NextBytes(junk);
            Encoding.ASCII.GetBytes("RIFF").CopyTo(junk, 0);
            Encoding.ASCII.GetBytes("WAVE").CopyTo(junk, 8);
            WavAudio.FromFile(junk, 80, out _);
        }
    }

    [Fact]
    public void ChoicesSpeakPlainly()
    {
        Assert.Equal("Once", AlertChoices.SoundLengthText(0));
        Assert.Equal("15 s", AlertChoices.SoundLengthText(15));
        Assert.Equal("5 min", AlertChoices.SoundLengthText(300));
        Assert.Equal("Until dismissed", AlertChoices.SoundLengthText(-1));
        Assert.Equal("Never", AlertChoices.CloseAfterText(0));
        Assert.Equal("1 min", AlertChoices.CloseAfterText(60));
        Assert.Equal(new[] { 0, 10, 30, 60, 300, 900 }, AlertChoices.CloseAfter);
    }

    // ---- monitors ------------------------------------------------------------------------

    private static readonly MonitorInfo Left = new(@"\\.\DISPLAY2", new(-1920, 0, 0, 1080), new(-1920, 0, 0, 1040), false, 1);
    private static readonly MonitorInfo Main = new(@"\\.\DISPLAY1", new(0, 0, 2560, 1440), new(0, 0, 2560, 1392), true, 1.5);

    [Fact]
    public void TheChosenMonitorIsUsedWhileItIsThere()
    {
        var both = new[] { Left, Main };
        Assert.Same(Main, MonitorChoice.Pick(both, null, 0, 0));
        Assert.Same(Main, MonitorChoice.Pick(both, AlertChoices.MonitorPrimary, -500, 10));
        Assert.Same(Left, MonitorChoice.Pick(both, @"\\.\display2", 100, 100));
        Assert.Same(Main, MonitorChoice.Pick(new[] { Main }, @"\\.\DISPLAY2", 0, 0)); // unplugged: the primary
        Assert.Same(Left, MonitorChoice.Pick(both, AlertChoices.MonitorCursor, -500, 10));
        Assert.Same(Main, MonitorChoice.Pick(both, AlertChoices.MonitorCursor, 100, 100));
        Assert.Same(Main, MonitorChoice.Pick(both, AlertChoices.MonitorCursor, 99999, 99999));
        Assert.Null(MonitorChoice.Pick(Array.Empty<MonitorInfo>(), null, 0, 0));
    }

    [Fact]
    public void MonitorsAreNamedSoTheyCanBeTold()
    {
        var both = new[] { Main, Left };
        Assert.Equal("Display 2 · 1920 × 1080 · left", MonitorChoice.Describe(Left, both));
        Assert.Equal("Display 1 · 2560 × 1440 · right · primary", MonitorChoice.Describe(Main, both));
        Assert.Equal("Display 1 · 2560 × 1440 · primary", MonitorChoice.Describe(Main, new[] { Main }));
        Assert.Equal(new[] { Left, Main }, MonitorChoice.Ordered(both));
    }

    // ---- conditions from ZIGMon 5.58 -----------------------------------------------------

    private static System.Text.Json.JsonElement Root(string json) => ProtocolParser.ParseDocument(Encoding.UTF8.GetBytes(json)).RootElement;

    [Fact]
    public void ConditionsAreListedWithTheirWords()
    {
        var s = ProtocolParser.Sensors(Root("""
            {"ok":true,"boot":"b","seq":5,"sensors":[
             {"id":"0xa","name":"PIR","room":"Hall","kind":"motion","active":false,"at":null,"battery":80,"online":true},
             {"id":"rule:0a1b2c3d4e","name":"Too hot","room":"Living","kind":"rule","active":false,"at":null,"battery":null,
              "online":true,"device":"0xb","device_name":"Thermometer",
              "rule":{"attr":"temperature","op":"ge","value":25,"value2":null,"hyst":0.5,"unit":"°C","text":"temperature ≥ 25 °C"},
              "value":23.4,"value_text":"23.4 °C"}]}
            """));
        var pir = s.Sensors[0];
        Assert.Equal(SensorKinds.Motion, pir.Kind);
        Assert.Null(pir.RuleText);
        var rule = s.Sensors[1];
        Assert.Equal("rule:0a1b2c3d4e", rule.Id);
        Assert.Equal(SensorKinds.Rule, rule.Kind);
        Assert.Equal("temperature ≥ 25 °C", rule.RuleText);
        Assert.Equal("23.4 °C", rule.ValueText);
        Assert.Equal("Thermometer", rule.DeviceName);
        var style = KindStyle.For(SensorKinds.Rule);
        Assert.Equal("Condition", style.Label);
        Assert.Equal("Met", style.StateWord(true, true));
        Assert.Equal("Not met", style.StateWord(false, true));
    }

    [Fact]
    public void AConditionAlertsWhenMetAndWhenNoLongerMetOnlyIfAsked()
    {
        var s = new NotifierSettings();
        s.Watched.Add(new WatchedSensor { Id = "rule:0a1b2c3d4e" });
        var met = new TriggerEvent(1, Now, "rule:0a1b2c3d4e", "Too hot", null, SensorKinds.Rule, "temperature", true, "temperature 25.3 °C (≥ 25 °C)");
        var gone = met with { Seq = 2, Active = false, What = "back to normal: temperature 24.2 °C" };
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, met, Now));
        Assert.Equal(AlertDecision.ClearingNotWanted, AlertFilter.Decide(s, gone, Now));
        s.Watched[0].AlsoWhenClears = true;
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, gone, Now));
        Assert.Equal("Temperature 25.3 °C (≥ 25 °C)", KindStyle.For(SensorKinds.Rule).Headline(met.What, true));
    }

    // ---- the look: what the screenshot showed ----------------------------------------------

    private static XDocument Xaml(string rel) => XDocument.Load(Path.Combine(ReleaseKeyTests.RepoRoot(), "windows", "ZigmonNotifier", rel));

    [Fact]
    public void TextBoxPaddingIsNotAppliedTwice()
    {
        // the box itself puts Padding round its text; a Margin of Padding on PART_ContentHost as well
        // put the caret far from the start of every field (1.1.0)
        var hosts = Xaml("Theme.xaml").Descendants().Where(e => (string?)e.Attribute(XName.Get("Name", "http://schemas.microsoft.com/winfx/2006/xaml")) == "PART_ContentHost").ToList();
        Assert.True(hosts.Count >= 2); // Field and SecretField, and (1.4.0) AreaField and BareField
        foreach (var h in hosts) Assert.Null(h.Attribute("Margin"));
    }

    [Fact]
    public void SensorNamesAreLightOnTheDarkList()
    {
        // a ListBox brings the system's black text; the names were black on dark grey (1.1.0)
        var doc = Xaml(Path.Combine("Views", "SensorsWindow.xaml"));
        XNamespace p = "http://schemas.microsoft.com/winfx/2006/xaml/presentation";
        var list = doc.Descendants(p + "ListBox").Single();
        Assert.Equal("{StaticResource TextBrush}", (string?)list.Attribute("Foreground"));
        var name = doc.Descendants(p + "TextBlock").First(t => (string?)t.Attribute("Text") == "{Binding Name}");
        Assert.Equal("{StaticResource TextBrush}", (string?)name.Attribute("Foreground"));
    }
}
