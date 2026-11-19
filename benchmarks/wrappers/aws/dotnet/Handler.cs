// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

// The benchmark must define Benchmark.Function with JsonObject Handler(JsonObject input).

using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using Amazon.Lambda.Core;

namespace ServerlessBench;

public class Handler
{
    private const string ColdStartMarker = "/tmp/cold_run";

    // Skip HTML-safe escaping, matching the other wrappers' output.
    private static readonly JsonSerializerOptions JsonOptions =
        new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    public Stream HandleRequest(Stream input, ILambdaContext context)
    {
        JsonObject evt = ParseEvent(input);

        DateTimeOffset begin = DateTimeOffset.UtcNow;
        JsonObject result = new Benchmark.Function().Handler(evt);
        DateTimeOffset end = DateTimeOffset.UtcNow;

        (bool isCold, string containerId) = CheckColdStart();

        var body = new JsonObject
        {
            ["begin"] = FormatTimestamp(begin),
            ["end"] = FormatTimestamp(end),
            ["results_time"] = 0,
            ["is_cold"] = isCold,
            ["result"] = result,
            ["request_id"] = context.AwsRequestId,
            ["cold_start_var"] = Environment.GetEnvironmentVariable("cold_start") ?? "",
            ["container_id"] = containerId,
        };
        var response = new JsonObject
        {
            ["statusCode"] = 200,
            ["body"] = body.ToJsonString(JsonOptions),
        };
        return new MemoryStream(Encoding.UTF8.GetBytes(response.ToJsonString(JsonOptions)));
    }

    // HTTP triggers wrap the input in a JSON string under "body".
    private static JsonObject ParseEvent(Stream input)
    {
        JsonObject evt = JsonNode.Parse(input) as JsonObject ?? new JsonObject();
        if (evt["body"] is JsonValue body && body.TryGetValue(out string? text)
            && JsonNode.Parse(text) is JsonObject parsed)
        {
            return parsed;
        }
        return evt;
    }

    private static (bool, string) CheckColdStart()
    {
        if (File.Exists(ColdStartMarker))
        {
            return (false, File.ReadAllText(ColdStartMarker));
        }
        string containerId = Guid.NewGuid().ToString("N").Substring(0, 8);
        try
        {
            File.WriteAllText(ColdStartMarker, containerId);
        }
        catch (IOException)
        {
            // Best effort.
        }
        return (true, containerId);
    }

    // seconds.microseconds, like the other wrappers.
    private static string FormatTimestamp(DateTimeOffset ts)
    {
        long micros = (ts.UtcTicks - DateTimeOffset.UnixEpoch.UtcTicks) / 10;
        return string.Format(
            CultureInfo.InvariantCulture, "{0}.{1:D6}", micros / 1_000_000, micros % 1_000_000);
    }
}
