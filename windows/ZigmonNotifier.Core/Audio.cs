using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace ZigmonNotifier.Core;

/// <summary>One built-in alarm sound: a name and how one round of it is drawn.</summary>
public sealed record AlarmSound(string Id, string Name, string Note);

/// <summary>
/// The alarm sounds, drawn in memory (no files shipped, nothing fetched). Each renders
/// one round; the app repeats the round for as long as the user chose.
/// </summary>
public static class AlarmSounds
{
    public const int SampleRate = 44100;
    public const string DefaultId = "chime";
    /// <summary>The id that means "the user's own .wav file".</summary>
    public const string FileId = "file";

    public static readonly IReadOnlyList<AlarmSound> All = new[]
    {
        new AlarmSound("chime", "Chime", "two soft bell notes"),
        new AlarmSound("doorbell", "Doorbell", "ding-dong"),
        new AlarmSound("bell", "Bell", "a ringing bell"),
        new AlarmSound("beeps", "Beeps", "three short beeps"),
        new AlarmSound("pulse", "Pulse", "a calm low pulse"),
        new AlarmSound("alarm", "Alarm", "fast urgent beeping"),
        new AlarmSound("siren", "Siren", "a rising and falling siren"),
        new AlarmSound("klaxon", "Klaxon", "a harsh horn"),
    };

    public static bool IsKnown(string? id) => id is not null && All.Any(s => s.Id == id);

    public static AlarmSound Find(string? id) => All.FirstOrDefault(s => s.Id == id) ?? All[0];

    /// <summary>One round of the sound, peak 1.0, at <see cref="SampleRate"/>, mono.</summary>
    public static double[] Render(string? id)
    {
        double[] b;
        switch (Find(id).Id)
        {
            case "doorbell":
                b = new double[(int)(SampleRate * 1.9)];
                Bell(b, 0.00, 659.25, 1.0, 0.45);  // E5
                Bell(b, 0.55, 523.25, 1.0, 0.60);  // C5
                break;
            case "bell":
                b = new double[(int)(SampleRate * 1.6)];
                for (int i = 0; i < 4; i++) Bell(b, i * 0.18, 1318.5, 0.8, 0.35, inharmonic: true);
                break;
            case "beeps":
                b = new double[(int)(SampleRate * 1.2)];
                for (int i = 0; i < 3; i++) Tone(b, i * 0.2, 0.12, 1760, square: false);
                break;
            case "pulse":
                b = new double[(int)(SampleRate * 1.4)];
                Tone(b, 0.0, 0.45, 440, square: false, soft: true);
                break;
            case "alarm":
                b = new double[(int)(SampleRate * 1.0)];
                for (int i = 0; i < 5; i++) Tone(b, i * 0.2, 0.1, 2400, square: true);
                break;
            case "siren":
                b = new double[(int)(SampleRate * 2.0)];
                Sweep(b, 600, 1400);
                break;
            case "klaxon":
                b = new double[(int)(SampleRate * 1.3)];
                Tone(b, 0.0, 0.5, 220, square: true);
                Tone(b, 0.0, 0.5, 277, square: true);
                Tone(b, 0.65, 0.5, 220, square: true);
                Tone(b, 0.65, 0.5, 277, square: true);
                break;
            default:
                b = new double[(int)(SampleRate * 1.05)];
                Bell(b, 0.00, 1046.50, 0.55, 0.28); // C6
                Bell(b, 0.13, 1567.98, 0.45, 0.28); // G6
                break;
        }
        Normalize(b);
        return b;
    }

    private static void Bell(double[] buf, double start, double freq, double amp, double decay, bool inharmonic = false)
    {
        int s0 = (int)(start * SampleRate);
        for (int i = s0; i < buf.Length; i++)
        {
            double t = (i - s0) / (double)SampleRate;
            double env = Math.Min(1, t / 0.006) * Math.Exp(-t / decay);
            double v = Math.Sin(2 * Math.PI * freq * t)
                + 0.22 * Math.Sin(2 * Math.PI * freq * 2 * t) * Math.Exp(-t / (decay * 0.45))
                + (inharmonic ? 0.3 * Math.Sin(2 * Math.PI * freq * 2.76 * t) * Math.Exp(-t / (decay * 0.3)) : 0.06 * Math.Sin(2 * Math.PI * freq * 3.01 * t) * Math.Exp(-t / 0.06));
            buf[i] += amp * env * v;
        }
    }

    private static void Tone(double[] buf, double start, double length, double freq, bool square, bool soft = false)
    {
        int s0 = (int)(start * SampleRate), n = (int)(length * SampleRate);
        double edge = soft ? length / 2 : 0.004;
        for (int k = 0; k < n && s0 + k < buf.Length; k++)
        {
            double t = k / (double)SampleRate;
            double env = Math.Min(1, Math.Min(t, length - t) / edge);
            double v = Math.Sin(2 * Math.PI * freq * t);
            if (square) v = Math.Tanh(4 * v); // a square with its corners rounded: loud but not shrill
            buf[s0 + k] += env * v;
        }
    }

    private static void Sweep(double[] buf, double low, double high)
    {
        double phase = 0;
        for (int i = 0; i < buf.Length; i++)
        {
            double x = i / (double)buf.Length;               // 0..1 over the round
            double f = low + (high - low) * (1 - Math.Cos(2 * Math.PI * x)) / 2;
            phase += 2 * Math.PI * f / SampleRate;
            double edge = Math.Min(1, Math.Min(i, buf.Length - i) / (0.01 * SampleRate));
            buf[i] = edge * Math.Tanh(2 * Math.Sin(phase));
        }
    }

    private static void Normalize(double[] b)
    {
        double peak = 0;
        foreach (double s in b) peak = Math.Max(peak, Math.Abs(s));
        if (peak <= 0) return;
        for (int i = 0; i < b.Length; i++) b[i] /= peak;
        int fade = Math.Min(b.Length, SampleRate / 50); // last 20 ms: no click when it repeats
        for (int k = 0; k < fade; k++) b[b.Length - 1 - k] *= k / (double)fade;
    }
}

/// <summary>Builds and checks the WAV bytes the app plays (16-bit PCM), with the volume applied.</summary>
public static class WavAudio
{
    public const long MaxFileBytes = 20L * 1024 * 1024;
    /// <summary>The loudest the app plays (a little under full scale).</summary>
    private const double Headroom = 0.89;

    /// <summary>Volume 0..100 as a gain: squared, so the slider feels even to the ear.</summary>
    public static double Gain(int volume)
    {
        double v = Math.Clamp(volume, 0, 100) / 100.0;
        return v * v;
    }

    /// <summary>Mono samples (peak 1) to a 16-bit WAV at that volume.</summary>
    public static byte[] Encode(double[] samples, int sampleRate, int volume)
    {
        double g = Gain(volume) * Headroom;
        var pcm = new short[samples.Length];
        for (int i = 0; i < samples.Length; i++) pcm[i] = (short)Math.Round(Math.Clamp(samples[i] * g, -1, 1) * 32767);
        return Write(pcm, sampleRate, 1);
    }

    /// <summary>The built-in sound at that volume.</summary>
    public static byte[] Builtin(string? id, int volume) => Encode(AlarmSounds.Render(id), AlarmSounds.SampleRate, volume);

    /// <summary>
    /// A user's .wav file (PCM 8/16/24/32-bit or 32-bit float, 1-8 channels) re-written as 16-bit
    /// PCM at that volume. Returns null with a reason for anything else; never throws on bad bytes.
    /// </summary>
    public static byte[]? FromFile(byte[] file, int volume, out string reason)
    {
        reason = "";
        try
        {
            return Parse(file, volume, out reason);
        }
        catch (Exception e) when (e is EndOfStreamException or ArgumentException or OverflowException or IOException)
        {
            reason = "The file is damaged.";
            return null;
        }
    }

    private static byte[]? Parse(byte[] file, int volume, out string reason)
    {
        reason = "";
        if (file.Length > MaxFileBytes) { reason = "The file is larger than 20 MB."; return null; }
        if (file.Length < 44 || Encoding.ASCII.GetString(file, 0, 4) != "RIFF" || Encoding.ASCII.GetString(file, 8, 4) != "WAVE")
        {
            reason = "This is not a WAV file.";
            return null;
        }
        int pos = 12, format = 0, channels = 0, rate = 0, bits = 0;
        int dataAt = -1, dataLen = 0;
        while (pos + 8 <= file.Length)
        {
            string id = Encoding.ASCII.GetString(file, pos, 4);
            long len = BitConverter.ToUInt32(file, pos + 4);
            int body = pos + 8;
            if (len > file.Length - body) len = file.Length - body; // a truncated last chunk: take what is there
            if (id == "fmt " && len >= 16)
            {
                format = BitConverter.ToUInt16(file, body);
                channels = BitConverter.ToUInt16(file, body + 2);
                rate = BitConverter.ToInt32(file, body + 4);
                bits = BitConverter.ToUInt16(file, body + 14);
                if (format == 0xFFFE && len >= 40) format = BitConverter.ToUInt16(file, body + 24); // WAVE_FORMAT_EXTENSIBLE
            }
            else if (id == "data")
            {
                dataAt = body;
                dataLen = (int)len;
            }
            pos = body + (int)len + (int)(len & 1);
        }
        bool pcm = format == 1 && bits is 8 or 16 or 24 or 32;
        bool fl = format == 3 && bits == 32;
        if (!pcm && !fl) { reason = "Only uncompressed WAV files can be played."; return null; }
        if (channels is < 1 or > 8 || rate is < 4000 or > 192000) { reason = "The file's format is not supported."; return null; }
        if (dataAt < 0) { reason = "The file has no sound in it."; return null; }
        int frameBytes = channels * (bits / 8);
        int frames = dataLen / frameBytes;
        if (frames == 0) { reason = "The file has no sound in it."; return null; }

        double g = Gain(volume);
        var pcm16 = new short[frames * channels];
        for (int i = 0; i < pcm16.Length; i++)
        {
            int at = dataAt + i * (bits / 8);
            double v = bits switch
            {
                8 => (file[at] - 128) / 128.0,
                16 => BitConverter.ToInt16(file, at) / 32768.0,
                24 => ((file[at] | file[at + 1] << 8 | (sbyte)file[at + 2] << 16)) / 8388608.0,
                _ when fl => BitConverter.ToSingle(file, at),
                _ => BitConverter.ToInt32(file, at) / 2147483648.0,
            };
            if (double.IsNaN(v)) v = 0;
            pcm16[i] = (short)Math.Round(Math.Clamp(v * g, -1, 1) * 32767);
        }
        return Write(pcm16, rate, channels);
    }

    private static byte[] Write(short[] pcm, int rate, int channels)
    {
        using var ms = new MemoryStream(44 + pcm.Length * 2);
        using var w = new BinaryWriter(ms, Encoding.ASCII);
        int dataBytes = pcm.Length * 2;
        w.Write(Encoding.ASCII.GetBytes("RIFF")); w.Write(36 + dataBytes);
        w.Write(Encoding.ASCII.GetBytes("WAVE"));
        w.Write(Encoding.ASCII.GetBytes("fmt ")); w.Write(16);
        w.Write((ushort)1); w.Write((ushort)channels); w.Write(rate); w.Write(rate * channels * 2);
        w.Write((ushort)(channels * 2)); w.Write((ushort)16);
        w.Write(Encoding.ASCII.GetBytes("data")); w.Write(dataBytes);
        foreach (short s in pcm) w.Write(s);
        w.Flush();
        return ms.ToArray();
    }

    /// <summary>The loudest sample of a 16-bit WAV this class wrote (for tests and the meter).</summary>
    public static int Peak(byte[] wav)
    {
        int peak = 0;
        for (int i = 44; i + 1 < wav.Length; i += 2) peak = Math.Max(peak, Math.Abs((int)BitConverter.ToInt16(wav, i)));
        return peak;
    }
}

/// <summary>The choices the Alert settings window offers, and how each is said.</summary>
public static class AlertChoices
{
    public const int Once = 0;
    public const int UntilDismissed = -1;
    public const string MonitorPrimary = "primary";
    public const string MonitorCursor = "cursor";

    /// <summary>How long the sound plays, in seconds (0 once, -1 until the alert is dismissed).</summary>
    public static readonly int[] SoundLengths = { Once, 5, 15, 30, 60, 300, UntilDismissed };
    /// <summary>When an alert closes by itself, in seconds (0 never).</summary>
    public static readonly int[] CloseAfter = { 0, 10, 30, 60, 300, 900 };
    /// <summary>Even "until dismissed" stops after this long, so a forgotten alarm does not ring all night.</summary>
    public static readonly TimeSpan LongestSound = TimeSpan.FromMinutes(30);

    public static string SoundLengthText(int s) => s switch
    {
        Once => "Once",
        UntilDismissed => "Until dismissed",
        _ => Seconds(s),
    };

    public static string CloseAfterText(int s) => s == 0 ? "Never" : Seconds(s);

    private static string Seconds(int s) => s % 60 == 0 ? s / 60 + " min" : s + " s";

    /// <summary>The nearest offered value at or above the one given (for old or hand-edited settings).</summary>
    public static int Snap(int value, int[] allowed, int fallback)
    {
        if (allowed.Contains(value)) return value;
        if (value < 0) return fallback;
        foreach (int a in allowed.Where(a => a >= 0).OrderBy(a => a)) if (a >= value) return a;
        return allowed.Where(a => a >= 0).Max();
    }
}
