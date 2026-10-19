# Integration contract

Status: design only. No runtime adapter or execution entry point is implemented.

## Harness2

The reviewed source defines `BenchmarkAdapter` and `BenchSpec` in
`harness2/core/spec.py`. A custom task adapter must provide task discovery,
prompts, input files, execution, delivery detection, readable trajectories,
deliverable extraction, a base harness, harness validation, and post-selection
scoring.

The substrate protocol in `harness2/substrate/base.py` describes harness surfaces,
materialization, execution, trajectory parsing, and preflight checks. Existing
OpenCode or Codex substrates can supply native harness formatting. Their launch
path still needs to be connected to OpenSandbox for this project.

The upstream CLI is oriented toward its bundled benchmarks. Adding our task JSON
does not register a benchmark. A project entry point must instantiate the adapter
and call the Harness2 core, or explicitly extend upstream CLI dispatch.

## OpenSandbox

The proposed launcher creates a fresh sandbox for each rollout, stages the task
inputs and materialized harness, launches the selected agent, and collects its
trace and deliverables. It records errors and timeout outcomes and destroys the
sandbox in a cleanup path.

Start with a Linux image containing Python, the selected executor, Chromium,
and Playwright. Pin the image digest after validating a smoke run. OpenSandbox's
Playwright example is a useful image reference. Its AIO example is an alternative
when a visible desktop is needed.

The host controller owns lifecycle access. Workloads must not receive the Docker
socket, host home directory, or the OpenSandbox control API credential. A model
credential routing strategy must be selected before model-backed runs.

## Acceptance criteria

1. A smoke run executes Python, writes and reads a file, and captures a local page.
2. Two rollouts cannot observe one another's files or browser sessions.
3. Timeout and failure paths collect diagnostics and clean up the sandbox.
4. The base and refined harnesses start from the same input snapshot.
5. External verification occurs after selection and its answers are excluded from
   improver and executor inputs.
6. Logs identify the task, harness revision, sandbox image, model configuration,
   elapsed time, and usage or cost when available.
