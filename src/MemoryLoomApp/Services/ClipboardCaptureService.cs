using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Windows;
using System.Windows.Interop;

namespace MemoryLoomApp.Services;

public sealed class ClipboardCaptureService : ICaptureService
{
    private const int WmClipboardUpdate = 0x031D;
    private const int MaxCapturedCharacters = 20_000;

    private HwndSource? _hwndSource;
    private IntPtr _windowHandle;
    private string? _lastContentHash;

    public event EventHandler<CaptureEvent>? Captured;

    public bool IsRunning { get; private set; }

    public void Start()
    {
        if (IsRunning)
        {
            return;
        }

        var mainWindow = Application.Current.MainWindow;
        if (mainWindow is null)
        {
            Trace.TraceWarning("Clipboard capture cannot start because MainWindow is not ready.");
            return;
        }

        _windowHandle = new WindowInteropHelper(mainWindow).Handle;
        if (_windowHandle == IntPtr.Zero)
        {
            Trace.TraceWarning("Clipboard capture cannot start because MainWindow handle is not ready.");
            return;
        }

        _hwndSource = HwndSource.FromHwnd(_windowHandle);
        if (_hwndSource is null)
        {
            Trace.TraceWarning("Clipboard capture cannot start because HwndSource is not available.");
            return;
        }

        _hwndSource.AddHook(WndProc);

        if (!AddClipboardFormatListener(_windowHandle))
        {
            var error = Marshal.GetLastWin32Error();
            _hwndSource.RemoveHook(WndProc);
            _hwndSource = null;
            _windowHandle = IntPtr.Zero;
            Trace.TraceError($"AddClipboardFormatListener failed. Win32Error={error}");
            return;
        }

        IsRunning = true;
        TryCaptureClipboardText();
    }

    public void Stop()
    {
        if (!IsRunning)
        {
            return;
        }

        if (_windowHandle != IntPtr.Zero)
        {
            RemoveClipboardFormatListener(_windowHandle);
        }

        _hwndSource?.RemoveHook(WndProc);
        _hwndSource = null;
        _windowHandle = IntPtr.Zero;
        IsRunning = false;
    }

    public void PollOnce()
    {
        if (!IsRunning)
        {
            return;
        }

        TryCaptureClipboardText();
    }

    public void Dispose()
    {
        Stop();
    }

    private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == WmClipboardUpdate && IsRunning)
        {
            TryCaptureClipboardText();
            handled = false;
        }

        return IntPtr.Zero;
    }

    private void TryCaptureClipboardText()
    {
        try
        {
            if (!Clipboard.ContainsText(TextDataFormat.UnicodeText))
            {
                return;
            }

            var text = Clipboard.GetText(TextDataFormat.UnicodeText).Trim();
            if (string.IsNullOrWhiteSpace(text))
            {
                return;
            }

            var originalLength = text.Length;
            var truncated = false;
            if (text.Length > MaxCapturedCharacters)
            {
                text = text[..MaxCapturedCharacters];
                truncated = true;
            }

            var hash = ComputeHash(text);
            if (string.Equals(hash, _lastContentHash, StringComparison.Ordinal))
            {
                return;
            }

            _lastContentHash = hash;

            var foregroundWindow = ForegroundWindowInfo.Capture();
            var metadata = new Dictionary<string, string>
            {
                ["format"] = "unicode-text",
                ["content_hash"] = hash,
                ["original_length"] = originalLength.ToString()
            };

            if (truncated)
            {
                metadata["truncated"] = "true";
                metadata["captured_length"] = text.Length.ToString();
            }

            Captured?.Invoke(
                this,
                new CaptureEvent(
                    Source: "clipboard",
                    Content: text,
                    CapturedAt: DateTimeOffset.UtcNow,
                    Metadata: metadata,
                    AppName: foregroundWindow.ProcessName,
                    WindowTitle: foregroundWindow.Title,
                    ProcessName: foregroundWindow.ProcessName));
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Clipboard capture failed: {ex}");
        }
    }

    private static string ComputeHash(string content)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(content));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AddClipboardFormatListener(IntPtr hwnd);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool RemoveClipboardFormatListener(IntPtr hwnd);

    private sealed record ForegroundWindowInfo(string? Title, string? ProcessName)
    {
        private const int MaxTitleLength = 512;

        public static ForegroundWindowInfo Capture()
        {
            try
            {
                var hwnd = GetForegroundWindow();
                if (hwnd == IntPtr.Zero)
                {
                    return new ForegroundWindowInfo(null, null);
                }

                var titleBuilder = new StringBuilder(MaxTitleLength);
                _ = GetWindowText(hwnd, titleBuilder, titleBuilder.Capacity);

                _ = GetWindowThreadProcessId(hwnd, out var processId);
                string? processName = null;
                try
                {
                    using var process = Process.GetProcessById((int)processId);
                    processName = process.ProcessName;
                }
                catch (Exception ex)
                {
                    Trace.TraceWarning($"Failed to resolve foreground process name: {ex.Message}");
                }

                return new ForegroundWindowInfo(
                    string.IsNullOrWhiteSpace(titleBuilder.ToString()) ? null : titleBuilder.ToString(),
                    processName);
            }
            catch (Exception ex)
            {
                Trace.TraceWarning($"Failed to capture foreground window info: {ex.Message}");
                return new ForegroundWindowInfo(null, null);
            }
        }

        [DllImport("user32.dll")]
        private static extern IntPtr GetForegroundWindow();

        [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    }
}
