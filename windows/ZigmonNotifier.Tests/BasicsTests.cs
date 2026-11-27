using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.RegularExpressions;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Tests;

public class ServerAddressTests
{
    [Theory]
    [InlineData("https://mqtt.example.net", "https://mqtt.example.net")]
    [InlineData("https://mqtt.example.net/", "https://mqtt.example.net")]
    [InlineData("https://mqtt.example.net/index.php", "https://mqtt.example.net")]
    [InlineData("  https://MQTT.Example.NET/INDEX.PHP  ", "https://mqtt.example.net")]
    [InlineData("mqtt.example.net", "https://mqtt.example.net")]
    [InlineData("https://host:8443/zigmon/", "https://host:8443/zigmon")]
    [InlineData("https://host:443/zigmon/index.php", "https://host/zigmon")]
    [InlineData("http://localhost:8080", "http://localhost:8080")]
    [InlineData("http://127.0.0.1/", "http://127.0.0.1")]
    [InlineData("http://[::1]:9000/index.php", "http://[::1]:9000")]
    [InlineData("https://192.168.1.10", "https://192.168.1.10")]
    public void Normalises(string input, string expected)
    {
        Assert.True(ServerAddress.TryParse(input, out var a, out var error), error);
        Assert.Equal(expected, a!.Base);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("http://mqtt.example.net")]          // plain http to another machine
    [InlineData("http://192.168.1.10")]
    [InlineData("http://127.0.0.2")]                 // only the three named loopbacks
    [InlineData("ftp://mqtt.example.net")]
    [InlineData("file:///c:/x")]
    [InlineData("javascript:alert(1)")]
    [InlineData("https://user:pass@mqtt.example.net")]
    [InlineData("https://mqtt.example.net/?api=notifier")]
    [InlineData("https://mqtt.example.net/#x")]
    [InlineData("https://mqtt example.net")]
    [InlineData("https://mqtt.example.net\\evil")]
    public void Refuses(string input)
    {
        Assert.False(ServerAddress.TryParse(input, out _, out var error));
        Assert.False(string.IsNullOrWhiteSpace(error));
    }

    [Fact]
    public void BuildsEndpoints()
    {
        var a = ServerAddress.Parse("https://mqtt.example.net/index.php");
        Assert.Equal("https://mqtt.example.net/index.php?api=notifier&do=hello", a.Endpoint("hello").AbsoluteUri);
        Assert.Equal("https://mqtt.example.net/index.php?api=notifier&do=wait&after=5&boot=ab", a.Endpoint("wait", "after=5&boot=ab").AbsoluteUri);
        Assert.Equal("https://mqtt.example.net/", a.DashboardUri.AbsoluteUri);
        Assert.Equal("mqtt.example.net:443", a.PinScope);
        Assert.Throws<ArgumentOutOfRangeException>(() => a.Endpoint("keys"));
    }
}

public class NotifierKeyTests
{
    [Fact]
    public void ParsesAndHides()
    {
        Assert.True(NotifierKey.TryParse("  " + FakeZigmon.GoodKey + "\n", out var key, out _));
        Assert.Equal("xQ", key!.Hint);
        Assert.Equal(FakeZigmon.GoodKey, key.Reveal());
        Assert.DoesNotContain("AbCdEf", key.ToString());
        Assert.EndsWith("xQ", key.ToString());
        Assert.DoesNotContain(FakeZigmon.GoodKey, $"{key}");
    }

    [Theory]
    [InlineData("")]
    [InlineData("abc")]
    [InlineData("zmn_short")]
    [InlineData("zmx_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_xQ")]
    [InlineData("zmn_AbCdEfGhIjKlMnOpQrStUvWxYz01234567 9-_xQ")]
    [InlineData("zmn_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/xQ")]
    public void RefusesNonsense(string input)
    {
        Assert.False(NotifierKey.TryParse(input, out _, out var error));
        Assert.NotNull(error);
        if (input.Length > 0) Assert.DoesNotContain(input, error);
    }

    [Fact]
    public void ScrubsEchoes()
    {
        NotifierKey.TryParse(FakeZigmon.GoodKey, out var key, out _);
        string s = key!.Scrub("bad key " + FakeZigmon.GoodKey + " and " + FakeZigmon.GoodKey[4..]);
        Assert.DoesNotContain("AbCdEfGh", s);
    }
}

public class SafeTextTests
{
    [Fact]
    public void DropsControlAndBidi()
    {
        Assert.Equal("evilgpj.exe", SafeText.Clean("evil\u202Egpj.exe", 80));
        Assert.Equal("a b", SafeText.Clean("  a\r\n\t\u0000b  ", 80));
        Assert.Equal("ab", SafeText.Clean("a\u200Bb", 80));
        Assert.DoesNotContain('\u202E', SafeText.Clean("x\u202Ey", 80));
        Assert.Equal("<Button Click=\"x\"/>", SafeText.Clean("<Button Click=\"x\"/>", 80)); // just text
    }

    [Fact]
    public void CapsLengthWithoutSplittingCharacters()
    {
        string s = SafeText.Clean(new string('a', 79) + "\U0001F600\U0001F600", 80);
        Assert.True(s.Length <= 80);
        Assert.EndsWith("\u2026", s);
        Assert.False(char.IsHighSurrogate(s[^2]));
        Assert.Equal(80, SafeText.Clean(new string('x', 10_000_000), 80).Length);
    }

    [Fact]
    public void Identifiers()
    {
        Assert.Equal("0x00158d0001a2b3c4", SafeText.Identifier(" 0x00158d0001a2b3c4 "));
        Assert.Equal("", SafeText.Identifier("a b"));
        Assert.Equal("", SafeText.Identifier("ž"));
    }
}

public class ParserTests
{
    private static System.Text.Json.JsonElement Root(string json) => ProtocolParser.ParseDocument(Encoding.UTF8.GetBytes(json)).RootElement;

    [Fact]
    public void Hello()
    {
        var h = ProtocolParser.Hello(Root("""{"ok":true,"api":1,"server":"zigmon","version":"5.57.0","house":"mqtt","key":{"name":"Office PC","devices":3,"hint":"xQ"},"boot":"a1b2c3d4e5f6","seq":1234}"""));
        Assert.Equal("mqtt", h.House);
        Assert.Equal("5.57.0", h.Version);
        Assert.Equal("Office PC", h.Key.Name);
        Assert.Equal(3, h.Key.Devices);
        Assert.Equal(1234, h.Seq);
        Assert.Equal("a1b2c3d4e5f6", h.Boot);
    }

    [Theory]
    [InlineData("""{"ok":true,"api":1,"server":"other","boot":"b","seq":1}""")]
    [InlineData("""{"ok":true,"api":2,"server":"zigmon","boot":"b","seq":1}""")]
    [InlineData("""{"ok":true,"api":1,"server":"zigmon","seq":1}""")]
    [InlineData("""{"ok":true,"api":1,"server":"zigmon","boot":"b","seq":"1"}""")]
    [InlineData("""{"ok":true,"api":1,"server":"zigmon","boot":"b c","seq":1}""")]
    public void HelloRefusesWhatIsNotV1(string json)
    {
        var e = Assert.Throws<ZigmonException>(() => ProtocolParser.Hello(Root(json)));
        Assert.Equal(ZigmonErrorKind.Protocol, e.Kind);
    }

    [Fact]
    public void SensorsAreValidated()
    {
        var s = ProtocolParser.Sensors(Root("""
            {"ok":true,"boot":"b1","seq":7,"sensors":[
              {"id":"0x1","name":"  PIR\u202e  Chodba ","room":"Hallway","kind":"motion","active":true,"at":1764151234.5,"battery":87,"online":true},
              {"id":"0x1","name":"duplicate"},
              {"id":"bad id","name":"x"},
              {"id":"0x2","name":"","kind":"laser","active":"yes","at":"never","battery":900},
              {"id":"0x3","name":"Door","kind":"CONTACT","active":null,"at":99999999999999,"online":false},
              42, null, "x"
            ]}
            """));
        Assert.Equal(3, s.Sensors.Count);
        var a = s.Sensors[0];
        Assert.Equal("PIR Chodba", a.Name);
        Assert.True(a.Active);
        Assert.Equal(87, a.Battery);
        Assert.NotNull(a.At);
        var b = s.Sensors[1];
        Assert.Equal("0x2", b.Name); // no name: the id
        Assert.Equal(SensorKinds.Other, b.Kind);
        Assert.Null(b.Active);
        Assert.Null(b.At);
        Assert.Null(b.Battery);
        Assert.True(b.Online);
        var c = s.Sensors[2];
        Assert.Equal(SensorKinds.Contact, c.Kind);
        Assert.Null(c.At);
        Assert.False(c.Online);
    }

    [Fact]
    public void WaitEventsAreSortedAndBounded()
    {
        var events = string.Join(",", Enumerable.Range(1, 300).Reverse().Select(i =>
            $$"""{"seq":{{i}},"at":1764151300.2,"device":"0x1","name":"PIR","room":"Hall","kind":"motion","key":"occupancy","active":true,"what":"motion"}"""));
        var w = ProtocolParser.Wait(Root("{\"ok\":true,\"boot\":\"b\",\"seq\":300,\"reset\":false,\"events\":[" + events + "]}"));
        Assert.Equal(ProtocolParser.MaxEvents, w.Events.Count);
        Assert.True(w.Events.Zip(w.Events.Skip(1)).All(p => p.First.Seq < p.Second.Seq));
        Assert.False(w.Reset);
    }

    [Fact]
    public void NotJsonIsAProtocolError()
    {
        var e = Assert.Throws<ZigmonException>(() => ProtocolParser.ParseDocument(Encoding.UTF8.GetBytes("<html>hi</html>")));
        Assert.Equal(ZigmonErrorKind.Protocol, e.Kind);
        Assert.Throws<ZigmonException>(() => ProtocolParser.ParseDocument(Encoding.UTF8.GetBytes("[1,2]")));
        var deep = new string('[', 100) + new string(']', 100);
        Assert.Throws<ZigmonException>(() => ProtocolParser.ParseDocument(Encoding.UTF8.GetBytes("{\"a\":" + deep + "}")));
    }
}

public class CertificatePolicyTests
{
    private static readonly string Hash = new('A', 64);
    private static readonly string Other = new('B', 64);

    [Theory]
    // no pin: only what Windows trusts
    [InlineData(SslPolicyErrors.None, null, CertificateVerdict.Trusted)]
    [InlineData(SslPolicyErrors.RemoteCertificateChainErrors, null, CertificateVerdict.Untrusted)]
    [InlineData(SslPolicyErrors.RemoteCertificateNameMismatch, null, CertificateVerdict.Untrusted)]
    // a pin: only the pinned one, trusted chain or not
    [InlineData(SslPolicyErrors.None, "same", CertificateVerdict.Pinned)]
    [InlineData(SslPolicyErrors.RemoteCertificateChainErrors, "same", CertificateVerdict.Pinned)]
    [InlineData(SslPolicyErrors.None, "other", CertificateVerdict.PinMismatch)]
    [InlineData(SslPolicyErrors.RemoteCertificateChainErrors, "other", CertificateVerdict.PinMismatch)]
    [InlineData(SslPolicyErrors.RemoteCertificateNotAvailable, "same", CertificateVerdict.Missing)]
    public void Rule(SslPolicyErrors errors, string? pin, CertificateVerdict expected)
    {
        string? p = pin switch { "same" => Hash.ToLowerInvariant(), "other" => Other, _ => null };
        Assert.Equal(expected, CertificatePolicy.Evaluate(Hash, errors, p));
    }

    [Fact]
    public void Fingerprints()
    {
        string formatted = CertificatePolicy.FormatFingerprint("ab" + new string('0', 62));
        Assert.StartsWith("AB:00:", formatted);
        Assert.Equal(95, formatted.Length);
        Assert.Equal(new string('0', 62) + "AB", CertificatePolicy.NormalizePin(string.Join(":", Enumerable.Repeat("00", 31)) + ":ab"));
        Assert.Null(CertificatePolicy.NormalizePin("xyz"));
        Assert.Null(CertificatePolicy.NormalizePin(new string('A', 40))); // a SHA-1 is not enough
        Assert.False(CertificatePolicy.Matches(Hash, null));
    }

    [Fact]
    public void CallbackUsesTheRealCertificateHash()
    {
        using var cert = TlsTests.SelfSigned("localhost");
        string sha = Convert.ToHexString(SHA256.HashData(cert.RawData));
        var observer = new CertificateObserver();
        Assert.False(HttpFactory.Validate(cert, SslPolicyErrors.RemoteCertificateChainErrors, null, observer));
        Assert.Equal(sha, observer.Last.Details!.Sha256);
        Assert.Equal(CertificateVerdict.Untrusted, observer.Last.Verdict);
        Assert.True(HttpFactory.Validate(cert, SslPolicyErrors.RemoteCertificateChainErrors, sha, observer));
        Assert.False(HttpFactory.Validate(cert, SslPolicyErrors.None, Other, observer));
        Assert.True(HttpFactory.Validate(cert, SslPolicyErrors.None, null, observer));
        Assert.Contains("CN=localhost", observer.Last.Details!.Subject);
    }

    [Fact]
    public void PinOnlyAppliesToItsHost()
    {
        var a = ServerAddress.Parse("https://zigmon.example.net");
        var pin = new CertificatePin("other.example.net:443", Hash, "CN=x", DateTimeOffset.UtcNow);
        using var h = HttpFactory.CreateHandler(a, pin, null);
        Assert.False(h.AllowAutoRedirect);
        Assert.False(h.UseCookies);
        Assert.NotNull(h.SslOptions.RemoteCertificateValidationCallback);
        // the other host's pin is not used: a trusted chain passes, an untrusted one does not
        using var cert = TlsTests.SelfSigned("zigmon.example.net");
        Assert.True(h.SslOptions.RemoteCertificateValidationCallback!(this, cert, null, SslPolicyErrors.None));
        Assert.False(h.SslOptions.RemoteCertificateValidationCallback!(this, cert, null, SslPolicyErrors.RemoteCertificateChainErrors));
    }
}

public class FilterTests
{
    private static readonly DateTimeOffset Now = new(2026, 11, 27, 12, 0, 0, TimeSpan.Zero);

    private static TriggerEvent Ev(string device, bool? active, string kind = "motion") =>
        new(1, Now, device, "x", null, kind, "occupancy", active, "motion");

    private static NotifierSettings Settings()
    {
        var s = new NotifierSettings();
        s.Watched.Add(new WatchedSensor { Id = "a" });
        s.Watched.Add(new WatchedSensor { Id = "b", AlsoWhenClears = true });
        s.Watched.Add(new WatchedSensor { Id = "btn" });
        return s;
    }

    [Fact]
    public void WatchedOnly()
    {
        var s = Settings();
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, Ev("a", true), Now));
        Assert.Equal(AlertDecision.NotWatched, AlertFilter.Decide(s, Ev("zzz", true), Now));
    }

    [Fact]
    public void ClearingOnlyWhenAsked()
    {
        var s = Settings();
        Assert.Equal(AlertDecision.ClearingNotWanted, AlertFilter.Decide(s, Ev("a", false), Now));
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, Ev("b", false), Now));
        Assert.Equal(AlertDecision.NoState, AlertFilter.Decide(s, Ev("a", null), Now));
    }

    [Fact]
    public void ButtonsAlwaysAlert()
    {
        var s = Settings();
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, Ev("btn", true, "button"), Now));
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, Ev("btn", null, "button"), Now));
    }

    [Fact]
    public void MuteAndPause()
    {
        var s = Settings();
        s.Mutes["a"] = Now.AddHours(1);
        Assert.Equal(AlertDecision.Muted, AlertFilter.Decide(s, Ev("a", true), Now));
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, Ev("a", true), Now.AddHours(1).AddSeconds(1)));
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, Ev("b", true), Now));

        s.PausedUntil = Now.AddMinutes(15);
        Assert.Equal(AlertDecision.Paused, AlertFilter.Decide(s, Ev("b", true), Now));
        Assert.Equal(AlertDecision.Alert, AlertFilter.Decide(s, Ev("b", true), Now.AddMinutes(16)));
        s.PausedUntil = null;
        s.PausedUntilResumed = true;
        Assert.Equal(AlertDecision.Paused, AlertFilter.Decide(s, Ev("b", true), Now.AddYears(5)));
    }
}

public class SettingsTests
{
    [Fact]
    public void KeyIsStoredEncryptedAndRoundTrips()
    {
        string dir = Path.Combine(Path.GetTempPath(), "zmn-test-" + Guid.NewGuid().ToString("N"));
        try
        {
            var store = new SettingsStore(Path.Combine(dir, "settings.json"));
            var s = store.Load(DateTimeOffset.UtcNow);
            Assert.False(s.HasConnection);
            NotifierKey.TryParse(FakeZigmon.GoodKey, out var key, out _);
            s.ServerUrl = "https://zigmon.example.net/index.php";
            KeyVault.Store(s, key!, new FakeProtector());
            s.Watched.Add(new WatchedSensor { Id = "0x1", Name = "PIR", AlsoWhenClears = true });
            s.SetPin(new CertificatePin("zigmon.example.net:443", new string('c', 64), "CN=zigmon", DateTimeOffset.UtcNow));
            store.Save(s);

            string text = File.ReadAllText(store.Path);
            Assert.DoesNotContain(FakeZigmon.GoodKey, text);
            Assert.DoesNotContain(FakeZigmon.GoodKey[4..20], text);
            Assert.Contains("\"keyHint\": \"xQ\"", text);

            var again = store.Load(DateTimeOffset.UtcNow);
            Assert.Equal("https://zigmon.example.net", again.ServerUrl);
            Assert.True(KeyVault.TryLoad(again, new FakeProtector())!.SameAs(key));
            Assert.True(again.FindWatched("0x1")!.AlsoWhenClears);
            Assert.Equal(new string('C', 64), again.GetPin()!.Sha256);
            Assert.True(again.HasConnection);

            // somebody else's blob (another user / machine): no key, no crash
            again.ProtectedKey = Convert.ToBase64String(new byte[] { 1, 2, 3 });
            Assert.Null(KeyVault.TryLoad(again, new FakeProtector()));
            again.ProtectedKey = "not base64 !!";
            Assert.Null(KeyVault.TryLoad(again, new FakeProtector()));
        }
        finally
        {
            if (Directory.Exists(dir)) Directory.Delete(dir, true);
        }
    }

    [Fact]
    public void DamagedFileGivesDefaults()
    {
        string dir = Path.Combine(Path.GetTempPath(), "zmn-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            var store = new SettingsStore(Path.Combine(dir, "settings.json"));
            File.WriteAllText(store.Path, "{ this is not json");
            var s = store.Load(DateTimeOffset.UtcNow);
            Assert.True(s.Sound);
            Assert.Empty(s.Watched);
            Assert.True(File.Exists(store.Path + ".unreadable"));
        }
        finally
        {
            Directory.Delete(dir, true);
        }
    }

    [Fact]
    public void SanitizeCleansUp()
    {
        var now = DateTimeOffset.UtcNow;
        var s = new NotifierSettings
        {
            ServerUrl = "http://evil.example.net",
            Pin = new PinSetting { Scope = "x:443", Sha256 = "nope" },
            PausedUntil = now.AddMinutes(-1),
        };
        s.Watched.Add(new WatchedSensor { Id = "a" });
        s.Watched.Add(new WatchedSensor { Id = "a" });
        s.Watched.Add(new WatchedSensor { Id = "bad id" });
        s.Mutes["a"] = now.AddMinutes(-5);
        s.Mutes["b"] = now.AddMinutes(5);
        s.Sanitize(now);
        Assert.Null(s.ServerUrl);
        Assert.Null(s.Pin);
        Assert.Null(s.PausedUntil);
        Assert.Single(s.Watched);
        Assert.Equal(new[] { "b" }, s.Mutes.Keys.ToArray());
    }
}

public class LooksTests
{
    // WPF's path markup and SVG both read this subset; it is checked here
    // because the app cannot be run on the build machine.
    private static readonly Regex Token = new(@"\G\s*(?:([MLHVCSQAZ])|(-?\d+(?:\.\d+)?))", RegexOptions.Compiled);
    private static readonly Dictionary<char, int> Arity = new() { ['M'] = 2, ['L'] = 2, ['H'] = 1, ['V'] = 1, ['C'] = 6, ['S'] = 4, ['Q'] = 4, ['A'] = 7, ['Z'] = 0 };

    public static IEnumerable<object[]> AllIcons() =>
        KindStyle.All.Select(k => new object[] { k.Kind, k.IconPath })
            .Append(new object[] { "radar", Icons.Radar })
            .Append(new object[] { "bell", Icons.Bell })
            .Append(new object[] { "gauge", Icons.Gauge });

    [Theory]
    [MemberData(nameof(AllIcons))]
    public void IconPathsAreWellFormed(string name, string path)
    {
        Assert.False(string.IsNullOrWhiteSpace(path), name);
        Assert.StartsWith("M ", path);
        int pos = 0;
        char cmd = ' ';
        int args = 0;
        var t = path.Trim();
        while (pos < t.Length)
        {
            var m = Token.Match(t, pos);
            Assert.True(m.Success, $"{name}: cannot read at {pos}: '{t[pos..]}'");
            if (m.Groups[1].Success)
            {
                if (cmd != ' ') Assert.True(args % Math.Max(1, Arity[cmd]) == 0 && (Arity[cmd] == 0 || args > 0), $"{name}: {cmd} has {args} numbers");
                cmd = m.Groups[1].Value[0];
                args = 0;
            }
            else
            {
                args++;
                double v = double.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
                Assert.InRange(v, -1, 25);
            }
            pos = m.Index + m.Length;
            while (pos < t.Length && t[pos] == ' ') pos++;
        }
        Assert.True(Arity[cmd] == 0 ? args == 0 : args % Arity[cmd] == 0 && args > 0, $"{name}: last {cmd} has {args}");
    }

    [Fact]
    public void EveryKindHasAStyle()
    {
        foreach (var k in SensorKinds.All)
        {
            var st = KindStyle.For(k);
            Assert.Equal(k, st.Kind);
            Assert.Matches("^#[0-9A-F]{6}$", st.Accent);
        }
        Assert.Equal(SensorKinds.Other, KindStyle.For("laser").Kind);
        Assert.Equal("Open", KindStyle.For("contact").StateWord(true, true));
        Assert.Equal("Offline", KindStyle.For("contact").StateWord(true, false));
        Assert.Equal("Pressed: single", KindStyle.For("button").Headline("pressed: single", true));
        Assert.Equal("Closed", KindStyle.For("contact").Headline("", false));
    }

    [Theory]
    [InlineData(16)]
    [InlineData(20)]
    [InlineData(32)]
    [InlineData(256)]
    public void IconRenders(int size)
    {
        foreach (var dot in Enum.GetValues<StatusDot>())
        {
            var px = IconPainter.Render(size, dot);
            Assert.Equal(size * size * 4, px.Length);
            Assert.Equal(0, px[3]); // the rounded corner stays see-through
            int mid = (size / 2 * size + size / 2) * 4;
            Assert.Equal(255, px[mid + 3]); // the middle is solid
        }
    }

    [Fact]
    public void IcoAndPngAreWellFormed()
    {
        var ico = ImageFiles.Ico(new[] { 16, 32, 256 }.Select(s => (s, IconPainter.Render(s))).ToList());
        Assert.Equal(new byte[] { 0, 0, 1, 0, 3, 0 }, ico[..6]);
        Assert.Equal(16, ico[6]);
        int pngAt = BitConverter.ToInt32(ico, 6 + 32 + 12);
        Assert.Equal(0x89, ico[pngAt]);
        Assert.Equal((byte)'P', ico[pngAt + 1]);
        int dibAt = BitConverter.ToInt32(ico, 6 + 12);
        Assert.Equal(40, BitConverter.ToInt32(ico, dibAt));
        Assert.Equal(32, BitConverter.ToInt32(ico, dibAt + 8)); // height is doubled
    }

    [Fact]
    public void ChimeIsAShortWav()
    {
        var wav = Chime.CreateWav();
        Assert.Equal("RIFF", Encoding.ASCII.GetString(wav, 0, 4));
        Assert.Equal("WAVE", Encoding.ASCII.GetString(wav, 8, 4));
        Assert.Equal(wav.Length - 8, BitConverter.ToInt32(wav, 4));
        double seconds = (wav.Length - 44) / 2.0 / Chime.SampleRate;
        Assert.InRange(seconds, 0.5, 1.5);
        short peak = 0;
        for (int i = 44; i < wav.Length; i += 2) peak = Math.Max(peak, Math.Abs(BitConverter.ToInt16(wav, i)));
        Assert.InRange(peak, 8000, 16000); // soft, not clipping
    }

    [Fact]
    public void Ago()
    {
        var now = new DateTimeOffset(2026, 11, 27, 12, 0, 0, TimeSpan.Zero);
        Assert.Equal("just now", TimeText.Ago(now.AddSeconds(-3), now));
        Assert.Equal("just now", TimeText.Ago(now.AddSeconds(30), now)); // clock skew
        Assert.Equal("42 s ago", TimeText.Ago(now.AddSeconds(-42), now));
        Assert.Equal("5 min ago", TimeText.Ago(now.AddMinutes(-5), now));
        Assert.Equal("2 h ago", TimeText.Ago(now.AddHours(-2), now));
    }
}
