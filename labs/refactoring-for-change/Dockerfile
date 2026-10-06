# Copyright (c) 2026 Zenable, Inc.
FROM golang:1.27.1-bookworm AS golang
FROM eclipse-temurin:21.0.12.1_1-jdk-jammy AS java
FROM ghcr.io/astral-sh/uv:0.12.19 AS uv
FROM python:3.14.7-slim-bookworm

COPY --from=golang /usr/local/go /usr/local/go
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=uv /uv /usr/local/bin/uv
ENV JAVA_HOME=/opt/java/openjdk
ENV PATH=/opt/venv/bin:/usr/local/go/bin:/opt/java/openjdk/bin:$PATH
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PYTHONDONTWRITEBYTECODE=1
ENV GOCACHE=/tmp/go-cache
ENV GOPATH=/tmp/go
ENV GOTOOLCHAIN=local
WORKDIR /dependencies
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-cache
WORKDIR /work
