using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Authentication;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace ZigmonNotifier.Core;

/// <summary>The three calls of protocol v1.</summary>
public interface INotifierApi
{
    Task<HelloInfo> HelloAsync(CancellationToken cancellationToken);
    Task<SensorsSnapshot> SensorsAsync(CancellationToken cancellationToken);
    Task<WaitResult> WaitAsync(long after, string boot, CancellationToken cancellationToken);
}

/// <summary>
/// Talks to one ZIGMon with one key. The key goes in the X-Zigmon-Notifier
/// header and nowhere else; errors come out as <see cref="ZigmonException"/>
/// with the key scrubbed from anything the server said.
/// </summary>
public sealed class ZigmonClient : INotifierApi, IUpdateSource, IDisposable
{
    /// <summary>No honest answer is bigger (2000 sensors are ~400 KB).</summary>
    public const int MaxResponseBytes = 2 * 1024 * 1024;
    private const int MaxErrorBytes = 64 * 1024;

    public static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(20);
    /// <summary>The server holds a wait for 25 s and the relay gives up at 45 s.</summary>
    public static readonly TimeSpan WaitTimeout = TimeSpan.FromSeconds(60);
    /// <summary>The app's exe through the relay (which itself gives up at 30 s).</summary>
    public static readonly TimeSpan DownloadTimeout = TimeSpan.FromSeconds(120);

    private readonly HttpClient _http;
    private readonly NotifierKey _key;
    private readonly CertificateObserver _observer;

    public ServerAddress Address { get; }

    /// <summary>The certificate the last new connection was shown (null over http).</summary>
    public CertificateDetails? LastCertificate => _observer.Last.Details;
    public CertificateVerdict LastCertificateVerdict => _observer.Last.Verdict;

    public ZigmonClient(ServerAddress address, NotifierKey key, HttpMessageHandler handler,
        bool disposeHandler = true, CertificateObserver? observer = null)
    {
        Address = address ?? throw new ArgumentNullException(nameof(address));
        _key = key ?? throw new ArgumentNullException(nameof(key));
        _observer = observer ?? new CertificateObserver();
        _http = new HttpClient(handler, disposeHandler)
        {
            // each request gets its own timeout below
            Timeout = Timeout.InfiniteTimeSpan,
            MaxResponseContentBufferSize = MaxResponseBytes,
        };
    }

    /// <summary>The real thing: system TLS validation, plus the pin when it belongs to this host.</summary>
    public static ZigmonClient Create(ServerAddress address, NotifierKey key, CertificatePin? pin)
    {
        var observer = new CertificateObserver();
        return new ZigmonClient(address, key, HttpFactory.CreateHandler(address, pin, observer), true, observer);
    }

    public async Task<HelloInfo> HelloAsync(CancellationToken cancellationToken)
    {
        using var doc = await GetAsync(Address.Endpoint("hello"), RequestTimeout, cancellationToken).ConfigureAwait(false);
        return ProtocolParser.Hello(doc.RootElement);
    }

    public async Task<SensorsSnapshot> SensorsAsync(CancellationToken cancellationToken)
    {
        using var doc = await GetAsync(Address.Endpoint("sensors"), RequestTimeout, cancellationToken).ConfigureAwait(false);
        return ProtocolParser.Sensors(doc.RootElement);
    }

    public async Task<WaitResult> WaitAsync(long after, string boot, CancellationToken cancellationToken)
    {
        string b = SafeText.Identifier(boot, 64);
        string q = "after=" + FormatInvariant.I(Math.Max(0, after)) + "&boot=" + Uri.EscapeDataString(b);
        using var doc = await GetAsync(Address.Endpoint("wait", q), WaitTimeout, cancellationToken).ConfigureAwait(false);
        return ProtocolParser.Wait(doc.RootElement);
    }

    /// <summary>/update: what the server offers (not verified here - see <see cref="UpdateVerifier"/>).</summary>
    public async Task<UpdateOffer> UpdateAsync(CancellationToken cancellationToken)
    {
        using var doc = await GetAsync(Address.Endpoint("update"), RequestTimeout, cancellationToken).ConfigureAwait(false);
        return ProtocolParser.Update(doc.RootElement);
    }

    /// <summary>
    /// /download: the exe, with the same header, certificate rules and no redirects
    /// as everything else; refused when it is bigger than <paramref name="expectedSize"/>
    /// (the signed size) or ends short of it.
    /// </summary>
    public async Task<byte[]> DownloadAsync(long expectedSize, CancellationToken cancellationToken)
    {
        if (expectedSize <= 0 || expectedSize > UpdateVerifier.MaxExeBytes)
            throw new ZigmonException(ZigmonErrorKind.TooLarge, "The update's size is not believable; not downloaded.");
        byte[] body = await FetchAsync(Address.Endpoint("download"), DownloadTimeout, "application/octet-stream",
            (int)expectedSize, cancellationToken).ConfigureAwait(false);
        if (body.LongLength != expectedSize)
            throw new ZigmonException(ZigmonErrorKind.Protocol, "The download ended short of the signed size.");
        return body;
    }

    // ---- SMS and contacts (5.59.4) ---------------------------------------------------------

    /// <summary>The longest message the app sends; ZIGMon's own limits apply on top.</summary>
    public const int MaxSmsText = SmsCounter.MaxText;

    /// <summary>GET /api/notifier/sms?limit=N: the latest SMS, in and out, newest first (needs sms.read).</summary>
    public async Task<IReadOnlyList<SmsMessage>> GetSmsAsync(int limit, CancellationToken cancellationToken)
    {
        int n = Math.Clamp(limit, 1, ProtocolParser.MaxSms);
        using var doc = await GetAsync(Address.Endpoint("sms", "limit=" + FormatInvariant.I(n)), RequestTimeout, cancellationToken).ConfigureAwait(false);
        return ProtocolParser.SmsList(doc.RootElement);
    }

    /// <summary>GET /api/notifier/contacts: ZIGMon's contacts, read-only (needs sms.contacts).</summary>
    public async Task<ContactBook> GetContactsAsync(CancellationToken cancellationToken)
    {
        using var doc = await GetAsync(Address.Endpoint("contacts"), RequestTimeout, cancellationToken).ConfigureAwait(false);
        return ProtocolParser.Contacts(doc.RootElement);
    }

    /// <summary>
    /// POST /api/notifier/sms/send {"to":[...],"text":"...","reply_to":"..."} (needs sms.send).
    /// ZIGMon's refusals (its SMS limits, the queue, a number it will not take) come back as a
    /// result that is not Ok, in ZIGMon's own words; only a broken connection or a wrong key throws.
    /// Neither the text nor the numbers are ever logged or put in an exception.
    /// </summary>
    public async Task<SmsSendResult> SendSmsAsync(IReadOnlyList<string> to, string text, string? replyTo, CancellationToken cancellationToken)
    {
        var wire = (to ?? Array.Empty<string>()).Where(Recipients.IsWire).Distinct(StringComparer.Ordinal).ToList();
        if (wire.Count == 0) return new SmsSendResult(false, 0, 0, "Add at least one recipient.");
        if (wire.Count > Recipients.MaxRecipients) return new SmsSendResult(false, 0, 0, "At most " + Recipients.MaxRecipients + " recipients at once.");
        string t = (text ?? "").Replace("\r\n", "\n", StringComparison.Ordinal).Trim();
        if (t.Length == 0) return new SmsSendResult(false, 0, 0, "Write something first.");
        if (t.Length > MaxSmsText) return new SmsSendResult(false, 0, 0, "The message is too long (at most " + MaxSmsText + " characters).");
        string reply = SafeText.Identifier(replyTo, 64);

        var ms = new MemoryStream();
        using (var w = new Utf8JsonWriter(ms))
        {
            w.WriteStartObject();
            w.WriteStartArray("to");
            foreach (var x in wire) w.WriteStringValue(x);
            w.WriteEndArray();
            w.WriteString("text", t);
            if (reply.Length > 0) w.WriteString("reply_to", reply);
            w.WriteEndObject();
        }
        byte[] body;
        try
        {
            body = await FetchAsync(Address.Endpoint("sms-send"), RequestTimeout, "application/json", MaxErrorBytes, cancellationToken,
                HttpMethod.Post, ms.ToArray(), refusalIsAnAnswer: true).ConfigureAwait(false);
        }
        catch (SmsRefused r)
        {
            return new SmsSendResult(false, 0, 0, r.Words);
        }
        if (body.Length == 0) return new SmsSendResult(false, 0, 0, "ZIGMon answered with nothing.");
        using var doc = ProtocolParser.ParseDocument(body);
        var result = ProtocolParser.SendResult(doc.RootElement);
        return result with { Message = _key.Scrub(result.Message) };
    }

    /// <summary>A send ZIGMon turned down, with its words (already scrubbed of the key).</summary>
    private sealed class SmsRefused : Exception
    {
        public string Words { get; }
        public SmsRefused(string words) : base("refused") => Words = words;
    }

    private async Task<JsonDocument> GetAsync(Uri uri, TimeSpan timeout, CancellationToken cancellationToken)
    {
        byte[] body = await FetchAsync(uri, timeout, "application/json", MaxResponseBytes, cancellationToken).ConfigureAwait(false);
        if (body.Length == 0)
            throw new ZigmonException(ZigmonErrorKind.Protocol, "ZIGMon answered with nothing.");
        var doc = ProtocolParser.ParseDocument(body);
        if (!ProtocolParser.IsOk(doc.RootElement))
        {
            string? words = ProtocolParser.ErrorText(doc.RootElement);
            doc.Dispose();
            throw new ZigmonException(ZigmonErrorKind.Protocol, words is null ? "ZIGMon said no, without saying why." : _key.Scrub(words), 200);
        }
        return doc;
    }

    /// <summary>One GET: the 2xx body (at most <paramref name="limit"/> bytes), or the error it was, in words.</summary>
    private async Task<byte[]> FetchAsync(Uri uri, TimeSpan timeout, string accept, int limit, CancellationToken cancellationToken,
        HttpMethod? method = null, byte[]? jsonBody = null, bool refusalIsAnAnswer = false)
    {
        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(timeout);
        using var request = new HttpRequestMessage(method ?? HttpMethod.Get, uri);
        if (jsonBody is not null)
        {
            request.Content = new ByteArrayContent(jsonBody);
            request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json") { CharSet = "utf-8" };
        }
        request.Headers.TryAddWithoutValidation(AppInfo.KeyHeader, _key.Reveal());
        request.Headers.TryAddWithoutValidation("User-Agent", AppInfo.UserAgent);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue(accept));
        request.Headers.CacheControl = new CacheControlHeaderValue { NoCache = true, NoStore = true };

        _observer.Record(null, CertificateVerdict.Missing);
        HttpResponseMessage response;
        try
        {
            response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeoutCts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (OperationCanceledException)
        {
            throw new ZigmonException(ZigmonErrorKind.Network, "ZIGMon did not answer in time.");
        }
        catch (HttpRequestException ex)
        {
            throw Translate(ex);
        }

        using (response)
        {
            int code = (int)response.StatusCode;
            bool success = code is >= 200 and < 300;
            byte[] body;
            try
            {
                body = await ReadBodyAsync(response, success ? limit : MaxErrorBytes, timeoutCts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (OperationCanceledException)
            {
                throw new ZigmonException(ZigmonErrorKind.Network, "ZIGMon did not finish its answer in time.");
            }
            catch (IOException ex)
            {
                throw new ZigmonException(ZigmonErrorKind.Network, _key.Scrub("The connection broke off: " + ex.Message));
            }
            catch (HttpRequestException ex)
            {
                throw Translate(ex);
            }

            if (code is >= 300 and < 400)
            {
                string where = response.Headers.Location is { } loc
                    ? (loc.IsAbsoluteUri ? SafeText.Clean(loc.GetLeftPart(UriPartial.Authority), 120) : "another page")
                    : "somewhere else";
                throw new ZigmonException(ZigmonErrorKind.Redirect,
                    "The server sends this address on to " + where + ". Enter the final dashboard address instead (redirects are not followed, to keep the key from going elsewhere).",
                    code);
            }

            if (success) return body;

            string? serverWords = null;
            if (body.Length > 0)
            {
                try
                {
                    using var doc = ProtocolParser.ParseDocument(body);
                    serverWords = ProtocolParser.ErrorText(doc.RootElement);
                    if (serverWords is not null) serverWords = _key.Scrub(serverWords);
                }
                catch (ZigmonException)
                {
                    // an error page that is not JSON: the status says enough
                }
            }
            // a send turned down (ZIGMon's SMS limits, a busy queue, no gateway): its words as they are
            if (refusalIsAnAnswer && code is not (401 or 404 or 405) && serverWords is not null)
                throw new SmsRefused(serverWords);
            throw StatusError(code, serverWords, response);
        }
    }

    private static ZigmonException StatusError(int code, string? words, HttpResponseMessage response)
    {
        switch (code)
        {
            case 401:
                return new ZigmonException(ZigmonErrorKind.Unauthorized,
                    "ZIGMon did not accept the key - it is wrong, or it was taken away. Make a new one in ZIGMon (Settings → Messages → Desktop app).", code);
            case 429:
                TimeSpan? after = null;
                var ra = response.Headers.RetryAfter;
                if (ra?.Delta is { } d) after = d;
                else if (ra?.Date is { } when) after = when - DateTimeOffset.UtcNow;
                if (after is { } a && (a < TimeSpan.Zero || a > TimeSpan.FromHours(1))) after = null;
                return new ZigmonException(ZigmonErrorKind.RateLimited,
                    "Too many tries from this address (ZIGMon counts wrong keys from your network) – waiting before trying again.", code, retryAfter: after);
            case 400:
                return new ZigmonException(ZigmonErrorKind.BadRequest, "ZIGMon did not understand: " + (words ?? "bad request") + ".", code);
            case 503:
                return new ZigmonException(ZigmonErrorKind.Unavailable,
                    "ZIGMon is not answering just now" + (words is null ? " (it may be restarting)." : ": " + words + "."), code);
            case 404:
                return new ZigmonException(ZigmonErrorKind.Http,
                    "Nothing found at this address (404). Is it your dashboard's address, and is ZIGMon new enough to have the desktop app?", code);
            default:
                return new ZigmonException(ZigmonErrorKind.Http,
                    "ZIGMon answered with HTTP " + FormatInvariant.I(code) + (words is null ? "." : ": " + words + "."), code);
        }
    }

    private ZigmonException Translate(HttpRequestException ex)
    {
        var (details, verdict) = _observer.Last;
        bool tls = false;
        for (Exception? e = ex; e is not null; e = e.InnerException)
            if (e is AuthenticationException) tls = true;

        if (tls && !CertificatePolicy.IsAccepted(verdict))
        {
            string words = verdict switch
            {
                CertificateVerdict.PinMismatch =>
                    "The server's certificate is not the one you trusted for it. If it was renewed, check the new fingerprint and trust it again in Connection.",
                CertificateVerdict.Untrusted =>
                    "Windows does not trust this server's certificate. " + (details?.ProblemText ?? ""),
                _ => "The server showed no usable certificate.",
            };
            return new ZigmonException(ZigmonErrorKind.Certificate, words.Trim(), certificate: details);
        }
        if (tls)
            return new ZigmonException(ZigmonErrorKind.Network, "The secure connection could not be made (TLS 1.2 or newer is needed).");

        string reason = ex.InnerException?.Message ?? ex.Message;
        return new ZigmonException(ZigmonErrorKind.Network,
            _key.Scrub("Could not reach " + Address.Host + ": " + SafeText.Clean(reason, 200)));
    }

    private static async Task<byte[]> ReadBodyAsync(HttpResponseMessage response, int limit, CancellationToken ct)
    {
        long? declared = response.Content.Headers.ContentLength;
        if (declared > limit)
            throw new ZigmonException(ZigmonErrorKind.TooLarge, "ZIGMon's answer was far bigger than it should be; not read.");
        await using var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var ms = new MemoryStream(declared is > 0 and <= 1 << 20 ? (int)declared.Value : 16 * 1024);
        byte[] buffer = new byte[16 * 1024];
        while (true)
        {
            int n = await stream.ReadAsync(buffer.AsMemory(), ct).ConfigureAwait(false);
            if (n == 0) break;
            if (ms.Length + n > limit)
                throw new ZigmonException(ZigmonErrorKind.TooLarge, "ZIGMon's answer was far bigger than it should be; not read.");
            ms.Write(buffer, 0, n);
        }
        return ms.ToArray();
    }

    public void Dispose() => _http.Dispose();

    public override string ToString() => "ZigmonClient(" + Address.Base + ", " + _key + ")";
}
