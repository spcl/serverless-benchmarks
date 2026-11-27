// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Text.Json.Nodes;
using ServerlessBench;

namespace Benchmark;

public class Function
{
    public JsonObject Handler(JsonObject input)
    {
        string bucket = GetString(input, "bucket", "bucket");
        string inputPrefix = GetString(input, "bucket", "input");
        string outputPrefix = GetString(input, "bucket", "output");
        string key = GetString(input, "object", "key");

        Storage client = Storage.GetInstance();
        string downloadPath = Path.Combine("/tmp", $"{key}-{Guid.NewGuid()}");
        Directory.CreateDirectory(downloadPath);

        long downloadBegin = Stopwatch.GetTimestamp();
        client.DownloadDirectory(bucket, JoinKey(inputPrefix, key), downloadPath);
        long downloadEnd = Stopwatch.GetTimestamp();
        long size = DirectorySize(downloadPath);

        string archiveName = key + ".zip";
        // Outside the downloaded directory, so that the archive does not contain itself
        string archivePath = downloadPath + ".zip";

        long compressBegin = Stopwatch.GetTimestamp();
        ZipFile.CreateFromDirectory(
            downloadPath, archivePath, CompressionLevel.Optimal, includeBaseDirectory: false);
        long compressEnd = Stopwatch.GetTimestamp();

        long archiveSize = new FileInfo(archivePath).Length;

        long uploadBegin = Stopwatch.GetTimestamp();
        string keyName = client.Upload(bucket, JoinKey(outputPrefix, archiveName), archivePath);
        long uploadEnd = Stopwatch.GetTimestamp();

        return new JsonObject
        {
            ["result"] = new JsonObject { ["bucket"] = bucket, ["key"] = keyName },
            ["measurement"] = new JsonObject
            {
                ["download_time"] = Microseconds(downloadBegin, downloadEnd),
                ["download_size"] = size,
                ["upload_time"] = Microseconds(uploadBegin, uploadEnd),
                ["upload_size"] = archiveSize,
                ["compute_time"] = Microseconds(compressBegin, compressEnd),
            },
        };
    }

    private static string GetString(JsonObject input, string section, string field) =>
        input[section]?[field]?.GetValue<string>()
        ?? throw new ArgumentException($"expected a string in '{section}.{field}'");

    private static string JoinKey(string prefix, string name) =>
        string.IsNullOrEmpty(prefix) ? name : $"{prefix}/{name}";

    private static long Microseconds(long begin, long end) =>
        (long)Stopwatch.GetElapsedTime(begin, end).TotalMicroseconds;

    private static long DirectorySize(string directory)
    {
        long size = 0;
        var files = Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories);
        foreach (string file in files)
        {
            size += new FileInfo(file).Length;
        }
        return size;
    }
}
