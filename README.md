# Agents Sandbox

A minimal local integration of Harness2, OpenSandbox, and Langfuse.

```text
Harness2 controller -> fresh OpenSandbox per rollout -> result and trajectory
        |
        +-> Langfuse trace with refinement and sandbox spans
```

The first workflow uses Harness2's deterministic ledger demo and its actual
sequential refinement loop. Its generated Python scripts run in OpenSandbox.
The proposer is scripted, so no LLM provider, API key, token usage, or model cost
is involved. This verifies the integration before adding a model-backed executor.

## Requirements

- Linux or Ubuntu under WSL2, with Python 3.12, Git, Make, and Python venv support.
- A running Docker Engine with Docker Compose v2, accessible from the same shell.
- Available ports 3000, 8080, and 9090.

Run these commands from the repository root. The Docker setup uses host networking
for the OpenSandbox control server and bridge networking for sandbox workloads.
It targets Linux. Docker Desktop users need WSL integration and host networking
support enabled for this layout.

## Start

```bash
make install
make init
make up
make doctor
make run
```

`make install` creates `.venv` and installs the Python integration and test tools
there. The OpenSandbox server and all Langfuse services run in Docker.
`make init` generates local credentials in `.env` and preserves an existing file.
`make up` builds the control server and starts Langfuse with PostgreSQL,
ClickHouse, Redis, and MinIO. These are Langfuse's required local services.

Open [Langfuse](http://localhost:3000) and sign in using `LANGFUSE_USER_EMAIL` and
`LANGFUSE_USER_PASSWORD` from `.env`. Organization, project, and API keys are
initialized automatically on the first startup. Preserving Docker volumes also
preserves those credentials and stored traces. Changing `.env` later does not
rotate credentials already stored by these services.

The terminal prints the trace URL and the local `summary.json` path. Every run
gets a new directory under ignored `runs/`. Langfuse receives a root trace,
refinement spans, and one tool span per sandbox rollout. Events are exported
asynchronously and flushed when the runner exits.

## Isolation

Each rollout receives only its Python script and CSV input. It has a 120-second
lifetime, a 30-second command timeout, one CPU, 512 MiB of memory, and a deny-all
outbound network policy enforced through the configured egress sidecar. The
runner destroys the sandbox after success or failure. No host directories,
Langfuse keys, or control-plane keys are passed to workloads.

The trusted OpenSandbox server needs the Docker socket to manage containers.
The socket is not mounted into sandbox workloads. This setup uses standard
Docker isolation with a shared kernel. Resource limits are per sandbox, not a
global limit across the complete stack. Images are version-tagged where possible;
this is not a full image-digest or transitive dependency lock.

## Development

```bash
make test
make logs
.venv/bin/agents-sandbox run --tasks 2 --k 1
make down
```

Tests exercise the real Harness2 loop and Langfuse SDK with simulated OpenSandbox
execution and in-memory telemetry. They do not substitute for a Docker smoke run.
`make doctor` checks API connectivity and authentication; `make run` verifies
container creation and execution. `make down` preserves database volumes.

The current integration has no graphical browser, live desktop, SSH setup, or
model-backed agent. Add those after the deterministic workflow passes.

## Sources

- [Harness2](https://github.com/google-research/harness2), pinned to commit
  `1cfe254e8d25b15f37048c3730134686abe60335`.
- [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox), SDK and server 1.1.1.
- [Langfuse Compose](https://langfuse.com/self-hosting/deployment/docker-compose),
  server 4.63.0 and Python SDK 5.0.2.
- [Langfuse initialization](https://langfuse.com/self-hosting/administration/headless-initialization).
