using System;
using System.Diagnostics;
using System.Windows;
using MemoryLoomApp.Services;

namespace MemoryLoomApp;

public partial class App : Application
{
    private BackendProcessManager? _backendProcessManager;
    private BackendIngestClient? _backendIngestClient;
    private CaptureIngestPipeline? _capturePipeline;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        _backendProcessManager = new BackendProcessManager();

        try
        {
            _backendProcessManager.Start();
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Failed to start Memory Loom backend: {ex}");
        }

        MainWindow = new MainWindow();
        MainWindow.Show();

        try
        {
            _backendIngestClient = new BackendIngestClient();
            _capturePipeline = new CaptureIngestPipeline(
                _backendIngestClient,
                [new ClipboardCaptureService()]);
            _capturePipeline.Start();
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Failed to start capture pipeline: {ex}");
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        try
        {
            _capturePipeline?.Dispose();
            _backendIngestClient?.Dispose();
            _backendProcessManager?.Dispose();
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Failed to stop Memory Loom services cleanly: {ex}");
        }
        finally
        {
            _capturePipeline = null;
            _backendIngestClient = null;
            _backendProcessManager = null;
        }

        base.OnExit(e);
    }
}
