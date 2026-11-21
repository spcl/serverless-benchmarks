# 311.compression - Compression

**Type:** Utilities
**Languages:** Python, Node.js, Java, .NET
**Architecture:** x64, arm64

## Description

The benchmark implements a common functionality of websites managing file operations - gather a set of files in cloud storage, compress them together, and return a single archive to the user. It implements the .zip file creation with the help of the `shutil` standard library in Python. The Java and .NET versions use their standard libraries, `java.util.zip` and `System.IO.Compression`, which compress with the platform's zlib and with zlib-ng respectively.
