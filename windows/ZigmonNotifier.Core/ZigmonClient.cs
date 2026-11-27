using System;
using System.IO;
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
public sealed class ZigmonClient : INotifierApi, IDisposable
{
    /// <summary>No honest answer is bigger (2000 sensors are ~400 KB).</summary>
    public const int MaxResponseBytes = 2 * 1024 * 1024;
    private const int MaxErrorBytes = 64 * 1024;

    public static readonly TimeSpan RequestTimeout = TimeSpan.FromSeconds(20);
    /// <summary>The server holds a wait for 25 s and the relay gives up at 45 s.</summary>
    public static readonly TimeSpan WaitTimeout = TimeSpan.FromSeconds(60);

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

    private async Task<JsonDocument> GetAsync(Uri uri, TimeSpan timeout, CancellationToken cancellationToken)
    {
        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(timeout);
        using var request = new HttpRequestMessage(HttpMethod.Get, uri);
        request.Headers.TryAddWithoutValidation(AppInfo.KeyHeader, _key.Reveal());
        request.Headers.TryAddWithoutValidation("User-Agent", AppInfo.UserAgent);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
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
            byte[] body;
            try
            {
                body = await ReadBodyAsync(response, code is >= 200 and < 300 ? MaxResponseBytes : MaxErrorBytes, timeoutCts.Token).ConfigureAwait(false);
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

            string? serverWords = null;
            JsonDocument? doc = null;
            if (body.Length > 0)
            {
                try
                {
                    doc = ProtocolParser.ParseDocument(body);
                    serverWords = ProtocolParser.ErrorText(doc.RootElement);
                    if (serverWords is not null) serverWords = _key.Scrub(serverWords);
                }
                catch (ZigmonException) when (code is < 200 or >= 300)
                {
                    doc = null; // an error page that is not JSON: the status says enough
                }
            }

            if (code is >= 200 and < 300)
            {
                if (doc is null)
                    throw new ZigmonException(ZigmonErrorKind.Protocol, "ZIGMon answered with nothing.");
                if (!ProtocolParser.IsOk(doc.RootElement))
                {
                    doc.Dispose();
                    throw new ZigmonException(ZigmonErrorKind.Protocol, serverWords ?? "ZIGMon said no, without saying why.", code);
                }
                return doc;
            }

            doc?.Dispose();
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
