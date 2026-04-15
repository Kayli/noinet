
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

# Minimal image that contains ping and the application baked in.
# Install system packages and upgrade pip first so those layers cache
# separately from project source changes.
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping ca-certificates curl \
    && python -m pip install --upgrade pip

# Copy project files after installing system deps so source changes
# won't invalidate the system package and pip-upgrade layers.
COPY . /app

# Install the package into the image (will re-run when source changes).
RUN pip install . 

CMD ["/bin/bash"]
