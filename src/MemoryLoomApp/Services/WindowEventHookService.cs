using System;

namespace MemoryLoomApp.Services;

public sealed class WindowEventHookService : ICaptureService
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

    public void Dispose()
    {
        Stop();
    }

    private void OnForegroundWindowChanged(string title)
    {
        Captured?.Invoke(
            this,
            new CaptureEvent("window", title, DateTimeOffset.UtcNow));
    }
}
