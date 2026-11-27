using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Numerics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using ZigmonNotifier.Core;

namespace ZigmonNotifier.Tests;

/// <summary>
/// An Ed25519 signer for the tests only (the app never signs), built on the
/// core's own point arithmetic. It is checked against RFC 8032's vectors, so
/// signatures made with it are honest ones.
/// </summary>
internal static class TestSigner
{
    private static BigInteger Le(ReadOnlySpan<byte> b) => new(b, isUnsigned: true, isBigEndian: false);

    private static BigInteger SecretScalar(byte[] h)
    {
        byte[] a = h[..32];
        a[0] &= 248;
        a[31] &= 127;
        a[31] |= 64;
        return Le(a);
    }

    public static byte[] PublicKey(byte[] seed) => Ed25519.EncodeBaseMultiple(SecretScalar(SHA512.HashData(seed)));

    public static byte[] Sign(byte[] seed, byte[] message)
    {
        byte[] h = SHA512.HashData(seed);
        var a = SecretScalar(h);
        byte[] pub = Ed25519.EncodeBaseMultiple(a);
        var r = Le(SHA512.HashData(h[32..].Concat(message).ToArray())) % Ed25519.L;
        byte[] rEnc = Ed25519.EncodeBaseMultiple(r);
        var k = Le(SHA512.HashData(rEnc.Concat(pub).Concat(message).ToArray())) % Ed25519.L;
        var s = (r + k * a) % Ed25519.L;
        byte[] sig = new byte[64];
        rEnc.CopyTo(sig, 0);
        s.TryWriteBytes(sig.AsSpan(32), out _, isUnsigned: true, isBigEndian: false);
        return sig;
    }

    public static byte[] NewSeed() => RandomNumberGenerator.GetBytes(32);
}

/// <summary>openssl on the PATH, for signatures made by something other than this code.</summary>
internal static class OpenSsl
{
    public static bool Run(string workDir, out string output, params string[] args)
    {
        output = "";
        var psi = new ProcessStartInfo("openssl") { WorkingDirectory = workDir, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        foreach (var a in args) psi.ArgumentList.Add(a);
        try
        {
            using var p = Process.Start(psi)!;
            output = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
            p.WaitForExit(30000);
            return p.ExitCode == 0;
        }
        catch (Win32Exception)
        {
            return false; // not installed
        }
    }

    public static bool Available => Run(Path.GetTempPath(), out _, "version");
}

internal sealed class TempDir : IDisposable
{
    public string Path { get; } = System.IO.Path.Combine(System.IO.Path.GetTempPath(), "zn-test-" + Guid.NewGuid().ToString("N"));
    public TempDir() => Directory.CreateDirectory(Path);
    public string this[string name] => System.IO.Path.Combine(Path, name);
    public void Dispose() { try { Directory.Delete(Path, true); } catch (IOException) { } }
}

public class Ed25519Tests
{
    // RFC 8032 section 7.1, TEST 1 .. TEST 3: (secret seed, public key, message, signature)
    public static readonly TheoryData<string, string, string, string> Rfc8032 = new()
    {
        {
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
            "",
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        },
        {
            "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
            "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
            "72",
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        },
        {
            "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
            "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
            "af82",
            "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
        },
    };

    private static byte[] H(string hex) => Convert.FromHexString(hex);

    [Theory]
    [MemberData(nameof(Rfc8032))]
    public void RfcVectorsVerify(string seed, string pub, string msg, string sig)
    {
        _ = seed;
        Assert.True(Ed25519.Verify(H(sig), H(msg), H(pub)));
    }

    [Theory]
    [MemberData(nameof(Rfc8032))]
    public void TheTestSignerIsHonest(string seed, string pub, string msg, string sig)
    {
        Assert.Equal(pub, Convert.ToHexStringLower(TestSigner.PublicKey(H(seed))));
        Assert.Equal(sig, Convert.ToHexStringLower(TestSigner.Sign(H(seed), H(msg))));
    }

    [Theory]
    [MemberData(nameof(Rfc8032))]
    public void AnyFlippedBitIsRefused(string seed, string pub, string msg, string sig)
    {
        _ = seed;
        byte[] s = H(sig), m = H(msg), k = H(pub);
        for (int bit = 0; bit < 512; bit += 7)
        {
            byte[] bad = (byte[])s.Clone();
            bad[bit / 8] ^= (byte)(1 << (bit % 8));
            Assert.False(Ed25519.Verify(bad, m, k), "signature bit " + bit);
        }
        for (int bit = 0; bit < 256; bit += 5)
        {
            byte[] bad = (byte[])k.Clone();
            bad[bit / 8] ^= (byte)(1 << (bit % 8));
            Assert.False(Ed25519.Verify(s, m, bad), "key bit " + bit);
        }
        if (m.Length > 0)
        {
            for (int bit = 0; bit < m.Length * 8; bit++)
            {
                byte[] bad = (byte[])m.Clone();
                bad[bit / 8] ^= (byte)(1 << (bit % 8));
                Assert.False(Ed25519.Verify(s, bad, k), "message bit " + bit);
            }
        }
        Assert.False(Ed25519.Verify(s, m.Concat(new byte[] { 0 }).ToArray(), k), "a byte more");
    }

    [Fact]
    public void SAtOrAboveTheOrderIsRefused()
    {
        // S + L is the same signature mathematically - RFC 8032 says refuse it (malleability)
        byte[] seed = H("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb");
        byte[] msg = H("72"), pub = TestSigner.PublicKey(seed), sig = TestSigner.Sign(seed, msg);
        Assert.True(Ed25519.Verify(sig, msg, pub));
        var s = new BigInteger(sig.AsSpan(32), isUnsigned: true, isBigEndian: false);
        byte[] bad = (byte[])sig.Clone();
        Array.Clear(bad, 32, 32);
        (s + Ed25519.L).TryWriteBytes(bad.AsSpan(32), out _, isUnsigned: true, isBigEndian: false);
        Assert.False(Ed25519.Verify(bad, msg, pub));

        byte[] l = (byte[])sig.Clone();
        Array.Clear(l, 32, 32);
        Ed25519.L.TryWriteBytes(l.AsSpan(32), out _, isUnsigned: true, isBigEndian: false);
        Assert.False(Ed25519.Verify(l, msg, pub));
        byte[] ff = (byte[])sig.Clone();
        for (int i = 32; i < 64; i++) ff[i] = 0xFF;
        Assert.False(Ed25519.Verify(ff, msg, pub));
    }

    [Fact]
    public void WrongLengthsAndNonPointsAreRefused()
    {
        byte[] seed = TestSigner.NewSeed(), msg = Encoding.UTF8.GetBytes("hello");
        byte[] pub = TestSigner.PublicKey(seed), sig = TestSigner.Sign(seed, msg);
        Assert.True(Ed25519.Verify(sig, msg, pub));
        Assert.False(Ed25519.Verify(sig[..63], msg, pub));
        Assert.False(Ed25519.Verify(sig.Concat(new byte[1]).ToArray(), msg, pub));
        Assert.False(Ed25519.Verify(Array.Empty<byte>(), msg, pub));
        Assert.False(Ed25519.Verify(sig, msg, pub[..31]));
        Assert.False(Ed25519.Verify(sig, msg, pub.Concat(new byte[1]).ToArray()));
        Assert.False(Ed25519.Verify(sig, msg, new byte[32]));            // a small-order point: it decodes, nothing verifies
        byte[] nonCanonical = Enumerable.Repeat((byte)0xFF, 32).ToArray();
        nonCanonical[31] = 0x7F;                                          // y = 2^255 - 1 ≥ p
        Assert.False(Ed25519.Verify(sig, msg, nonCanonical));
        byte[] badR = (byte[])sig.Clone();
        for (int i = 0; i < 31; i++) badR[i] = 0xFF;
        badR[31] = 0x7F;
        Assert.False(Ed25519.Verify(badR, msg, pub));
    }

    [Fact]
    public void SignaturesMadeByOpenSslVerify()
    {
        if (!OpenSsl.Available) return; // nothing to compare with here
        using var dir = new TempDir();
        var rnd = new Random(557);
        for (int round = 0; round < 3; round++)
        {
            string key = dir["k" + round + ".pem"], pubPem = dir["k" + round + ".pub"];
            Assert.True(OpenSsl.Run(dir.Path, out var o1, "genpkey", "-algorithm", "ed25519", "-out", key), o1);
            Assert.True(OpenSsl.Run(dir.Path, out var o2, "pkey", "-in", key, "-pubout", "-out", pubPem), o2);
            Assert.True(ReleaseKeys.TryFromPem(File.ReadAllText(pubPem), out var pub));
            foreach (int len in new[] { 1, 64, 1023, 5000 })
            {
                byte[] msg = new byte[len];
                rnd.NextBytes(msg);
                string mPath = dir["m.bin"], sPath = dir["s.bin"];
                File.WriteAllBytes(mPath, msg);
                File.Delete(sPath);
                Assert.True(OpenSsl.Run(dir.Path, out var o3, "pkeyutl", "-sign", "-inkey", key, "-rawin", "-in", mPath, "-out", sPath), o3);
                byte[] sig = File.ReadAllBytes(sPath);
                Assert.Equal(64, sig.Length);
                Assert.True(Ed25519.Verify(sig, msg, pub), "openssl signature, " + len + " bytes");
                msg[len / 2] ^= 0x10;
                Assert.False(Ed25519.Verify(sig, msg, pub));
                msg[len / 2] ^= 0x10;
                sig[5] ^= 1;
                Assert.False(Ed25519.Verify(sig, msg, pub));
            }
        }
    }
}

public class ReleaseKeyTests
{
    internal static string RepoRoot()
    {
        for (var d = new DirectoryInfo(AppContext.BaseDirectory); d is not null; d = d.Parent)
            if (Directory.Exists(Path.Combine(d.FullName, "deploy", "release-keys")) && Directory.Exists(Path.Combine(d.FullName, "windows")))
                return d.FullName;
        throw new DirectoryNotFoundException("deploy/release-keys not found above " + AppContext.BaseDirectory);
    }

    [Fact]
    public void EmbeddedKeysAreTheReleaseKeysFolder()
    {
        var folder = ReleaseKeys.LoadFolder(Path.Combine(RepoRoot(), "deploy", "release-keys"));
        Assert.NotEmpty(folder);
        Assert.Equal(folder.Select(k => k.Name + "=" + k.Hex), ReleaseKeys.Embedded.Select(k => k.Name + "=" + k.Hex));
    }

    [Fact]
    public void PemReaderTakesOnlyEd25519()
    {
        const string ok = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAErjsm6vu+D/XuWz77ZYD0QiIcAN/TNShUbcGrUJbhMc=\n-----END PUBLIC KEY-----\n";
        Assert.True(ReleaseKeys.TryFromPem(ok, out var k));
        Assert.Equal("12b8ec9babeef83fd7b96cfbed9603d1088870037f4cd4a151b706ad425b84c7", Convert.ToHexStringLower(k));
        Assert.False(ReleaseKeys.TryFromPem(ok.Replace("MCowBQYDK2VwAyEA", "MCowBQYDK2VxAyEA"), out _)); // Ed448's OID
        Assert.False(ReleaseKeys.TryFromPem("", out _));
        Assert.False(ReleaseKeys.TryFromPem("-----BEGIN PUBLIC KEY-----\n!!!\n-----END PUBLIC KEY-----", out _));
        using var rsa = RSA.Create(2048);
        Assert.False(ReleaseKeys.TryFromPem(rsa.ExportSubjectPublicKeyInfoPem(), out _));
    }
}

public class AppVersionTests
{
    [Fact]
    public void TheBuildsVersionIsAppInfos()
    {
        var info = typeof(AppInfo).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion;
        Assert.Equal(AppInfo.Version, info);
        Assert.Equal("ZigmonNotifier/" + AppInfo.Version + " (Windows)", AppInfo.UserAgent);
    }

    [Theory]
    [InlineData("1.1.0", "1.0.0", true)]
    [InlineData("1.1", "1.1.0", false)]
    [InlineData("1.1.0.1", "1.1.0", true)]
    [InlineData("1.10.0", "1.9.9", true)]
    [InlineData("1.0.9", "1.1.0", false)]
    [InlineData("2", "1.99.99", true)]
    [InlineData("1.1.0-beta", "1.0.0", false)]
    [InlineData(" 1.2.0", "1.0.0", false)]
    [InlineData("1..2", "1.0.0", false)]
    [InlineData("1.2.3.4.5", "1.0.0", false)]
    [InlineData("", "1.0.0", false)]
    [InlineData("99999999999.0", "1.0.0", false)]
    public void Newer(string candidate, string running, bool newer)
    {
        Assert.Equal(newer, AppVersions.IsNewer(candidate, AppVersions.Parse(running)));
    }

    [Fact]
    public void Formats()
    {
        Assert.Equal("1.1.0", AppVersions.Format(AppVersions.Parse("1.1")));
        Assert.Equal("1.1.0.3", AppVersions.Format(AppVersions.Parse("1.1.0.3")));
    }
}

/// <summary>A release made the way build.sh and make-release.sh make one, signed with a throwaway key.</summary>
internal sealed class FakeRelease
{
    public byte[] Seed { get; } = TestSigner.NewSeed();
    public ReleaseKey Key => new("throwaway", TestSigner.PublicKey(Seed));
    public byte[] Exe { get; }
    public string Version { get; }

    public FakeRelease(string version, int size = 4096)
    {
        Version = version;
        Exe = new byte[size];
        new Random(size).NextBytes(Exe);
        Exe[0] = (byte)'M';
        Exe[1] = (byte)'Z';
    }

    public string Sha => Convert.ToHexStringLower(SHA256.HashData(Exe));

    public byte[] Manifest(string? product = null, string? file = null, string? version = null, long? size = null, string? sha = null) =>
        Encoding.UTF8.GetBytes(
            "{\"product\":\"" + (product ?? "ZIGMon Notifier") + "\",\"file\":\"" + (file ?? "ZigmonNotifier.exe")
            + "\",\"version\":\"" + (version ?? Version) + "\",\"size\":" + (size ?? Exe.Length)
            + ",\"sha256\":\"" + (sha ?? Sha) + "\",\"runtime\":\"Microsoft.WindowsDesktop.App 10.0\"}\n");

    public UpdateOffer Offer(byte[]? manifest = null, byte[]? sig = null, string? version = null, long? size = null, string? sha = null)
    {
        manifest ??= Manifest();
        return new UpdateOffer(true, version ?? Version, size ?? Exe.Length, sha ?? Sha, manifest, sig ?? TestSigner.Sign(Seed, manifest));
    }

    public string Json(UpdateOffer? offer = null)
    {
        offer ??= Offer();
        return JsonSerializer.Serialize(new
        {
            ok = true, available = true, version = offer.Version, size = offer.Size, sha256 = offer.Sha256,
            manifest = Convert.ToBase64String(offer.Manifest), sig = Convert.ToBase64String(offer.Signature),
        });
    }
}

public class UpdateVerifierTests
{
    private static readonly Version Running = AppVersions.Parse("1.1.0");

    [Fact]
    public void AGoodOfferVerifies()
    {
        var r = new FakeRelease("1.2.0");
        var v = UpdateVerifier.Verify(r.Offer(), new[] { r.Key }, Running);
        Assert.Equal("1.2.0", v.VersionText);
        Assert.Equal(r.Exe.Length, v.Manifest.Size);
        Assert.Equal("throwaway", v.KeyName);
    }

    [Fact]
    public void AnyOfSeveralKeysWill()
    {
        var r = new FakeRelease("1.2.0");
        var other = new ReleaseKey("other", TestSigner.PublicKey(TestSigner.NewSeed()));
        Assert.Equal("throwaway", UpdateVerifier.Verify(r.Offer(), new[] { other, r.Key }, Running).KeyName);
        Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(r.Offer(), new[] { other }, Running));
        Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(r.Offer(), Array.Empty<ReleaseKey>(), Running));
    }

    [Fact]
    public void TheEmbeddedKeyDoesNotTakeAThrowawaySignature()
    {
        var r = new FakeRelease("1.2.0");
        var e = Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(r.Offer(), ReleaseKeys.Embedded, Running));
        Assert.Contains("not signed", e.Message);
    }

    [Fact]
    public void TamperingIsCaught()
    {
        var r = new FakeRelease("1.2.0");
        var keys = new[] { r.Key };
        var good = r.Offer();

        // a byte of the manifest changed after signing
        byte[] m = (byte[])good.Manifest.Clone();
        m[m.Length - 3] ^= 1;
        Assert.Contains("not signed", Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(good with { Manifest = m }, keys, Running)).Message);
        // a bit of the signature
        byte[] s = (byte[])good.Signature.Clone();
        s[40] ^= 0x80;
        Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(good with { Signature = s }, keys, Running));
        Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(good with { Signature = s[..63] }, keys, Running));
        // the envelope disagreeing with what is signed
        Assert.Contains("advertised", Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(good with { Version = "1.3.0" }, keys, Running)).Message);
        Assert.Contains("advertised", Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(good with { Size = good.Size + 1 }, keys, Running)).Message);
        Assert.Contains("advertised", Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(good with { Sha256 = new string('a', 64) }, keys, Running)).Message);
        Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(UpdateOffer.None, keys, Running));
    }

    [Theory]
    [InlineData("product")]
    [InlineData("file")]
    [InlineData("older")]
    [InlineData("same")]
    [InlineData("notversion")]
    [InlineData("huge")]
    [InlineData("zero")]
    [InlineData("SHA")]
    public void SignedButWrongManifestsAreRefused(string what)
    {
        var r = new FakeRelease("1.2.0");
        byte[] m = what switch
        {
            "product" => r.Manifest(product: "Other Thing"),
            "file" => r.Manifest(file: "evil.exe"),
            "older" => r.Manifest(version: "1.0.5"),
            "same" => r.Manifest(version: "1.1.0"),
            "notversion" => r.Manifest(version: "1.2.0; rm"),
            "huge" => r.Manifest(size: 60L * 1024 * 1024),
            "zero" => r.Manifest(size: 0),
            _ => r.Manifest(sha: r.Sha.ToUpperInvariant()),
        };
        string version = what switch { "older" => "1.0.5", "same" => "1.1.0", "notversion" => "1.2.0; rm", _ => "1.2.0" };
        long size = what switch { "huge" => 60L * 1024 * 1024, "zero" => 0, _ => r.Exe.Length };
        string sha = what == "SHA" ? r.Sha.ToUpperInvariant() : r.Sha;
        var offer = r.Offer(m, version: version, size: size, sha: sha);
        Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(offer, new[] { r.Key }, Running));
    }

    [Fact]
    public void ManifestMustBeStrictJson()
    {
        Assert.Throws<UpdateException>(() => UpdateVerifier.ParseManifest(Encoding.UTF8.GetBytes("[1]")));
        Assert.Throws<UpdateException>(() => UpdateVerifier.ParseManifest(Encoding.UTF8.GetBytes("{\"product\":1}")));
        Assert.Throws<UpdateException>(() => UpdateVerifier.ParseManifest(Encoding.UTF8.GetBytes("not json")));
        Assert.Throws<UpdateException>(() => UpdateVerifier.ParseManifest(Encoding.UTF8.GetBytes(
            "{\"product\":\"ZIGMon Notifier\",\"file\":\"ZigmonNotifier.exe\",\"version\":\"1.2.0\",\"size\":5,\"sha256\":\"x\",\"version\":\"9.0\"}")));
        Assert.Throws<UpdateException>(() => UpdateVerifier.ParseManifest(Encoding.UTF8.GetBytes(
            "{\"product\":\"ZIGMon Notifier\",\"file\":\"ZigmonNotifier.exe\",\"version\":\"1.2.0\",\"size\":5.5,\"sha256\":\"x\"}")));
    }

    [Fact]
    public void ATestToolMayCheckWithoutTheNewerRule()
    {
        var r = new FakeRelease("1.1.0");
        Assert.Throws<UpdateException>(() => UpdateVerifier.Verify(r.Offer(), new[] { r.Key }, Running));
        Assert.Equal("1.1.0", UpdateVerifier.Verify(r.Offer(), new[] { r.Key }, null).VersionText);
    }
}

/// <summary>The real file system, with any one operation made to fail.</summary>
internal sealed class FaultyFileSystem : IFileSystem
{
    public Func<string, string, string?, bool> FailWhen { get; set; } = (_, _, _) => false;
    public List<string> Log { get; } = new();

    private void Check(string op, string a, string? b = null)
    {
        Log.Add(op + " " + Path.GetFileName(a) + (b is null ? "" : " " + Path.GetFileName(b)));
        if (FailWhen(op, a, b)) throw new IOException("injected failure: " + op);
    }

    public bool Exists(string path) => RealFileSystem.Instance.Exists(path);
    public void Delete(string path) { Check("delete", path); RealFileSystem.Instance.Delete(path); }
    public void Move(string from, string to) { Check("move", from, to); RealFileSystem.Instance.Move(from, to); }
    public void Copy(string from, string to) { Check("copy", from, to); RealFileSystem.Instance.Copy(from, to); }
    public void CreateDirectory(string path) { Check("mkdir", path); RealFileSystem.Instance.CreateDirectory(path); }
    public void WriteAllBytes(string path, byte[] bytes) { Check("write", path); RealFileSystem.Instance.WriteAllBytes(path, bytes); }
    public byte[] ReadAllBytes(string path) { Check("read", path); return RealFileSystem.Instance.ReadAllBytes(path); }
}

public class UpdateInstallerTests
{
    private static readonly byte[] OldExe = Encoding.ASCII.GetBytes("MZ the old one, running");

    private sealed class Setup : IDisposable
    {
        public TempDir Dir { get; } = new();
        public FaultyFileSystem Fs { get; } = new();
        public FakeRelease Release { get; } = new("1.2.0");
        public VerifiedUpdate Update { get; }
        public string Exe => Dir["app/ZigmonNotifier.exe"];
        public string Staging => Dir["local/update"];
        public List<(string Path, IReadOnlyList<string> Args)> Started { get; } = new();
        public Func<bool> StartAnswer { get; set; } = () => true;

        public Setup()
        {
            Directory.CreateDirectory(Dir["app"]);
            File.WriteAllBytes(Exe, OldExe);
            Update = UpdateVerifier.Verify(Release.Offer(), new[] { Release.Key }, AppVersions.Parse("1.1.0"));
        }

        public InstallResult Run(byte[]? bytes = null) =>
            new UpdateInstaller(Fs).Install(bytes ?? Release.Exe, Update, Exe, Staging, "1.1.0", (p, a) =>
            {
                Started.Add((p, a));
                // what was started is the signed file, in the exe's own place
                Assert.Equal(Release.Exe, File.ReadAllBytes(p));
                return StartAnswer();
            });

        public void AssertUntouched()
        {
            Assert.Equal(OldExe, File.ReadAllBytes(Exe));
            Assert.False(File.Exists(UpdateInstaller.OldPath(Exe)), ".old left behind");
            Assert.False(File.Exists(UpdateInstaller.NewPath(Exe)), ".new left behind");
        }

        public void Dispose() => Dir.Dispose();
    }

    [Fact]
    public void SwapsStartsAndKeepsTheOldOneAside()
    {
        using var s = new Setup();
        var r = s.Run();
        Assert.Equal(InstallOutcome.Started, r.Outcome);
        Assert.Equal(s.Release.Exe, File.ReadAllBytes(s.Exe));
        Assert.Equal(OldExe, File.ReadAllBytes(UpdateInstaller.OldPath(s.Exe)));
        Assert.False(File.Exists(UpdateInstaller.NewPath(s.Exe)));
        var (path, args) = Assert.Single(s.Started);
        Assert.Equal(s.Exe, path);
        Assert.Equal(new[] { "--updated", "1.1.0" }, args);
        Assert.False(File.Exists(UpdateInstaller.StagedPath(s.Staging, s.Update)), "the staged copy is tidied away");

        // the next start (as the new version) clears the old one away
        Assert.True(new UpdateInstaller(s.Fs).CleanUp(s.Exe));
        Assert.False(File.Exists(UpdateInstaller.OldPath(s.Exe)));
        Assert.Equal(s.Release.Exe, File.ReadAllBytes(s.Exe));
    }

    [Fact]
    public void BytesThatAreNotTheSignedOnesAreNeverWritten()
    {
        using var s = new Setup();
        byte[] evil = (byte[])s.Release.Exe.Clone();
        evil[100] ^= 1;
        var r = s.Run(evil);
        Assert.Equal(InstallOutcome.Failed, r.Outcome);
        Assert.Empty(s.Started);
        Assert.Empty(s.Fs.Log);
        s.AssertUntouched();
        Assert.Equal(InstallOutcome.Failed, s.Run(s.Release.Exe[..^1]).Outcome);
        Assert.Equal(InstallOutcome.Failed, s.Run(s.Release.Exe.Concat(new byte[] { 0 }).ToArray()).Outcome);
        Assert.Empty(s.Started);
    }

    [Theory]
    [InlineData("mkdir", 0)]
    [InlineData("write", 0)]
    [InlineData("read", 0)]
    [InlineData("copy", 0)]
    [InlineData("read", 1)]
    [InlineData("move", 0)]   // the running exe → .old
    [InlineData("move", 1)]   // .new → the exe
    public void AFailingStepLeavesTheOldExe(string op, int nth)
    {
        using var s = new Setup();
        int seen = 0;
        s.Fs.FailWhen = (o, _, _) => o == op && seen++ == nth;
        var r = s.Run();
        Assert.Equal(InstallOutcome.Failed, r.Outcome);
        Assert.Empty(s.Started);
        s.AssertUntouched();
    }

    [Fact]
    public void DamageOnTheDiskIsCaught()
    {
        using var s = new Setup();
        var fs = new CorruptingFileSystem();
        var r = new UpdateInstaller(fs).Install(s.Release.Exe, s.Update, s.Exe, s.Staging, "1.1.0", (_, _) => throw new Exception("must not start"));
        Assert.Equal(InstallOutcome.Failed, r.Outcome);
        Assert.Contains("damaged", r.Message);
        s.AssertUntouched();
    }

    private sealed class CorruptingFileSystem : IFileSystem
    {
        public bool Exists(string path) => RealFileSystem.Instance.Exists(path);
        public void Delete(string path) => RealFileSystem.Instance.Delete(path);
        public void Move(string from, string to) => RealFileSystem.Instance.Move(from, to);
        public void Copy(string from, string to) => RealFileSystem.Instance.Copy(from, to);
        public void CreateDirectory(string path) => RealFileSystem.Instance.CreateDirectory(path);
        public void WriteAllBytes(string path, byte[] bytes)
        {
            var b = (byte[])bytes.Clone();
            b[^1] ^= 0xFF;
            RealFileSystem.Instance.WriteAllBytes(path, b);
        }
        public byte[] ReadAllBytes(string path) => RealFileSystem.Instance.ReadAllBytes(path);
    }

    [Fact]
    public void NotStartingRollsBack()
    {
        using var s = new Setup { StartAnswer = () => false };
        var r = s.Run();
        Assert.Equal(InstallOutcome.Failed, r.Outcome);
        Assert.Contains("did not start", r.Message);
        Assert.Single(s.Started);
        s.AssertUntouched();
    }

    [Fact]
    public void AStartThatThrowsRollsBack()
    {
        using var s = new Setup { StartAnswer = () => throw new Win32Exception(5) };
        var r = s.Run();
        Assert.Equal(InstallOutcome.Failed, r.Outcome);
        s.AssertUntouched();
    }

    [Fact]
    public void ALeftoverOldIsClearedFirst()
    {
        using var s = new Setup();
        File.WriteAllText(UpdateInstaller.OldPath(s.Exe), "from the update before");
        File.WriteAllText(UpdateInstaller.NewPath(s.Exe), "half a copy");
        Assert.Equal(InstallOutcome.Started, s.Run().Outcome);
        Assert.Equal(OldExe, File.ReadAllBytes(UpdateInstaller.OldPath(s.Exe)));
        Assert.Equal(s.Release.Exe, File.ReadAllBytes(s.Exe));
    }

    [Fact]
    public void ALeftoverOldThatCannotGoStopsCleanly()
    {
        using var s = new Setup();
        File.WriteAllText(UpdateInstaller.OldPath(s.Exe), "locked");
        s.Fs.FailWhen = (o, a, _) => o == "delete" && a.EndsWith(".old", StringComparison.Ordinal);
        var r = s.Run();
        Assert.Equal(InstallOutcome.Failed, r.Outcome);
        Assert.Equal(OldExe, File.ReadAllBytes(s.Exe));
        Assert.Equal("locked", File.ReadAllText(UpdateInstaller.OldPath(s.Exe)));
        Assert.False(File.Exists(UpdateInstaller.NewPath(s.Exe)));
        Assert.Empty(s.Started);
    }

    [Fact]
    public void WhenEvenTheRollBackFailsItSaysWhereTheOldOneIs()
    {
        using var s = new Setup { StartAnswer = () => false };
        int moves = 0;
        s.Fs.FailWhen = (o, _, _) => o == "move" && ++moves == 3; // the move back
        var r = s.Run();
        Assert.Equal(InstallOutcome.Broken, r.Outcome);
        Assert.Equal(UpdateInstaller.OldPath(s.Exe), r.OldPath);
        Assert.Equal(OldExe, File.ReadAllBytes(UpdateInstaller.OldPath(s.Exe)));
        Assert.Contains(".old", r.Message);
    }

    [Fact]
    public void ARelativeOrMissingExePathIsRefused()
    {
        using var s = new Setup();
        var i = new UpdateInstaller(s.Fs);
        Assert.Equal(InstallOutcome.Failed, i.Install(s.Release.Exe, s.Update, "ZigmonNotifier.exe", s.Staging, "1.1.0", (_, _) => true).Outcome);
        Assert.Equal(InstallOutcome.Failed, i.Install(s.Release.Exe, s.Update, "", s.Staging, "1.1.0", (_, _) => true).Outcome);
        Assert.Empty(s.Fs.Log);
    }
}

public class UpdateManagerTests
{
    private sealed class FakeSource : IUpdateSource
    {
        public Func<UpdateOffer> Offer { get; set; } = () => UpdateOffer.None;
        public Func<long, byte[]> Download { get; set; } = _ => throw new Exception("must not download");
        public int Downloads;

        public Task<UpdateOffer> UpdateAsync(CancellationToken ct) => Task.FromResult(Offer());
        public Task<byte[]> DownloadAsync(long size, CancellationToken ct)
        {
            Downloads++;
            return Task.FromResult(Download(size));
        }
    }

    private sealed class Rig : IDisposable
    {
        public TempDir Dir { get; } = new();
        public FakeRelease Release { get; }
        public FakeSource Source { get; } = new();
        public List<IReadOnlyList<string>> Started { get; } = new();
        public List<UpdateStatus> Seen { get; } = new();
        public UpdateManager Manager { get; }
        public string Exe => Dir["ZigmonNotifier.exe"];

        public Rig(string version = "1.2.0")
        {
            Release = new FakeRelease(version);
            File.WriteAllText(Exe, "old");
            Manager = new UpdateManager(AppVersions.Parse("1.1.0"), new[] { Release.Key }, new UpdateInstaller(RealFileSystem.Instance),
                Exe, Dir["staging"], (_, a) => { Started.Add(a); return true; });
            Manager.StatusChanged += Seen.Add;
        }

        public void Dispose() => Dir.Dispose();
    }

    [Fact]
    public async Task InstallsAVerifiedNewerVersion()
    {
        using var r = new Rig();
        r.Source.Offer = () => r.Release.Offer();
        r.Source.Download = size => { Assert.Equal(r.Release.Exe.Length, size); return r.Release.Exe; };
        var s = await r.Manager.CheckAsync(r.Source, install: true, default);
        Assert.Equal(UpdateState.Restarting, s.State);
        Assert.Single(r.Started);
        Assert.Equal(r.Release.Exe, File.ReadAllBytes(r.Exe));
        Assert.Equal(new[] { UpdateState.Checking, UpdateState.Updating, UpdateState.Restarting }, r.Seen.Select(x => x.State));
        Assert.Equal("Updating to 1.2.0…", r.Seen[1].Text);
    }

    [Fact]
    public async Task WithoutInstallItOnlySaysSo()
    {
        using var r = new Rig();
        r.Source.Offer = () => r.Release.Offer();
        var s = await r.Manager.CheckAsync(r.Source, install: false, default);
        Assert.Equal(UpdateState.Available, s.State);
        Assert.Equal("1.2.0", s.Version);
        Assert.Equal(0, r.Source.Downloads);
        Assert.Empty(r.Started);
    }

    [Fact]
    public async Task NothingNewerIsUpToDate()
    {
        using var r = new Rig("1.1.0");
        r.Source.Offer = () => r.Release.Offer();
        Assert.Equal("Up to date – 1.1.0", (await r.Manager.CheckAsync(r.Source, true, default)).Text);
        r.Source.Offer = () => UpdateOffer.None;
        Assert.Equal(UpdateState.UpToDate, (await r.Manager.CheckAsync(r.Source, true, default)).State);
        Assert.Equal(0, r.Source.Downloads);
    }

    [Fact]
    public async Task NeverDowngrades()
    {
        using var r = new Rig("1.0.0");
        r.Source.Offer = () => r.Release.Offer(); // honestly signed, but older
        Assert.Equal(UpdateState.UpToDate, (await r.Manager.CheckAsync(r.Source, true, default)).State);
        // an envelope that lies "newer" around an older signed manifest
        r.Source.Offer = () => r.Release.Offer(version: "9.0.0");
        var s = await r.Manager.CheckAsync(r.Source, true, default);
        Assert.Equal(UpdateState.Failed, s.State);
        Assert.Equal(0, r.Source.Downloads);
        Assert.Empty(r.Started);
    }

    [Fact]
    public async Task ABadSignatureIsNeverDownloaded()
    {
        using var r = new Rig();
        var other = new FakeRelease("1.2.0");
        r.Source.Offer = () => other.Offer(); // signed by a key the app does not know
        var s = await r.Manager.CheckAsync(r.Source, true, default);
        Assert.Equal(UpdateState.Failed, s.State);
        Assert.StartsWith("Update failed: ", s.Text);
        Assert.Contains("not signed", s.Text);
        Assert.Equal(0, r.Source.Downloads);
        Assert.Equal("old", File.ReadAllText(r.Exe));
    }

    [Fact]
    public async Task AWrongDownloadIsNeverRun()
    {
        using var r = new Rig();
        r.Source.Offer = () => r.Release.Offer();
        r.Source.Download = _ => { var b = (byte[])r.Release.Exe.Clone(); b[9] ^= 4; return b; };
        var s = await r.Manager.CheckAsync(r.Source, true, default);
        Assert.Equal(UpdateState.Failed, s.State);
        Assert.Empty(r.Started);
        Assert.Equal("old", File.ReadAllText(r.Exe));
    }

    [Theory]
    [InlineData(404)]
    [InlineData(400)]
    public async Task AnOlderZigmonMeansNoUpdates(int status)
    {
        using var r = new Rig();
        r.Source.Offer = () => throw new ZigmonException(status == 400 ? ZigmonErrorKind.BadRequest : ZigmonErrorKind.Http, "x", status);
        var s = await r.Manager.CheckAsync(r.Source, true, default);
        Assert.Equal(UpdateState.NotOffered, s.State);
        Assert.StartsWith("Up to date – 1.1.0", s.Text);
    }

    [Fact]
    public async Task OtherErrorsAreFailures()
    {
        using var r = new Rig();
        r.Source.Offer = () => throw new ZigmonException(ZigmonErrorKind.Network, "Could not reach it");
        Assert.Equal(UpdateState.Failed, (await r.Manager.CheckAsync(r.Source, true, default)).State);
        r.Source.Offer = () => throw new InvalidOperationException("boom");
        Assert.Equal(UpdateState.Failed, (await r.Manager.CheckAsync(r.Source, true, default)).State);
    }

    [Fact]
    public void HelloDecidesTheAutomaticLook()
    {
        using var r = new Rig();
        var h = new HelloInfo(1, "zigmon", "5.58.0", "h", new KeyInfo("k", 1, "xQ"), "bbbbbbbbbbbb", 1);
        Assert.False(r.Manager.HelloOffersNewer(h));                                              // an older ZIGMon: no "app"
        Assert.False(r.Manager.HelloOffersNewer(h with { AdvertisesApp = true }));                // "app": null
        Assert.False(r.Manager.HelloOffersNewer(h with { AdvertisesApp = true, AppVersion = "1.1.0" }));
        Assert.False(r.Manager.HelloOffersNewer(h with { AdvertisesApp = true, AppVersion = "1.0.0" }));
        Assert.True(r.Manager.HelloOffersNewer(h with { AdvertisesApp = true, AppVersion = "1.1.1" }));
    }
}

public class UpdateClientTests
{
    [Fact]
    public async Task HelloCarriesTheAppVersionOnlyWhenNewServersSendIt()
    {
        var fake = new FakeZigmon();
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var old = await c.HelloAsync(default);
        Assert.False(old.AdvertisesApp);
        Assert.Null(old.AppVersion);
        fake.HelloAppNull = true;
        var none = await c.HelloAsync(default);
        Assert.True(none.AdvertisesApp);
        Assert.Null(none.AppVersion);
        fake.HelloAppNull = false;
        fake.HelloAppVersion = "1.2.0";
        var some = await c.HelloAsync(default);
        Assert.True(some.AdvertisesApp);
        Assert.Equal("1.2.0", some.AppVersion);
        fake.HelloAppVersion = "1.2.0‮<script>";
        Assert.Null((await c.HelloAsync(default)).AppVersion);
    }

    [Fact]
    public async Task UpdateAndDownloadTravelLikeEverythingElse()
    {
        var r = new FakeRelease("1.2.0", 100_000);
        var fake = new FakeZigmon { UpdateJson = r.Json(), DownloadBytes = r.Exe };
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        var offer = await c.UpdateAsync(default);
        Assert.True(offer.Available);
        Assert.Equal(r.Offer().Manifest, offer.Manifest);
        var v = UpdateVerifier.Verify(offer, new[] { r.Key }, AppVersions.Parse("1.1.0"));
        byte[] exe = await c.DownloadAsync(v.Manifest.Size, default);
        Assert.Equal(r.Exe, exe);
        foreach (var q in fake.Requests)
        {
            Assert.Equal(FakeZigmon.GoodKey, q.Headers[AppInfo.KeyHeader]);
            Assert.DoesNotContain(FakeZigmon.GoodKey[4..], q.Uri.ToString());
        }
        Assert.Contains(fake.Requests, q => q.Uri.Query.Contains("do=update"));
        Assert.Contains(fake.Requests, q => q.Uri.Query.Contains("do=download"));
    }

    [Fact]
    public async Task NotAvailableAndOldServers()
    {
        var fake = new FakeZigmon { UpdateJson = "{\"ok\":true,\"available\":false}" };
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        Assert.False((await c.UpdateAsync(default)).Available);
        fake.UpdateJson = null; // a ZIGMon from before updates answers 400
        var e = await Assert.ThrowsAsync<ZigmonException>(() => c.UpdateAsync(default));
        Assert.Equal(400, e.Status);
        var d = await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(10, default));
        Assert.Equal(404, d.Status);
        fake.UpdateJson = "{\"ok\":true,\"available\":true,\"version\":\"1.2.0\"}";
        Assert.Equal(ZigmonErrorKind.Protocol, (await Assert.ThrowsAsync<ZigmonException>(() => c.UpdateAsync(default))).Kind);
    }

    [Fact]
    public async Task TheDownloadIsCappedAtTheSignedSize()
    {
        var r = new FakeRelease("1.2.0", 50_000);
        var fake = new FakeZigmon { DownloadBytes = r.Exe };
        using var c = new ZigmonClient(K.Address, K.Good, fake);
        Assert.Equal(ZigmonErrorKind.TooLarge, (await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(49_999, default))).Kind);
        Assert.Equal(ZigmonErrorKind.Protocol, (await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(50_001, default))).Kind);
        Assert.Equal(ZigmonErrorKind.TooLarge, (await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(0, default))).Kind);
        Assert.Equal(ZigmonErrorKind.TooLarge, (await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(UpdateVerifier.MaxExeBytes + 1, default))).Kind);
        Assert.Equal(r.Exe, await c.DownloadAsync(50_000, default));
    }

    [Fact]
    public async Task ADownloadRedirectIsNotFollowedAndTheHeaderIsOnTheWire()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        int port = ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        using var listener = new HttpListener();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        var seen = new ConcurrentQueue<(string Url, string? Key)>();
        var serve = Task.Run(async () =>
        {
            while (listener.IsListening)
            {
                HttpListenerContext ctx;
                try { ctx = await listener.GetContextAsync(); } catch { return; }
                seen.Enqueue((ctx.Request.Url!.ToString(), ctx.Request.Headers[AppInfo.KeyHeader]));
                ctx.Response.StatusCode = 302;
                ctx.Response.RedirectLocation = $"http://127.0.0.1:{port}/elsewhere.exe";
                ctx.Response.Close();
            }
        });
        using (var c = ZigmonClient.Create(ServerAddress.Parse($"http://127.0.0.1:{port}/index.php"), K.Good, null))
        {
            var e = await Assert.ThrowsAsync<ZigmonException>(() => c.DownloadAsync(1000, default));
            Assert.Equal(ZigmonErrorKind.Redirect, e.Kind);
        }
        listener.Stop();
        var one = Assert.Single(seen);
        Assert.Contains("do=download", one.Url);
        Assert.Equal(FakeZigmon.GoodKey, one.Key);
    }
}

public class UpdateSettingTests
{
    [Fact]
    public void AutomaticUpdatesAreOnByDefaultAndForOldSettingsFiles()
    {
        Assert.True(new NotifierSettings().AutoUpdate);
        using var dir = new TempDir();
        var store = new SettingsStore(dir["settings.json"]);
        File.WriteAllText(store.Path, "{\"format\":1,\"sound\":false}"); // as 1.0.0 wrote it
        var s = store.Load(DateTimeOffset.UtcNow);
        Assert.True(s.AutoUpdate);
        Assert.False(s.Sound);
        s.AutoUpdate = false;
        store.Save(s);
        Assert.False(store.Load(DateTimeOffset.UtcNow).AutoUpdate);
    }
}
