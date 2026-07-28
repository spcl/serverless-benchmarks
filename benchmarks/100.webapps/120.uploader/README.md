# 120.uploader - Uploader

**Type:** Webapps
**Languages:** Python, Node.js
**Architecture:** x64, arm64

## Description

The benchmark implements the common workflow of uploading user-defined data to the persistent cloud storage. It accepts a URL, downloads file contents, and uploads them to the storage. Python implementation uses the standard library `requests`, while the Node.js version uses the third-party `requests` library installed with `npm`.

While 128 MB is technically sufficient for memory size, a larger memory value or a longer timeout might be required for the `large` input size.

It works with the three types of inputs:
* `test` fetches a small image from Wikipedia.
* `small` downloads a release of HPX source code from GitHub.
* `large` downloads a larger ResNet model file from PyTorch website.
