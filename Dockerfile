# What: container image for traces.md, published to ghcr.io by the release workflow.
# Why: GitHub Packages does not host Python packages, so the image is the package.
# How: docker run --rm ghcr.io/maxont/traces --help
# Generated from the-greatness-lab publish/templates/Dockerfile.
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/MaxonT/TRACES.md" \
      org.opencontainers.image.description="TRACES.md is a simple, open format for recording what AI agents did: objective, append-only, failures included. This package ships the reference CLI." \
      org.opencontainers.image.licenses="MIT"
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY traces ./traces
RUN pip install --no-cache-dir . && rm -rf /src
WORKDIR /data
ENTRYPOINT ["traces"]
CMD ["--help"]
