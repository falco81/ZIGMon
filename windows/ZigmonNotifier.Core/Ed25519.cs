using System;
using System.Numerics;
using System.Security.Cryptography;

namespace ZigmonNotifier.Core;

/// <summary>
/// Ed25519 signature verification (RFC 8032, section 5.1.7), in plain managed
/// code: .NET has no Ed25519 of its own on Windows. Only verification - the app
/// never signs. Not constant-time, which does not matter: everything it handles
/// (public key, message, signature) is public.
/// </summary>
public static class Ed25519
{
    public const int PublicKeySize = 32;
    public const int SignatureSize = 64;

    private static readonly BigInteger P = BigInteger.Pow(2, 255) - 19;
    /// <summary>The order of the base point.</summary>
    internal static readonly BigInteger L = BigInteger.Pow(2, 252) + BigInteger.Parse("27742317777372353535851937790883648493");
    private static readonly BigInteger D = Mod(-121665 * Inv(121666));
    private static readonly BigInteger D2 = Mod(2 * D);
    /// <summary>sqrt(-1) mod p = 2^((p-1)/4).</summary>
    private static readonly BigInteger SqrtM1 = BigInteger.ModPow(2, (P - 1) / 4, P);

    /// <summary>A point in extended homogeneous coordinates: x = X/Z, y = Y/Z, x*y = T/Z.</summary>
    private readonly record struct Point(BigInteger X, BigInteger Y, BigInteger Z, BigInteger T);

    private static readonly Point Identity = new(0, 1, 1, 0);
    private static readonly Point B = BasePoint();

    /// <summary>
    /// True only when <paramref name="signature"/> is a valid Ed25519 signature of
    /// <paramref name="message"/> by <paramref name="publicKey"/>. Wrong lengths,
    /// keys or R that are not points on the curve, and S ≥ L are all just false.
    /// </summary>
    public static bool Verify(ReadOnlySpan<byte> signature, ReadOnlySpan<byte> message, ReadOnlySpan<byte> publicKey)
    {
        if (signature.Length != SignatureSize || publicKey.Length != PublicKeySize) return false;

        // 1. decode R, S and A; any failure is a rejection
        if (!TryDecode(signature[..32], out var r)) return false;
        var s = new BigInteger(signature[32..], isUnsigned: true, isBigEndian: false);
        if (s >= L) return false;
        if (!TryDecode(publicKey, out var a)) return false;

        // 2. k = SHA-512(R || A || M), as a little-endian integer mod L
        byte[] input = new byte[64 + message.Length];
        signature[..32].CopyTo(input);
        publicKey.CopyTo(input.AsSpan(32));
        message.CopyTo(input.AsSpan(64));
        var k = new BigInteger(SHA512.HashData(input), isUnsigned: true, isBigEndian: false) % L;

        // 3. [S]B = R + [k]A (the cofactorless check RFC 8032 allows)
        var left = Multiply(B, s);
        var right = Add(r, Multiply(a, k));
        return SameAs(left, right);
    }

    /// <summary>The encoding of [s]B. For the tests' own signer, which checks this code against RFC 8032's vectors.</summary>
    internal static byte[] EncodeBaseMultiple(BigInteger s) => Encode(Multiply(B, s));

    // ---- field --------------------------------------------------------------------------

    private static BigInteger Mod(BigInteger v)
    {
        var m = v % P;
        return m.Sign < 0 ? m + P : m;
    }

    private static BigInteger Inv(BigInteger v) => BigInteger.ModPow(Mod(v), P - 2, P);

    // ---- points -------------------------------------------------------------------------

    /// <summary>RFC 8032 5.1.4 (complete for Ed25519, so it also doubles).</summary>
    private static Point Add(Point p, Point q)
    {
        var a = Mod((p.Y - p.X) * (q.Y - q.X));
        var b = Mod((p.Y + p.X) * (q.Y + q.X));
        var c = Mod(p.T * D2 * q.T);
        var d = Mod(p.Z * 2 * q.Z);
        var e = b - a;
        var f = d - c;
        var g = d + c;
        var h = b + a;
        return new Point(Mod(e * f), Mod(g * h), Mod(f * g), Mod(e * h));
    }

    private static Point Multiply(Point p, BigInteger scalar)
    {
        var q = Identity;
        var addend = p;
        while (scalar.Sign > 0)
        {
            if (!scalar.IsEven) q = Add(q, addend);
            addend = Add(addend, addend);
            scalar >>= 1;
        }
        return q;
    }

    /// <summary>RFC 8032 5.1.2: y little-endian, the top bit the parity of x.</summary>
    private static byte[] Encode(Point p)
    {
        var zi = Inv(p.Z);
        var x = Mod(p.X * zi);
        var y = Mod(p.Y * zi);
        byte[] enc = new byte[32];
        y.TryWriteBytes(enc, out _, isUnsigned: true, isBigEndian: false);
        if (!x.IsEven) enc[31] |= 0x80;
        return enc;
    }

    /// <summary>Projective equality: x1/z1 == x2/z2 and y1/z1 == y2/z2.</summary>
    private static bool SameAs(Point p, Point q) =>
        Mod(p.X * q.Z - q.X * p.Z).IsZero && Mod(p.Y * q.Z - q.Y * p.Z).IsZero;

    /// <summary>RFC 8032 5.1.3, with all of its checks.</summary>
    private static bool TryDecode(ReadOnlySpan<byte> encoded, out Point point)
    {
        point = default;
        if (encoded.Length != 32) return false;
        Span<byte> buf = stackalloc byte[32];
        encoded.CopyTo(buf);
        int x0 = buf[31] >> 7;
        buf[31] &= 0x7F;
        var y = new BigInteger(buf, isUnsigned: true, isBigEndian: false);
        if (y >= P) return false;

        var y2 = y * y % P;
        var u = Mod(y2 - 1);
        var v = Mod(D * y2 + 1);
        // x = u v^3 (u v^7)^((p-5)/8)
        var v3 = v * v % P * v % P;
        var v7 = v3 * v3 % P * v % P;
        var x = u * v3 % P * BigInteger.ModPow(u * v7 % P, (P - 5) / 8, P) % P;
        var vx2 = v * x % P * x % P;
        if (vx2 == u)
        {
            // x is a square root
        }
        else if (vx2 == Mod(-u))
        {
            x = x * SqrtM1 % P;
        }
        else
        {
            return false;
        }
        if (x.IsZero && x0 == 1) return false;
        if ((int)(x % 2) != x0) x = P - x;
        point = new Point(x, y, 1, x * y % P);
        return true;
    }

    private static Point BasePoint()
    {
        var y = Mod(4 * Inv(5));
        Span<byte> enc = stackalloc byte[32];
        y.TryWriteBytes(enc, out _, isUnsigned: true, isBigEndian: false); // x of B is even: top bit 0
        if (!TryDecode(enc, out var b)) throw new InvalidOperationException("Ed25519 base point");
        return b;
    }
}
