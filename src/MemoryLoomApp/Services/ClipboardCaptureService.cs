using System;
using System.Diagnostics;
using System.Windows;

namespace MemoryLoomApp.Services;

public sealed class ClipboardCaptureService : ICaptureService
{
    public event EventHandler<CaptureEvent>? Captured;

    public bool IsRunning { get; private set; }

    public void Start()
    {
        IsRunning = true;
    }

    public void Stop()
    {
        IsRunning = false;
    }

    public void PollOnce()
    {
        if (!IsRunning)
        {
            return;
        }

        try
        {
            if (Clipboard.ContainsText())
            {
                Captured?.Invoke(
                    this,
                    new CaptureEvent("clipboard", Clipboard.GetText(), DateTimeOffset.UtcNow));
            }
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Clipboard capture failed: {ex}");
        }
    }

    public void Dispose()
    {
        Stop();
    }
}
