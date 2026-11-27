// Writes the app icon (ZigmonNotifier/Assets/app.ico) from the same painter the
// tray icon uses at run time. Usage: IconGen <out.ico> [preview-dir]
using System;
using System.Collections.Generic;
using System.IO;
using ZigmonNotifier.Core;

if (args.Length < 1)
{
    Console.Error.WriteLine("usage: IconGen <out.ico> [preview-dir]");
    return 2;
}

int[] sizes = { 16, 20, 24, 32, 40, 48, 64, 256 };
var frames = new List<(int, byte[])>();
foreach (int s in sizes) frames.Add((s, IconPainter.Render(s)));
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[0]))!);
File.WriteAllBytes(args[0], ImageFiles.Ico(frames));
Console.WriteLine("wrote " + args[0]);

if (args.Length > 1)
{
    Directory.CreateDirectory(args[1]);
    foreach (var (s, rgba) in frames)
        File.WriteAllBytes(Path.Combine(args[1], "app-" + s + ".png"), ImageFiles.Png(s, s, rgba));
    foreach (StatusDot d in Enum.GetValues<StatusDot>())
        foreach (int s in new[] { 16, 24, 32, 64 })
            File.WriteAllBytes(Path.Combine(args[1], "tray-" + d + "-" + s + ".png"), ImageFiles.Png(s, s, IconPainter.Render(s, d)));
    File.WriteAllBytes(Path.Combine(args[1], "chime.wav"), Chime.CreateWav());
    Console.WriteLine("previews in " + args[1]);
}
return 0;
