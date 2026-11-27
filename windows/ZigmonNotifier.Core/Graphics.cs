using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace ZigmonNotifier.Core;

public enum StatusDot { None, Green, Grey, Red, Amber }

/// <summary>
/// Draws the app's mark - a dark rounded tile with a sensor sending out its waves
/// in ZIGMon's blue - at any pixel size, anti-aliased by supersampling. Used for
/// the .exe icon (at build time) and the tray icon with its status dot (at run time).
/// Output: straight (non-premultiplied) RGBA, rows top to bottom.
/// </summary>
public static class IconPainter
{
    private readonly record struct Rgba(double R, double G, double B, double A)
    {
        public static Rgba Hex(string hex, double alpha = 1)
        {
            int v = Convert.ToInt32(hex.TrimStart('#'), 16);
            return new(((v >> 16) & 255) / 255.0, ((v >> 8) & 255) / 255.0, (v & 255) / 255.0, alpha);
        }
        public Rgba WithAlpha(double a) => this with { A = A * a };
        public static Rgba Mix(Rgba a, Rgba b, double t) =>
            new(a.R + (b.R - a.R) * t, a.G + (b.G - a.G) * t, a.B + (b.B - a.B) * t, a.A + (b.A - a.A) * t);
    }

    // premultiplied accumulator
    private struct Px
    {
        public double R, G, B, A;
        public void Over(Rgba c)
        {
            double a = c.A;
            R = c.R * a + R * (1 - a);
            G = c.G * a + G * (1 - a);
            B = c.B * a + B * (1 - a);
            A = a + A * (1 - a);
        }
    }

    private static readonly Rgba TileTop = Rgba.Hex("#1F2937");
    private static readonly Rgba TileBottom = Rgba.Hex(Palette.Bg);
    private static readonly Rgba Accent = Rgba.Hex(Palette.Info);
    private static readonly Rgba Ring = Rgba.Hex(Palette.Bg);

    private static Rgba DotColour(StatusDot dot) => dot switch
    {
        StatusDot.Green => Rgba.Hex(Palette.Ok),
        StatusDot.Red => Rgba.Hex(Palette.Crit),
        StatusDot.Amber => Rgba.Hex(Palette.Warn),
        _ => Rgba.Hex("#8B94A3"),
    };

    public static byte[] Render(int size, StatusDot dot = StatusDot.None)
    {
        if (size < 8 || size > 1024) throw new ArgumentOutOfRangeException(nameof(size));
        int ss = size <= 32 ? 6 : size <= 64 ? 4 : 3;
        double px = 1.0 / size;
        // small icons use the whole square; large ones leave a little air like Windows' own
        double margin = size >= 48 ? 0.045 : size >= 24 ? 0.02 : 0;
        double half = 0.5 - margin;
        double radius = half * 0.46;
        double border = Math.Max(px * 0.9, 0.022);

        var o = (X: 0.5, Y: 0.5);
        double r1 = 0.20, r2 = 0.355;
        double stroke = Math.Max(px * 0.8, size <= 20 ? 0.056 : 0.048);
        double dotR = Math.Max(px * 1.1, size <= 20 ? 0.10 : 0.09);

        var dc = DotColour(dot);
        (double X, double Y) sc = (0.775, 0.775);
        double sRing = 0.215, sInner = 0.150;

        var result = new byte[size * size * 4];
        for (int y = 0; y < size; y++)
        for (int x = 0; x < size; x++)
        {
            double r = 0, g = 0, b = 0, a = 0;
            for (int sy = 0; sy < ss; sy++)
            for (int sx = 0; sx < ss; sx++)
            {
                double u = (x + (sx + 0.5) / ss) * px;
                double v = (y + (sy + 0.5) / ss) * px;
                var p = new Px();

                double dTile = RoundBox(u - 0.5, v - 0.5, half, radius);
                if (dTile < 0)
                {
                    var fill = Rgba.Mix(TileTop, TileBottom, Math.Clamp((v - margin) / (1 - 2 * margin), 0, 1));
                    p.Over(fill);
                    // a soft blue glow where the waves start
                    double gd = Dist(u, v, o.X, o.Y);
                    p.Over(Accent.WithAlpha(0.16 * Math.Clamp(1 - gd / 0.5, 0, 1)));
                    if (dTile > -border) p.Over(Accent.WithAlpha(0.42));

                    // the sensor and its waves to both sides: (( o ))
                    if (Dist(u, v, o.X, o.Y) <= dotR) p.Over(Accent);
                    if (OnArc(u, v, o, r1, stroke, 0) || OnArc(u, v, o, r1, stroke, 180)) p.Over(Accent);
                    if (OnArc(u, v, o, r2, stroke, 0) || OnArc(u, v, o, r2, stroke, 180)) p.Over(Accent.WithAlpha(0.72));
                }

                if (dot != StatusDot.None)
                {
                    double dd = Dist(u, v, sc.X, sc.Y);
                    if (dd <= sRing) p.Over(Ring);
                    if (dd <= sInner) p.Over(dc);
                }
                r += p.R; g += p.G; b += p.B; a += p.A;
            }
            int n = ss * ss;
            r /= n; g /= n; b /= n; a /= n;
            int i = (y * size + x) * 4;
            if (a > 0)
            {
                result[i] = ToByte(r / a);
                result[i + 1] = ToByte(g / a);
                result[i + 2] = ToByte(b / a);
            }
            result[i + 3] = ToByte(a);
        }
        return result;
    }

    private const double ArcHalfSpan = 44;

    /// <summary>On an arc of <paramref name="radius"/> centred on the direction <paramref name="facing"/> (degrees, 0 = right), round ends.</summary>
    private static bool OnArc(double u, double v, (double X, double Y) o, double radius, double halfWidth, double facing)
    {
        double angle = Math.Atan2(o.Y - v, u - o.X) * 180 / Math.PI;
        double off = Math.Abs(((angle - facing) % 360 + 540) % 360 - 180);
        if (off <= ArcHalfSpan)
            return Math.Abs(Dist(u, v, o.X, o.Y) - radius) <= halfWidth;
        for (int side = -1; side <= 1; side += 2)
        {
            double a = (facing + side * ArcHalfSpan) * Math.PI / 180;
            if (Dist(u, v, o.X + radius * Math.Cos(a), o.Y - radius * Math.Sin(a)) <= halfWidth) return true;
        }
        return false;
    }

    private static double Dist(double x1, double y1, double x2, double y2)
    {
        double dx = x1 - x2, dy = y1 - y2;
        return Math.Sqrt(dx * dx + dy * dy);
    }

    private static double RoundBox(double px, double py, double half, double r)
    {
        double qx = Math.Abs(px) - (half - r), qy = Math.Abs(py) - (half - r);
        double ox = Math.Max(qx, 0), oy = Math.Max(qy, 0);
        return Math.Sqrt(ox * ox + oy * oy) + Math.Min(Math.Max(qx, qy), 0) - r;
    }

    private static byte ToByte(double v) => (byte)Math.Clamp((int)Math.Round(v * 255), 0, 255);
}

/// <summary>Minimal PNG (RGBA, 8 bit) and ICO writers.</summary>
public static class ImageFiles
{
    public static byte[] Png(int width, int height, byte[] rgba)
    {
        using var ms = new MemoryStream();
        ms.Write(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A });
        var ihdr = new byte[13];
        WriteBE(ihdr, 0, width);
        WriteBE(ihdr, 4, height);
        ihdr[8] = 8; ihdr[9] = 6; // 8-bit RGBA
        Chunk(ms, "IHDR", ihdr);

        using var raw = new MemoryStream();
        using (var z = new ZLibStream(raw, CompressionLevel.SmallestSize, leaveOpen: true))
        {
            for (int y = 0; y < height; y++)
            {
                z.WriteByte(0);
                z.Write(rgba, y * width * 4, width * 4);
            }
        }
        Chunk(ms, "IDAT", raw.ToArray());
        Chunk(ms, "IEND", Array.Empty<byte>());
        return ms.ToArray();
    }

    /// <summary>An .ico: 32-bit BMP frames below 256 px (read by everything), PNG at 256.</summary>
    public static byte[] Ico(IReadOnlyList<(int Size, byte[] Rgba)> frames)
    {
        var images = new List<byte[]>();
        foreach (var (size, rgba) in frames)
            images.Add(size >= 256 ? Png(size, size, rgba) : Dib(size, rgba));

        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms, Encoding.ASCII, leaveOpen: true);
        w.Write((ushort)0); w.Write((ushort)1); w.Write((ushort)frames.Count);
        int offset = 6 + 16 * frames.Count;
        for (int i = 0; i < frames.Count; i++)
        {
            int s = frames[i].Size;
            w.Write((byte)(s >= 256 ? 0 : s));
            w.Write((byte)(s >= 256 ? 0 : s));
            w.Write((byte)0); w.Write((byte)0);
            w.Write((ushort)1); w.Write((ushort)32);
            w.Write(images[i].Length);
            w.Write(offset);
            offset += images[i].Length;
        }
        foreach (var img in images) w.Write(img);
        w.Flush();
        return ms.ToArray();
    }

    private static byte[] Dib(int size, byte[] rgba)
    {
        int maskStride = ((size + 31) / 32) * 4;
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(40); w.Write(size); w.Write(size * 2);
        w.Write((ushort)1); w.Write((ushort)32);
        w.Write(0); w.Write(size * size * 4 + maskStride * size);
        w.Write(0); w.Write(0); w.Write(0); w.Write(0);
        for (int y = size - 1; y >= 0; y--)
        for (int x = 0; x < size; x++)
        {
            int i = (y * size + x) * 4;
            w.Write(rgba[i + 2]); w.Write(rgba[i + 1]); w.Write(rgba[i]); w.Write(rgba[i + 3]);
        }
        for (int y = size - 1; y >= 0; y--)
        {
            var row = new byte[maskStride];
            for (int x = 0; x < size; x++)
                if (rgba[(y * size + x) * 4 + 3] == 0) row[x / 8] |= (byte)(0x80 >> (x % 8));
            w.Write(row);
        }
        w.Flush();
        return ms.ToArray();
    }

    private static void Chunk(Stream s, string type, byte[] data)
    {
        var len = new byte[4];
        WriteBE(len, 0, data.Length);
        s.Write(len);
        var t = Encoding.ASCII.GetBytes(type);
        s.Write(t);
        s.Write(data);
        uint crc = Crc32(t, 0xFFFFFFFF);
        crc = Crc32(data, crc) ^ 0xFFFFFFFF;
        var c = new byte[4];
        WriteBE(c, 0, (int)crc);
        s.Write(c);
    }

    private static uint[]? _crcTable;
    private static uint Crc32(byte[] data, uint crc)
    {
        var table = _crcTable ??= MakeTable();
        foreach (byte b in data) crc = table[(crc ^ b) & 0xFF] ^ (crc >> 8);
        return crc;
    }

    private static uint[] MakeTable()
    {
        var t = new uint[256];
        for (uint n = 0; n < 256; n++)
        {
            uint c = n;
            for (int k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320 ^ (c >> 1) : c >> 1;
            t[n] = c;
        }
        return t;
    }

    private static void WriteBE(byte[] b, int at, int v)
    {
        b[at] = (byte)(v >> 24); b[at + 1] = (byte)(v >> 16); b[at + 2] = (byte)(v >> 8); b[at + 3] = (byte)v;
    }
}

/// <summary>A short, soft two-note chime, made from sine waves (no recorded sound, nobody's copyright).</summary>
public static class Chime
{
    public const int SampleRate = 44100;

    public static byte[] CreateWav()
    {
        double duration = 1.05;
        int n = (int)(SampleRate * duration);
        var samples = new double[n];
        Note(samples, 0.00, 1046.50, 0.55); // C6
        Note(samples, 0.13, 1567.98, 0.45); // G6
        double peak = 0;
        foreach (double s in samples) peak = Math.Max(peak, Math.Abs(s));
        double gain = peak > 0 ? 0.42 / peak : 0;

        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms, Encoding.ASCII);
        int dataBytes = n * 2;
        w.Write(Encoding.ASCII.GetBytes("RIFF")); w.Write(36 + dataBytes);
        w.Write(Encoding.ASCII.GetBytes("WAVE"));
        w.Write(Encoding.ASCII.GetBytes("fmt ")); w.Write(16);
        w.Write((ushort)1); w.Write((ushort)1); w.Write(SampleRate); w.Write(SampleRate * 2);
        w.Write((ushort)2); w.Write((ushort)16);
        w.Write(Encoding.ASCII.GetBytes("data")); w.Write(dataBytes);
        for (int i = 0; i < n; i++)
        {
            double fade = i > n - 2205 ? (n - i) / 2205.0 : 1; // last 50 ms
            w.Write((short)Math.Round(Math.Clamp(samples[i] * gain * fade, -1, 1) * 32767));
        }
        w.Flush();
        return ms.ToArray();
    }

    private static void Note(double[] buffer, double start, double freq, double amp)
    {
        int s0 = (int)(start * SampleRate);
        for (int i = s0; i < buffer.Length; i++)
        {
            double t = (i - s0) / (double)SampleRate;
            double attack = Math.Min(1, t / 0.006);
            double env = attack * Math.Exp(-t / 0.28);
            double v = Math.Sin(2 * Math.PI * freq * t)
                + 0.22 * Math.Sin(2 * Math.PI * freq * 2 * t) * Math.Exp(-t / 0.12)
                + 0.06 * Math.Sin(2 * Math.PI * freq * 3.01 * t) * Math.Exp(-t / 0.06);
            buffer[i] += amp * env * v;
        }
    }
}
