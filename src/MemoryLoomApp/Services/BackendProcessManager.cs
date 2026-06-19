using System;
using System.Diagnostics;
using System.IO;

namespace MemoryLoomApp.Services;

public sealed class BackendProcessManager : IDisposable
{
    private const string BackendExecutableName = "backend.exe";

    private Process? _process;
    private bool _disposed;

    public bool IsRunning => _process is { HasExited: false };

    public void Start()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        if (IsRunning)
        {
            return;
        }

        var backendPath = ResolveBackendPath();
        if (!File.Exists(backendPath))
        {
            Trace.TraceWarning($"Memory Loom backend executable was not found: {backendPath}");
            return;
        }

        var workingDirectory = Path.GetDirectoryName(backendPath)
            ?? AppContext.BaseDirectory;

        var startInfo = new ProcessStartInfo
        {
            FileName = backendPath,
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };

        startInfo.Environment.TryAdd("MEMORYLOOM_BACKEND_HOST", "127.0.0.1");
        startInfo.Environment.TryAdd("MEMORYLOOM_BACKEND_PORT", "8765");

        var process = new Process
        {
            StartInfo = startInfo,
            EnableRaisingEvents = true
        };

        process.OutputDataReceived += (_, args) =>
        {
            if (!string.IsNullOrWhiteSpace(args.Data))
            {
                Trace.TraceInformation($"[backend] {args.Data}");
            }
        };

        process.ErrorDataReceived += (_, args) =>
        {
            if (!string.IsNullOrWhiteSpace(args.Data))
            {
                Trace.TraceError($"[backend] {args.Data}");
            }
        };

        process.Exited += (_, _) =>
        {
            Trace.TraceWarning("Memory Loom backend process exited.");
        };

        try
        {
            if (!process.Start())
            {
                process.Dispose();
                throw new InvalidOperationException("Process.Start returned false for backend.exe.");
            }

            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            _process = process;
        }
        catch
        {
            process.Dispose();
            throw;
        }
    }

    public void Stop()
    {
        var process = _process;
        if (process is null)
        {
            return;
        }

        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(5000);
            }
        }
        catch (InvalidOperationException)
        {
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Failed to terminate backend process: {ex}");
        }
        finally
        {
            process.Dispose();
            _process = null;
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        Stop();
        _disposed = true;
        GC.SuppressFinalize(this);
    }

    private static string ResolveBackendPath()
    {
        var configuredPath = Environment.GetEnvironmentVariable("MEMORYLOOM_BACKEND_PATH");
        if (!string.IsNullOrWhiteSpace(configuredPath))
        {
            return Path.GetFullPath(configuredPath);
        }

        var baseDirectory = AppContext.BaseDirectory;
        var candidates = new[]
        {
            Path.Combine(baseDirectory, BackendExecutableName),
            Path.Combine(baseDirectory, "backend", BackendExecutableName),
            Path.GetFullPath(Path.Combine(baseDirectory, "..", "..", "..", "..", "..", "backend", "dist", BackendExecutableName))
        };

        foreach (var candidate in candidates)
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        return candidates[0];
    }
}
