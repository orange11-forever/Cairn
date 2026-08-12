ARG GO_VERSION=1.24.8
FROM golang:${GO_VERSION}-bookworm AS builder

ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z
ARG CAIRN_BUILD_CA_CERT_BASE64=""
RUN if [ -n "${CAIRN_BUILD_CA_CERT_BASE64}" ]; then \
      printf '%s' "${CAIRN_BUILD_CA_CERT_BASE64}" \
        | base64 --decode > /usr/local/share/ca-certificates/cairn-build.crt; \
      update-ca-certificates; \
    fi \
    && git clone --branch "${MINIO_VERSION}" --depth 1 https://github.com/minio/minio.git /src/minio
COPY deploy/docker/minio/build.sh /usr/local/src/build-minio.sh
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    MINIO_SOURCE_DIR=/src/minio MINIO_OUTPUT_PATH=/out/minio sh /usr/local/src/build-minio.sh

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 minio \
    && useradd --create-home --gid 10001 --uid 10001 minio \
    && install --directory --owner 10001 --group 10001 /data
COPY --from=builder --chown=minio:minio /out/minio /usr/local/bin/minio

USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
