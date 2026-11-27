// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.Json.Nodes;
using Stubble.Core.Builders;

namespace Benchmark;

public class Function
{
    public JsonObject Handler(JsonObject input)
    {
        string username = input["username"]?.GetValue<string>() ?? "Guest";
        int randomLen = ParseRandomLen(input["random_len"]);

        var random = new Random();
        var randomNumbers = new List<int>(randomLen);
        for (int i = 0; i < randomLen; i++)
        {
            randomNumbers.Add(random.Next(1000000));
        }

        string currentTime =
            DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);

        var data = new Dictionary<string, object>
        {
            ["username"] = username,
            ["cur_time"] = currentTime,
            ["random_numbers"] = randomNumbers,
        };

        // Compiled on every call, like the Java version
        string html = new StubbleBuilder().Build().Render(ReadTemplate(), data);
        return new JsonObject { ["result"] = html };
    }

    // A number or a numeric string, 10 by default, like the Java version
    private static int ParseRandomLen(JsonNode? node)
    {
        if (node is JsonValue value)
        {
            if (value.TryGetValue(out int number))
            {
                return number;
            }
            if (value.TryGetValue(out string? text) && int.TryParse(text, out number))
            {
                return number;
            }
        }
        return 10;
    }

    private static string ReadTemplate()
    {
        using Stream stream =
            typeof(Function).Assembly.GetManifestResourceStream("template.html")
            ?? throw new InvalidOperationException("template.html is not embedded");
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }
}
