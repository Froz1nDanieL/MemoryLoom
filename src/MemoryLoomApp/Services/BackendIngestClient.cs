using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace MemoryLoomApp.Services;

public sealed class BackendIngestClient : IDisposable
{
    private static readonly TimeSpan DefaultTimeout = TimeSpan.FromSeconds(8);

    private readonly HttpClient _httpClient;
    private bool _disposed;

    public BackendIngestClient()
        : this(CreateDefaultHttpClient())
    {
    }

    public BackendIngestClient(HttpClient httpClient)
    {
        _httpClient = httpClient;
    }

    public async Task IngestAsync(CaptureEvent captureEvent, CancellationToken cancellationToken)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        var request = new IngestRequest(
            Source: captureEvent.Source,
            Content: captureEvent.Content,
            AppName: captureEvent.AppName,
            WindowTitle: captureEvent.WindowTitle,
            ProcessName: captureEvent.ProcessName,
            Timezone: TimeZoneInfo.Local.Id,
            CapturedAt: captureEvent.CapturedAt,
            Metadata: captureEvent.Metadata ?? new Dictionary<string, string>());

        using var response = await _httpClient.PostAsJsonAsync(
            "ingest",
            request,
            cancellationToken);

        response.EnsureSuccessStatusCode();
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _httpClient.Dispose();
        _disposed = true;
    }

    private static HttpClient CreateDefaultHttpClient()
    {
        var configuredUrl = Environment.GetEnvironmentVariable("MEMORYLOOM_BACKEND_URL");
        var baseAddress = string.IsNullOrWhiteSpace(configuredUrl)
            ? new Uri("http://127.0.0.1:8765/")
            : new Uri(configuredUrl, UriKind.Absolute);

        return new HttpClient
        {
            BaseAddress = baseAddress,
            Timeout = DefaultTimeout
        };
    }

    private sealed record IngestRequest(
        [property: JsonPropertyName("source")] string Source,
        [property: JsonPropertyName("content")] string Content,
        [property: JsonPropertyName("app_name")] string? AppName,
        [property: JsonPropertyName("window_title")] string? WindowTitle,
        [property: JsonPropertyName("process_name")] string? ProcessName,
        [property: JsonPropertyName("timezone")] string Timezone,
        [property: JsonPropertyName("captured_at")] DateTimeOffset CapturedAt,
        [property: JsonPropertyName("metadata")] IReadOnlyDictionary<string, string> Metadata);
}
