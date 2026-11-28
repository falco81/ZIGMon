using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace ZigmonNotifier;

/// <summary>The few Win32 calls WPF has no word for.</summary>
internal static class Native
{
    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X; public int Y; }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct MONITORINFO
    {
        public int cbSize;
        public RECT rcMonitor;
        public RECT rcWork;
        public uint dwFlags;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct MONITORINFOEX
    {
        public int cbSize;
        public RECT rcMonitor;
        public RECT rcWork;
        public uint dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        public string szDevice;
    }

    private delegate bool MonitorEnumProc(IntPtr monitor, IntPtr hdc, IntPtr rect, IntPtr data);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorEnumProc proc, IntPtr data);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetMonitorInfoW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetMonitorInfoEx(IntPtr monitor, ref MONITORINFOEX info);

    private const uint MONITORINFOF_PRIMARY = 1;

    [StructLayout(LayoutKind.Sequential)]
    private struct FLASHWINFO
    {
        public uint cbSize;
        public IntPtr hwnd;
        public uint dwFlags;
        public uint uCount;
        public uint dwTimeout;
    }

    private const uint MONITOR_DEFAULTTONEAREST = 2;
    private const int MDT_EFFECTIVE_DPI = 0;
    private const uint SWP_NOSIZE = 0x0001, SWP_NOZORDER = 0x0004, SWP_NOACTIVATE = 0x0010;
    private const uint FLASHW_TRAY = 0x2, FLASHW_TIMERNOFG = 0xC;
    private const int GWL_EXSTYLE = -20;
    private const long WS_EX_TOOLWINDOW = 0x80, WS_EX_APPWINDOW = 0x40000;
    private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19;
    private const int DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWA_BORDER_COLOR = 34, DWMWA_CAPTION_COLOR = 35, DWMWA_TEXT_COLOR = 36;

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetCursorPos(out POINT point);

    [DllImport("user32.dll")]
    private static extern IntPtr MonitorFromPoint(POINT pt, uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);

    [DllImport("shcore.dll")]
    private static extern int GetDpiForMonitor(IntPtr monitor, int type, out uint dpiX, out uint dpiY);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int cx, int cy, uint flags);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool FlashWindowEx(ref FLASHWINFO info);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetForegroundWindow(IntPtr hwnd);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    private static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr value);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    public static POINT CursorPosition()
    {
        return GetCursorPos(out var p) ? p : new POINT();
    }

    /// <summary>The work area (screen minus taskbar) of the monitor at a point, in pixels, and that monitor's scale.</summary>
    public static (RECT Work, double Scale) WorkAreaAt(POINT pt)
    {
        IntPtr mon = MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST);
        var info = new MONITORINFO { cbSize = Marshal.SizeOf<MONITORINFO>() };
        RECT work = GetMonitorInfo(mon, ref info)
            ? info.rcWork
            : new RECT { Left = 0, Top = 0, Right = (int)SystemParameters.PrimaryScreenWidth, Bottom = (int)SystemParameters.PrimaryScreenHeight };
        double scale = 1;
        try
        {
            if (GetDpiForMonitor(mon, MDT_EFFECTIVE_DPI, out uint dx, out _) == 0 && dx > 0) scale = dx / 96.0;
        }
        catch (Exception)
        {
            // shcore missing (very old Windows): stay at 100 %
        }
        return (work, scale);
    }

    /// <summary>Every monitor now connected: device name, bounds and work area in pixels, scale.</summary>
    public static System.Collections.Generic.List<Core.MonitorInfo> Monitors()
    {
        var list = new System.Collections.Generic.List<Core.MonitorInfo>();
        try
        {
            EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (mon, _, _, _) =>
            {
                var info = new MONITORINFOEX { cbSize = Marshal.SizeOf<MONITORINFOEX>(), szDevice = "" };
                if (GetMonitorInfoEx(mon, ref info))
                {
                    double scale = 1;
                    try
                    {
                        if (GetDpiForMonitor(mon, MDT_EFFECTIVE_DPI, out uint dx, out _) == 0 && dx > 0) scale = dx / 96.0;
                    }
                    catch (Exception)
                    {
                        // 100 %
                    }
                    list.Add(new Core.MonitorInfo(info.szDevice ?? "",
                        new Core.PixelRect(info.rcMonitor.Left, info.rcMonitor.Top, info.rcMonitor.Right, info.rcMonitor.Bottom),
                        new Core.PixelRect(info.rcWork.Left, info.rcWork.Top, info.rcWork.Right, info.rcWork.Bottom),
                        (info.dwFlags & MONITORINFOF_PRIMARY) != 0, scale));
                }
                return true;
            }, IntPtr.Zero);
        }
        catch (Exception)
        {
            // no list: the caller falls back to the primary work area
        }
        return list;
    }

    public static void MoveWindow(Window w, int x, int y)
    {
        IntPtr h = new WindowInteropHelper(w).Handle;
        if (h != IntPtr.Zero) SetWindowPos(h, IntPtr.Zero, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
    }

    /// <summary>Flashes the taskbar button until the window is looked at.</summary>
    public static void Flash(Window w)
    {
        IntPtr h = new WindowInteropHelper(w).Handle;
        if (h == IntPtr.Zero) return;
        var fi = new FLASHWINFO
        {
            cbSize = (uint)Marshal.SizeOf<FLASHWINFO>(),
            hwnd = h,
            dwFlags = FLASHW_TRAY | FLASHW_TIMERNOFG,
            uCount = 0,
            dwTimeout = 0,
        };
        FlashWindowEx(ref fi);
    }

    /// <summary>Keeps a popup out of Alt+Tab and the taskbar.</summary>
    public static void MakeToolWindow(Window w)
    {
        IntPtr h = new WindowInteropHelper(w).Handle;
        if (h == IntPtr.Zero) return;
        long ex = GetWindowLongPtr(h, GWL_EXSTYLE).ToInt64();
        ex = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW;
        SetWindowLongPtr(h, GWL_EXSTYLE, new IntPtr(ex));
    }

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd, IntPtr processId);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, [MarshalAs(UnmanagedType.Bool)] bool attach);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool BringWindowToTop(IntPtr hwnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ShowWindow(IntPtr hwnd, int cmd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsIconic(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);

    private const int SW_RESTORE = 9, SW_SHOW = 5;
    private const byte VK_MENU = 0x12;
    private const uint KEYEVENTF_KEYUP = 0x2;

    /// <summary>
    /// Brings a window to the front and gives it the keyboard, past Windows' foreground lock
    /// (a Stream Deck press is not this app's input, so a plain SetForegroundWindow only
    /// flashes the taskbar button): the input of the window in front is joined for a moment,
    /// so this thread may take it over; if Windows still says no, an Alt tap (which counts
    /// as fresh input) and once more. Returns whether the window is now in front.
    /// </summary>
    public static bool ForceForeground(Window w)
    {
        IntPtr h = new WindowInteropHelper(w).Handle;
        if (h == IntPtr.Zero) return false;
        try
        {
            if (IsIconic(h)) ShowWindow(h, SW_RESTORE);
            else ShowWindow(h, SW_SHOW);
            IntPtr front = GetForegroundWindow();
            if (front == h) return true;
            uint mine = GetCurrentThreadId();
            uint theirs = front == IntPtr.Zero ? 0 : GetWindowThreadProcessId(front, IntPtr.Zero);
            bool joined = theirs != 0 && theirs != mine && AttachThreadInput(mine, theirs, true);
            try
            {
                BringWindowToTop(h);
                SetForegroundWindow(h);
            }
            finally
            {
                if (joined) AttachThreadInput(mine, theirs, false);
            }
            if (GetForegroundWindow() != h)
            {
                keybd_event(VK_MENU, 0, 0, UIntPtr.Zero);
                keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
                SetForegroundWindow(h);
            }
            return GetForegroundWindow() == h;
        }
        catch (Exception)
        {
            return false; // the window is still shown, on top; the taskbar button flashes
        }
    }

    /// <summary>A dark title bar in ZIGMon's colours (Windows 10 20H1+ dark mode; Windows 11 colours and round corners).</summary>
    public static void DarkTitleBar(Window w)
    {
        IntPtr h = new WindowInteropHelper(w).Handle;
        if (h == IntPtr.Zero) return;
        try
        {
            int on = 1;
            if (DwmSetWindowAttribute(h, DWMWA_USE_IMMERSIVE_DARK_MODE, ref on, sizeof(int)) != 0)
                DwmSetWindowAttribute(h, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, ref on, sizeof(int));
            int caption = 0x22 << 16 | 0x1B << 8 | 0x16; // COLORREF 0x00BBGGRR of #161B22
            DwmSetWindowAttribute(h, DWMWA_CAPTION_COLOR, ref caption, sizeof(int));
            int border = 0x37 << 16 | 0x2C << 8 | 0x26; // #262C37
            DwmSetWindowAttribute(h, DWMWA_BORDER_COLOR, ref border, sizeof(int));
            int text = 0xEF << 16 | 0xE9 << 8 | 0xE6; // #E6E9EF
            DwmSetWindowAttribute(h, DWMWA_TEXT_COLOR, ref text, sizeof(int));
            int round = 2; // DWMWCP_ROUND
            DwmSetWindowAttribute(h, DWMWA_WINDOW_CORNER_PREFERENCE, ref round, sizeof(int));
        }
        catch (Exception)
        {
            // dwmapi without these attributes: the ordinary title bar stays
        }
    }
}
