using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;

namespace MemoryLoomApp.Services;

public sealed class CaptureIngestPipeline : IDisposable
{
    private readonly BackendIngestClient _backendClient;
    private readonly IReadOnlyList<ICaptureService> _captureServices;
    private readonly CancellationTokenSource _cancellation = new();
    private readonly SemaphoreSlim _sendGate = new(1, 1);
    private bool _disposed;
    private bool _started;

    public CaptureIngestPipeline(
        BackendIngestClient backendClient,
        IReadOnlyList<ICaptureService> captureServices)
    {
        _backendClient = backendClient;
        _captureServices = captureServices;
    }

    public void Start()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (_started)
        {
            return;
        }

        foreach (var service in _captureServices)
        {
            service.Captured += OnCaptured;
            service.Start();
        }

        _started = true;
    }

    public void Stop()
    {
        if (!_started)
        {
            return;
        }

        _cancellation.Cancel();

        foreach (var service in _captureServices)
        {
            service.Captured -= OnCaptured;
            service.Stop();
        }

        _started = false;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        Stop();

        foreach (var service in _captureServices)
        {
            service.Dispose();
        }

        _sendGate.Dispose();
        _cancellation.Dispose();
        _disposed = true;
    }

    private void OnCaptured(object? sender, CaptureEvent captureEvent)
    {
        if (string.IsNullOrWhiteSpace(captureEvent.Content))
        {
            return;
        }

        _ = IngestCapturedEventAsync(captureEvent);
    }

    private async Task IngestCapturedEventAsync(CaptureEvent captureEvent)
    {
        try
        {
            await _sendGate.WaitAsync(_cancellation.Token);
            try
            {
                await _backendClient.IngestAsync(captureEvent, _cancellation.Token);
                Trace.TraceInformation(
                    $"Captured {captureEvent.Source} event sent to backend. Length={captureEvent.Content.Length}");
            }
            finally
            {
                _sendGate.Release();
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Failed to ingest captured {captureEvent.Source} event: {ex}");
        }
    }
}
