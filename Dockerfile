# guardrail-trader: bot (supercronic scheduler) and dashboard share this image.
#   docker compose build
# Pinned by digest (Dependabot bumps it). Tag kept for readability.
FROM python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0

ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.49
# SHA-256 of the release binaries (computed from downloads that matched the SHA-1 sums
# published in the supercronic v0.2.49 release notes)
ARG SUPERCRONIC_SHA256_amd64=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1
ARG SUPERCRONIC_SHA256_arm64=02aa0cb229ba09050cba6638059dadb9eedc2276632ea43d6a57a2f8c1629dd5

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# supercronic: cron built for containers (logs to stdout, handles signals, no root needed)
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" \
 && case "$ARCH" in \
      amd64) SHA="$SUPERCRONIC_SHA256_amd64" ;; \
      arm64) SHA="$SUPERCRONIC_SHA256_arm64" ;; \
      *) echo "unsupported arch: $ARCH" && exit 1 ;; \
    esac \
 && curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH}" \
 && echo "${SHA}  /usr/local/bin/supercronic" | sha256sum -c - \
 && chmod +x /usr/local/bin/supercronic \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 bot
WORKDIR /app

# Runtime dependencies only, every package hash-checked (requirements/runtime.txt, made by uv).
# The package itself is not pip-installed: /app is on PYTHONPATH, and the code finds data/,
# config/ and web/ relative to /app. No tests or dev tools in the image.
COPY requirements/runtime.txt ./requirements/runtime.txt
RUN pip install --require-hashes --no-deps -r requirements/runtime.txt
ENV PYTHONPATH=/app

COPY guardrail_trader ./guardrail_trader
COPY scripts ./scripts
COPY config ./config
COPY docker/crontab ./docker/crontab
RUN mkdir -p /app/data /app/logs && chown -R bot:bot /app/data /app/logs

USER bot
CMD ["supercronic", "/app/docker/crontab"]
