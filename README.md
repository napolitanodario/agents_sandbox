# agents_sandbox

An experiment workspace for agents that work with code, files, and browsers.

Harness2 is the planned harness improvement engine. OpenSandbox is the selected
execution runtime. The initial repository contains an architecture, an experiment
configuration, a sample task, and pinned upstream references. The integration
adapter and execution runner are not implemented yet.

## Repository layout

```text
configs/                 Project configuration examples
docs/                    Architecture and implementation roadmap
harnesses/               Harness versioning conventions
integrations/            Harness2 and OpenSandbox integration contracts
tasks/examples/          Custom task definitions
tasks/fixtures/          Small public input files
upstreams.lock.json      Reviewed upstream source revisions
```

`dependencies/`, `runs/`, and `artifacts/` are reserved for local checkouts,
execution evidence, and generated deliverables. They are ignored by Git.

## First experiment

The sample task reads a CSV, creates an HTML sales report, and verifies the report
in Chromium inside OpenSandbox. It uses a local web server so that the first
browser experiment does not depend on external websites.

See [the architecture](docs/architecture.md), [the experiment configuration](configs/experiment.example.toml),
and [the task definition](tasks/examples/sales-report.json).

## Runtime requirements

- Linux, with Ubuntu under WSL as the intended local environment.
- Python 3.12 for Harness2 benchmark runs. Its package also supports Python 3.13.
- Docker Engine or Docker Desktop with a working daemon accessible from Linux.
- uv for the upstream setup workflow.
- Node.js 20 or newer when using the upstream agent executors.
- Model credentials only when running model-backed experiments.

Harness2 provides a deterministic demo that does not require model credentials.
The benchmark CLI does not automatically discover the custom task JSON in this
repository. A project adapter and entry point must connect it to Harness2.

## Upstream projects

- [Harness2](https://github.com/google-research/harness2)
- [OpenSandbox](https://github.com/opensandbox-group/OpenSandbox)

Both upstream repositories use Apache-2.0. Their third-party components and datasets
may have separate terms. No upstream source is vendored in this scaffold.
