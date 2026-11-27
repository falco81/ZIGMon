// The app's own client against a running ZIGMon - for the end-to-end check
// (test/review557_e2e.py). Reads the address and the key from standard input
// (two lines), so the key is never on a command line. Prints one line per
// thing seen; exits 0 after the first event of the sensor named in args[0].
using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using ZigmonNotifier.Core;

var address = ServerAddress.Parse(Console.ReadLine() ?? "");
if (!NotifierKey.TryParse(Console.ReadLine(), out var key, out var err)) { Console.WriteLine("BADKEY " + err); return 2; }
using var client = ZigmonClient.Create(address, key, null);
using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(90));
var hello = await client.HelloAsync(cts.Token);
Console.WriteLine($"HELLO api={hello.Api} server={hello.Server} key={hello.Key.Name}");
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
