# 210.thumbnailer - Thumbnailer

**Type:** Multimedia
**Languages:** Python, Node.js
**Architecture:** x64, arm64

## Description

This benchmark implements one of the most common serverless workloads. It downloads an image from the cloud storage, resizes it to a thumbnail size, uploads the new smaller version to the cloud storage, and returns the location to the caller, allowing them to insert the newly created thumbnail. To resize the image, it uses the `Pillow` and `sharp` libraries on Python and Node.js, respectively.

[Inspired by AWS Lambda tutorial code.](https://docs.aws.amazon.com/lambda/latest/dg/with-s3-example-deployment-pkg.html)
