using System;

namespace MemoryLoomApp.Services;

public interface ICaptureService : IDisposable
{
    event EventHandler<CaptureEvent>? Captured;

    bool IsRunning { get; }

    void Start();

    void Stop();
}
