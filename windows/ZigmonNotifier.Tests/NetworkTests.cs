using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Tests;

internal static class K
{
    public static NotifierKey Good => NotifierKey.TryParse(FakeZigmon.GoodKey, out var k, out _) ? k : throw new Exception();
    public static NotifierKey Wrong => NotifierKey.TryParse("zmn_ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", out var k, out _) ? k : throw new Exception();
    public static readonly ServerAddress Address = ServerAddress.Parse("https://zigmon.example.net/index.php");
}

public class ClientTests
{
    [Fact]
    public async Task HelloSensorsWait()
    {
        var fake = new FakeZigmon();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var h = await c.HelloAsync(default);
        Assert.Equal("mqtt", h.House);
        Assert.Equal("Office PC", h.Key.Name);
        var s = await c.SensorsAsync(default);
        Assert.Equal(3, s.Sensors.Count);
        Assert.Equal(SensorKinds.Button, s.Sensors[2].Kind);

        fake.Push("0x00158d0001a2b3c4", "PIR-Chodba", "motion", true, "motion");
        var w = await c.WaitAsync(h.Seq, h.Boot, default);
        Assert.False(w.Reset);
        var e = Assert.Single(w.Events);
        Assert.Equal(h.Seq + 1, e.Seq);
        Assert.True(e.Active);
        Assert.Equal("motion", e.What);
        Assert.Equal(h.Seq + 1, w.Seq);

        var empty = await c.WaitAsync(w.Seq, h.Boot, default);
        Assert.Empty(empty.Events);
        var reset = await c.WaitAsync(w.Seq, "0ther0b00t00", default);
        Assert.True(reset.Reset);
    }

    [Fact]
    public async Task KeyTravelsOnlyInItsHeader()
    {
        var fake = new FakeZigmon();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var h = await c.HelloAsync(default);
        await c.SensorsAsync(default);
        await c.WaitAsync(h.Seq, h.Boot, default);
        Assert.Equal(3, fake.Requests.Count);
        foreach (var r in fake.Requests)
        {
            Assert.Equal(FakeZigmon.GoodKey, r.Headers[AppInfo.KeyHeader]);
            Assert.Equal("ZigmonNotifier/1.2.0 (Windows)", r.Headers["User-Agent"]);
            Assert.DoesNotContain(FakeZigmon.GoodKey[4..], r.Uri.ToString());
            foreach (var (name, value) in r.Headers)
                if (!name.Equals(AppInfo.KeyHeader, StringComparison.OrdinalIgnoreCase))
                    Assert.DoesNotContain(FakeZigmon.GoodKey[4..], value);
            Assert.Equal("zigmon.example.net", r.Uri.Host);
            Assert.Equal("/index.php", r.Uri.AbsolutePath);
        }
        Assert.Contains("do=wait&after=1234&boot=a1b2c3d4e5f6", fake.Requests.Last().Uri.Query);
        Assert.DoesNotContain(FakeZigmon.GoodKey, c.ToString());
    }

    [Fact]
    public async Task WrongKeyIs401AndTheMessageHoldsNoKey()
    {
        var fake = new FakeZigmon();
        fake.Scripted.Enqueue((401, "{\"ok\":false,\"error\":\"key " + FakeZigmon.GoodKey + " is not known\"}", null));
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
        Assert.Equal(ZigmonErrorKind.Unauthorized, e.Kind);
        Assert.Equal(401, e.Status);
        Assert.DoesNotContain(FakeZigmon.GoodKey[4..], e.Message);
        Assert.DoesNotContain(FakeZigmon.GoodKey[4..], e.ToString());

        using var wrong = new ZigmonClient(K.Address, K.Wrong, fake);
        var e2 = await Assert.ThrowsAsync<ZigmonException>(() => wrong.HelloAsync(default));
        Assert.Equal(ZigmonErrorKind.Unauthorized, e2.Kind);
    }

    [Fact]
    public async Task ServerEchoOfTheKeyIsScrubbed()
    {
        var fake = new FakeZigmon();
        fake.Scripted.Enqueue((400, "{\"ok\":false,\"error\":\"what is " + FakeZigmon.GoodKey + "\"}", null));
        fake.Scripted.Enqueue((503, "{\"ok\":false,\"error\":\"daemon down, key " + FakeZigmon.GoodKey[4..] + "\"}", null));
        fake.Scripted.Enqueue((200, "{\"ok\":false,\"error\":\"nope " + FakeZigmon.GoodKey + "\"}", null));
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        for (int i = 0; i < 3; i++)
        {
            var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
            Assert.DoesNotContain(FakeZigmon.GoodKey[4..], e.Message);
            Assert.Contains("…xQ", e.Message);
        }
    }

    [Fact]
    public async Task RateLimitCarriesRetryAfter()
    {
        var fake = new FakeZigmon();
        fake.Scripted.Enqueue((429, "{\"ok\":false,\"error\":\"too many\"}",
            r => r.Headers.RetryAfter = new System.Net.Http.Headers.RetryConditionHeaderValue(TimeSpan.FromSeconds(120))));
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
        Assert.Equal(ZigmonErrorKind.RateLimited, e.Kind);
        Assert.Equal(TimeSpan.FromSeconds(120), e.RetryAfter);
    }

    [Theory]
    [InlineData(503, ZigmonErrorKind.Unavailable)]
    [InlineData(400, ZigmonErrorKind.BadRequest)]
    [InlineData(404, ZigmonErrorKind.Http)]
    [InlineData(500, ZigmonErrorKind.Http)]
    [InlineData(302, ZigmonErrorKind.Redirect)]
    public async Task StatusesMapToKinds(int status, ZigmonErrorKind kind)
    {
        var fake = new FakeZigmon();
        fake.Scripted.Enqueue((status, "<html>error page</html>", r =>
        {
            if (status == 302) r.Headers.Location = new Uri("https://elsewhere.example.org/steal");
        }));
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.SensorsAsync(default));
        Assert.Equal(kind, e.Kind);
        if (status == 302) Assert.Contains("elsewhere.example.org", e.Message);
        Assert.Single(fake.Requests); // nothing followed
    }

    [Fact]
    public async Task HtmlInsteadOfJsonIsAProtocolError()
    {
        var fake = new FakeZigmon();
        fake.Scripted.Enqueue((200, "<!doctype html><title>Sign in</title>", null));
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
        Assert.Equal(ZigmonErrorKind.Protocol, e.Kind);
    }

    [Fact]
    public async Task HugeAnswersAreNotRead()
    {
        var fake = new FakeZigmon();
        fake.Scripted.Enqueue((200, "{\"ok\":true,\"pad\":\"" + new string('x', ZigmonClient.MaxResponseBytes + 10) + "\"}", null));
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
        Assert.Equal(ZigmonErrorKind.TooLarge, e.Kind);
    }

    [Fact]
    public async Task CancellingAWaitIsQuick()
    {
        var fake = new FakeZigmon { Hold = TimeSpan.FromSeconds(30) };
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var h = await c.HelloAsync(default);
        using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(150));
        var sw = System.Diagnostics.Stopwatch.StartNew();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => c.WaitAsync(h.Seq, h.Boot, cts.Token));
        Assert.True(sw.Elapsed < TimeSpan.FromSeconds(5));
    }
}

/// <summary>Real sockets: plain http on loopback via HttpListener.</summary>
public class LoopbackHttpTests
{
    private static int FreePort()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        int p = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return p;
    }

    [Fact]
    public async Task HeaderOnTheWireAndRedirectNotFollowed()
    {
        int port = FreePort();
        using var listener = new HttpListener();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        var seen = new ConcurrentQueue<(string Url, string? Key, string? Agent)>();
        var serve = Task.Run(async () =>
        {
            while (listener.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = await listener.GetContextAsync(); } catch { return; }
                seen.Enqueue((ctx.Request.Url!.ToString(), ctx.Request.Headers[AppInfo.KeyHeader], ctx.Request.UserAgent));
                if (ctx.Request.Url!.Query.Contains("do=sensors"))
                {
                    ctx.Response.StatusCode = 302;
                    ctx.Response.RedirectLocation = $"http://127.0.0.1:{port}/elsewhere";
                    ctx.Response.Close();
                    continue;
                }
                byte[] body = Encoding.UTF8.GetBytes("""{"ok":true,"api":1,"server":"zigmon","version":"5.57.0","house":"loop","key":{"name":"T","devices":1,"hint":"xQ"},"boot":"bbbbbbbbbbbb","seq":3}""");
                ctx.Response.ContentType = "application/json";
                ctx.Response.ContentLength64 = body.Length;
                await ctx.Response.OutputStream.WriteAsync(body);
                ctx.Response.Close();
            }
        });

        var address = ServerAddress.Parse($"http://127.0.0.1:{port}/index.php");
        using (var c = ZigmonClient.Create(address, K.Good, null))
        {
            var h = await c.HelloAsync(default);
            Assert.Equal("loop", h.House);
            var e = await Assert.ThrowsAsync<ZigmonException>(() => c.SensorsAsync(default));
            Assert.Equal(ZigmonErrorKind.Redirect, e.Kind);
        }
        listener.Stop();
        Assert.Equal(2, seen.Count); // /elsewhere was never asked for
        foreach (var (url, key, agent) in seen)
        {
            Assert.Equal(FakeZigmon.GoodKey, key);
            Assert.Equal(AppInfo.UserAgent, agent);
            Assert.DoesNotContain(FakeZigmon.GoodKey[4..], url);
        }
    }
}

/// <summary>Real TLS with a self-made certificate: untrusted unless pinned.</summary>
public class TlsTests
{
    public static X509Certificate2 SelfSigned(string name)
    {
        using var rsa = RSA.Create(2048);
        var req = new CertificateRequest("CN=" + name, rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        var san = new SubjectAlternativeNameBuilder();
        san.AddDnsName(name);
        req.CertificateExtensions.Add(san.Build());
        req.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(new OidCollection { new Oid("1.3.6.1.5.5.7.3.1") }, false));
        using var cert = req.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(1));
        return X509CertificateLoader.LoadPkcs12(cert.Export(X509ContentType.Pfx), null);
    }

    private sealed class TlsServer : IDisposable
    {
        private readonly TcpListener _listener;
        private readonly X509Certificate2 _cert;
        private readonly CancellationTokenSource _stop = new();
        public int Port { get; }
        public int Served;

        public TlsServer(X509Certificate2 cert)
        {
            _cert = cert;
            _listener = new TcpListener(IPAddress.Loopback, 0);
            _listener.Start();
            Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
            _ = Task.Run(Loop);
        }

        private async Task Loop()
        {
            while (!_stop.IsCancellationRequested)
            {
                TcpClient client;
                try { client = await _listener.AcceptTcpClientAsync(_stop.Token); } catch { return; }
                _ = Task.Run(async () =>
                {
                    using (client)
                    {
                        try
                        {
                            using var ssl = new SslStream(client.GetStream());
                            await ssl.AuthenticateAsServerAsync(_cert);
                            var buf = new byte[8192];
                            var sb = new StringBuilder();
                            while (!sb.ToString().Contains("\r\n\r\n"))
                            {
                                int n = await ssl.ReadAsync(buf);
                                if (n == 0) return;
                                sb.Append(Encoding.ASCII.GetString(buf, 0, n));
                            }
                            byte[] body = Encoding.UTF8.GetBytes("""{"ok":true,"api":1,"server":"zigmon","version":"5.57.0","house":"tls","key":{"name":"T","devices":1,"hint":"xQ"},"boot":"cccccccccccc","seq":9}""");
                            string head = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n";
                            await ssl.WriteAsync(Encoding.ASCII.GetBytes(head));
                            await ssl.WriteAsync(body);
                            Interlocked.Increment(ref Served);
                        }
                        catch (Exception)
                        {
                            // the client refused the certificate: expected in some tests
                        }
                    }
                });
            }
        }

        public void Dispose()
        {
            _stop.Cancel();
            _listener.Stop();
        }
    }

    [Fact]
    public async Task UntrustedUnlessPinned()
    {
        using var cert = SelfSigned("localhost");
        string sha = Convert.ToHexString(SHA256.HashData(cert.RawData));
        using var server = new TlsServer(cert);
        var address = ServerAddress.Parse($"https://localhost:{server.Port}");

        // 1. no pin: refused, and the certificate is there to be shown
        using (var c = ZigmonClient.Create(address, K.Good, null))
        {
            var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
            Assert.Equal(ZigmonErrorKind.Certificate, e.Kind);
            Assert.NotNull(e.Certificate);
            Assert.Equal(sha, e.Certificate!.Sha256);
            Assert.Contains("CN=localhost", e.Certificate.Subject);
            Assert.False(e.Certificate.TrustedByWindows);
            // the update's download goes through the very same rules
            var d = await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(1000, default));
            Assert.Equal(ZigmonErrorKind.Certificate, d.Kind);
            Assert.Equal(ZigmonErrorKind.Certificate, (await Assert.ThrowsAsync<ZigmonException>(() => c.UpdateAsync(default))).Kind);
        }

        // 2. pinned: accepted
        var pin = new CertificatePin(address.PinScope, sha, "CN=localhost", DateTimeOffset.UtcNow);
        using (var c = ZigmonClient.Create(address, K.Good, pin))
        {
            var h = await c.HelloAsync(default);
            Assert.Equal("tls", h.House);
            Assert.Equal(CertificateVerdict.Pinned, c.LastCertificateVerdict);
        }

        // 3. another certificate pinned: refused as a mismatch
        var wrongPin = pin with { Sha256 = new string('0', 64) };
        using (var c = ZigmonClient.Create(address, K.Good, wrongPin))
        {
            var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
            Assert.Equal(ZigmonErrorKind.Certificate, e.Kind);
            Assert.Contains("not the one you trusted", e.Message);
            Assert.Equal(ZigmonErrorKind.Certificate, (await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(1000, default))).Kind);
        }

        // 4. a pin for another port does not apply
        var otherScope = pin with { Scope = "localhost:1" };
        using (var c = ZigmonClient.Create(address, K.Good, otherScope))
        {
            var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
            Assert.Equal(ZigmonErrorKind.Certificate, e.Kind);
        }
        Assert.Equal(1, server.Served);
    }

    [Fact]
    public async Task UnreachableIsANetworkError()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        int port = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        using var c = ZigmonClient.Create(ServerAddress.Parse($"https://127.0.0.1:{port}"), K.Good, null);
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.HelloAsync(default));
        Assert.Equal(ZigmonErrorKind.Network, e.Kind);
        Assert.DoesNotContain(FakeZigmon.GoodKey[4..], e.Message);
    }
}

public class ServiceTests
{
    private sealed class Harness
    {
        public readonly FakeZigmon Fake = new();
        public readonly List<TimeSpan> Delays = new();
        public readonly List<ConnectionStatus> Statuses = new();
        public readonly ConcurrentQueue<TriggerEvent> Events = new();
        public readonly ConcurrentQueue<string> Log = new();
        public readonly NotifierService Service;
        public readonly ZigmonClient Client;

        public Harness(Func<int, TimeSpan, CancellationToken, Task>? onDelay = null)
        {
            Client = new ZigmonClient(K.Address, K.Good, Fake);
            Service = new NotifierService(Client, Log.Enqueue, async (t, ct) =>
            {
                lock (Delays) Delays.Add(t);
                if (onDelay is not null) await onDelay(Delays.Count, t, ct);
            });
            Service.StatusChanged += s => { lock (Statuses) Statuses.Add(s); };
            Service.EventsArrived += list => { foreach (var e in list) Events.Enqueue(e); };
        }

        public static async Task Until(Func<bool> condition, int ms = 5000)
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();
            while (!condition())
            {
                if (sw.ElapsedMilliseconds > ms) throw new TimeoutException("condition not met");
                await Task.Delay(10);
            }
        }
    }

    [Fact]
    public void BackoffDoubles()
    {
        var got = Enumerable.Range(1, 9).Select(i => (int)NotifierService.Backoff(i).TotalSeconds).ToArray();
        Assert.Equal(new[] { 1, 2, 4, 8, 16, 32, 60, 60, 60 }, got);
    }

    [Fact]
    public async Task DeliversEventsAndKeepsStateLive()
    {
        var h = new Harness();
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        Assert.Equal("mqtt", h.Service.Status.Hello!.House);
        Assert.Equal(3, h.Service.Sensors.Count);

        h.Fake.Push("0x00158d0001a2b3c4", "PIR-Chodba", "motion", true, "motion");
        h.Fake.Push("0x00158d0001a2b3c5", "Front door", "contact", true, "opened");
        await Harness.Until(() => h.Events.Count == 2);
        Assert.Equal(new long[] { 1235, 1236 }, h.Events.Select(e => e.Seq).ToArray());
        Assert.True(h.Service.Sensors.First(s => s.Id == "0x00158d0001a2b3c5").Active);

        // the first wait asked from hello's seq, the later ones from what came back
        var waits = h.Fake.Requests.Where(r => r.Uri.Query.Contains("do=wait")).Select(r => r.Uri.Query).ToList();
        Assert.Contains("after=1234&", waits[0]);
        await Harness.Until(() => h.Fake.Requests.Any(r => r.Uri.Query.Contains("after=1236&")));

        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(ConnectionState.Stopped, h.Service.Status.State);
        Assert.Empty(h.Delays);
    }

    [Fact]
    public async Task ResetReReadsSensorsAndGoesOnFromTheirSeq()
    {
        var h = new Harness();
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        int sensorsBefore = h.Fake.Count("sensors");

        h.Fake.Restart("ffffffffffff"); // the daemon restarted: boot changes, seq starts again
        await Harness.Until(() => h.Fake.Count("sensors") > sensorsBefore);
        h.Fake.Push("0x00158d0001a2b3c6", "Doorbell", "button", true, "pressed: single");
        await Harness.Until(() => h.Events.Count == 1);
        Assert.Equal(6, h.Events.Single().Seq);
        Assert.Contains(h.Fake.Requests, r => r.Uri.Query.Contains("after=5&boot=ffffffffffff"));

        h.Fake.ResetsToGive = 1; // reset:true with the same boot (fell behind the buffer)
        int n = h.Fake.Count("sensors");
        await Harness.Until(() => h.Fake.Count("sensors") > n);
        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task BacksOffThenRecovers()
    {
        var h = new Harness();
        for (int i = 0; i < 8; i++) h.Fake.Scripted.Enqueue((503, "{\"ok\":false,\"error\":\"daemon\"}", null));
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        Assert.Equal(new[] { 1, 2, 4, 8, 16, 32, 60, 60 }, h.Delays.Select(d => (int)d.TotalSeconds).ToArray());
        lock (h.Statuses)
            Assert.Contains(h.Statuses, s => s.State == ConnectionState.Retrying && s.Error == ZigmonErrorKind.Unavailable);

        // a failure after success starts again from 1 s, and resumes the same stream (no new hello)
        int hellos = h.Fake.Count("hello");
        h.Fake.Scripted.Enqueue((500, "oops", null));
        await Harness.Until(() => h.Delays.Count == 9);
        Assert.Equal(TimeSpan.FromSeconds(1), h.Delays[8]);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        Assert.Equal(hellos, h.Fake.Count("hello"));
        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task AnswerCutAtFiftyGoesOnFromItsOwnSeq()
    {
        var h = new Harness();
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        for (int i = 0; i < 120; i++) h.Fake.Push("0x00158d0001a2b3c4", "PIR-Chodba", "motion", i % 2 == 0, "motion");
        await Harness.Until(() => h.Events.Count == 120);
        var seqs = h.Events.Select(e => e.Seq).ToArray();
        Assert.Equal(Enumerable.Range(1235, 120).Select(i => (long)i).ToArray(), seqs); // none lost, none twice
        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task TooManyWaitingIsTransient()
    {
        var h = new Harness();
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        h.Fake.Scripted.Enqueue((503, "{\"ok\":false,\"error\":\"too many waiting\"}", null));
        await Harness.Until(() => h.Delays.Count == 1);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        lock (h.Statuses) Assert.Contains(h.Statuses, s => s.Message.Contains("too many waiting"));
        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task RateLimitWaitsAtLeastAMinute()
    {
        var h = new Harness();
        h.Fake.Scripted.Enqueue((429, "{\"ok\":false,\"error\":\"slow down\"}", null));
        h.Fake.Scripted.Enqueue((429, "{\"ok\":false,\"error\":\"slow down\"}",
            r => r.Headers.RetryAfter = new System.Net.Http.Headers.RetryConditionHeaderValue(TimeSpan.FromSeconds(300))));
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        Assert.Equal(new[] { 60, 300 }, h.Delays.Select(d => (int)d.TotalSeconds).ToArray());
        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
    }

    [Fact]
    public async Task WrongKeyStopsTheLoop()
    {
        var fake = new FakeZigmon();
        using var client = new ZigmonClient(K.Address, K.Wrong, fake);
        var log = new ConcurrentQueue<string>();
        var service = new NotifierService(client, log.Enqueue, (t, ct) => Task.CompletedTask);
        await service.RunAsync(default).WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(ConnectionState.NeedsAttention, service.Status.State);
        Assert.Equal(ZigmonErrorKind.Unauthorized, service.Status.Error);
        Assert.Single(fake.Requests); // no hammering with a wrong key
    }

    [Fact]
    public async Task RevokedKeyDuringWaitStops()
    {
        var h = new Harness();
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        h.Fake.Scripted.Enqueue((401, "{\"ok\":false,\"error\":\"revoked\"}", null));
        await run.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(ConnectionState.NeedsAttention, h.Service.Status.State);
    }

    [Fact]
    public async Task CancelDuringBackoffStops()
    {
        var gate = new TaskCompletionSource();
        var h = new Harness(async (n, t, ct) => { gate.TrySetResult(); await Task.Delay(Timeout.Infinite, ct); });
        h.Fake.Scripted.Enqueue((503, "{}", null));
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await gate.Task.WaitAsync(TimeSpan.FromSeconds(5));
        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.Equal(ConnectionState.Stopped, h.Service.Status.State);
    }

    [Fact]
    public async Task NothingLeaksTheKey()
    {
        var h = new Harness();
        h.Fake.Scripted.Enqueue((503, "{\"ok\":false,\"error\":\"echo " + FakeZigmon.GoodKey + "\"}", null));
        h.Fake.Scripted.Enqueue((400, "{\"ok\":false,\"error\":\"echo " + FakeZigmon.GoodKey + "\"}", null));
        using var cts = new CancellationTokenSource();
        var run = h.Service.RunAsync(cts.Token);
        await Harness.Until(() => h.Service.Status.State == ConnectionState.Connected);
        cts.Cancel();
        await run.WaitAsync(TimeSpan.FromSeconds(5));
        string secret = FakeZigmon.GoodKey[4..];
        Assert.NotEmpty(h.Log);
        foreach (var line in h.Log) Assert.DoesNotContain(secret, line);
        lock (h.Statuses)
            foreach (var s in h.Statuses)
            {
                Assert.DoesNotContain(secret, s.Message);
                Assert.DoesNotContain(secret, s.ToString());
            }
        Assert.DoesNotContain(secret, h.Client.ToString());
        Assert.DoesNotContain(secret, h.Service.Status.Hello!.ToString());
    }
}
