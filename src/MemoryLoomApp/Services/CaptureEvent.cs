using System;
using System.Collections.Generic;

namespace MemoryLoomApp.Services;

public sealed record CaptureEvent(
    string Source,
    string Content,
    DateTimeOffset CapturedAt,
    IReadOnlyDictionary<string, string>? Metadata = null);
