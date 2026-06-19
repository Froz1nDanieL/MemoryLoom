using System;

namespace MemoryLoomApp.Services;

public sealed class UiAutomationCaptureService : ICaptureService
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

    private void OnAddressOrChatTextCaptured(string source, string content)
    {
        Captured?.Invoke(
            this,
            new CaptureEvent(source, content, DateTimeOffset.UtcNow));
    }
}
