#!/bin/bash

cd /mnt/function
go mod init github.com/spcl/serverless-benchmarks
go get github.com/minio/minio-go/v7
go get github.com/google/uuid

go mod tidy
