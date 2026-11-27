// The app's own client against a running ZIGMon - for the end-to-end checks
// (test/review557_e2e.py). Reads the address and the key from standard input
// (two lines), so the key is never on a command line. Prints one line per
// thing seen.
//
//   Probe <sensor name>   hello, sensors, then the long poll; exits 0 after the
//                         first event of that sensor.
//   Probe --update-check  asks /update, verifies the offer the way the app does
//                         (signature by a release key, then the manifest - but
//                         without the "newer than this build" rule), prints
//                         UPDATE <version> VERIFIED, downloads the exe, checks
//                         its size and sha256 and prints DOWNLOADED <sha256>.
//                         UPDATE NONE when nothing is offered, UPDATE REJECTED
//                         <why> (exit 1) when the offer fails a check.
//                         ZIGMON_PROBE_KEYS = a folder of *.pub release keys to
//                         use instead of the embedded ones (a throwaway key).
using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using ZigmonNotifier.Core;

var address = ServerAddress.Parse(Console.ReadLine() ?? "");
if (!NotifierKey.TryParse(Console.ReadLine(), out var key, out var err)) { Console.WriteLine("BADKEY " + err); return 2; }
using var client = ZigmonClient.Create(address, key, null);
using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(90));
var hello = await client.HelloAsync(cts.Token);
Console.WriteLine($"HELLO api={hello.Api} server={hello.Server} key={hello.Key.Name} app={(hello.AdvertisesApp ? hello.AppVersion ?? "null" : "absent")}");

if (args.Length > 0 && args[0] == "--update-check")
{
    string? folder = Environment.GetEnvironmentVariable("ZIGMON_PROBE_KEYS");
    IReadOnlyList<ReleaseKey> keys = string.IsNullOrEmpty(folder) ? ReleaseKeys.Embedded : ReleaseKeys.LoadFolder(folder);
    Console.WriteLine("KEYS " + string.Join(",", keys.Select(k => k.Name)));
    UpdateOffer offer;
    try
    {
        offer = await client.UpdateAsync(cts.Token);
    }
    catch (ZigmonException z)
    {
        Console.WriteLine("UPDATE ERROR " + z.Status + " " + z.Message);
        return 1;
    }
    if (!offer.Available) { Console.WriteLine("UPDATE NONE"); return 0; }
    VerifiedUpdate update;
    try
    {
        update = UpdateVerifier.Verify(offer, keys, mustBeNewerThan: null);
    }
    catch (UpdateException u)
    {
        Console.WriteLine("UPDATE REJECTED " + u.Message);
        return 1;
    }
    Console.WriteLine($"UPDATE {update.VersionText} VERIFIED key={update.KeyName} size={update.Manifest.Size}");
    Console.Out.Flush();
    byte[] exe;
    try
    {
        exe = await client.DownloadAsync(update.Manifest.Size, cts.Token);
    }
    catch (ZigmonException z)
    {
        Console.WriteLine("DOWNLOAD ERROR " + z.Status + " " + z.Message);
        return 1;
    }
    if (!UpdateInstaller.Matches(exe, update.Manifest))
    {
        Console.WriteLine("DOWNLOAD MISMATCH " + Convert.ToHexStringLower(SHA256.HashData(exe)));
        return 1;
    }
    Console.WriteLine("DOWNLOADED " + Convert.ToHexStringLower(SHA256.HashData(exe)));
    return 0;
}

var sensors = await client.SensorsAsync(cts.Token);
Console.WriteLine("SENSORS " + string.Join(",", sensors.Sensors.Select(s => $"{s.Name}:{s.Kind}:{s.Active}")));
Console.Out.Flush();
var service = new NotifierService(client, s => { });
var done = new TaskCompletionSource<int>();
service.StatusChanged += s => Console.WriteLine("STATUS " + s.State);
service.EventsArrived += evs =>
{
    foreach (var e in evs)
    {
        Console.WriteLine($"EVENT {e.Name} {e.Kind} {e.Key} {e.Active} {e.What} room={e.Room}");
        if (e.Name == args[0]) done.TrySetResult(0);
    }
    Console.Out.Flush();
};
var run = service.RunAsync(cts.Token);
var first = await Task.WhenAny(done.Task, run, Task.Delay(Timeout.Infinite, cts.Token).ContinueWith(_ => 0));
cts.Cancel();
Console.WriteLine(done.Task.IsCompleted ? "DONE" : "TIMEOUT " + service.Status.Message);
Console.WriteLine("LEAK " + (client.ToString()!.Contains(key.ToString()) ? "hint-only" : "none"));
return done.Task.IsCompleted ? 0 : 1;
