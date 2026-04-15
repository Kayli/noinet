
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Minimal image that contains ping and the application baked in.
# Install system packages and upgrade pip first so those layers cache
# separately from project source changes.
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping ca-certificates curl \
    && python -m pip install --upgrade pip build wheel \
    && rm -rf /var/lib/apt/lists/*

# Copy only package metadata and package sources needed to build/install the
# package. This lets Docker cache the dependency-install step when source
# files change frequently.
COPY pyproject.toml pyproject.toml
COPY noinet/ noinet/

# Install the package into the image. This step will be re-run only when
# package metadata or package sources change.
RUN pip install --no-cache-dir .

# Copy remaining files (tests, docs, CI, etc.) without affecting the
# previously cached install step.
COPY . /app

CMD ["/bin/bash"]
