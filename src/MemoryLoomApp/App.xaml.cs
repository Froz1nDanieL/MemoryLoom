using System;
using System.Diagnostics;
using System.Windows;
using MemoryLoomApp.Services;

namespace MemoryLoomApp;

public partial class App : Application
{
    private BackendProcessManager? _backendProcessManager;

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
    }

    protected override void OnExit(ExitEventArgs e)
    {
        try
        {
            _backendProcessManager?.Dispose();
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Failed to stop Memory Loom backend cleanly: {ex}");
        }
        finally
        {
            _backendProcessManager = null;
        }

        base.OnExit(e);
    }
}
