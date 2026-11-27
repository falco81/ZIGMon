using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Web;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Tests;

public sealed record SeenRequest(Uri Uri, Dictionary<string, string> Headers);

/// <summary>A ZIGMon relay speaking protocol v1, in memory, as an HttpMessageHandler.</summary>
public sealed class FakeZigmon : HttpMessageHandler
{
    public const string GoodKey = "zmn_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_xQ";

    public string Boot { get; set; } = "a1b2c3d4e5f6";
    public long Seq { get; private set; } = 1234;
    public string House { get; set; } = "mqtt";
    public TimeSpan Hold { get; set; } = TimeSpan.FromMilliseconds(30);
    public List<object> Sensors { get; } = new();
    public List<(long Seq, object Event)> Events { get; } = new();

    /// <summary>Answers to give before behaving normally: (status, body, extra headers).</summary>
    public ConcurrentQueue<(int Status, string Body, Action<HttpResponseMessage>? Tweak)> Scripted { get; } = new();
    /// <summary>The next "wait" calls answer reset:true.</summary>
    public int ResetsToGive { get; set; }

    /// <summary>hello's "app": absent (an older ZIGMon) unless set; <see cref="HelloAppNull"/> sends "app": null.</summary>
    public string? HelloAppVersion { get; set; }
    public bool HelloAppNull { get; set; }
    /// <summary>The /update answer (JSON); null answers 400 like a ZIGMon from before updates.</summary>
    public string? UpdateJson { get; set; }
    /// <summary>The /download body; null answers 404.</summary>
    public byte[]? DownloadBytes { get; set; }
    /// <summary>Sent as Content-Length when set (to lie with).</summary>
    public long? DownloadLength { get; set; }

    public ConcurrentQueue<SeenRequest> Requests { get; } = new();
    public int Count(string what) => Requests.Count(r => r.Uri.Query.Contains("do=" + what, StringComparison.Ordinal));

    private readonly SemaphoreSlim _news = new(0);

    public FakeZigmon()
    {
        Sensors.Add(new { id = "0x00158d0001a2b3c4", name = "PIR-Chodba", room = "Hallway", kind = "motion", active = false, at = 1764151234.5, battery = 87, online = true });
        Sensors.Add(new { id = "0x00158d0001a2b3c5", name = "Front door", room = "Hall", kind = "contact", active = false, at = (double?)null, battery = (int?)null, online = true });
        Sensors.Add(new { id = "0x00158d0001a2b3c6", name = "Doorbell", room = (string?)null, kind = "button", active = (bool?)null, at = (double?)null, battery = 50, online = true });
    }

    public void Push(string device, string name, string kind, bool? active, string what)
    {
        lock (Events)
        {
            Seq++;
            Events.Add((Seq, new { seq = Seq, at = 1764151300.2, device, name, room = "Hallway", kind, key = "occupancy", active, what }));
        }
        _news.Release();
    }

    /// <summary>The daemon restarted: new boot id, buffer gone.</summary>
    public void Restart(string newBoot)
    {
        lock (Events) { Events.Clear(); Boot = newBoot; Seq = 5; }
    }

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        Requests.Enqueue(new SeenRequest(request.RequestUri!,
            request.Headers.ToDictionary(h => h.Key,
                h => h.Key == "User-Agent" ? request.Headers.UserAgent.ToString() : string.Join(",", h.Value),
                StringComparer.OrdinalIgnoreCase)));

        if (Scripted.TryDequeue(out var s))
        {
            var r = Json(s.Status, s.Body);
            s.Tweak?.Invoke(r);
            return r;
        }

        if (!request.Headers.TryGetValues(AppInfo.KeyHeader, out var keys) || keys.Single() != GoodKey)
            return Json(401, "{\"ok\":false,\"error\":\"wrong key\"}");

        var q = HttpUtility.ParseQueryString(request.RequestUri!.Query);
        if (q["api"] != "notifier") return Json(400, "{\"ok\":false,\"error\":\"no such api\"}");
        switch (q["do"])
        {
            case "hello":
                var hello = new Dictionary<string, object?>
                {
                    ["ok"] = true, ["api"] = 1, ["server"] = "zigmon", ["version"] = "5.57.0", ["house"] = House,
                    ["key"] = new { name = "Office PC", devices = Sensors.Count, hint = "xQ" }, ["boot"] = Boot, ["seq"] = Seq,
                };
                if (HelloAppNull) hello["app"] = null;
                else if (HelloAppVersion is not null) hello["app"] = new { version = HelloAppVersion };
                return Json(200, JsonSerializer.Serialize(hello));
            case "update":
                return UpdateJson is null
                    ? Json(400, "{\"ok\":false,\"error\":\"do must be hello, sensors or wait\"}")
                    : Json(200, UpdateJson);
            case "download":
                if (DownloadBytes is null) return Json(404, "{\"ok\":false,\"error\":\"no app here\"}");
                var bin = new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(DownloadBytes) };
                bin.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/octet-stream");
                if (DownloadLength is { } len) bin.Content.Headers.ContentLength = len;
                return bin;
            case "sensors":
                return Json(200, JsonSerializer.Serialize(new { ok = true, boot = Boot, seq = Seq, sensors = Sensors }));
            case "wait":
                long after = long.Parse(q["after"] ?? "-1");
                string boot = q["boot"] ?? "";
                if (ResetsToGive > 0 || boot != Boot || after > Seq)
                {
                    if (ResetsToGive > 0) ResetsToGive--;
                    return Json(200, JsonSerializer.Serialize(new { ok = true, boot = Boot, seq = Seq, reset = true, events = Array.Empty<object>() }));
                }
                var deadline = DateTime.UtcNow + Hold;
                while (true)
                {
                    object[] fresh;
                    long seqNow;
                    lock (Events)
                    {
                        fresh = Events.Where(e => e.Seq > after).Take(50).Select(e => e.Event).ToArray();
                        seqNow = fresh.Length > 0 ? Events.Where(e => e.Seq > after).Take(50).Last().Seq : Seq;
                    }
                    if (fresh.Length > 0 || DateTime.UtcNow >= deadline)
                        return Json(200, JsonSerializer.Serialize(new { ok = true, boot = Boot, seq = seqNow, reset = false, events = fresh }));
                    var left = deadline - DateTime.UtcNow;
                    if (left > TimeSpan.Zero) await _news.WaitAsync(left, ct);
                }
            default:
                return Json(400, "{\"ok\":false,\"error\":\"do must be hello, sensors or wait\"}");
        }
    }

    public static HttpResponseMessage Json(int status, string body) => new((HttpStatusCode)status)
    {
        Content = new StringContent(body, Encoding.UTF8, "application/json"),
    };
}

/// <summary>Stands in for DPAPI: reversible, and the stored text does not contain the key.</summary>
public sealed class FakeProtector : ISecretProtector
{
    public byte[] Protect(byte[] plain) => new byte[] { 0x5A }.Concat(plain.Select(b => (byte)(b ^ 0xA5))).ToArray();
    public byte[] Unprotect(byte[] data)
    {
        if (data.Length == 0 || data[0] != 0x5A) throw new System.Security.Cryptography.CryptographicException("not ours");
        return data.Skip(1).Select(b => (byte)(b ^ 0xA5)).ToArray();
    }
}
