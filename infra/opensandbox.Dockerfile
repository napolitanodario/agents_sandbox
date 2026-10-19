# Build the trusted lifecycle server image, not an agent workload image.
# The Python controller runs in the host .venv and workloads use SANDBOX_IMAGE.
FROM python:3.12-slim-bookworm
# Install the fixed server release inside this container's Python environment.
RUN pip install --no-cache-dir opensandbox-server==1.1.1
# Compose mounts the server TOML here and injects the API key at runtime.
WORKDIR /app
# Use an argument-list command so no intermediate shell interprets these values.
CMD ["opensandbox-server", "--config", "/app/opensandbox.toml"]
