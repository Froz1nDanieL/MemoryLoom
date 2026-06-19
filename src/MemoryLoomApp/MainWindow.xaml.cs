using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;

namespace MemoryLoomApp;

public partial class MainWindow : Window
{
    private static readonly HttpClient BackendClient = new()
    {
        BaseAddress = new Uri("http://127.0.0.1:8765/")
    };

    public MainWindow()
    {
        InitializeComponent();
        Loaded += (_, _) => SearchBox.Focus();
    }

    private async void SearchBox_OnKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Close();
            return;
        }

        if (e.Key != Key.Enter)
        {
            return;
        }

        e.Handled = true;
        await SearchAsync();
    }

    private void SearchBox_OnTextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(SearchBox.Text))
        {
            ResultsList.ItemsSource = null;
            StatusText.Text = "Press Enter to search. Press Esc to close.";
        }
    }

    private async Task SearchAsync()
    {
        var query = SearchBox.Text.Trim();
        if (query.Length == 0)
        {
            return;
        }

        StatusText.Text = "Searching local memory...";

        try
        {
            using var response = await BackendClient.PostAsJsonAsync("search", new SearchRequest(query, 10));
            response.EnsureSuccessStatusCode();

            var payload = await response.Content.ReadFromJsonAsync<SearchResponse>();
            ResultsList.ItemsSource = payload?.Results ?? [];
            StatusText.Text = payload is null
                ? "No response from backend."
                : $"{payload.Results.Count} result(s) from {payload.Backend}.";
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Search request failed: {ex}");
            ResultsList.ItemsSource = null;
            StatusText.Text = "Backend is not available yet.";
        }
    }

    private sealed record SearchRequest(
        [property: JsonPropertyName("query")] string Query,
        [property: JsonPropertyName("top_k")] int TopK);

    private sealed record SearchResponse(
        [property: JsonPropertyName("query")] string Query,
        [property: JsonPropertyName("backend")] string Backend,
        [property: JsonPropertyName("results")] IReadOnlyList<SearchResult> Results);

    private sealed record SearchResult(
        [property: JsonPropertyName("id")] string Id,
        [property: JsonPropertyName("source")] string Source,
        [property: JsonPropertyName("content")] string Content,
        [property: JsonPropertyName("score")] double Score);
}
