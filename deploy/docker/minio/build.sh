#!/bin/sh
set -eu

source_dir=${MINIO_SOURCE_DIR:-/src/minio}
output_path=${MINIO_OUTPUT_PATH:-/out/minio}

mkdir -p "$(dirname "$output_path")"
cd "$source_dir"
ldflags=$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go)
CGO_ENABLED=0 go build \
    -tags kqueue \
    -trimpath \
    -ldflags "$ldflags" \
    -o "$output_path" \
    .
