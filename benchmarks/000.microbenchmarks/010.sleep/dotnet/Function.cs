// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
using System;
using System.Diagnostics;
using System.Text.Json.Nodes;
using System.Threading;

namespace Benchmark;

public class Function
{
    public JsonObject Handler(JsonObject input)
    {
        double seconds = input["sleep"]?.GetValue<double>()
            ?? throw new ArgumentException("expected a number in 'sleep'");

        var stopwatch = Stopwatch.StartNew();
        Thread.Sleep(TimeSpan.FromSeconds(seconds));
        return new JsonObject { ["result"] = stopwatch.Elapsed.TotalSeconds };
    }
}
