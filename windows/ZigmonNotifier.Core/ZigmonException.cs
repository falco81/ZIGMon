using System;

namespace ZigmonNotifier.Core;

public enum ZigmonErrorKind
{
    /// <summary>Could not reach the server (DNS, refused, timed out, TLS broke off).</summary>
    Network,
    /// <summary>The server's certificate was not accepted (not trusted by Windows, or not the pinned one).</summary>
    Certificate,
    /// <summary>401: the key is wrong or was taken away.</summary>
    Unauthorized,
    /// <summary>429: too many wrong tries from this address.</summary>
    RateLimited,
    /// <summary>400: the server did not like the request.</summary>
    BadRequest,
    /// <summary>503: the relay could not reach the daemon.</summary>
    Unavailable,
    /// <summary>A 3xx answer; redirects are never followed.</summary>
    Redirect,
    /// <summary>Any other HTTP status.</summary>
    Http,
    /// <summary>The answer is not what protocol v1 says.</summary>
    Protocol,
    /// <summary>The answer was bigger than any honest answer is.</summary>
    TooLarge,
}

/// <summary>
/// An error with words fit to show the user. The message never holds the key
/// (it is scrubbed from anything the server echoes) and never the request headers.
/// </summary>
public sealed class ZigmonException : Exception
{
    public ZigmonErrorKind Kind { get; }
    public int? Status { get; }
    /// <summary>The certificate that was presented, when <see cref="Kind"/> is Certificate.</summary>
    public CertificateDetails? Certificate { get; }
    /// <summary>For 429: how long the server asks us to stay away.</summary>
    public TimeSpan? RetryAfter { get; }

    public ZigmonException(ZigmonErrorKind kind, string message, int? status = null,
        CertificateDetails? certificate = null, TimeSpan? retryAfter = null)
        : base(message)
    {
        Kind = kind;
        Status = status;
        Certificate = certificate;
        RetryAfter = retryAfter;
    }

    /// <summary>Whether trying again later can help without the user doing anything.</summary>
    public bool IsTransient => Kind is ZigmonErrorKind.Network or ZigmonErrorKind.RateLimited
        or ZigmonErrorKind.Unavailable or ZigmonErrorKind.Http or ZigmonErrorKind.Protocol
        or ZigmonErrorKind.TooLarge or ZigmonErrorKind.BadRequest;

    // ToString would add a stack trace and inner exceptions; keep it to the words.
    public override string ToString() => nameof(ZigmonException) + " (" + Kind + "): " + Message;
}
