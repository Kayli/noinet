FROM mcr.microsoft.com/devcontainers/python:3.11

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl openssh-client \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
 && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends gh \
 && python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir git-filter-repo \
 && python -m pip install --no-cache-dir pyspark

 
# Install ping in a separate layer so heavy changes to other packages don't bust cache
RUN apt-get install -y --no-install-recommends iputils-ping

# Ensure system Python has pip available for background jobs that call
# `/usr/bin/python3 -m pip` (avoids "No module named pip" errors).
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip time default-jre-headless \
 && rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME for PySpark / JVM-based tools
ENV JAVA_HOME=/usr/lib/jvm/default-java
ENV PATH="$JAVA_HOME/bin:$PATH"
 
CMD ["/bin/bash"]