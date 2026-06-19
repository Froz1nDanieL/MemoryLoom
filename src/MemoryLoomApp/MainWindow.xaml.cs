using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;

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
        Loaded += (_, _) =>
        {
            UpdatePlaceholderVisibility();
            SearchBox.Focus();
        };
    }

    private void Window_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        SearchBox.Focus();
    }

    private void DialogChrome_OnMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        SearchBox.Focus();
        e.Handled = true;
    }

    private void SearchBox_OnGotKeyboardFocus(object sender, KeyboardFocusChangedEventArgs e)
    {
        AnimateDialogFocusState(isFocused: true);
    }

    private void SearchBox_OnLostKeyboardFocus(object sender, KeyboardFocusChangedEventArgs e)
    {
        AnimateDialogFocusState(isFocused: false);
    }

    private async void SearchButton_OnClick(object sender, RoutedEventArgs e)
    {
        if (!SearchButton.IsEnabled)
        {
            return;
        }

        await SearchAsync();
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
        UpdatePlaceholderVisibility();

        if (string.IsNullOrWhiteSpace(SearchBox.Text))
        {
            ResultsList.ItemsSource = null;
            HideResultsPanel();
        }
    }

    private void UpdatePlaceholderVisibility()
    {
        var hasText = !string.IsNullOrWhiteSpace(SearchBox.Text);
        SearchPlaceholder.Visibility = string.IsNullOrEmpty(SearchBox.Text)
            ? Visibility.Visible
            : Visibility.Collapsed;
        SearchButton.IsEnabled = hasText;
    }

    private async Task SearchAsync()
    {
        var query = SearchBox.Text.Trim();
        if (query.Length == 0)
        {
            return;
        }

        ResultsList.ItemsSource = new[]
        {
            new SearchResult("status", string.Empty, "Searching local memory...", 0)
        };
        ShowResultsPanel();

        try
        {
            using var response = await BackendClient.PostAsJsonAsync("search", new SearchRequest(query, 10));
            response.EnsureSuccessStatusCode();

            var payload = await response.Content.ReadFromJsonAsync<SearchResponse>();
            ResultsList.ItemsSource = payload?.Results.Count > 0
                ? payload.Results
                : new[]
                {
                    new SearchResult("empty", string.Empty, "No matching memory found.", 0)
                };
        }
        catch (Exception ex)
        {
            Trace.TraceError($"Search request failed: {ex}");
            ResultsList.ItemsSource = new[]
            {
                new SearchResult("error", string.Empty, "Backend is not available yet.", 0)
            };
            ShowResultsPanel();
        }
    }

    private void AnimateDialogFocusState(bool isFocused)
    {
        DialogLeftStop.BeginAnimation(
            GradientStop.ColorProperty,
            CreateColorAnimation(isFocused
                ? Color.FromRgb(0x06, 0x27, 0x2D)
                : Color.FromRgb(0x06, 0x27, 0x2D), 520));

        DialogMiddleStop.BeginAnimation(
            GradientStop.ColorProperty,
            CreateColorAnimation(isFocused
                ? Color.FromRgb(0x06, 0x27, 0x2D)
                : Color.FromRgb(0x06, 0x27, 0x2D), 560));

        DialogRightStop.BeginAnimation(
            GradientStop.ColorProperty,
            CreateColorAnimation(isFocused
                ? Color.FromRgb(0x08, 0x45, 0x36)
                : Color.FromRgb(0x06, 0x27, 0x2D), 620));
    }

    private void ShowResultsPanel()
    {
        ResultsPanel.Visibility = Visibility.Visible;
        ResultsPanel.BeginAnimation(OpacityProperty, CreateDoubleAnimation(1, 320));

        if (ResultsPanel.RenderTransform is TranslateTransform translate)
        {
            translate.BeginAnimation(TranslateTransform.XProperty, CreateDoubleAnimation(0, 420));
        }
    }

    private void HideResultsPanel()
    {
        var fade = CreateDoubleAnimation(0, 220);
        fade.Completed += (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(SearchBox.Text))
            {
                ResultsPanel.Visibility = Visibility.Collapsed;
            }
        };
        ResultsPanel.BeginAnimation(OpacityProperty, fade);

        if (ResultsPanel.RenderTransform is TranslateTransform translate)
        {
            translate.BeginAnimation(TranslateTransform.XProperty, CreateDoubleAnimation(34, 260));
        }
    }

    private static DoubleAnimation CreateDoubleAnimation(double to, int milliseconds)
    {
        return new DoubleAnimation
        {
            To = to,
            Duration = TimeSpan.FromMilliseconds(milliseconds),
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
        };
    }

    private static ColorAnimation CreateColorAnimation(Color to, int milliseconds)
    {
        return new ColorAnimation
        {
            To = to,
            Duration = TimeSpan.FromMilliseconds(milliseconds),
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
        };
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
