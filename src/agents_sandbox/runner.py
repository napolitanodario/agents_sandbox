"""Run the upstream deterministic Harness2 workflow in disposable sandboxes.

This module runs on the trusted host. Harness2 owns task scheduling and harness
refinement, OpenSandbox executes each generated script in a separate container,
and Langfuse records the operations as related observations.

The integration deliberately reuses Harness2's ledger demo. Its proposer makes
scripted changes rather than calling an LLM. Only the generated ledger script is
sent to a sandbox; service credentials remain in this host process.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import uuid

from dotenv import load_dotenv
# These imports use the installed Harness2 implementation, including its real
# scheduler. The subclasses below customize execution and add instrumentation.
from harness2.core.schedule import run_domain
from harness2.demo import DemoAdapter, DemoProposer
import httpx
from langfuse import Langfuse
from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync
from opensandbox.models import NetworkPolicy, WriteEntry
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.execd_sync import ExecutionHandlersSync


@dataclass(frozen=True)
class Settings:
    """Hold the connection settings shared by one complete experiment.

    A frozen dataclass prevents accidental reassignment while Harness2 worker
    threads share this object. The fields contain control-plane credentials,
    so instances must not be included in traces or passed to sandbox workloads.
    """

    # The SDK uses this key to create and manage sandboxes through the server.
    sandbox_key: str
    # These keys authenticate this host process to the local Langfuse project.
    langfuse_public_key: str
    langfuse_secret_key: str
    # The OpenSandbox domain excludes the scheme; the SDK defaults to HTTP.
    sandbox_domain: str = "127.0.0.1:8080"
    # Langfuse expects a complete base URL, including the HTTP or HTTPS scheme.
    langfuse_url: str = "http://localhost:3000"
    # This image needs Python and sleep, but does not contain the controller.
    image: str = "python:3.12-slim-bookworm"

    @classmethod
    def load(cls) -> Settings:
        """Read local configuration, keeping exported environment values first."""
        # Resolve .env from the working directory. Commands should therefore be
        # launched from the repository root. load_dotenv does not override
        # variables already exported by the caller unless explicitly requested.
        load_dotenv(Path.cwd() / ".env")

        def required(name: str) -> str:
            """Reject missing credentials and unexpanded template placeholders."""
            value = os.getenv(name, "").strip()
            if not value or "__GENERATE__" in value:
                raise ValueError(f"Set {name} in .env. Run make init first.")
            return value

        # Local endpoint defaults make the generated Compose setup usable
        # without requiring a hosted Langfuse account or a remote sandbox server.
        return cls(
            sandbox_key=required("OPEN_SANDBOX_API_KEY"),
            langfuse_public_key=required("LANGFUSE_PUBLIC_KEY"),
            langfuse_secret_key=required("LANGFUSE_SECRET_KEY"),
            sandbox_domain=os.getenv("OPEN_SANDBOX_DOMAIN", "127.0.0.1:8080"),
            langfuse_url=os.getenv("LANGFUSE_BASE_URL", "http://localhost:3000"),
            image=os.getenv("SANDBOX_IMAGE", "python:3.12-slim-bookworm"),
        )

    def connection(self) -> ConnectionConfigSync:
        """Build SDK options for authenticated, synchronous sandbox requests."""
        return ConnectionConfigSync(
            domain=self.sandbox_domain,
            api_key=self.sandbox_key,
            # Route file and command requests through the control server. The
            # runner does not need direct access to each container's private IP.
            use_server_proxy=True,
            # This is an HTTP request limit, separate from sandbox lifetime,
            # sandbox readiness, and the command execution timeout below.
            request_timeout=timedelta(seconds=60),
        )


class SandboxAdapter(DemoAdapter):
    """Adapt Harness2's ledger tasks to execute through OpenSandbox.

    DemoAdapter supplies task IDs, CSV fixtures, a base harness, validation, and
    methods for reading the resulting artifacts. Overriding execute() replaces
    its host subprocess with a disposable remote sandbox while retaining the
    artifact format that the Harness2 scheduler expects.
    """

    def __init__(self, root: Path, settings: Settings, tracing: Langfuse):
        """Create the demo inputs and retain host-side service clients."""
        # The parent creates the base scripts and source ledgers under root.
        super().__init__(root)
        self.settings = settings
        self.tracing = tracing
        # run_demo fills this with the root trace and parent span IDs. Explicit
        # context also works when execution occurs in a different worker thread.
        self.trace_context = None

    def execute(self, task_id, harness_dir, run_id, *, timeout=None) -> Path:
        """Execute one harness version and return its local artifact directory.

        task_id selects the ledger input. harness_dir selects a candidate harness;
        None selects the original base harness. run_id identifies this rollout
        and may contain scheduler-generated directory components. timeout is the
        command budget requested by Harness2, capped here at 30 seconds.

        Exceptions propagate to Harness2. Once creation succeeds, cleanup is
        attempted in a finally block even if upload, execution, or saving fails.
        """
        self.execution_count += 1
        # These paths are on the host and survive destruction of the sandbox.
        run_dir = self.root / "executions" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        # Harness2 supplies a modified script for candidate runs. Reference runs
        # receive no candidate directory and use the parent's original script.
        script = (harness_dir or self.base_harness()) / "scripts/summarize.py"
        source = self.task_files(task_id) / "ledger.csv"
        # Both /tmp paths below refer to the sandbox filesystem, not the host.
        command = "python /tmp/summarize.py /tmp/ledger.csv"

        # One tool observation covers creation, file staging, execution, and
        # cleanup. Its context manager also records exceptions from that scope.
        with self.tracing.start_as_current_observation(
            trace_context=self.trace_context,
            as_type="tool",
            name="sandbox-rollout",
            input={"task_id": task_id, "run_id": run_id},
        ) as span:
            # A fresh instance prevents one candidate from inheriting another
            # candidate's modified files or running processes. No env or volumes
            # argument is supplied, so this adapter passes no credentials or
            # host filesystem mounts into the workload.
            sandbox = SandboxSync.create(
                self.settings.image,
                connection_config=self.settings.connection(),
                # Sandbox lifetime: the environment expires after this duration.
                timeout=timedelta(seconds=120),
                # Readiness budget: how long the SDK waits for a usable instance.
                ready_timeout=timedelta(seconds=60),
                # These limits apply to this workload, not the complete stack.
                resource={"cpu": "1", "memory": "512Mi"},
                # Keep the container alive until commands are submitted or its
                # lifecycle ends; this entrypoint does not run the ledger script.
                entrypoint=["sleep", "infinity"],
                # The demo needs no outbound network. Enforcement depends on
                # the egress sidecar configured in infra/opensandbox.toml.
                network_policy=NetworkPolicy(defaultAction="deny", egress=[]),
                # These labels help identify workloads through the server API.
                metadata={"project": "agents-sandbox", "task": task_id},
            )
            try:
                # Record enough identity information to correlate local files,
                # Langfuse observations, and OpenSandbox diagnostics.
                identity = {"sandbox_id": sandbox.id, "image": self.settings.image}
                span.update(metadata=identity)
                (run_dir / "sandbox.json").write_text(json.dumps(identity) + "\n")
                # Upload only the two required inputs. Octal 0644 grants the
                # owner read/write permission and everyone else read permission.
                # Python reads the script directly, so it needs no execute bit.
                sandbox.files.write_files([
                    WriteEntry(path="/tmp/summarize.py", data=script.read_text(), mode=0o644),
                    WriteEntry(path="/tmp/ledger.csv", data=source.read_text(), mode=0o644),
                ])
                # The synchronous call returns when execution completes or the
                # SDK raises an error. Stream handlers print output while it runs;
                # the SDK also accumulates the messages for later persistence.
                execution = sandbox.commands.run(
                    command,
                    # Use 30 seconds when no nonzero timeout is supplied, and
                    # never allow a requested command budget above 30 seconds.
                    opts=RunCommandOpts(timeout=timedelta(seconds=min(timeout or 30, 30))),
                    handlers=ExecutionHandlersSync(
                        on_stdout=lambda message: print(f"[{run_id}] {message.text}", flush=True),
                        on_stderr=lambda message: print(f"[{run_id}] {message.text}", file=sys.stderr, flush=True),
                    ),
                )
                # Reconstruct the returned output streams. Persist them before
                # checking success so failed commands still leave diagnostics.
                stdout = "\n".join(message.text for message in execution.logs.stdout)
                stderr = "\n".join(message.text for message in execution.logs.stderr)
                (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
                (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
                # The action/observation/error markers describe the rollout in
                # the readable format consumed by the inherited demo adapter.
                (run_dir / "trajectory.md").write_text(
                    f"[ACTION] {command}\n[OBSERVATION]\n{stdout}\n[ERROR]\n{stderr}\n",
                    encoding="utf-8",
                )
                # Keep full output locally and bound only the trace payload.
                span.update(output={"stdout": stdout[:2000], "stderr": stderr[:2000], "exit_code": execution.exit_code})
                # None is accepted when no exit code was provided by the runtime.
                # This checks execution and output presence, not arithmetic
                # correctness; Harness2 compares the resulting candidate outputs.
                if execution.error or execution.exit_code not in (None, 0) or not stdout.strip():
                    raise RuntimeError("Sandbox command failed. Inspect the local execution logs.")
                # DemoAdapter.delivered() recognizes this file as a deliverable.
                # It is created only after the execution checks above succeed.
                (run_dir / "answer.txt").write_text(stdout, encoding="utf-8")
            finally:
                # destroy() terminates the remote environment and closes the
                # SDK resources. A cleanup failure propagates to the caller too.
                sandbox.destroy()
        # Harness2 reads artifacts from this directory after the sandbox is gone.
        return run_dir


class TracedProposer(DemoProposer):
    """Instrument the upstream scripted proposer without changing its edits.

    DemoProposer handles proposal, composition, selection, and experience labels
    with predetermined behavior. This subclass only wraps those calls in spans;
    it does not introduce model inference or usage-based LLM costs.
    """

    def __init__(self, channel, tracing):
        """Retain the Harness2 channel specification and shared tracing client."""
        super().__init__(channel)
        self.tracing = tracing
        self.trace_context = None

    def call(self, mission, context_dir, label, **kwargs):
        """Run the original proposer call and attach its bounded notes to a span.

        mission describes the requested operation, context_dir contains its files,
        and label identifies the Harness2 stage. Extra options are forwarded
        unchanged so the inherited proposer keeps its existing call contract.
        """
        with self.tracing.start_as_current_observation(
            trace_context=self.trace_context, name=f"harness.{label}"
        ) as span:
            reply = super().call(mission, context_dir, label, **kwargs)
            span.update(output={"ok": reply.ok, "notes": reply.text[:2000]})
            return reply


def run_demo(root: Path, settings: Settings, tracing: Langfuse, *, k=1, tasks=1) -> dict:
    """Run selected ledger tasks and persist a summary for one experiment.

    k controls the sequential refinement budget. tasks selects the first one or
    two demo tasks; processing two lets the upstream library carry lessons from
    the first task into the second. root is unique for each CLI invocation.
    """
    adapter = SandboxAdapter(root, settings, tracing)
    proposer = TracedProposer(adapter.spec.channels["proposer"], tracing)
    # All instrumented stages belong to this experiment's root observation.
    with tracing.start_as_current_observation(
        name="harness2-demo",
        input={"mode": "sequential", "k": k, "tasks": tasks},
        metadata={"executor": "deterministic", "runtime": "opensandbox"},
    ) as span:
        # Harness2 starts worker threads. Their current OpenTelemetry context may
        # differ, so pass the same trace and parent IDs to each observation.
        context = {"trace_id": span.trace_id, "parent_span_id": span.id}
        adapter.trace_context = context
        proposer.trace_context = context
        # Delegate scheduling, reference runs, refinement, selection, and the
        # improvement library to the real Harness2 core. "seq" selects sequential
        # refinement; internal proposal work may still use concurrent threads.
        result = run_domain(
            "accounting", adapter.tasks()[:tasks], k,
            adapter=adapter, prop=proposer,
            runs_root=adapter.spec.runs_root,
            library_root=root / "library", modes=("seq",),
        )
        # Extend the upstream result with integration-specific diagnostics.
        # get_trace_url may query Langfuse to resolve the authenticated project.
        result["execution_count"] = adapter.execution_count
        result["trace_url"] = tracing.get_trace_url(trace_id=span.trace_id)
        # Harness2 can report task failures without raising an exception. Mark
        # the root observation accordingly and retain its complete summary.
        span.update(output=result, level="ERROR" if result["failed"] else "DEFAULT")
        (root / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def check_services(settings: Settings, tracing: Langfuse) -> None:
    """Check authenticated API access without creating a sandbox or running a task.

    This is a connectivity preflight. Successful checks do not prove that Docker
    can launch workload images or that network isolation is correctly enforced.
    Those paths are exercised by the run command.
    """
    # Ignore HTTP proxy environment settings for these direct local API checks.
    with httpx.Client(timeout=5, trust_env=False) as client:
        # Listing sandboxes checks the control-plane key as well as reachability.
        response = client.get(
            f"http://{settings.sandbox_domain}/v1/sandboxes",
            headers={"OPEN-SANDBOX-API-KEY": settings.sandbox_key},
        )
        response.raise_for_status()
        # The health endpoint checks service availability; the SDK authentication
        # check below separately verifies the Langfuse project's API keys.
        client.get(f"{settings.langfuse_url}/api/public/health").raise_for_status()
    if not tracing.auth_check():
        raise RuntimeError("Langfuse authentication failed. Check .env and make logs.")
    print("OpenSandbox and Langfuse are reachable and authenticated.")


def main(argv=None) -> int:
    """Expose preflight and demo commands, returning a shell-friendly exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check service availability and credentials.")
    run = commands.add_parser("run", help="Run the integrated deterministic demo.")
    # Bound this demo to small experiments and the two fixtures it actually has.
    run.add_argument("--k", type=int, choices=range(1, 4), default=1)
    run.add_argument("--tasks", type=int, choices=(1, 2), default=1)
    args = parser.parse_args(argv)
    # Initialization may fail before a client exists; the finally block handles
    # that case without attempting to flush an uninitialized object.
    tracing = None
    try:
        settings = Settings.load()
        tracing = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_url,
        )
        # Run the same preflight for both commands to surface configuration
        # failures before allocating sandbox resources.
        check_services(settings, tracing)
        if args.command == "doctor":
            return 0
        # A fresh directory keeps artifacts and improvement libraries from this
        # invocation separate from previous experiments.
        root = Path("runs") / uuid.uuid4().hex
        result = run_demo(root, settings, tracing, k=args.k, tasks=args.tasks)
        print(f"Summary: {root / 'summary.json'}")
        print(f"Trace: {result['trace_url']}")
        # Return 0 for success and 1 when Harness2 reported any failed task.
        return int(result["failed"] > 0)
    except Exception as error:
        # Provide a concise CLI diagnostic while keeping failures nonzero for
        # Make, shell scripts, and future automation.
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1
    finally:
        if tracing is not None:
            # Trace export is asynchronous. Flush queued observations before
            # stopping the client so a short-lived CLI process retains its spans.
            tracing.flush()
            tracing.shutdown()


if __name__ == "__main__":
    # Support both the installed entry point and direct module execution.
    raise SystemExit(main())
