using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;

namespace ZigmonNotifier.Core;

/// <summary>The few file operations the installer needs, so tests can make any one of them fail.</summary>
public interface IFileSystem
{
    bool Exists(string path);
    /// <summary>Deletes when present; no error when absent.</summary>
    void Delete(string path);
    /// <summary>Renames or moves; fails when the destination exists.</summary>
    void Move(string from, string to);
    void Copy(string from, string to);
    void CreateDirectory(string path);
    /// <summary>Writes and flushes to the disk.</summary>
    void WriteAllBytes(string path, byte[] bytes);
    byte[] ReadAllBytes(string path);
}

public sealed class RealFileSystem : IFileSystem
{
    public static readonly RealFileSystem Instance = new();

    public bool Exists(string path) => File.Exists(path);
    public void Delete(string path) { if (File.Exists(path)) File.Delete(path); }
    public void Move(string from, string to) => File.Move(from, to, overwrite: false);
    public void Copy(string from, string to) => File.Copy(from, to, overwrite: false);
    public void CreateDirectory(string path) => Directory.CreateDirectory(path);

    public void WriteAllBytes(string path, byte[] bytes)
    {
        using var fs = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None, 64 * 1024, FileOptions.WriteThrough);
        fs.Write(bytes);
        fs.Flush(true);
    }

    public byte[] ReadAllBytes(string path) => File.ReadAllBytes(path);
}

public enum InstallOutcome
{
    /// <summary>The new exe is in place and running; this process should exit now.</summary>
    Started,
    /// <summary>Nothing changed: the old exe is where it was.</summary>
    Failed,
    /// <summary>A step failed and so did putting the old exe back - the user must look (the old exe is at <see cref="InstallResult.OldPath"/>).</summary>
    Broken,
}

public sealed record InstallResult(InstallOutcome Outcome, string Message, string? OldPath = null);

/// <summary>
/// Puts a verified exe in place of the running one:
/// stage (write, read back, check) → copy next to the exe as .new (check) →
/// rename the running exe to .old (Windows allows that) → rename .new to the exe →
/// start it with --updated &lt;old version&gt;. A failure at any step puts the old exe
/// back, so there is always an exe. The bytes are checked against the signed
/// size and sha256 before anything is written, and again after every copy.
/// </summary>
public sealed class UpdateInstaller
{
    private readonly IFileSystem _fs;

    public UpdateInstaller(IFileSystem fs) => _fs = fs ?? throw new ArgumentNullException(nameof(fs));

    public static string OldPath(string exePath) => exePath + ".old";
    public static string NewPath(string exePath) => exePath + ".new";

    /// <summary>%LOCALAPPDATA%\ZIGMon Notifier\update</summary>
    public static string DefaultStagingDir() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), AppInfo.Name, "update");

    public static string StagedPath(string stagingDir, VerifiedUpdate update) =>
        Path.Combine(stagingDir, "ZigmonNotifier-" + update.VersionText + ".exe");

    /// <param name="start">Starts the given exe with the given arguments; true when it started.</param>
    public InstallResult Install(byte[] exe, VerifiedUpdate update, string exePath, string stagingDir,
        string runningVersion, Func<string, IReadOnlyList<string>, bool> start)
    {
        ArgumentNullException.ThrowIfNull(exe);
        ArgumentNullException.ThrowIfNull(update);
        ArgumentNullException.ThrowIfNull(start);
        if (string.IsNullOrEmpty(exePath) || !Path.IsPathFullyQualified(exePath))
            return Failed("the app's own file cannot be found");
        if (!Matches(exe, update.Manifest))
            return Failed("the download is not the signed file (size or checksum differ)");

        string staged = StagedPath(stagingDir, update);
        string fresh = NewPath(exePath);
        string old = OldPath(exePath);

        // 1. stage, and read it back
        try
        {
            _fs.CreateDirectory(stagingDir);
            _fs.Delete(staged);
            _fs.WriteAllBytes(staged, exe);
            if (!Matches(_fs.ReadAllBytes(staged), update.Manifest)) return Failed("the downloaded file was damaged on the disk");
        }
        catch (Exception ex) when (IsFileError(ex))
        {
            return Failed("could not save the download (" + ex.GetType().Name + ")");
        }

        // 2. next to the exe, so the renames below stay on one disk
        try
        {
            _fs.Delete(fresh);
            _fs.Copy(staged, fresh);
            if (!Matches(_fs.ReadAllBytes(fresh), update.Manifest))
            {
                TryDelete(fresh);
                return Failed("the new file was damaged when copied next to the app");
            }
        }
        catch (Exception ex) when (IsFileError(ex))
        {
            TryDelete(fresh);
            return Failed("cannot write in the app's folder (" + ex.GetType().Name + ")");
        }

        // 3. out of the way with the running exe (a leftover .old from before goes first)
        try
        {
            _fs.Delete(old);
            _fs.Move(exePath, old);
        }
        catch (Exception ex) when (IsFileError(ex))
        {
            TryDelete(fresh);
            return Failed("cannot rename the running app (" + ex.GetType().Name + ")");
        }

        // 4. the new one in its place
        try
        {
            _fs.Move(fresh, exePath);
        }
        catch (Exception ex) when (IsFileError(ex))
        {
            return RollBack(exePath, old, fresh, "cannot put the new version in place (" + ex.GetType().Name + ")", removeExe: false);
        }

        // 5. start it; it waits for this one to exit
        bool started;
        try
        {
            started = start(exePath, new[] { "--updated", runningVersion });
        }
        catch (Exception ex)
        {
            return RollBack(exePath, old, fresh, "the new version did not start (" + ex.GetType().Name + ")", removeExe: true);
        }
        if (!started) return RollBack(exePath, old, fresh, "the new version did not start", removeExe: true);

        TryDelete(staged);
        return new InstallResult(InstallOutcome.Started, "Updated to " + update.VersionText + "; restarting.");
    }

    /// <summary>On the first start of the new version: the old exe (and any half-made .new) go. True when no .old is left.</summary>
    public bool CleanUp(string exePath)
    {
        bool gone = TryDelete(OldPath(exePath));
        TryDelete(NewPath(exePath));
        return gone;
    }

    private InstallResult RollBack(string exePath, string old, string fresh, string why, bool removeExe)
    {
        try
        {
            if (removeExe) _fs.Delete(exePath);
            if (!_fs.Exists(exePath)) _fs.Move(old, exePath);
            TryDelete(fresh);
            return Failed(why);
        }
        catch (Exception ex) when (IsFileError(ex))
        {
            return new InstallResult(InstallOutcome.Broken,
                why + "; putting the old version back failed too - it is " + Path.GetFileName(old) + " next to the app", old);
        }
    }

    private static InstallResult Failed(string why) => new(InstallOutcome.Failed, why);

    private bool TryDelete(string path)
    {
        try
        {
            _fs.Delete(path);
            return !_fs.Exists(path);
        }
        catch (Exception ex) when (IsFileError(ex))
        {
            return false;
        }
    }

    public static bool Matches(byte[] bytes, UpdateManifest m) =>
        bytes.LongLength == m.Size && string.Equals(Convert.ToHexStringLower(SHA256.HashData(bytes)), m.Sha256, StringComparison.Ordinal);

    private static bool IsFileError(Exception ex) => ex is IOException or UnauthorizedAccessException or NotSupportedException
        or System.Security.SecurityException or ArgumentException;
}
