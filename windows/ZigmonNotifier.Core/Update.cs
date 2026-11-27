using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace ZigmonNotifier.Core;

/// <summary>Version numbers of the app: 1 to 4 plain numbers with dots, compared as System.Version.</summary>
public static class AppVersions
{
    /// <summary>The version this build is.</summary>
    public static Version Running { get; } = Parse(AppInfo.Version);

    /// <summary>"1.1" and "1.1.0" are the same version: missing parts count as 0.</summary>
    public static bool TryParse(string? text, out Version version)
    {
        version = new Version(0, 0, 0, 0);
        if (string.IsNullOrEmpty(text) || text.Length > 24) return false;
        string[] parts = text.Split('.');
        if (parts.Length is < 1 or > 4) return false;
        var n = new int[4];
        for (int i = 0; i < parts.Length; i++)
        {
            string p = parts[i];
            if (p.Length is 0 or > 9 || !p.All(c => c is >= '0' and <= '9')) return false;
            n[i] = int.Parse(p, NumberStyles.None, CultureInfo.InvariantCulture);
        }
        version = new Version(n[0], n[1], n[2], n[3]);
        return true;
    }

    public static Version Parse(string text) =>
        TryParse(text, out var v) ? v : throw new FormatException("not a version: " + text);

    /// <summary>1.1.0, or 1.1.0.5 when the fourth part is not 0.</summary>
    public static string Format(Version v) =>
        v.Revision > 0
            ? string.Create(CultureInfo.InvariantCulture, $"{v.Major}.{v.Minor}.{Math.Max(0, v.Build)}.{v.Revision}")
            : string.Create(CultureInfo.InvariantCulture, $"{v.Major}.{v.Minor}.{Math.Max(0, v.Build)}");

    /// <summary>True only when <paramref name="candidate"/> is a version and strictly newer.</summary>
    public static bool IsNewer(string? candidate, Version than) => TryParse(candidate, out var v) && v > than;
}

/// <summary>What /update said. Nothing in it is trusted before <see cref="UpdateVerifier.Verify"/>.</summary>
public sealed record UpdateOffer(bool Available, string Version, long Size, string Sha256, byte[] Manifest, byte[] Signature)
{
    public static readonly UpdateOffer None = new(false, "", 0, "", Array.Empty<byte>(), Array.Empty<byte>());
}

/// <summary>notifier.json, the signed manifest of one release of the app.</summary>
public sealed record UpdateManifest(string Product, string File, string Version, long Size, string Sha256, string Runtime);

/// <summary>An offer whose manifest is signed by a release key and agrees with what was advertised.</summary>
public sealed record VerifiedUpdate(UpdateManifest Manifest, Version Version, string KeyName)
{
    public string VersionText => AppVersions.Format(Version);
}

/// <summary>An update that is not installed, with words fit to show (never anything secret).</summary>
public sealed class UpdateException : Exception
{
    public UpdateException(string message) : base(message) { }
    public override string ToString() => nameof(UpdateException) + ": " + Message;
}

/// <summary>Where updates come from: the ZIGMon the app is connected to (<see cref="ZigmonClient"/>).</summary>
public interface IUpdateSource
{
    Task<UpdateOffer> UpdateAsync(CancellationToken cancellationToken);
    /// <summary>The exe, at most <paramref name="expectedSize"/> bytes (more is an error).</summary>
    Task<byte[]> DownloadAsync(long expectedSize, CancellationToken cancellationToken);
}

/// <summary>Checks an offer: the signature first, then every field of the signed manifest.</summary>
public static class UpdateVerifier
{
    public const string Product = "ZIGMon Notifier";
    public const string FileName = "ZigmonNotifier.exe";
    public const long MaxExeBytes = 50L * 1024 * 1024;
    public const int MaxManifestBytes = 4096;

    private static readonly Regex Sha256Hex = new("^[0-9a-f]{64}$", RegexOptions.CultureInvariant);

    /// <param name="mustBeNewerThan">The running version; null only for tools that check an offer without installing it.</param>
    public static VerifiedUpdate Verify(UpdateOffer offer, IReadOnlyList<ReleaseKey> keys, Version? mustBeNewerThan)
    {
        ArgumentNullException.ThrowIfNull(offer);
        ArgumentNullException.ThrowIfNull(keys);
        if (!offer.Available) throw new UpdateException("no update is offered");
        if (offer.Manifest.Length is 0 or > MaxManifestBytes) throw new UpdateException("the update's manifest is missing or too big");
        if (offer.Signature.Length != Ed25519.SignatureSize) throw new UpdateException("the update's signature is malformed");
        if (keys.Count == 0) throw new UpdateException("this build has no release key to check updates with");

        // 1. the signature, over the manifest's exact bytes, by any one release key
        ReleaseKey? by = keys.FirstOrDefault(k => Ed25519.Verify(offer.Signature, offer.Manifest, k.PublicKey));
        if (by is null) throw new UpdateException("the update is not signed by ZIGMon's release key");

        // 2. what the signed manifest says, and that the offer around it agrees
        var m = ParseManifest(offer.Manifest);
        if (m.Product != Product) throw new UpdateException("the update is for another product");
        if (m.File != FileName) throw new UpdateException("the update is not " + FileName);
        if (!AppVersions.TryParse(m.Version, out var version)) throw new UpdateException("the update's version is not a version");
        if (!AppVersions.TryParse(offer.Version, out var advertised) || advertised != version)
            throw new UpdateException("the update's signed version is not the one advertised");
        if (mustBeNewerThan is not null && version <= mustBeNewerThan)
            throw new UpdateException("the update (" + AppVersions.Format(version) + ") is not newer than this app");
        if (m.Size <= 0 || m.Size > MaxExeBytes) throw new UpdateException("the update's size is not believable");
        if (m.Size != offer.Size) throw new UpdateException("the update's signed size is not the one advertised");
        if (!Sha256Hex.IsMatch(m.Sha256)) throw new UpdateException("the update's checksum is malformed");
        if (!string.Equals(m.Sha256, offer.Sha256, StringComparison.Ordinal))
            throw new UpdateException("the update's signed checksum is not the one advertised");
        return new VerifiedUpdate(m, version, by.Name);
    }

    /// <summary>notifier.json, strictly: an object with string product/file/version/sha256, an integer size; no key twice.</summary>
    public static UpdateManifest ParseManifest(byte[] bytes)
    {
        try
        {
            using var doc = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 4, AllowTrailingCommas = false });
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object) throw new UpdateException("the update's manifest is not an object");
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var p in root.EnumerateObject())
                if (!seen.Add(p.Name)) throw new UpdateException("the update's manifest names " + SafeText.Clean(p.Name, 20) + " twice");
            string S(string name, bool required = true)
            {
                if (root.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String) return v.GetString() ?? "";
                if (required) throw new UpdateException("the update's manifest has no " + name);
                return "";
            }
            if (!root.TryGetProperty("size", out var sz) || sz.ValueKind != JsonValueKind.Number || !sz.TryGetInt64(out long size))
                throw new UpdateException("the update's manifest has no size");
            return new UpdateManifest(S("product"), S("file"), S("version"), size, S("sha256"), S("runtime", required: false));
        }
        catch (JsonException)
        {
            throw new UpdateException("the update's manifest is not valid JSON");
        }
    }
}
