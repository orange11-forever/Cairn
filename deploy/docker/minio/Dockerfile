ARG GO_VERSION=1.24.8
FROM golang:${GO_VERSION}-bookworm AS builder

ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z
RUN git clone --branch "${MINIO_VERSION}" --depth 1 https://github.com/minio/minio.git /src/minio \
    && cd /src/minio \
    && CGO_ENABLED=0 go build -trimpath -o /out/minio .

FROM debian:bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 minio
COPY --from=builder --chown=minio:minio /out/minio /usr/local/bin/minio

USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
