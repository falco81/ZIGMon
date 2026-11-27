using System;
using System.Globalization;
using System.Net.Security;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace ZigmonNotifier.Core;

/// <summary>What the user is shown about a server certificate.</summary>
public sealed record CertificateDetails(
    string Sha256, string Subject, string Issuer, DateTimeOffset NotBefore, DateTimeOffset NotAfter,
    SslPolicyErrors Errors)
{
    /// <summary>"AB:CD:..." - 32 pairs.</summary>
    public string Fingerprint => CertificatePolicy.FormatFingerprint(Sha256);

    public bool TrustedByWindows => Errors == SslPolicyErrors.None;

    public string ProblemText
    {
        get
        {
            if (Errors == SslPolicyErrors.None) return "Trusted by Windows.";
            var sb = new StringBuilder();
            if (Errors.HasFlag(SslPolicyErrors.RemoteCertificateChainErrors))
                sb.Append("Windows does not trust whoever issued it (self-made certificate?). ");
            if (Errors.HasFlag(SslPolicyErrors.RemoteCertificateNameMismatch))
                sb.Append("It was made for another name than this address. ");
            if (Errors.HasFlag(SslPolicyErrors.RemoteCertificateNotAvailable))
                sb.Append("The server showed no certificate. ");
            return sb.ToString().Trim();
        }
    }

    public static CertificateDetails From(X509Certificate certificate, SslPolicyErrors errors)
    {
        if (certificate is X509Certificate2 own) return From(own, errors);
        using var c2 = new X509Certificate2(certificate);
        return From(c2, errors);
    }

    public static CertificateDetails From(X509Certificate2 certificate, SslPolicyErrors errors) => new(
        CertificatePolicy.Sha256Of(certificate),
        SafeText.Clean(certificate.Subject, 300),
        SafeText.Clean(certificate.Issuer, 300),
        new DateTimeOffset(certificate.NotBefore.ToUniversalTime(), TimeSpan.Zero),
        new DateTimeOffset(certificate.NotAfter.ToUniversalTime(), TimeSpan.Zero),
        errors);
}

/// <summary>A certificate the user chose to trust for one host:port.</summary>
public sealed record CertificatePin(string Scope, string Sha256, string Subject, DateTimeOffset PinnedAt);

public enum CertificateVerdict
{
    /// <summary>Windows trusts the chain and there is no pin.</summary>
    Trusted,
    /// <summary>It is the pinned certificate.</summary>
    Pinned,
    /// <summary>Not trusted by Windows, and not pinned.</summary>
    Untrusted,
    /// <summary>A pin is set for this host and this is not that certificate.</summary>
    PinMismatch,
    /// <summary>No certificate at all.</summary>
    Missing,
}

public static class CertificatePolicy
{
    public static string Sha256Of(X509Certificate2 certificate) =>
        Convert.ToHexString(certificate.GetCertHash(HashAlgorithmName.SHA256));

    /// <summary>64 upper-case hex digits, or null when it is not a SHA-256 fingerprint.</summary>
    public static string? NormalizePin(string? pin)
    {
        if (string.IsNullOrWhiteSpace(pin)) return null;
        var sb = new StringBuilder(64);
        foreach (char c in pin)
        {
            if (c is ':' or ' ' or '-') continue;
            if (!Uri.IsHexDigit(c)) return null;
            sb.Append(char.ToUpperInvariant(c));
        }
        return sb.Length == 64 ? sb.ToString() : null;
    }

    public static string FormatFingerprint(string sha256Hex)
    {
        string? h = NormalizePin(sha256Hex);
        if (h is null) return sha256Hex;
        var sb = new StringBuilder(95);
        for (int i = 0; i < h.Length; i += 2)
        {
            if (i > 0) sb.Append(':');
            sb.Append(h, i, 2);
        }
        return sb.ToString();
    }

    public static bool Matches(string? certificateSha256, string? pinSha256)
    {
        string? a = NormalizePin(certificateSha256), b = NormalizePin(pinSha256);
        if (a is null || b is null) return false;
        return CryptographicOperations.FixedTimeEquals(Convert.FromHexString(a), Convert.FromHexString(b));
    }

    /// <summary>
    /// The one rule: with no pin, only what Windows trusts. With a pin, only the
    /// pinned certificate - whether Windows trusts the chain or not.
    /// </summary>
    public static CertificateVerdict Evaluate(string? certificateSha256, SslPolicyErrors errors, string? pinSha256)
    {
        if (certificateSha256 is null || errors.HasFlag(SslPolicyErrors.RemoteCertificateNotAvailable))
            return CertificateVerdict.Missing;
        if (NormalizePin(pinSha256) is not null)
            return Matches(certificateSha256, pinSha256) ? CertificateVerdict.Pinned : CertificateVerdict.PinMismatch;
        return errors == SslPolicyErrors.None ? CertificateVerdict.Trusted : CertificateVerdict.Untrusted;
    }

    public static bool IsAccepted(CertificateVerdict v) => v is CertificateVerdict.Trusted or CertificateVerdict.Pinned;
}

/// <summary>Remembers the last certificate a connection was shown, so the UI can offer to pin it.</summary>
public sealed class CertificateObserver
{
    private readonly object _gate = new();
    private CertificateDetails? _last;
    private CertificateVerdict _verdict = CertificateVerdict.Missing;

    public void Record(CertificateDetails? details, CertificateVerdict verdict)
    {
        lock (_gate) { _last = details; _verdict = verdict; }
    }

    public (CertificateDetails? Details, CertificateVerdict Verdict) Last
    {
        get { lock (_gate) return (_last, _verdict); }
    }
}

internal static class FormatInvariant
{
    public static string I(long v) => v.ToString(CultureInfo.InvariantCulture);
}
