"""Exercise real Harness2 orchestration with simulated OpenSandbox workloads.

The scheduler, deterministic proposer, Langfuse SDK, and OpenTelemetry span
objects are real. Container execution and Langfuse HTTP responses are simulated,
so the suite verifies integration contracts without Docker or external services.
Generated workload code is never executed on the host by this test suite.
"""

import csv
from decimal import Decimal
from io import StringIO
from pathlib import Path
import subprocess
from types import SimpleNamespace
import uuid

import httpx
import pytest
from langfuse import Langfuse
from opensandbox.models.execd import Execution, ExecutionLogs, OutputMessage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import yaml

from agents_sandbox.runner import SandboxAdapter, Settings, run_demo


@pytest.fixture
def settings():
    """Provide synthetic credentials that cannot authenticate to real services."""
    return Settings("test-sandbox-key", "pk-lf-test", "sk-lf-test")


@pytest.fixture
def telemetry():
    """Create a real SDK client whose HTTP calls and trace export stay in memory."""
    # The exporter retains completed spans so tests can inspect trace structure.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    client = Langfuse(
        # Langfuse shares resources by public key. A unique key avoids reusing a
        # provider or exporter shut down by a previous test.
        public_key=f"pk-lf-{uuid.uuid4().hex}",
        secret_key="sk-lf-offline-tests",
        base_url="http://langfuse.test",
        # get_trace_url resolves the current project through the HTTP API. This
        # transport supplies that response without DNS or network access.
        httpx_client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{
                "id": "agents-sandbox", "name": "Agents Sandbox",
                "organization": {"id": "agents-sandbox", "name": "Agents Sandbox"},
                "metadata": {},
            }]}),
        )),
        tracer_provider=provider,
        span_exporter=exporter,
    )
    yield client, exporter
    # Mirror CLI cleanup and drain asynchronous export before stopping the SDK.
    client.flush()
    client.shutdown()


class FakeSandbox:
    """Simulate the known ledger workload without running generated code locally."""

    def __init__(self, identifier, failure=None):
        """Expose the small portion of the SDK used by SandboxAdapter.

        failure selects a controlled fault. contents represents sandbox files,
        and destroyed records whether the adapter attempted lifecycle cleanup.
        """
        self.id = identifier
        self.failure = failure
        self.destroyed = False
        self.contents = {}
        # Preserve the real SDK's sandbox.files and sandbox.commands call shape.
        self.files = SimpleNamespace(write_files=self.write_files)
        self.commands = SimpleNamespace(run=self.run)

    def write_files(self, entries):
        """Stage uploaded data or fail before command execution begins."""
        if self.failure == "upload":
            raise RuntimeError("Simulated upload failure")
        self.contents = {entry.path: entry.data for entry in entries}

    def run(self, command, *, opts, handlers):
        """Model the demo's arithmetic and return actual SDK response objects.

        The known original script filters out negative amounts. The known
        deterministic refinement removes that filter. Recognize these two cases
        to simulate their outputs without eval(), exec(), or a host subprocess.
        This is a workload simulation, not a general Python execution engine.
        """
        # Check the adapter's runtime request at the fake service boundary.
        assert command == "python /tmp/summarize.py /tmp/ledger.csv"
        assert opts.timeout.total_seconds() <= 30
        if self.failure == "transport":
            raise RuntimeError("Simulated transport failure")
        # Decimal matches the upstream demo's exact signed arithmetic.
        rows = csv.DictReader(StringIO(self.contents["/tmp/ledger.csv"]))
        amounts = [Decimal(row["amount"]) for row in rows]
        if "if amount > 0" in self.contents["/tmp/summarize.py"]:
            amounts = [amount for amount in amounts if amount > 0]
        message = OutputMessage(text=f"Total: {sum(amounts):.2f}", timestamp=0)
        # Exercise the adapter's live-output callback as well as the accumulated
        # response logs that it writes to local artifacts.
        handlers.on_stdout(message)
        return Execution(
            exit_code=1 if self.failure == "exit" else 0,
            logs=ExecutionLogs(stdout=[message]),
        )

    def destroy(self):
        """Record cleanup so success and failure paths can assert it occurred."""
        self.destroyed = True


@pytest.fixture
def fake_service(monkeypatch):
    """Replace SDK creation while retaining every simulated rollout for checks."""
    created = []

    def install(failure=None):
        """Configure the failure mode for sandboxes created by this test."""
        def create(image, **options):
            """Validate isolation-related request options and allocate a fresh fake."""
            assert image.startswith("python:3.12")
            assert options["network_policy"].default_action == "deny"
            assert options["network_policy"].egress == []
            assert options["resource"] == {"cpu": "1", "memory": "512Mi"}
            assert options["timeout"].total_seconds() == 120
            # The runner must not send host credentials or filesystem mounts
            # into the workload through these SDK arguments.
            assert "env" not in options and "volumes" not in options
            assert options["connection_config"].use_server_proxy
            sandbox = FakeSandbox(f"sandbox-{len(created)}", failure)
            created.append(sandbox)
            return sandbox

        # Patch only the external service boundary. Harness2 itself stays real.
        monkeypatch.setattr("agents_sandbox.runner.SandboxSync.create", create)
        return created

    return install


def test_full_refinement_uses_new_sandboxes_and_emits_nested_traces(tmp_path, settings, telemetry, fake_service):
    """Verify refinement, isolation per rollout, artifacts, and trace correlation."""
    client, exporter = telemetry
    sandboxes = fake_service()
    # Two refinement steps also exercise selection calls, which Harness2 can
    # bypass for a single composed candidate. Two tasks exercise lesson reuse.
    result = run_demo(tmp_path, settings, client, k=2, tasks=2)
    client.flush()

    assert result["done"] == 2
    assert result["failed"] == 0
    # Each execute call must allocate its own environment and clean it up.
    assert len(sandboxes) == result["execution_count"] > 2
    assert len({sandbox.id for sandbox in sandboxes}) == len(sandboxes)
    assert all(sandbox.destroyed for sandbox in sandboxes)
    assert (tmp_path / "summary.json").is_file()
    # Include nested scheduler run IDs. Corrected totals prove that the refined
    # scripts, rather than only the base script, reached the simulated backend.
    answers = {path.read_text().strip() for path in (tmp_path / "executions").rglob("answer.txt")}
    assert "Total: 85.15" in answers
    assert "Total: 20.25" in answers
    # Explicit trace propagation must keep observations created by different
    # Harness2 threads in one experiment trace.
    spans = exporter.get_finished_spans()
    assert len([span for span in spans if span.name == "sandbox-rollout"]) == len(sandboxes)
    assert any(span.name.startswith("harness.select.") for span in spans), [span.name for span in spans]
    assert any(span.name.startswith("harness.experience.") for span in spans)
    assert len({span.context.trace_id for span in spans}) == 1


@pytest.mark.parametrize("failure", ["upload", "transport", "exit"])
def test_failed_rollout_still_destroys_sandbox(tmp_path, settings, telemetry, fake_service, failure):
    """Check cleanup for upload errors, command transport errors, and failed exits."""
    client, exporter = telemetry
    sandboxes = fake_service(failure)
    adapter = SandboxAdapter(tmp_path, settings, client)
    with pytest.raises(RuntimeError):
        adapter.execute("ledger-1", None, "failing-run")
    client.flush()
    assert sandboxes[0].destroyed
    # A failed execution must not masquerade as a successful deliverable, and
    # the exception should be visible in the completed telemetry observation.
    assert not (tmp_path / "executions/failing-run/answer.txt").exists()
    assert any(span.status.is_ok is False for span in exporter.get_finished_spans())


def test_init_generates_unique_secrets_and_preserves_existing_file(tmp_path):
    """Run credential bootstrap twice in a temporary, isolated project layout."""
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts/init_env.py"
    # Copy the real bootstrap script and template, never the actual project .env.
    script.write_bytes((root / "scripts/init_env.py").read_bytes())
    (tmp_path / ".env.example").write_bytes((root / ".env.example").read_bytes())
    import sys
    # This subprocess executes our configuration bootstrap, not agent code.
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    original = (tmp_path / ".env").read_text()
    assert "__GENERATE__" not in original
    # Independent passwords avoid unintentionally sharing a secret across services.
    secret_values = [line.split("=", 1)[1] for line in original.splitlines() if "PASSWORD=" in line]
    assert len(secret_values) == len(set(secret_values))
    subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    # Re-running initialization must not rotate credentials in an existing setup.
    assert (tmp_path / ".env").read_text() == original


def test_compose_keeps_services_local_and_socket_in_control_plane():
    """Inspect Compose data without starting containers or reading real secrets."""
    root = Path(__file__).resolve().parents[1]
    services = yaml.safe_load((root / "compose.yaml").read_text())["services"]
    # All explicitly published service ports should bind only to loopback. The
    # host-networked OpenSandbox server sets its own bind address in its TOML.
    for name, service in services.items():
        assert all(port.startswith("127.0.0.1:") for port in service.get("ports", []))
        # Only the trusted control server needs access to the Docker daemon.
        if name != "opensandbox":
            assert not any("docker.sock" in volume for volume in service.get("volumes", []))
    assert services["opensandbox"]["network_mode"] == "host"
    assert services["langfuse-web"]["environment"]["LANGFUSE_INIT_PROJECT_ID"] == "agents-sandbox"
