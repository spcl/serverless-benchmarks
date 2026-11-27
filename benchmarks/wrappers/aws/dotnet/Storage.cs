// Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.

using System;
using System.Collections.Generic;
using System.IO;
using Amazon.S3;
using Amazon.S3.Model;
using Amazon.S3.Transfer;

namespace ServerlessBench;

// S3 storage with the interface of the Python wrapper's storage class.
public sealed class Storage
{
    private static readonly Lazy<Storage> instance = new(() => new Storage());

    private readonly IAmazonS3 client;
    private readonly TransferUtility transfer;

    private Storage()
    {
        this.client = new AmazonS3Client();
        this.transfer = new TransferUtility(this.client);
    }

    public static Storage GetInstance() => instance.Value;

    // Inserts a random suffix before the extension, e.g. archive.1a2b3c4d.zip.
    public static string UniqueName(string name)
    {
        int separator = name.LastIndexOf('/');
        int dot = name.LastIndexOf('.');
        string file = name;
        string extension = "";
        if (dot > separator)
        {
            file = name.Substring(0, dot);
            extension = name.Substring(dot);
        }
        string random = Guid.NewGuid().ToString("N").Substring(0, 8);
        return $"{file}.{random}{extension}";
    }

    // Uploads a local file under UniqueName(file) and returns that key.
    public string Upload(string bucket, string file, string filepath)
    {
        string keyName = UniqueName(file);
        this.transfer.UploadAsync(filepath, bucket, keyName).GetAwaiter().GetResult();
        return keyName;
    }

    // Downloads an object to a local file, creating its parent directories.
    public void Download(string bucket, string file, string filepath)
    {
        string? directory = Path.GetDirectoryName(filepath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
        this.transfer.DownloadAsync(filepath, bucket, file).GetAwaiter().GetResult();
    }

    // Downloads every object under a prefix into path, keeping the key structure.
    public void DownloadDirectory(string bucket, string prefix, string path)
    {
        var request = new ListObjectsV2Request { BucketName = bucket, Prefix = prefix };
        bool found = false;
        do
        {
            ListObjectsV2Response objects =
                this.client.ListObjectsV2Async(request).GetAwaiter().GetResult();
            // The SDK returns null instead of an empty list
            foreach (S3Object entry in objects.S3Objects ?? new List<S3Object>())
            {
                found = true;
                Download(bucket, entry.Key, Path.Combine(path, entry.Key));
            }
            request.ContinuationToken = objects.NextContinuationToken;
        }
        while (request.ContinuationToken != null);

        if (!found)
        {
            throw new IOException(
                $"No objects found in bucket '{bucket}' with prefix '{prefix}'");
        }
    }

    // Uploads bytes under UniqueName(file) and returns that key.
    public string UploadStream(string bucket, string file, byte[] data)
    {
        string keyName = UniqueName(file);
        using var stream = new MemoryStream(data);
        this.transfer.UploadAsync(stream, bucket, keyName).GetAwaiter().GetResult();
        return keyName;
    }

    // Downloads an object into memory.
    public byte[] DownloadStream(string bucket, string file)
    {
        using Stream stream =
            this.transfer.OpenStreamAsync(bucket, file).GetAwaiter().GetResult();
        using var buffer = new MemoryStream();
        stream.CopyTo(buffer);
        return buffer.ToArray();
    }
}
