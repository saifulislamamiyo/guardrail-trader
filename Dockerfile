# guardrail-trader: bot (supercronic scheduler) and dashboard share this image.
#   docker compose build
FROM python:3.13-slim

ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.49
# SHA-1 sums published in the supercronic v0.2.49 release notes
ARG SUPERCRONIC_SHA1_amd64=e63c11a9726b775a6a11801e81af4f3fb926aa68
ARG SUPERCRONIC_SHA1_arm64=0b6c5bb743e0b0dafed1132198c81807927ac413

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# supercronic: cron built for containers (logs to stdout, handles signals, no root needed)
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" \
 && case "$ARCH" in \
      amd64) SHA="$SUPERCRONIC_SHA1_amd64" ;; \
      arm64) SHA="$SUPERCRONIC_SHA1_arm64" ;; \
      *) echo "unsupported arch: $ARCH" && exit 1 ;; \
    esac \
 && curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${ARCH}" \
 && echo "${SHA}  /usr/local/bin/supercronic" | sha1sum -c - \
 && chmod +x /usr/local/bin/supercronic \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 bot
WORKDIR /app

# Editable install on purpose: the code locates data/, config/ and web/ relative to /app.
COPY pyproject.toml ./
COPY guardrail_trader ./guardrail_trader
RUN pip install -e ".[tools,dev]"

COPY scripts ./scripts
COPY tests ./tests
COPY config ./config
COPY docker/crontab ./docker/crontab
RUN mkdir -p /app/data /app/logs && chown -R bot:bot /app/data /app/logs

USER bot
CMD ["supercronic", "/app/docker/crontab"]
