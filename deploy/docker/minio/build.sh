#!/bin/sh
set -eu

source_dir=${MINIO_SOURCE_DIR:-/src/minio}
output_path=${MINIO_OUTPUT_PATH:-/out/minio}
max_attempts=${MINIO_BUILD_MAX_ATTEMPTS:-3}
retry_delay_seconds=${MINIO_BUILD_RETRY_DELAY_SECONDS:-2}

case $max_attempts in
    ''|*[!0-9]*|0)
        echo "MINIO_BUILD_MAX_ATTEMPTS must be a positive integer" >&2
        exit 2
        ;;
esac
case $retry_delay_seconds in
    ''|*[!0-9]*)
        echo "MINIO_BUILD_RETRY_DELAY_SECONDS must be a non-negative integer" >&2
        exit 2
        ;;
esac

mkdir -p "$(dirname "$output_path")"
cd "$source_dir"

build_minio() {
    ldflags=$(MINIO_RELEASE=RELEASE go run buildscripts/gen-ldflags.go) || return $?
    CGO_ENABLED=0 go build \
        -tags kqueue \
        -trimpath \
        -ldflags "$ldflags" \
        -o "$output_path" \
        .
}

attempt=1
while [ "$attempt" -le "$max_attempts" ]; do
    if build_minio; then
        exit 0
    else
        build_status=$?
    fi
    if [ "$attempt" -eq "$max_attempts" ]; then
        exit "$build_status"
    fi
    echo "MinIO build attempt $attempt failed; retrying" >&2
    sleep "$retry_delay_seconds"
    attempt=$((attempt + 1))
done
