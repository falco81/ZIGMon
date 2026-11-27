using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace ZigmonNotifier.Core;

/// <summary>One Ed25519 release public key (raw 32 bytes).</summary>
public sealed class ReleaseKey
{
    private readonly byte[] _key;

    public string Name { get; }
    public ReadOnlySpan<byte> PublicKey => _key;
    public string Hex => Convert.ToHexStringLower(_key);

    public ReleaseKey(string name, ReadOnlySpan<byte> publicKey)
    {
        if (publicKey.Length != Ed25519.PublicKeySize)
            throw new ArgumentException("An Ed25519 public key is 32 bytes.", nameof(publicKey));
        Name = name ?? "";
        _key = publicKey.ToArray();
    }

    public override string ToString() => Name + " " + Hex;
}

/// <summary>The keys ZIGMon's releases are signed with (embedded at build time), and the PEM reader for them.</summary>
public static partial class ReleaseKeys
{
    /// <summary>DER of SubjectPublicKeyInfo { id-Ed25519 }, before the 32 key bytes.</summary>
    private static readonly byte[] SpkiPrefix = Convert.FromHexString("302a300506032b6570032100");

    private static IReadOnlyList<ReleaseKey>? _embedded;

    /// <summary>The keys from deploy/release-keys, as embedded in this build.</summary>
    public static IReadOnlyList<ReleaseKey> Embedded =>
        _embedded ??= EmbeddedHex.Select(k => new ReleaseKey(k.Name, Convert.FromHexString(k.Hex))).ToArray();

    /// <summary>
    /// Reads a PEM "PUBLIC KEY" (SubjectPublicKeyInfo) holding an Ed25519 key:
    /// the raw key is the last 32 bytes of the DER. Anything else is refused.
    /// </summary>
    public static bool TryFromPem(string? pem, out byte[] publicKey)
    {
        publicKey = Array.Empty<byte>();
        if (string.IsNullOrEmpty(pem) || pem.Length > 4096) return false;
        const string begin = "-----BEGIN PUBLIC KEY-----", end = "-----END PUBLIC KEY-----";
        int b = pem.IndexOf(begin, StringComparison.Ordinal);
        int e = pem.IndexOf(end, StringComparison.Ordinal);
        if (b < 0 || e < b) return false;
        string body = pem.Substring(b + begin.Length, e - b - begin.Length);
        byte[] der;
        try
        {
            der = Convert.FromBase64String(string.Concat(body.Where(c => !char.IsWhiteSpace(c))));
        }
        catch (FormatException)
        {
            return false;
        }
        if (der.Length != SpkiPrefix.Length + Ed25519.PublicKeySize || !der.AsSpan(0, SpkiPrefix.Length).SequenceEqual(SpkiPrefix))
            return false;
        publicKey = der[SpkiPrefix.Length..];
        return true;
    }

    /// <summary>Every *.pub in a folder (sorted by name); a file that is not an Ed25519 key is an error.</summary>
    public static IReadOnlyList<ReleaseKey> LoadFolder(string folder)
    {
        var list = new List<ReleaseKey>();
        foreach (var path in Directory.GetFiles(folder, "*.pub").OrderBy(p => p, StringComparer.Ordinal))
        {
            if (!TryFromPem(File.ReadAllText(path), out var key))
                throw new InvalidDataException(Path.GetFileName(path) + " is not an Ed25519 public key (PEM).");
            list.Add(new ReleaseKey(Path.GetFileNameWithoutExtension(path), key));
        }
        return list;
    }
}
