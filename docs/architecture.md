# Architecture and implementation roadmap

## Intended workflow

```text
Task and input snapshot
  -> Harness2 controller
  -> Base harness or candidate harness
  -> Project launcher
  -> Fresh OpenSandbox environment
  -> Agent tools: commands, files, Chromium
  -> Deliverables and execution trace
  -> Harness2 comparison and composition
  -> Adopted harness and evidence-supported lessons
  -> Separate verification and experiment report
```

This diagram is the proposed integration. The controller, adapter, launcher, and
verification runner have not been implemented in this repository.

## What the combination enables

- Compare a base agent with a refined harness on identical inputs.
- Explore several harness candidates in parallel or refine them sequentially.
- Improve prompts, tool guidance, scripts, skills, and memory without training
  model weights.
- Run workflows that combine code execution, document or data processing, and
  browser interaction.
- Retain useful lessons between tasks and compare performance on unseen tasks.
- Record deliverables, trajectories, latency, failures, and available model usage.
- Start with Docker locally and consider Kubernetes after the local runner works.

These capabilities require the corresponding adapter and tooling. In particular,
Harness2 does not automatically turn an arbitrary repository into an executable
task suite, and OpenSandbox does not itself optimize an agent harness.

## First workload

Use `tasks/examples/sales-report.json`. It combines arithmetic over a CSV,
generated Python, an HTML artifact, and browser verification. A local page keeps
the first experiment reproducible. Later tasks can cover repository fixes,
spreadsheet processing, public website research, and multi-step browser workflows.

Start with the base harness, then use one sequential refinement step. Add multiple
tasks and a held-out split before drawing conclusions about general improvement.

## Isolation boundary

The OpenSandbox server manages execution environments. The trusted controller
stages inputs and collects outputs. Agent code and browser sessions run inside a
fresh sandbox per rollout. Resource and network controls belong to infrastructure
and are not editable harness components.

Harness2's documented Codex benchmark configuration disables its internal sandbox.
That makes the proposed OpenSandbox launch boundary especially relevant. Docker
is the intended first runtime; it should not be described as a VM isolation
guarantee. Stronger runtime choices can be assessed for untrusted workloads later.

The initial task needs no external website access. Model-backed execution will
need the chosen model endpoint. Configure and verify OpenSandbox egress policy
for that deployment rather than assuming a container has restricted networking.

## Implementation sequence

1. Verify Docker access from Ubuntu under WSL and install the required Linux tools.
2. Check out the revisions in `upstreams.lock.json` under ignored `dependencies/`.
3. Run the upstream deterministic Harness2 demo without model credentials.
4. Build and pin a mixed workload image, then verify OpenSandbox command, file,
   and Chromium operations without an LLM.
5. Choose the executor and model provider and configure credentials locally.
6. Implement the custom task adapter and OpenSandbox launcher described in
   `integrations/README.md`.
7. Run the sample baseline and one refinement, then add independent verification.
8. Expand the task collection and compare success rate, elapsed time, and cost.

## Environment review

On 2026-10-19, Ubuntu under WSL reported Linux and Python 3.12.3. Docker and uv
were not found on either the Windows command path or the checked Ubuntu login
shell path. Docker was also not found at the standard Docker Desktop executable
path. No sandbox server, images, dependencies, or model-backed runs were started
as part of this scaffold.

## Reviewed sources

- [Harness2 overview](https://github.com/google-research/harness2)
- [Harness2 setup](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/docs/SETUP.md)
- [Harness2 adapter contract](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/core/spec.py)
- [Harness2 substrate contract](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/substrate/base.py)
- [OpenSandbox overview](https://github.com/opensandbox-group/OpenSandbox)
- [OpenSandbox Playwright example](https://github.com/opensandbox-group/OpenSandbox/blob/0548e18f5ee7377b538d3f8a8245f1f0ebdd5c7f/docs/examples/playwright.md)
- [OpenSandbox AIO example](https://github.com/opensandbox-group/OpenSandbox/blob/0548e18f5ee7377b538d3f8a8245f1f0ebdd5c7f/docs/examples/aio-sandbox.md)
- [OpenSandbox egress](https://github.com/opensandbox-group/OpenSandbox/blob/0548e18f5ee7377b538d3f8a8245f1f0ebdd5c7f/docs/architecture/network/egress.md)
