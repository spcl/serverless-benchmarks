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
        // Next to the downloaded directory rather than inside it, so that the archive holds only
        // the downloaded data, as in the other implementations.
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

    // Joins an object storage prefix and a name, as the other implementations do.
    private static string JoinKey(string prefix, string name) =>
        string.IsNullOrEmpty(prefix) ? name : $"{prefix}/{name}";

    private static long Microseconds(long begin, long end) =>
        (long)Stopwatch.GetElapsedTime(begin, end).TotalMicroseconds;

    // Total size of every file below a directory.
    private static long DirectorySize(string directory)
    {
        long size = 0;
        foreach (string file in Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories))
        {
            size += new FileInfo(file).Length;
        }
        return size;
    }
}
