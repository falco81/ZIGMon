using System;
using System.Net;
using System.Net.Http;
using System.Net.Security;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;

namespace ZigmonNotifier.Core;

/// <summary>Builds the one kind of HTTP handler the app uses.</summary>
public static class HttpFactory
{
    /// <param name="address">The server; its host:port decides whether <paramref name="pin"/> applies.</param>
    /// <param name="pin">A pinned certificate; ignored when it belongs to another host:port.</param>
    /// <param name="observer">Gets every certificate the server presents (for the "trust this certificate" flow).</param>
    public static SocketsHttpHandler CreateHandler(ServerAddress address, CertificatePin? pin, CertificateObserver? observer)
    {
        string? pinHash = pin is not null && string.Equals(pin.Scope, address.PinScope, StringComparison.OrdinalIgnoreCase)
            ? pin.Sha256 : null;

        var handler = new SocketsHttpHandler
        {
            // a redirect would carry the key's header to wherever it points: never follow one
            AllowAutoRedirect = false,
            UseCookies = false,
            PreAuthenticate = false,
            Credentials = null,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate | DecompressionMethods.Brotli,
            ConnectTimeout = TimeSpan.FromSeconds(15),
            PooledConnectionIdleTimeout = TimeSpan.FromSeconds(90),
            PooledConnectionLifetime = TimeSpan.FromMinutes(10),
            MaxConnectionsPerServer = 4,
            MaxResponseHeadersLength = 64, // KiB
            MaxResponseDrainSize = 64 * 1024,
        };
        handler.SslOptions = new SslClientAuthenticationOptions
        {
            EnabledSslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
            RemoteCertificateValidationCallback = (sender, certificate, chain, errors) =>
                Validate(certificate, errors, pinHash, observer),
        };
        return handler;
    }

    /// <summary>The certificate callback, separate so tests can call it directly.</summary>
    internal static bool Validate(X509Certificate? certificate, SslPolicyErrors errors, string? pinHash, CertificateObserver? observer)
    {
        CertificateDetails? details = null;
        try
        {
            if (certificate is not null) details = CertificateDetails.From(certificate, errors);
        }
        catch (Exception)
        {
            details = null;
        }
        var verdict = CertificatePolicy.Evaluate(details?.Sha256, errors, pinHash);
        observer?.Record(details, verdict);
        return CertificatePolicy.IsAccepted(verdict);
    }
}
